import json
import time

import pytest
from app.pricing import BestBuyPricer


class TestCache:
    def test_disk_cache_roundtrip(self, tmp_path):
        cache_file = tmp_path / "bb.json"
        p = BestBuyPricer(api_key="fake", cache_path=cache_file)
        p._store("sku:1", {"live_price_usd": 9.99})
        assert cache_file.exists()

        p2 = BestBuyPricer(api_key="fake", cache_path=cache_file)
        assert p2._cached("sku:1") == {"live_price_usd": 9.99}

    def test_expired_cache_returns_none(self, tmp_path):
        cache_file = tmp_path / "bb.json"
        p = BestBuyPricer(api_key="fake", cache_path=cache_file, cache_ttl=1)
        p._store("sku:1", {"live_price_usd": 9.99})
        # simulate aging
        p._cache["sku:1"]["fetched_at"] = time.time() - 10
        assert p._cached("sku:1") is None

    def test_corrupt_cache_ignored(self, tmp_path):
        cache_file = tmp_path / "bb.json"
        cache_file.write_text("{not json")
        p = BestBuyPricer(api_key="fake", cache_path=cache_file)
        assert p._cache == {}


class TestFallback:
    def test_no_api_key_falls_back_to_baseline(self, tmp_path):
        part = {"id": "x", "name": "Thing", "price_usd": 100, "bestbuy_sku": None, "search_term": None}
        p = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        assert not p.enabled
        p.enrich_part(part)
        assert part["effective_price_usd"] == 100
        assert part["live"]["price_source"] == "baseline"
        assert part["live"]["in_stock"] is None

    def test_enrich_builds_recomputes_totals(self, tmp_path):
        p = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        part = {"id": "x", "name": "Thing", "price_usd": 100, "bestbuy_sku": None, "search_term": None}
        result = {"builds": [{"parts": {"gpu": part, "cpu": None}}]}
        p.enrich_builds(result)
        assert result["builds"][0]["total_price_usd"] == 100
