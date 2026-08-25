import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


class TestApi:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_games_list(self, client):
        games = client.get("/api/games").json()["games"]
        ids = [g["id"] for g in games]
        assert "hunt-showdown-1896" in ids
        assert "cyberpunk-2077" in ids

    def test_build_request(self, client):
        r = client.post(
            "/api/builds",
            json={"game_id": "hunt-showdown-1896", "resolution": "1080p",
                  "settings": "low", "target_fps": 144},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["live_pricing"] is False
        build = body["builds"][0]
        assert build["compatibility_errors"] == []
        assert build["parts"]["gpu"]["effective_price_usd"] > 0

    def test_unknown_game_404(self, client):
        r = client.post("/api/builds", json={"game_id": "nope"})
        assert r.status_code == 404

    def test_impossible_build_422(self, client):
        r = client.post(
            "/api/builds",
            json={"game_id": "elden-ring", "resolution": "1080p",
                  "settings": "high", "target_fps": 144},
        )
        assert r.status_code == 422
        assert "capped" in r.json()["detail"]

    def test_invalid_resolution_rejected(self, client):
        r = client.post("/api/builds", json={"game_id": "valorant", "resolution": "720p"})
        assert r.status_code == 422

    def test_require_in_stock_accepted(self, client):
        r = client.post(
            "/api/builds",
            json={"game_id": "valorant", "target_fps": 144, "require_in_stock": True},
        )
        assert r.status_code == 200
        for build in r.json()["builds"]:
            assert build.get("stock_swaps") == []

    def test_parts_endpoint(self, client):
        r = client.get("/api/parts", params={"category": "gpus"})
        assert r.status_code == 200
        assert len(r.json()["parts"]) >= 5
        assert client.get("/api/parts", params={"category": "toasters"}).status_code == 404
