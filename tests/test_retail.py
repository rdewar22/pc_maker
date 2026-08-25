from app import retail
from app import builder
from app.data import get_game, find_part


class TestRetailLinks:
    def test_bestbuy_search_url(self):
        url = retail.bestbuy_search_url("Radeon RX 6600")
        assert url.startswith("https://www.bestbuy.com/site/searchpage.jsp?st=")
        assert "Radeon+RX+6600" in url

    def test_newegg_search_url(self):
        url = retail.newegg_search_url("Ryzen 5 5600")
        assert url.startswith("https://www.newegg.com/p/pl?d=")
        assert "Ryzen+5+5600" in url

    def test_retail_links_uses_search_term(self):
        part = find_part("gpus", "rx-6600")
        links = retail.retail_links(part)
        assert "bestbuy" in links and "newegg" in links
        assert "RX+6600" in links["bestbuy"]

    def test_retail_links_falls_back_to_name(self):
        part = {"name": "Weird Part With No Search Term", "search_term": None}
        links = retail.retail_links(part)
        assert "Weird+Part" in links["newegg"]


class TestPrebuiltMatching:
    def test_prebuilts_included_in_result(self):
        result = builder.generate_builds("hunt-showdown-1896", "1080p", "low", 144)
        assert "prebuilts" in result
        for pb in result["prebuilts"]:
            assert pb["estimated_fps"] >= 144
            assert "bestbuy" in pb["retail_urls"]

    def test_prebuilts_sorted_cheapest_first(self):
        result = builder.generate_builds("cyberpunk-2077", "1080p", "high", 60)
        prices = [p["price_usd"] for p in result["prebuilts"]]
        assert prices == sorted(prices)

    def test_easy_game_gets_budget_prebuilts(self):
        result = builder.generate_builds("valorant", "1080p", "high", 144)
        assert any(p["price_usd"] <= 700 for p in result["prebuilts"])

    def test_harder_target_excludes_weak_prebuilts(self):
        game = get_game("cyberpunk-2077")
        result = builder.generate_builds("cyberpunk-2077", "1440p", "ultra", 100)
        for pb in result["prebuilts"]:
            # anything matched must genuinely meet the target per the perf model
            from app import perf
            assert pb["gpu_tier"] >= perf.required_gpu_tier(game, "1440p", "ultra", 100)

    def test_impossible_target_no_prebuilts(self):
        game = get_game("cyberpunk-2077")
        assert builder.matching_prebuilts(game, "4k", "ultra", 240) == []


class TestEnrichmentLinks:
    def test_enrich_part_adds_retail_urls(self, tmp_path):
        from app.pricing import BestBuyPricer

        part = find_part("gpus", "rtx-4060")
        p = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        p.enrich_part(part)
        assert "bestbuy.com" in part["retail_urls"]["bestbuy"]
        assert "newegg.com" in part["retail_urls"]["newegg"]

    def test_enrich_builds_adds_prebuilt_urls(self, tmp_path):
        from app.pricing import BestBuyPricer

        result = builder.generate_builds("hunt-showdown-1896", "1080p", "low", 144)
        BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json").enrich_builds(result)
        for pb in result["prebuilts"]:
            assert "bestbuy.com" in pb["retail_urls"]["bestbuy"]
