"""SearchAPI.io integration for multi-retailer price aggregation.

Uses SearchAPI.io's Google Shopping engine: one query returns current prices
for a product across all retailers (Best Buy, Walmart, Newegg, Amazon, eBay...).

Get a key at https://www.searchapi.io (100 free requests, no card required).
Set SEARCHAPI_API_KEY in .env to enable.

Design notes:
- Prices are the median of merchant offers, outlier-filtered (0.5x-2x median band)
- The cheapest surviving offer is linked (merchant + buy URL)
- Cache TTL is 6h by default (vs 1h elsewhere) to stretch the small free tier
- Falls back to "no data" markers so builds always render
"""

import json
import os
import re
import time
from pathlib import Path
from statistics import median

import httpx

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SEARCH_URL = "https://www.searchapi.io/api/v1/search"
CACHE_TTL_SECONDS = 21600  # 6h: free tier is small, cache harder
CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "searchapi.json"
# Google Shopping is a live-scraping engine: queries regularly take 10-25s.
REQUEST_TIMEOUT = 35.0
MAX_CONCURRENT_LOOKUPS = 6


def _parse_price(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _model_tokens(query: str) -> list:
    """Discriminating tokens from a query: alphanumeric tokens that contain digits.

    e.g. 'Corsair CV550 550W' -> ['cv550', '550w']; 'GeForce RTX 4060' -> ['4060'].
    These distinguish the exact product from siblings (CX550 vs CV550, 4060 Ti vs 4060).
    """
    tokens = []
    for tok in re.findall(r"[a-z0-9]+", query.lower()):
        if len(tok) >= 3 and any(c.isdigit() for c in tok) and tok not in tokens:
            tokens.append(tok)
    return tokens


def _title_has_token(title: str, token: str) -> bool:
    """Token appears in title on non-alphanumeric boundaries (4060 != 4060ti),
    and is not a pricier sibling SKU like '4060 Ti' or '4060 Super'."""
    m = re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", title.lower())
    if not m:
        return False
    after = title.lower()[m.end():]
    return re.match(r"\s+(ti|super)\b", after) is None


def _filter_outliers(offers: list) -> list:
    if len(offers) < 3:
        return offers
    med = median(o["price"] for o in offers)
    return [o for o in offers if 0.5 * med <= o["price"] <= 2.0 * med]


def _percentile(sorted_values: list, pct: float) -> float:
    """Linear-interpolated percentile of already-sorted values."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _market_summary(offers: list) -> dict:
    """Aggregate merchant offers.

    Google Shopping mixes product variants (capacities, kit sizes, bundles) in one
    result set, so the raw median overprices the base product. We report the 25th
    percentile of the outlier-filtered offers as the market price — the cheap
    cluster matches the product searched for; upgrades and bundles sit above it.
    """
    kept = _filter_outliers(offers) or offers
    prices = sorted(o["price"] for o in kept)
    cheapest = min(kept, key=lambda o: o["price"])
    return {
        "market_price_usd": round(_percentile(prices, 0.25), 2),
        "best_price_usd": cheapest["price"],
        "best_merchant": cheapest["merchant"],
        "buy_url": cheapest["buy_url"],
        "matched_title": cheapest["title"],
        "offer_count": len(offers),
    }


class SearchApiPricer:
    def __init__(self, api_key: str = None, cache_path: Path = CACHE_PATH,
                 cache_ttl: int = CACHE_TTL_SECONDS):
        self.api_key = api_key if api_key is not None else os.environ.get("SEARCHAPI_API_KEY", "")
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

    # -- search ----------------------------------------------------------

    def _search(self, query: str) -> list:
        """Google Shopping lookup. Returns raw shopping_results (may be empty)."""
        if not self.enabled:
            return []
        try:
            resp = httpx.get(
                SEARCH_URL,
                params={
                    "engine": "google_shopping",
                    "q": query,
                    "gl": "us",
                    "hl": "en",
                    "api_key": self.api_key,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("shopping_results", [])
        except (httpx.HTTPError, json.JSONDecodeError):
            return []

    def warm_queries(self, parts: list) -> None:
        """Concurrently pre-fetch market data for all uncached parts."""
        from concurrent.futures import ThreadPoolExecutor

        uncached = []
        seen = set()
        for part in parts:
            query = part.get("search_term") or part["name"]
            if query in seen:
                continue
            seen.add(query)
            if self._cached(f"q:{query}") is None:
                uncached.append(part)
        if not uncached:
            return
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LOOKUPS) as pool:
            list(pool.map(self.lookup_part, uncached))

    def lookup_part(self, part: dict) -> dict:
        """Multi-retailer market pricing for a part.

        Includes a plausibility guard: if even the cheapest filtered offer costs
        more than 2.5x the curated baseline, the search results are dominated by
        different product variants — the match is discarded rather than trusted.
        """
        query = part.get("search_term") or part["name"]
        cache_key = f"q:{query}"
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        if not self.enabled:
            result = {"enabled": False, "market": None, "price_source": "baseline"}
        else:
            offers = []
            model_tokens = _model_tokens(query)
            for r in self._search(query):
                price = _parse_price(r.get("extracted_price", r.get("price")))
                if price is None or price <= 0:
                    continue
                title = r.get("title", "")
                if model_tokens and not all(
                    _title_has_token(title, t) for t in model_tokens
                ):
                    continue  # wrong/sibling product
                offers.append(
                    {
                        "price": price,
                        "merchant": r.get("seller") or r.get("source") or "retailer",
                        "buy_url": r.get("link") or r.get("product_link"),
                        "title": title,
                    }
                )
            market = _market_summary(offers) if offers else None
            baseline = part.get("price_usd")
            if market and baseline and market["best_price_usd"] > 2.5 * baseline:
                market = None  # variant pollution; don't trust the match
            result = {"enabled": True, "market": market, "price_source": "searchapi"}
        self._store(cache_key, result)
        return result
