"""Retailer link generation.

Search URLs are always-valid deep links — they never 404 the way hardcoded
product URLs do, and they don't require any API key.
"""

from urllib.parse import quote_plus


def bestbuy_search_url(query: str) -> str:
    return f"https://www.bestbuy.com/site/searchpage.jsp?st={quote_plus(query)}"


def newegg_search_url(query: str) -> str:
    return f"https://www.newegg.com/p/pl?d={quote_plus(query)}"


def retail_links(part: dict) -> dict:
    """Best Buy + Newegg search links for a part (or prebuilt)."""
    query = part.get("search_term") or part["name"]
    return {
        "bestbuy": bestbuy_search_url(query),
        "newegg": newegg_search_url(query),
    }
