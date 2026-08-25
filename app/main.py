"""PC Maker API.

Run: uvicorn app.main:app --reload
"""

import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import builder
from app.data import games_db, parts_db
from app.pricing import BestBuyPricer

app = FastAPI(title="PC Maker", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

pricer = BestBuyPricer()
_build_cache = {}  # (request tuple) -> (result, timestamp)


class BuildRequest(BaseModel):
    game_id: str
    resolution: str = Field(default="1080p", pattern="^(1080p|1440p|4k)$")
    settings: str = Field(default="high", pattern="^(low|medium|high|ultra)$")
    target_fps: int = Field(default=60, ge=30, le=480)
    budget_usd: float | None = Field(default=None, gt=0)


@app.get("/api/games")
def list_games():
    return {
        "games": sorted(
            (
                {
                    "id": g["id"],
                    "name": g["name"],
                    "genre": g["genre"],
                    "notes": g.get("notes", ""),
                    "fps_cap": g.get("fps_cap"),
                }
                for g in games_db().values()
            ),
            key=lambda g: g["name"].lower(),
        )
    }


@app.get("/api/games/{game_id}")
def get_game(game_id: str):
    game = games_db().get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"Unknown game: {game_id}")
    return game


@app.post("/api/builds")
def create_builds(req: BuildRequest):
    key = (
        req.game_id,
        req.resolution,
        req.settings,
        req.target_fps,
        req.budget_usd,
        pricer.enabled,
    )
    cached = _build_cache.get(key)
    if cached and time.time() - cached[1] < 600:
        return cached[0]

    try:
        result = builder.generate_builds(
            game_id=req.game_id,
            resolution=req.resolution,
            settings=req.settings,
            target_fps=req.target_fps,
            budget_usd=req.budget_usd,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except builder.BuildImpossibleError as e:
        raise HTTPException(status_code=422, detail=str(e))

    pricer.enrich_builds(result)
    result["live_pricing"] = pricer.enabled
    _build_cache[key] = (result, time.time())
    return result


@app.get("/api/parts")
def list_parts(category: str = Query(description="One of: " + ", ".join(parts_db().keys()))):
    if category not in parts_db():
        raise HTTPException(status_code=404, detail=f"Unknown category: {category}")
    return {"category": category, "parts": parts_db()[category]}


@app.get("/api/health")
def health():
    return {"status": "ok", "live_pricing": pricer.enabled}
