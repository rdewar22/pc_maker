import pytest

from app import builder, compat
from app.pricing import BestBuyPricer, _category_of, _is_equivalent
from app.data import find_part


class TestCategoryMapping:
    def test_all_slots_map(self):
        for slot in ["gpu", "cpu", "motherboard", "ram", "storage", "psu", "case", "cooler"]:
            assert _category_of(slot)


class TestEquivalence:
    def test_gpu_same_tier_enough_vram(self):
        a = find_part("gpus", "rtx-4060")
        b = {"id": "x", "tier": 3, "vram_gb": 12}
        assert _is_equivalent(b, a)

    def test_gpu_lower_vram_not_equivalent(self):
        a = find_part("gpus", "rtx-5070")  # tier 5, 12GB
        b = {"id": "x", "tier": 5, "vram_gb": 8}
        assert not _is_equivalent(b, a)

    def test_ram_upgrade_is_equivalent(self):
        a = find_part("ram", "ddr5-32")
        b = find_part("ram", "ddr5-64")
        assert _is_equivalent(b, a)
        assert not _is_equivalent(find_part("ram", "ddr4-32"), a)

    def test_psu_higher_wattage_is_equivalent(self):
        a = find_part("psus", "psu-650")
        b = find_part("psus", "psu-850")
        assert _is_equivalent(b, a)

    def test_motherboard_same_socket_ddr(self):
        a = find_part("motherboards", "b650m")
        b = find_part("motherboards", "b650-tomahawk")
        assert _is_equivalent(b, a)
        assert not _is_equivalent(find_part("motherboards", "x670e"), find_part("motherboards", "b550m"))


class TestStockSwaps:
    def _pricer(self, tmp_path, oos_ids):
        """Pricer whose live data marks given part ids out of stock, others in stock."""
        p = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")

        def fake_lookup(part):
            oos = part["id"] in oos_ids
            return {
                "live_price_usd": None,
                "in_stock": (not oos) if part.get("id") else None,
                "buy_url": None,
                "price_source": "bestbuy" if part.get("id") else "baseline",
            }

        p.lookup_part = fake_lookup
        return p

    def test_oos_part_swapped_for_in_stock_equivalent(self, tmp_path):
        pricer = self._pricer(tmp_path, oos_ids={"ddr5-32"})
        result = builder.generate_builds("hunt-showdown-1896", "1080p", "low", 144)
        pricer.enrich_builds(result, require_in_stock=True)
        for build in result["builds"]:
            ram = build["parts"]["ram"]
            if ram["id"] == "ddr5-32":
                # only allowed to stay if no swap was possible; 32GB+ DDR5 exists though
                assert any("ram" in s or "DDR5" in s for s in build.get("stock_swaps", [])), \
                    "expected OOS RAM to be swapped"
            else:
                assert ram["live"]["in_stock"] is not False

    def test_swapped_build_still_compatible(self, tmp_path):
        pricer = self._pricer(tmp_path, oos_ids={"psu-650", "case-atx-mid", "ddr5-32"})
        result = builder.generate_builds("cyberpunk-2077", "1080p", "high", 60)
        pricer.enrich_builds(result, require_in_stock=True)
        for build in result["builds"]:
            assert compat.is_compatible(build["parts"])

    def test_no_equivalent_keeps_part_flagged(self, tmp_path):
        # make the only cooler for a hot CPU OOS along with everything else
        pricer = self._pricer(tmp_path, oos_ids={"cooler-pa120", "cooler-aio240"})
        result = builder.generate_builds("cyberpunk-2077", "1080p", "high", 60)
        pricer.enrich_builds(result, require_in_stock=True)
        for build in result["builds"]:
            for part in build["parts"].values():
                if part and part["id"] in {"cooler-pa120", "cooler-aio240"}:
                    assert part["live"]["in_stock"] is False

    def test_no_stock_flag_leaves_builds_untouched(self, tmp_path):
        pricer = self._pricer(tmp_path, oos_ids={"rtx-4060"})
        result = builder.generate_builds("cyberpunk-2077", "1080p", "high", 60)
        before = [dict(b["parts"]) for b in result["builds"]]
        pricer.enrich_builds(result, require_in_stock=False)
        for orig, build in zip(before, result["builds"]):
            assert orig.keys() == build["parts"].keys()
            assert build.get("stock_swaps") == []

    def test_totals_recomputed_after_swap(self, tmp_path):
        pricer = self._pricer(tmp_path, oos_ids={"nvme-1tb"})
        result = builder.generate_builds("valorant", "1080p", "high", 144)
        pricer.enrich_builds(result, require_in_stock=True)
        for build in result["builds"]:
            expected = sum(p["effective_price_usd"] for p in build["parts"].values() if p)
            assert build["total_price_usd"] == expected


class TestWarmSkus:
    def test_warm_skus_no_key_is_noop(self, tmp_path):
        p = BestBuyPricer(api_key="", cache_path=tmp_path / "bb.json")
        parts = [find_part("gpus", "rtx-4060")]  # has a SKU
        p.warm_skus(parts)  # should not raise; no API call possible
        part = dict(parts[0])
        p.enrich_part(part)
        assert part["effective_price_usd"] == 300
