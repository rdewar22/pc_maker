"""Load curated parts, games, and performance model data."""

import json
from pathlib import Path
from functools import lru_cache

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

PART_CATEGORIES = [
    "gpus",
    "cpus",
    "motherboards",
    "ram",
    "storage",
    "psus",
    "cases",
    "coolers",
]


def _load(name: str) -> dict:
    with open(DATA_DIR / f"{name}.json", "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def parts_db() -> dict:
    """Return the parts database keyed by category."""
    raw = _load("parts")
    return {cat: raw[cat] for cat in PART_CATEGORIES}


@lru_cache(maxsize=1)
def games_db() -> dict:
    """Return games keyed by game id."""
    raw = _load("games")
    return {g["id"]: g for g in raw["games"]}


@lru_cache(maxsize=1)
def prebuilts_db() -> list:
    """Return the curated prebuilt systems list."""
    return _load("prebuilts")["prebuilts"]


@lru_cache(maxsize=1)
def perf_model() -> dict:
    raw = _load("perf")["_meta"]
    return {
        "gpu_tier_base_fps": {int(k): v for k, v in raw["gpu_tier_base_fps"].items()},
        "resolution_mult": raw["resolution_mult"],
        "settings_mult": raw["settings_mult"],
    }


def get_game(game_id: str) -> dict:
    game = games_db().get(game_id)
    if game is None:
        raise KeyError(f"Unknown game: {game_id}")
    return game


def find_part(category: str, part_id: str) -> dict:
    for part in parts_db()[category]:
        if part["id"] == part_id:
            return part
    raise KeyError(f"Unknown {category} part: {part_id}")
