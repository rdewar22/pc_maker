"""Best Buy live pricing with on-disk cache and graceful fallback to baseline prices.

Uses the Best Buy Products API (https://developer.bestbuy.com).
Set the BESTBUY_API_KEY environment variable to enable live pricing.
Without a key, builds silently fall back to curated baseline prices.

Deep integration features:
- Batch SKU lookups via the `sku in(...)` filter (one API call for a whole build)
- Stock-aware part substitution: when require_in_stock, out-of-stock parts are
  swapped for the cheapest in-stock equivalent that keeps the build compatible
"""

import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app import compat
from app import retail
from app.data import parts_db

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_BASE = "https://api.bestbuy.com/v1/products"
CACHE_TTL_SECONDS = 3600
CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "bestbuy.json"
REQUEST_TIMEOUT = 4.0
SHOW_FIELDS = "sku,name,salePrice,onlineAvailability,addToCartUrl,condition"


class BestBuyPricer:
    def __init__(self, api_key: str = None, cache_path: Path = CACHE_PATH,
                 cache_ttl: int = CACHE_TTL_SECONDS):
        self.api_key = api_key if api_key is not None else os.environ.get("BESTBUY_API_KEY", "")
        self.cache_ttl = cache_ttl
        self.cache_path = cache_path
        self._cache = self._load_cache()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # -- cache -----------------------------------------------------------

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache), encoding="utf-8")

    def _cached(self, key: str) -> dict | None:
        entry = self._cache.get(key)
        if entry and time.time() - entry["fetched_at"] < self.cache_ttl:
            return entry["data"]
        return None

    def _store(self, key: str, data: dict) -> None:
        self._cache[key] = {"fetched_at": time.time(), "data": data}
        self._save_cache()

    # -- best buy api ----------------------------------------------------

    def _fetch(self, query: str, page_size: int = 8) -> list:
        """Query the Products API. `query` is the filter expression, e.g. (sku=6425753).
        Returns the raw product list (may be empty)."""
        if not self.enabled:
            return []
        url = f"{API_BASE}({query})"
        params = {
            "apiKey": self.api_key,
            "format": "json",
            "show": SHOW_FIELDS,
            "pageSize": page_size,
            "sort": "salePrice.asc",
        }
        try:
            resp = httpx.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("products", [])
        except (httpx.HTTPError, json.JSONDecodeError):
            return []

    @staticmethod
    def _newest(products: list) -> dict | None:
        new_ = [p for p in products if p.get("condition") == "New"]
        return new_[0] if new_ else (products[0] if products else None)

    def _result_from_product(self, data: dict | None) -> dict:
        if data is None:
            return {
                "live_price_usd": None,
                "in_stock": None,
                "buy_url": None,
                "price_source": "baseline",
            }
        return {
            "live_price_usd": data.get("salePrice"),
            "in_stock": bool(data.get("onlineAvailability")),
            "buy_url": data.get("addToCartUrl"),
            "bestbuy_sku": data.get("sku"),
            "matched_name": data.get("name"),
            "price_source": "bestbuy",
        }

    def lookup_part(self, part: dict) -> dict:
        """Return live pricing info for a part, or a fallback marker."""
        sku = part.get("bestbuy_sku")
        cache_key = f"sku:{sku}" if sku else f"search:{part.get('search_term') or part['name']}"
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        data = None
        if sku:
            data = self._newest(self._fetch(f"sku={sku}"))
        if data is None and part.get("search_term"):
            data = self._newest(self._fetch(f"search={part['search_term']}"))

        result = self._result_from_product(data)
        self._store(cache_key, result)
        return result

    def warm_skus(self, parts: list) -> None:
        """Batch-lookup pricing for all parts with SKUs in one API call."""
        skus = {p["bestbuy_sku"] for p in parts if p.get("bestbuy_sku")}
        skus = {s for s in skus if self._cached(f"sku:{s}") is None}
        if not skus:
            return
        products = self._fetch("sku in(" + ",".join(str(s) for s in sorted(skus)) + ")",
                               page_size=100)
        by_sku = {p.get("sku"): p for p in products}
        for sku in skus:
            self._store(f"sku:{sku}", self._result_from_product(by_sku.get(sku)))

    # -- build enrichment --------------------------------------------------

    def enrich_part(self, part: dict, ebay=None, market=None) -> dict:
        """Add live pricing fields, retail links, and marketplace data to a part.

        Price precedence: Best Buy live -> eBay new median -> market
        (SearchAPI/Google Shopping) median -> curated baseline.
        """
        info = self.lookup_part(part)
        part["live"] = info
        part["retail_urls"] = retail.retail_links(part)
        if info["live_price_usd"] is not None:
            part["effective_price_usd"] = info["live_price_usd"]
            part["price_source"] = "bestbuy"
        else:
            part["effective_price_usd"] = None
            part["price_source"] = None
            if ebay is not None and ebay.enabled:
                part["ebay"] = ebay.lookup_part(part)
                ebay_new = part["ebay"].get("new")
                if ebay_new and ebay_new.get("median_price_usd") is not None:
                    part["effective_price_usd"] = ebay_new["median_price_usd"]
                    part["price_source"] = "ebay"
            if (part["effective_price_usd"] is None
                    and market is not None and market.enabled):
                part["shopping"] = market.lookup_part(part)
                m = part["shopping"].get("market")
                # For query-based aggregation the cheapest filtered offer matches
                # the searched product; higher prices are usually bigger variants.
                if m and m.get("best_price_usd") is not None:
                    part["effective_price_usd"] = m["best_price_usd"]
                    part["price_source"] = "market"
            if part["effective_price_usd"] is None:
                part["effective_price_usd"] = part["price_usd"]
                part["price_source"] = "baseline"
        if ebay is not None and ebay.enabled and "ebay" not in part:
            part["ebay"] = ebay.lookup_part(part)
        if market is not None and market.enabled and "shopping" not in part:
            part["shopping"] = market.lookup_part(part)
        return part

    def enrich_builds(self, result: dict, require_in_stock: bool = False, ebay=None,
                      market=None) -> dict:
        """Enrich every part and prebuilt in the result and recompute totals.

        With require_in_stock=True, out-of-stock parts are swapped for the cheapest
        in-stock equivalent that keeps the build fully compatible. Parts that can't
        be swapped stay in place, flagged out-of-stock.
        """
        all_parts = [p for b in result.get("builds", []) for p in b["parts"].values() if p]
        self.warm_skus(all_parts)
        if market is not None and market.enabled:
            market.warm_queries(all_parts)
        enriched = {}
        for part in all_parts:
            if part["id"] not in enriched:
                self.enrich_part(part, ebay=ebay, market=market)
                enriched[part["id"]] = part

        for build in result.get("builds", []):
            swaps = []
            for slot, part in list(build["parts"].items()):
                if part is None:
                    continue
                if require_in_stock and part["live"]["in_stock"] is False:
                    replacement = self._find_in_stock_replacement(build, slot, part,
                                                                  ebay=ebay, market=market)
                    if replacement is not None:
                        swaps.append(f"{part['name']} -> {replacement['name']}")
                        build["parts"][slot] = replacement
            build["stock_swaps"] = swaps
            build["total_price_usd"] = sum(
                p["effective_price_usd"] for p in build["parts"].values() if p
            )

        for pb in result.get("prebuilts", []):
            if "retail_urls" not in pb:
                pb["retail_urls"] = retail.retail_links(pb)
        return result

    def _find_in_stock_replacement(self, build: dict, slot: str, part: dict,
                                   ebay=None, market=None) -> dict | None:
        """Cheapest in-stock equivalent for `part` that keeps `build` compatible."""
        candidates = []
        for cand in parts_db().get(_category_of(slot), []):
            if cand["id"] == part["id"] or not _is_equivalent(cand, part):
                continue
            candidates.append(cand)
        candidates.sort(key=lambda c: c["price_usd"])
        for cand in candidates:
            self.enrich_part(cand, ebay=ebay, market=market)
            if cand["live"]["in_stock"] is not True:
                continue
            trial = dict(build["parts"])
            trial[slot] = cand
            if compat.is_compatible(trial):
                return cand
        return None


_SLOT_TO_CATEGORY = {
    "gpu": "gpus",
    "cpu": "cpus",
    "motherboard": "motherboards",
    "ram": "ram",
    "storage": "storage",
    "psu": "psus",
    "case": "cases",
    "cooler": "coolers",
}


def _category_of(slot: str) -> str:
    return _SLOT_TO_CATEGORY[slot]


def _is_equivalent(cand: dict, part: dict) -> bool:
    """True when `cand` can fill the same role as `part` (same tier/class, >= specs)."""
    if "tier" in part and "vram_gb" in part:  # gpu
        return cand.get("tier") == part["tier"] and cand.get("vram_gb", 0) >= part["vram_gb"]
    if "tier" in part:  # cpu
        return cand.get("tier") == part["tier"]
    if "socket" in part and "ddr" in part:  # motherboard
        return cand["socket"] == part["socket"] and cand["ddr"] == part["ddr"]
    if "sockets" in part:  # cooler
        return (
            set(part["sockets"]) <= set(cand.get("sockets", []))
            and cand.get("tdp_capacity_w", 0) >= part["tdp_capacity_w"]
        )
    if "socket" in part:  # cpu
        return cand["socket"] == part["socket"]
    if "capacity_gb" in part and "ddr" in part:  # ram
        return cand["ddr"] == part["ddr"] and cand["capacity_gb"] >= part["capacity_gb"]
    if "capacity_gb" in part:  # storage
        return cand["capacity_gb"] >= part["capacity_gb"]
    if "wattage" in part:  # psu
        return cand["wattage"] >= part["wattage"]
    if "max_gpu_len_mm" in part:  # case
        return (
            cand["max_gpu_len_mm"] >= part["max_gpu_len_mm"]
            and cand["max_cooler_height_mm"] >= part["max_cooler_height_mm"]
            and set(part["supports_form_factors"]) <= set(cand["supports_form_factors"])
        )
    return cand["id"] == part["id"]
