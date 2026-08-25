"""Performance estimation: game + resolution + settings + target FPS -> required hardware tiers."""

from app.data import perf_model, parts_db


def estimate_fps(gpu_tier: int, game: dict, resolution: str, settings: str) -> float:
    """Estimated average FPS for a GPU tier in a given game at resolution/settings."""
    m = perf_model()
    base = m["gpu_tier_base_fps"][gpu_tier]
    return (
        base
        * m["resolution_mult"][resolution]
        * m["settings_mult"][settings]
        / game["gpu_load"]
    )


def required_gpu_tier(game: dict, resolution: str, settings: str, target_fps: int) -> int:
    """Smallest GPU tier that meets target FPS. Returns None if impossible."""
    if game.get("fps_cap") and target_fps > game["fps_cap"]:
        return None
    for tier in sorted(perf_model()["gpu_tier_base_fps"]):
        if estimate_fps(tier, game, resolution, settings) >= target_fps:
            return tier
    return None


def required_vram_gb(game: dict, resolution: str) -> int:
    return game["vram_gb"].get(resolution, 8)


def required_cpu_tier(game: dict, gpu_tier: int) -> int:
    """CPU tier that avoids bottlenecking the chosen GPU tier, weighted by game CPU load."""
    import math

    return max(1, min(8, math.ceil(gpu_tier * game["cpu_load"])))


def max_achievable_fps(game: dict, resolution: str, settings: str) -> int:
    """Best FPS with the strongest GPU in the database (capped by any engine fps cap)."""
    best = max(perf_model()["gpu_tier_base_fps"])
    fps = estimate_fps(best, game, resolution, settings)
    cap = game.get("fps_cap")
    return int(min(fps, cap)) if cap else int(fps)


def gpu_meets_vram(gpu: dict, game: dict, resolution: str) -> bool:
    return gpu["vram_gb"] >= required_vram_gb(game, resolution)


def select_gpu_for_tier(tier: int, game: dict, resolution: str) -> dict:
    """Cheapest GPU at exactly the given tier that satisfies VRAM needs."""
    candidates = [
        g
        for g in parts_db()["gpus"]
        if g["tier"] == tier and gpu_meets_vram(g, game, resolution)
    ]
    return min(candidates, key=lambda g: g["price_usd"]) if candidates else None


def select_cpu_for_tier(tier: int) -> dict:
    """Cheapest CPU at exactly the given tier."""
    candidates = [c for c in parts_db()["cpus"] if c["tier"] == tier]
    return min(candidates, key=lambda c: c["price_usd"]) if candidates else None
