import pytest

from app.ebay import EbayPricer, _filter_outliers, _split_conditions, _summarize


def make_summary(price, condition="New", url="https://ebay.com/x", title="Thing"):
    return {
        "price": {"value": str(price)},
        "condition": condition,
        "itemWebUrl": url,
        "title": title,
        "pricingModel": "FIXED_PRICE",
    }


class TestConditionSplit:
    def test_new_vs_used(self):
        summaries = [
            make_summary(100, "New"),
            make_summary(60, "Used"),
            make_summary(70, "Certified - Refurbished"),
            make_summary(55, "Seller Refurbished"),
            make_summary(50, "Open Box"),
        ]
        new_items, used_items = _split_conditions(summaries)
        assert len(new_items) == 1
        assert len(used_items) == 4

    def test_missing_price_skipped(self):
        summaries = [{"condition": "New", "itemWebUrl": "x", "title": "t"}]
        new_items, used_items = _split_conditions(summaries)
        assert new_items == [] and used_items == []

    def test_auction_skipped(self):
        summaries = [make_summary(10), {**make_summary(10), "pricingModel": "AUCTION"}]
        new_items, _ = _split_conditions(summaries)
        assert len(new_items) == 1


class TestOutliers:
    def test_outliers_dropped(self):
        items = [(100, "u", "t")] * 5 + [(10, "u", "t"), (1000, "u", "t")]
        kept = _filter_outliers(items)
        assert all(0.5 * 100 <= p <= 200 for p, _, _ in kept)

    def test_small_lists_kept(self):
        items = [(10, "u", "t"), (1000, "u", "t")]
        assert _filter_outliers(items) == items


class TestSummarize:
    def test_median_and_cheapest(self):
        items = [(90, "a", "A"), (100, "b", "B"), (110, "c", "C")]
        s = _summarize(items)
        assert s["median_price_usd"] == 100
        assert s["best_price_usd"] == 90
        assert s["buy_url"] == "a"
        assert s["listing_count"] == 3

    def test_empty_returns_none(self):
        assert _summarize([]) is None


class TestEbayPricer:
    def test_disabled_lookup(self, tmp_path):
        p = EbayPricer(client_id="", client_secret="", cache_path=tmp_path / "e.json")
        assert not p.enabled
        part = {"id": "x", "name": "Thing", "price_usd": 100, "search_term": "Thing"}
        info = p.lookup_part(part)
        assert info["price_source"] == "baseline"
        assert info["new"] is None and info["used"] is None

    def test_lookup_with_mocked_search(self, tmp_path):
        p = EbayPricer(client_id="id", client_secret="sec", cache_path=tmp_path / "e.json")
        assert p.enabled
        p._search = lambda q: [
            make_summary(299, "New"),
            make_summary(305, "New"),
            make_summary(310, "New"),
            make_summary(180, "Used"),
            make_summary(190, "Used"),
            make_summary(200, "Used"),
        ]
        part = {"id": "x", "name": "RTX 4060", "price_usd": 300, "search_term": "RTX 4060"}
        info = p.lookup_part(part)
        assert info["price_source"] == "ebay"
        assert info["new"]["median_price_usd"] == 305
        assert info["used"]["median_price_usd"] == 190
        assert info["used"]["best_price_usd"] == 180

    def test_lookup_cached(self, tmp_path):
        p = EbayPricer(client_id="id", client_secret="sec", cache_path=tmp_path / "e.json")
        calls = []
        p._search = lambda q: (calls.append(q), [make_summary(100)])[1]
        part = {"id": "x", "name": "Thing", "price_usd": 100, "search_term": "Thing"}
        p.lookup_part(part)
        p.lookup_part(part)
        assert len(calls) == 1

    def test_search_error_returns_empty(self, tmp_path):
        p = EbayPricer(client_id="id", client_secret="sec", cache_path=tmp_path / "e.json")
        p._get_token = lambda: None
        assert p._search("whatever") == []
        part = {"id": "x", "name": "Thing", "price_usd": 100, "search_term": "Thing"}
        info = p.lookup_part(part)
        assert info["new"] is None


class TestEnrichIntegration:
    def _ebay_with(self, tmp_path, summaries):
        e = EbayPricer(client_id="id", client_secret="sec", cache_path=tmp_path / "e.json")
        e._search = lambda q: summaries
        return e

    def test_ebay_fills_price_when_bestbuy_absent(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app.data import find_part

        part = find_part("gpus", "rx-6600")
        ebay = self._ebay_with(tmp_path, [make_summary(190, "New"), make_summary(200, "New"),
                                          make_summary(120, "Used"), make_summary(130, "Used")])
        bb = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        bb.enrich_part(part, ebay=ebay)
        assert part["price_source"] == "ebay"
        assert part["effective_price_usd"] == 195
        assert part["ebay"]["used"]["median_price_usd"] == 125

    def test_bestbuy_wins_when_present(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app.data import find_part

        part = find_part("gpus", "rtx-4060")
        ebay = self._ebay_with(tmp_path, [make_summary(250, "New"), make_summary(260, "New")])

        bb = BestBuyPricer(api_key="fake", cache_path=tmp_path / "bb.json")
        bb.lookup_part = lambda p: {
            "live_price_usd": 299.99, "in_stock": True, "buy_url": "https://bb.com",
            "price_source": "bestbuy",
        }
        bb.enrich_part(part, ebay=ebay)
        assert part["price_source"] == "bestbuy"
        assert part["effective_price_usd"] == 299.99
        assert part["ebay"]["new"]["median_price_usd"] == 255  # still attached

    def test_no_ebay_falls_back_to_baseline(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app.data import find_part

        part = find_part("gpus", "rx-6600")
        bb = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        bb.enrich_part(part, ebay=None)
        assert part["price_source"] == "baseline"
        assert part["effective_price_usd"] == part["price_usd"]

    def test_enrich_builds_with_ebay(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app import builder

        ebay = self._ebay_with(tmp_path, [make_summary(100, "New"), make_summary(50, "Used")])
        bb = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        result = builder.generate_builds("valorant", "1080p", "high", 144)
        bb.enrich_builds(result, ebay=ebay)
        for build in result["builds"]:
            expected = sum(p["effective_price_usd"] for p in build["parts"].values() if p)
            assert build["total_price_usd"] == expected
            for part in build["parts"].values():
                if part:
                    assert part.get("ebay") is not None
