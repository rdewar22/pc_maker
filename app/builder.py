"""Build generator: game requirements -> complete compatible part lists."""

import itertools

from app.data import parts_db, get_game, prebuilts_db
from app import perf as perf_mod
from app import compat
from app import retail

VARIANTS = [
    {"name": "value", "gpu_tier_offset": 0, "min_ram_gb": 16, "storage_gb": 1000},
    {"name": "balanced", "gpu_tier_offset": 1, "min_ram_gb": 32, "storage_gb": 1000},
    {"name": "headroom", "gpu_tier_offset": 2, "min_ram_gb": 32, "storage_gb": 2000},
]


class BuildImpossibleError(Exception):
    pass


def _cheapest_compatible_core(gpu: dict, cpu: dict, min_ram_gb: int, storage_gb: int) -> dict:
    """Greedy search for the cheapest fully compatible set of remaining parts.

    Candidate lists are sorted by price; we take the first fully compatible
    combination found, exploring up to a few options per category.
    """
    mobo_candidates = sorted(
        [m for m in parts_db()["motherboards"] if m["socket"] == cpu["socket"]],
        key=lambda m: m["price_usd"],
    )
    ram_candidates = sorted(
        [r for r in parts_db()["ram"] if r["capacity_gb"] >= min_ram_gb],
        key=lambda r: r["price_usd"],
    )
    storage_candidates = sorted(
        [s for s in parts_db()["storage"] if s["capacity_gb"] >= storage_gb],
        key=lambda s: s["price_usd"],
    )
    psu_min = compat.recommended_psu_wattage({"cpu": cpu, "gpu": gpu})
    psu_candidates = sorted(
        [p for p in parts_db()["psus"] if p["wattage"] >= psu_min],
        key=lambda p: p["price_usd"],
    )
    case_candidates = sorted(parts_db()["cases"], key=lambda c: c["price_usd"])

    if cpu["includes_cooler"]:
        cooler_options = [None]
    else:
        cooler_candidates = sorted(
            [c for c in parts_db()["coolers"] if c["tdp_capacity_w"] >= cpu["tdp_w"]],
            key=lambda c: c["price_usd"],
        )
        cooler_options = cooler_candidates[:3] or [None]

    best = None
    best_price = float("inf")
    for mobo, ram, storage, psu, case, cooler in itertools.product(
        mobo_candidates[:3],
        ram_candidates[:3],
        storage_candidates[:2],
        psu_candidates[:3],
        case_candidates[:3],
        cooler_options,
    ):
        build = {
            "gpu": gpu,
            "cpu": cpu,
            "motherboard": mobo,
            "ram": ram,
            "storage": storage,
            "psu": psu,
            "case": case,
            "cooler": cooler,
        }
        if not compat.is_compatible(build):
            continue
        price = sum(p["price_usd"] for p in build.values() if p)
        if price < best_price:
            best, best_price = build, price
    if best is None:
        raise BuildImpossibleError("No compatible combination of parts found")
    return best


def matching_prebuilts(game: dict, resolution: str, settings: str, target_fps: int) -> list:
    """Prebuilts that meet the game target, cheapest first, with FPS estimates and links."""
    required_gpu = perf_mod.required_gpu_tier(game, resolution, settings, target_fps)
    if required_gpu is None:
        return []
    required_cpu = perf_mod.required_cpu_tier(game, required_gpu)
    min_vram = perf_mod.required_vram_gb(game, resolution)

    matches = []
    for pb in prebuilts_db():
        if pb["gpu_tier"] < required_gpu or pb["cpu_tier"] < required_cpu:
            continue
        if pb["vram_gb"] < min_vram:
            continue
        matches.append(
            {
                **pb,
                "retail_urls": retail.retail_links(pb),
                "estimated_fps": int(
                    perf_mod.estimate_fps(pb["gpu_tier"], game, resolution, settings)
                ),
            }
        )
    return sorted(matches, key=lambda p: p["price_usd"])[:4]


def generate_builds(
    game_id: str,
    resolution: str = "1080p",
    settings: str = "high",
    target_fps: int = 60,
    budget_usd: float = None,
) -> dict:
    """Generate up to 3 builds (value / balanced / headroom) for a game request."""
    game = get_game(game_id)
    notes = [game.get("notes", "")] if game.get("notes") else []

    tier = perf_mod.required_gpu_tier(game, resolution, settings, target_fps)
    if tier is None:
        cap = game.get("fps_cap")
        if cap and target_fps > cap:
            raise BuildImpossibleError(
                f"{game['name']} is engine-capped at {cap} FPS; target of {target_fps} is unreachable"
            )
        best = perf_mod.max_achievable_fps(game, resolution, settings)
        raise BuildImpossibleError(
            f"No GPU in the database can hit {target_fps} FPS in {game['name']} "
            f"at {resolution}/{settings} (best estimate: ~{best} FPS)"
        )

    builds = []
    for variant in VARIANTS:
        gpu_tier = tier + variant["gpu_tier_offset"]
        gpu = perf_mod.select_gpu_for_tier(gpu_tier, game, resolution)
        if gpu is None:
            # No GPU at that tier with enough VRAM; try one tier higher.
            gpu = perf_mod.select_gpu_for_tier(gpu_tier + 1, game, resolution)
            if gpu is None:
                continue
        cpu_tier = perf_mod.required_cpu_tier(game, gpu["tier"])
        cpu = perf_mod.select_cpu_for_tier(cpu_tier)
        if cpu is None:
            cpu_tier = min(8, cpu_tier + 1)
            cpu = perf_mod.select_cpu_for_tier(cpu_tier)
            if cpu is None:
                continue

        try:
            parts = _cheapest_compatible_core(
                gpu, cpu, variant["min_ram_gb"], variant["storage_gb"]
            )
        except BuildImpossibleError:
            continue

        total = sum(p["price_usd"] for p in parts.values() if p)
        builds.append(
            {
                "variant": variant["name"],
                "estimated_fps": int(
                    perf_mod.estimate_fps(gpu["tier"], game, resolution, settings)
                ),
                "target_met": True,
                "parts": parts,
                "total_price_usd": total,
                "compatibility_errors": compat.check_compatibility(parts),
                "system_draw_w": compat.BASE_SYSTEM_DRAW_W
                + cpu["tdp_w"]
                + gpu["tdp_w"],
            }
        )

    if not builds:
        raise BuildImpossibleError(
            f"Could not assemble a compatible build for {game['name']} at {resolution}/{settings}/{target_fps} FPS"
        )

    if budget_usd is not None:
        within = [b for b in builds if b["total_price_usd"] <= budget_usd]
        if within:
            builds = within
        else:
            cheapest = min(builds, key=lambda b: b["total_price_usd"])
            notes.append(
                f"Budget ${budget_usd:g} is below the cheapest compatible build "
                f"(${cheapest['total_price_usd']}). Showing all variants anyway."
            )

    return {
        "game": game,
        "resolution": resolution,
        "settings": settings,
        "target_fps": target_fps,
        "builds": builds,
        "prebuilts": matching_prebuilts(game, resolution, settings, target_fps),
        "notes": [n for n in notes if n],
    }
