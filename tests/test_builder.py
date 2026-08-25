import pytest

from app import builder, compat


class TestGenerateBuilds:
    def test_basic_build_hunt_showdown(self):
        result = builder.generate_builds("hunt-showdown-1896", "1080p", "low", 144)
        assert 1 <= len(result["builds"]) <= 3
        assert result["builds"][0]["variant"] == "value"
        for build in result["builds"]:
            assert build["compatibility_errors"] == []
            assert build["estimated_fps"] >= 144
            assert build["total_price_usd"] > 0
            assert set(build["parts"]) >= {
                "gpu", "cpu", "motherboard", "ram", "storage", "psu", "case"
            }

    def test_builds_scale_with_variant(self):
        result = builder.generate_builds("cyberpunk-2077", "1080p", "high", 60)
        prices = [b["total_price_usd"] for b in result["builds"]]
        assert prices == sorted(prices)  # value <= balanced <= headroom
        fps = [b["estimated_fps"] for b in result["builds"]]
        assert fps == sorted(fps)

    def test_every_part_used_is_compatible(self):
        result = builder.generate_builds("monster-hunter-wilds", "1440p", "high", 100)
        for build in result["builds"]:
            assert compat.is_compatible(build["parts"])

    def test_elden_ring_144_raises(self):
        with pytest.raises(builder.BuildImpossibleError, match="capped"):
            builder.generate_builds("elden-ring", "1080p", "high", 144)

    def test_impossible_target_raises(self):
        with pytest.raises(builder.BuildImpossibleError):
            builder.generate_builds("cyberpunk-2077", "4k", "ultra", 300)

    def test_budget_filters_or_notes(self):
        rich = builder.generate_builds("valorant", "1080p", "high", 144, budget_usd=100000)
        assert all(b["total_price_usd"] <= 100000 for b in rich["builds"])
        poor = builder.generate_builds("cyberpunk-2077", "4k", "ultra", 60, budget_usd=50)
        assert poor["notes"], "expected a budget warning note"

    def test_unknown_game_raises(self):
        with pytest.raises(KeyError):
            builder.generate_builds("not-a-game")

    def test_all_games_all_resolutions_smoke(self):
        from app.data import games_db
        for game_id in games_db():
            for res in ["1080p", "1440p"]:
                result = builder.generate_builds(game_id, res, "high", 60)
                assert result["builds"]
                for b in result["builds"]:
                    assert b["compatibility_errors"] == []
