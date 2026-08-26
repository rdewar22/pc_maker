"""Retailer link generation.

Search URLs are always-valid deep links — they never 404 the way hardcoded
product URLs do, and they don't require any API key.
"""

from urllib.parse import quote_plus


def bestbuy_search_url(query: str) -> str:
    return f"https://www.bestbuy.com/site/searchpage.jsp?st={quote_plus(query)}"


def newegg_search_url(query: str) -> str:
    return f"https://www.newegg.com/p/pl?d={quote_plus(query)}"


def ebay_search_url(query: str) -> str:
    return f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(query)}"


def walmart_search_url(query: str) -> str:
    return f"https://www.walmart.com/search?q={quote_plus(query)}"


def amazon_search_url(query: str) -> str:
    return f"https://www.amazon.com/s?k={quote_plus(query)}"


def target_search_url(query: str) -> str:
    return f"https://www.target.com/s?searchTerm={quote_plus(query)}"


_MERCHANTS = [
    ("ebay", ebay_search_url),
    ("best buy", bestbuy_search_url),
    ("newegg", newegg_search_url),
    ("walmart", walmart_search_url),
    ("amazon", amazon_search_url),
    ("target", target_search_url),
]


def merchant_search_url(merchant: str, query: str) -> str | None:
    """Search URL on the merchant's own site for a query, or None if unknown."""
    name = (merchant or "").strip().lower()
    if not name:
        return None
    for key, builder in _MERCHANTS:
        if key in name:
            return builder(query)
    return None


def retail_links(part: dict) -> dict:
    """Best Buy + Newegg search links for a part (or prebuilt)."""
    query = part.get("search_term") or part["name"]
    return {
        "bestbuy": bestbuy_search_url(query),
        "newegg": newegg_search_url(query),
    }
