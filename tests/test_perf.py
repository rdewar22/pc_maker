import pytest

from app import perf
from app.data import get_game, games_db


class TestEstimates:
    def test_higher_tier_more_fps(self):
        game = get_game("cyberpunk-2077")
        low = perf.estimate_fps(2, game, "1080p", "high")
        high = perf.estimate_fps(5, game, "1080p", "high")
        assert high > low

    def test_4k_slower_than_1080p(self):
        game = get_game("cyberpunk-2077")
        assert perf.estimate_fps(5, game, "4k", "high") < perf.estimate_fps(5, game, "1080p", "high")

    def test_light_game_runs_faster(self):
        cp = get_game("cyberpunk-2077")
        val = get_game("valorant")
        assert perf.estimate_fps(3, val, "1080p", "high") > perf.estimate_fps(3, cp, "1080p", "high")


class TestRequiredTiers:
    def test_valorant_needs_low_tier(self):
        game = get_game("valorant")
        assert perf.required_gpu_tier(game, "1080p", "high", 60) == 1

    def test_cyberpunk_4k_ultra_needs_top(self):
        game = get_game("cyberpunk-2077")
        assert perf.required_gpu_tier(game, "4k", "ultra", 60) >= 7

    def test_impossible_target_returns_none(self):
        game = get_game("cyberpunk-2077")
        assert perf.required_gpu_tier(game, "4k", "ultra", 500) is None

    def test_elden_ring_cap_blocks_144(self):
        game = get_game("elden-ring")
        assert perf.required_gpu_tier(game, "1080p", "high", 144) is None
        assert perf.required_gpu_tier(game, "1080p", "high", 60) is not None

    def test_hunt_showdown_cpu_heavy(self):
        game = get_game("hunt-showdown-1896")
        gpu_tier = perf.required_gpu_tier(game, "1080p", "low", 144)
        assert gpu_tier is not None
        # cpu_load 1.3 -> cpu tier well above gpu tier
        assert perf.required_cpu_tier(game, gpu_tier) > gpu_tier


class TestPartSelection:
    def test_gpu_selection_respects_vram(self):
        game = get_game("alan-wake-2")
        # 1080p wants 10GB VRAM -> tier 3 (RTX 4060, 8GB) is skipped at that tier
        gpu = perf.select_gpu_for_tier(3, game, "1080p")
        assert gpu is None or gpu["vram_gb"] >= 10

    def test_all_games_have_valid_data(self):
        for game in games_db().values():
            assert 0 < game["gpu_load"] <= 2
            assert 0 < game["cpu_load"] <= 2
            for res in ["1080p", "1440p", "4k"]:
                assert res in game["vram_gb"]
