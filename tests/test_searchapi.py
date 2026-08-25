import pytest

from app.searchapi import SearchApiPricer, _filter_outliers, _parse_price


def make_result(price, source="Walmart", link="https://walmart.com/x", title="Thing"):
    return {"source": source, "link": link, "title": title,
            "price": f"${price:,.2f}", "extracted_price": price}


class TestPriceParsing:
    def test_numeric(self):
        assert _parse_price(299.99) == 299.99

    def test_dollar_string(self):
        assert _parse_price("$1,299.00") == 1299.0

    def test_garbage(self):
        assert _parse_price("n/a") is None
        assert _parse_price(None) is None


class TestOutliers:
    def test_outliers_dropped(self):
        offers = [{"price": 100}] * 5 + [{"price": 10}, {"price": 1000}]
        kept = _filter_outliers(offers)
        assert all(50 <= o["price"] <= 200 for o in kept)

    def test_small_list_kept(self):
        offers = [{"price": 10}, {"price": 900}]
        assert _filter_outliers(offers) == offers


class TestSearchApiPricer:
    def test_disabled_lookup(self, tmp_path):
        p = SearchApiPricer(api_key="", cache_path=tmp_path / "s.json")
        assert not p.enabled
        part = {"id": "x", "name": "Thing", "price_usd": 100, "search_term": "Thing"}
        info = p.lookup_part(part)
        assert info["price_source"] == "baseline"
        assert info["market"] is None

    def test_lookup_with_mocked_search(self, tmp_path):
        p = SearchApiPricer(api_key="key", cache_path=tmp_path / "s.json")
        p._search = lambda q: [
            make_result(280, "Walmart"),
            make_result(300, "Best Buy"),
            make_result(320, "Newegg"),
            make_result(5, "SketchyShop"),   # outlier, filtered
            make_result(5000, "ScalperInc"),  # outlier, filtered
        ]
        part = {"id": "x", "name": "RTX 4060", "price_usd": 300, "search_term": "RTX 4060"}
        info = p.lookup_part(part)
        assert info["price_source"] == "searchapi"
        m = info["market"]
        assert m["median_price_usd"] == 300
        assert m["best_price_usd"] == 280
        assert m["best_merchant"] == "Walmart"
        assert m["offer_count"] == 5

    def test_no_offers(self, tmp_path):
        p = SearchApiPricer(api_key="key", cache_path=tmp_path / "s.json")
        p._search = lambda q: []
        part = {"id": "x", "name": "Thing", "price_usd": 100, "search_term": "Thing"}
        info = p.lookup_part(part)
        assert info["market"] is None

    def test_search_error_returns_empty(self, tmp_path):
        p = SearchApiPricer(api_key="key", cache_path=tmp_path / "s.json")
        p._search = None  # force the real _search, which has no valid key path
        # simulate httpx failure by disabling the key post-hoc
        p.api_key = "key"
        results = SearchApiPricer._search(p, "x")
        assert results == []

    def test_lookup_cached(self, tmp_path):
        p = SearchApiPricer(api_key="key", cache_path=tmp_path / "s.json")
        calls = []
        p._search = lambda q: (calls.append(q), [make_result(100)])[1]
        part = {"id": "x", "name": "Thing", "price_usd": 100, "search_term": "Thing"}
        p.lookup_part(part)
        p.lookup_part(part)
        assert len(calls) == 1


class TestPrecedenceChain:
    def _market_with(self, tmp_path, results):
        m = SearchApiPricer(api_key="key", cache_path=tmp_path / "s.json")
        m._search = lambda q: results
        return m

    def _ebay_with(self, tmp_path, summaries):
        from app.ebay import EbayPricer

        def make_summary(price, condition="New"):
            return {"price": {"value": str(price)}, "condition": condition,
                    "itemWebUrl": "u", "title": "t", "pricingModel": "FIXED_PRICE"}

        e = EbayPricer(client_id="id", client_secret="sec", cache_path=tmp_path / "e.json")
        e._search = lambda q: summaries
        return e

    def test_market_used_when_no_bestbuy_no_ebay(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app.data import find_part

        part = find_part("gpus", "rx-6600")
        market = self._market_with(tmp_path, [make_result(200), make_result(210), make_result(220)])
        bb = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        bb.enrich_part(part, ebay=None, market=market)
        assert part["price_source"] == "market"
        assert part["effective_price_usd"] == 210
        assert part["shopping"]["market"]["best_price_usd"] == 200

    def test_ebay_wins_over_market(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app.data import find_part

        part = find_part("gpus", "rx-6600")
        market = self._market_with(tmp_path, [make_result(200), make_result(210), make_result(220)])
        ebay = self._ebay_with(tmp_path, [
            {"price": {"value": "190"}, "condition": "New", "itemWebUrl": "u",
             "title": "t", "pricingModel": "FIXED_PRICE"},
            {"price": {"value": "195"}, "condition": "New", "itemWebUrl": "u",
             "title": "t", "pricingModel": "FIXED_PRICE"},
        ])
        bb = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        bb.enrich_part(part, ebay=ebay, market=market)
        assert part["price_source"] == "ebay"
        assert part["effective_price_usd"] == 192.5
        # market data still attached for the UI
        assert part["shopping"]["market"]["median_price_usd"] == 210

    def test_bestbuy_wins_over_everything(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app.data import find_part

        part = find_part("gpus", "rtx-4060")
        market = self._market_with(tmp_path, [make_result(250), make_result(260), make_result(270)])
        ebay = self._ebay_with(tmp_path, [])
        bb = BestBuyPricer(api_key="fake", cache_path=tmp_path / "bb.json")
        bb.lookup_part = lambda p: {
            "live_price_usd": 299.99, "in_stock": True, "buy_url": "https://bb.com",
            "price_source": "bestbuy",
        }
        bb.enrich_part(part, ebay=ebay, market=market)
        assert part["price_source"] == "bestbuy"
        assert part["effective_price_usd"] == 299.99

    def test_baseline_when_all_fail(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app.data import find_part

        part = find_part("gpus", "rx-6600")
        market = self._market_with(tmp_path, [])
        bb = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        bb.enrich_part(part, ebay=None, market=market)
        assert part["price_source"] == "baseline"
        assert part["effective_price_usd"] == part["price_usd"]

    def test_enrich_builds_market_totals(self, tmp_path):
        from app.pricing import BestBuyPricer
        from app import builder

        market = self._market_with(tmp_path, [make_result(100)])
        bb = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        result = builder.generate_builds("valorant", "1080p", "high", 144)
        bb.enrich_builds(result, market=market)
        for build in result["builds"]:
            expected = sum(p["effective_price_usd"] for p in build["parts"].values() if p)
            assert build["total_price_usd"] == expected
