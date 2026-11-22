from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ghostlight import series
from ghostlight.app import create_app
from ghostlight.events import EventBus
from ghostlight.scheduler import Scheduler


class _Studio:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.youtube = None

    def is_busy(self) -> bool:
        return False

    def queue_size(self) -> int:
        return 0

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "episode-film"}


def test_create_sets_the_first_slot_and_guidance(cfg, db):
    now = datetime(2026, 11, 2, 9, 30, tzinfo=cfg.timezone())
    item = series.create(cfg, db, {
        "title": "Small Machines",
        "premise": "Everyday devices with secret lives.",
        "niche": "quiet_tech",
        "cadence_days": 2,
        "time": "18:30",
        "max_episodes": 3,
    }, now=now)

    assert item["id"] == "small-machines"
    assert item["next_at"].startswith("2026-11-02T18:30")
    assert item["enabled"] == 1

    text = series.guidance(item, 2)
    assert "Episode 2" in text
    assert "standalone" in text
    assert "Do not continue or reference any earlier episode." in text


def test_validation_and_duplicate_titles(cfg, db):
    with pytest.raises(series.SeriesError):
        series.create(cfg, db, {"title": ""})
    with pytest.raises(series.SeriesError):
        series.create(cfg, db, {"title": "Odd", "niche": "made_up"})
    with pytest.raises(series.SeriesError):
        series.create(cfg, db, {"title": "Odd", "time": "25:99"})

    series.create(cfg, db, {"title": "Odd"})
    second = series.create(cfg, db, {"title": "Odd"})
    assert second["id"] == "odd-2"


def test_update_recomputes_the_next_slot(cfg, db):
    now = datetime(2026, 11, 2, 9, 30, tzinfo=cfg.timezone())
    item = series.create(cfg, db, {"title": "Evening", "time": "20:00"}, now=now)
    assert item["next_at"].startswith("2026-11-02T20:00")

    changed = series.update(cfg, db, item["id"], {"time": "21:15"}, now=now)
    assert changed["time"] == "21:15"
    assert changed["next_at"].startswith("2026-11-02T21:15")


def test_advance_stops_at_the_cap(cfg, db):
    now = datetime(2026, 11, 2, 9, 30, tzinfo=cfg.timezone())
    item = series.create(cfg, db, {"title": "Capped", "time": "10:00", "max_episodes": 1}, now=now)
    done = series.advance(db, item, "ep-1", now + timedelta(hours=1))

    assert done["episodes"] == 1
    assert done["enabled"] == 0
    assert done["last_episode_id"] == "ep-1"
    assert series.public(done)["complete"] is True
    assert series.due(db, now + timedelta(days=2)) == []


def test_scheduler_fires_a_due_series_as_a_standalone_short(cfg, db):
    cfg.set("autopilot.enabled", False)
    cfg.set("schedule.enabled", True)
    cfg.set("schedule.paused", False)
    now = datetime.now(cfg.timezone())
    item = series.create(cfg, db, {"title": "Nightly", "time": "00:01"}, now=now)
    db.update_series(item["id"], next_at=(now - timedelta(minutes=5)).isoformat(timespec="minutes"))

    studio = _Studio()
    scheduler = Scheduler(cfg, db, EventBus(db), studio)
    scheduler._tick()

    assert len(studio.calls) == 1
    call = studio.calls[0]
    assert call["fmt"] == "short"
    assert "Do not continue or reference any earlier episode." in call["guidance"]
    assert db.get_series(item["id"])["episodes"] == 1
    assert db.get_series(item["id"])["last_episode_id"] == "episode-film"


def test_series_api_round_trip(cfg):
    client = TestClient(create_app(cfg))

    created = client.post("/api/series", json={
        "title": "Tiny Rituals", "time": "07:00", "cadence_days": 1,
        "niche": "quiet_tech",
    })
    assert created.status_code == 200
    body = created.json()
    assert body["id"] == "tiny-rituals"
    assert body["enabled"] == 1

    assert client.get("/api/series").json()["count"] == 1
    assert client.get("/api/series/tiny-rituals").json()["cadence_days"] == 1

    patched = client.patch("/api/series/tiny-rituals", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] == 0

    assert client.post("/api/series", json={"title": ""}).status_code == 400
    assert client.patch("/api/series/nope", json={"enabled": False}).status_code == 404

    fired = client.post("/api/series/tiny-rituals/fire")
    assert fired.status_code == 200
    assert fired.json()["episode"]["id"]
    assert fired.json()["series"]["episodes"] == 1

    assert client.delete("/api/series/tiny-rituals").status_code == 200
    assert client.get("/api/series").json()["count"] == 0
