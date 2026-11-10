from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from ghostlight import ideas, trends
from ghostlight.app import create_app
from ghostlight.channels import ensure_lineup
from ghostlight.db import Database


def test_radar_is_scored_and_sorted():
    when = datetime(2026, 5, 4, 12, tzinfo=timezone.utc)
    data = trends.radar(None, niches=["cosmic"], now=when, limit=6)

    assert data["catalog_count"] >= 6
    assert len(data["items"]) == 6
    scores = [row["opportunity"] for row in data["items"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= score <= 100 for score in scores)
    assert all(row["grade"] in {"hot", "rising", "steady", "cool"} for row in data["items"])
    assert all(row["niche"] == "cosmic" for row in data["items"])
    assert "opportunity" in data["note"].lower()


def test_radar_is_stable_within_a_day():
    when = datetime(2026, 5, 4, 8, tzinfo=timezone.utc)
    first = trends.radar(None, niches=["deep_sea"], now=when, limit=10)
    later = trends.radar(None, niches=["deep_sea"], now=when.replace(hour=20), limit=10)
    assert [r["opportunity"] for r in first["items"]] == [r["opportunity"] for r in later["items"]]


def test_top_for_channel_respects_its_niches(cfg, db):
    channel = db.create_channel({
        "id": "sea",
        "name": "Sea",
        "niches": ["deep_sea"],
        "styles": ["aurora"],
        "formats": ["short"],
        "times": ["09:00"],
    })
    signal = trends.top_for_channel(channel)
    assert signal is not None
    assert signal["niche"] == "deep_sea"
    assert "Current signal" in trends.guidance(signal)


def test_idea_wall_pitches_distinct_standalone_films(cfg, db):
    channel = db.create_channel({
        "id": "quiet",
        "name": "The Quiet Machine",
        "niches": ["quiet_tech"],
        "styles": ["neon"],
        "formats": ["short"],
        "times": ["08:30"],
    })
    wall = ideas.generate(cfg, db, channel, count=4, seed=7)

    assert wall["channel_id"] == "quiet"
    assert len(wall["items"]) == 4
    subjects = {item["subject"] for item in wall["items"]}
    assert len(subjects) == 4
    assert len({item["id"] for item in wall["items"]}) == 4
    assert all(item["niche"] == "quiet_tech" for item in wall["items"])
    assert all(item["guidance"] for item in wall["items"])
    assert "Pitches only" in wall["note"]


def test_radar_apis_serve_the_view(cfg):
    client = TestClient(create_app(cfg))
    ensure_lineup(cfg, Database(cfg.db_path))

    radar = client.get("/api/trends", params={"channel_id": "ghostlight", "limit": 5})
    assert radar.status_code == 200
    assert radar.json()["items"]
    assert radar.json()["live"] is False

    wall = client.post("/api/ideas", json={"channel_id": "ghostlight", "count": 2, "seed": 3})
    assert wall.status_code == 200
    assert len(wall.json()["items"]) == 2

    assert client.get("/api/trends", params={"channel_id": "nobody"}).status_code == 200
    assert client.post("/api/ideas", json={"channel_id": "nobody"}).status_code == 404


def test_calendar_and_brain_explain_the_network(cfg):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    ensure_lineup(cfg, db)

    calendar = client.get("/api/calendar", params={"days": 2}).json()
    assert len(calendar["days"]) == 2
    assert calendar["days"][0]["is_today"] is True
    assert calendar["days"][0]["slots"]
    assert all(
        slot["state"] in {"empty", "planned", "ready", "producing", "published", "done"}
        for day in calendar["days"] for slot in day["slots"]
    )

    brain = client.get("/api/brain").json()
    assert len(brain["channels"]) == 3
    assert all("recommendation" in c for c in brain["channels"])
    assert "note" in brain
    assert client.get("/api/brain", params={"channel_id": "nope"}).status_code == 404


def test_queueing_an_idea_creates_a_commission(cfg):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    ensure_lineup(cfg, db)

    created = client.post("/api/ideas/queue", json={
        "channel_id": "ghostlight",
        "title": "A Field Note on Fog",
        "subject": "fog",
        "niche": "liminal_places",
        "format": "short",
        "guidance": "hold the frame longer than feels comfortable",
    })
    assert created.status_code == 200
    video = created.json()
    assert video["status"] == "queued"
    assert video["channel_id"] == "ghostlight"
    stored = db.get_video(video["id"])
    assert stored["niche"] == "liminal_places"
    journal = db.list_journal(limit=5, channel_id="ghostlight")
    assert journal and journal[0]["headline"].startswith("Idea approved")
