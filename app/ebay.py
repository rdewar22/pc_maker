"""eBay Browse API integration for marketplace pricing (new + used).

Uses the eBay Browse API (https://developer.ebay.com/api-docs/buy/browse/overview.html).
Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env (free keys at
https://developer.ebay.com — create an app, then use the "Application Keys"
prod/sandbox keyset's Client ID + Client Secret).

Design:
- OAuth2 client-credentials token, cached in memory until ~2 min before expiry
- Searches fixed-price (Buy-It-Now) USD listings for each part
- Splits results into new vs used/refurbished by condition
- Filters outliers (listings far from the median) then reports the median price
  and links the cheapest surviving listing
- Falls back to "no data" markers so builds always render
"""

import json
import os
import time
from pathlib import Path
from statistics import median

import httpx

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
SANDBOX_SEARCH_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
API_SCOPE = "https://api.ebay.com/oauth/api_scope"
CACHE_TTL_SECONDS = 3600
CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "ebay.json"
REQUEST_TIMEOUT = 4.0
LISTING_LIMIT = 40

USED_CONDITIONS = {"used", "seller refurbished", "certified - refurbished",
                   "very good", "good", "acceptable", "open box"}


def _split_conditions(summaries: list) -> tuple:
    """Split item summaries into (new, used) price/URL pairs."""
    new_items, used_items = [], []
    for s in summaries:
        price = s.get("price", {}).get("value")
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if s.get("pricingModel") not in (None, "FIXED_PRICE"):
            continue
        entry = (price, s.get("itemWebUrl", ""), s.get("title", ""))
        cond = (s.get("condition") or "").strip().lower()
        if cond == "new":
            new_items.append(entry)
        elif cond in USED_CONDITIONS:
            used_items.append(entry)
    return new_items, used_items


def _filter_outliers(items: list) -> list:
    """Drop listings more than 2x or less than 0.5x the median (typos/scams)."""
    if len(items) < 3:
        return items
    med = median(p for p, _, _ in items)
    return [it for it in items if 0.5 * med <= it[0] <= 2.0 * med]


def _summarize(items: list) -> dict | None:
    """Median price + cheapest surviving listing link for a condition bucket."""
    if not items:
        return None
    kept = _filter_outliers(items)
    if not kept:
        kept = items
    cheapest = min(kept)
    return {
        "median_price_usd": round(median(p for p, _, _ in kept), 2),
        "best_price_usd": cheapest[0],
        "buy_url": cheapest[1] or None,
        "matched_title": cheapest[2] or None,
        "listing_count": len(items),
    }


class EbayPricer:
    def __init__(self, client_id: str = None, client_secret: str = None,
                 cache_path: Path = CACHE_PATH, cache_ttl: int = CACHE_TTL_SECONDS):
        self.client_id = client_id if client_id is not None else os.environ.get("EBAY_CLIENT_ID", "")
        self.client_secret = client_secret if client_secret is not None else os.environ.get("EBAY_CLIENT_SECRET", "")
        self.cache_ttl = cache_ttl
        self.cache_path = cache_path
        self._cache = self._load_cache()
        self._token = None
        self._token_expires_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def sandbox(self) -> bool:
        """Sandbox keys are auto-detected from the '-SBX-' marker in the client id."""
        return "-sbx-" in (self.client_id or "").lower()

    @property
    def _token_url(self) -> str:
        return SANDBOX_TOKEN_URL if self.sandbox else TOKEN_URL

    @property
    def _search_url(self) -> str:
        return SANDBOX_SEARCH_URL if self.sandbox else SEARCH_URL

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

    # -- oauth -----------------------------------------------------------

    def _get_token(self) -> str | None:
        if not self.enabled:
            return None
        if self._token and time.time() < self._token_expires_at - 120:
            return self._token
        try:
            resp = httpx.post(
                self._token_url,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials", "scope": API_SCOPE},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return self._token  # best-effort: reuse stale token if we have one
        self._token = body.get("access_token")
        self._token_expires_at = time.time() + int(body.get("expires_in", 7200))
        return self._token

    # -- search ----------------------------------------------------------

    def _search(self, query: str) -> list:
        """Search fixed-price USD listings. Returns raw item summaries (may be empty)."""
        token = self._get_token()
        if not token:
            return []
        try:
            resp = httpx.get(
                self._search_url,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "q": query,
                    "limit": LISTING_LIMIT,
                    "filter": "buyOptions:BUY_NOW",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("itemSummaries", [])
        except (httpx.HTTPError, json.JSONDecodeError):
            return []

    def lookup_part(self, part: dict) -> dict:
        """Marketplace pricing for a part: new/used medians + cheapest listings."""
        query = part.get("search_term") or part["name"]
        cache_key = f"q:{query}"
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        if not self.enabled:
            result = {"enabled": False, "new": None, "used": None, "price_source": "baseline"}
        else:
            new_items, used_items = _split_conditions(self._search(query))
            result = {
                "enabled": True,
                "new": _summarize(new_items),
                "used": _summarize(used_items),
                "price_source": "ebay",
            }
        self._store(cache_key, result)
        return result
