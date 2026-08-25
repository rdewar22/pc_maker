"""Best Buy live pricing with on-disk cache and graceful fallback to baseline prices.

Uses the Best Buy Products API (https://developer.bestbuy.com).
Set the BESTBUY_API_KEY environment variable to enable live pricing.
Without a key, builds silently fall back to curated baseline prices.
"""

import json
import os
import time
from pathlib import Path

import httpx

from app import retail

API_BASE = "https://api.bestbuy.com/v1/products"
CACHE_TTL_SECONDS = 3600
CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "bestbuy.json"
REQUEST_TIMEOUT = 4.0


class BestBuyPricer:
    def __init__(self, api_key: str = None, cache_path: Path = CACHE_PATH,
                 cache_ttl: int = CACHE_TTL_SECONDS):
        self.api_key = api_key or os.environ.get("BESTBUY_API_KEY", "")
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

    def _fetch(self, query: str) -> dict | None:
        """Query the Products API. `query` is the filter expression, e.g. (sku=6425753)."""
        if not self.enabled:
            return None
        url = f"{API_BASE}({query})"
        params = {
            "apiKey": self.api_key,
            "format": "json",
            "show": "sku,name,salePrice,onlineAvailability,addToCartUrl,condition",
            "pageSize": 8,
            "sort": "salePrice.asc",
        }
        try:
            resp = httpx.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            products = resp.json().get("products", [])
        except (httpx.HTTPError, json.JSONDecodeError):
            return None
        new_ = [p for p in products if p.get("condition") == "New"]
        return new_[0] if new_ else (products[0] if products else None)

    def lookup_part(self, part: dict) -> dict:
        """Return live pricing info for a part, or a fallback marker."""
        sku = part.get("bestbuy_sku")
        cache_key = f"sku:{sku}" if sku else f"search:{part.get('search_term') or part['name']}"
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        data = None
        if sku:
            data = self._fetch(f"sku={sku}")
        if data is None and part.get("search_term"):
            data = self._fetch(f"search={part['search_term']}")

        if data is None:
            result = {
                "live_price_usd": None,
                "in_stock": None,
                "buy_url": None,
                "price_source": "baseline",
            }
        else:
            result = {
                "live_price_usd": data.get("salePrice"),
                "in_stock": bool(data.get("onlineAvailability")),
                "buy_url": data.get("addToCartUrl"),
                "bestbuy_sku": data.get("sku"),
                "matched_name": data.get("name"),
                "price_source": "bestbuy",
            }
        self._store(cache_key, result)
        return result

    # -- build enrichment --------------------------------------------------

    def enrich_part(self, part: dict) -> dict:
        """Add live pricing fields and retail links to a part (mutates and returns it)."""
        info = self.lookup_part(part)
        part["live"] = info
        part["retail_urls"] = retail.retail_links(part)
        if info["live_price_usd"] is not None:
            part["effective_price_usd"] = info["live_price_usd"]
        else:
            part["effective_price_usd"] = part["price_usd"]
        return part

    def enrich_builds(self, result: dict) -> dict:
        """Enrich every part and prebuilt in the result and recompute totals. Mutates `result`."""
        seen = {}
        for build in result.get("builds", []):
            for slot, part in build["parts"].items():
                if part is None:
                    continue
                if part["id"] in seen:
                    build["parts"][slot] = seen[part["id"]]
                    continue
                self.enrich_part(part)
                seen[part["id"]] = part
            build["total_price_usd"] = sum(
                p["effective_price_usd"] for p in build["parts"].values() if p
            )
        for pb in result.get("prebuilts", []):
            if "retail_urls" not in pb:
                pb["retail_urls"] = retail.retail_links(pb)
        return result
