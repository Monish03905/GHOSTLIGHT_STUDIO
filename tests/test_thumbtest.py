from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ghostlight import thumbtest
from ghostlight.app import create_app
from ghostlight.db import Database


def _plate(path: Path, colour: tuple[int, int, int]) -> Path:
    Image.new("RGB", (320, 180), colour).save(path, "JPEG")
    return path


def _film(db: Database, tmp_path: Path, *, youtube_id: str = "yt-film", takes: int = 3) -> dict:
    variants = []
    for index, name in enumerate(("hero", "close", "quiet")[:takes]):
        path = _plate(tmp_path / f"{name}.jpg", (20 + index * 40, 20, 40))
        variants.append({
            "id": name,
            "label": name.title(),
            "path": str(path),
            "recommended": index == 0,
        })
    db.create_video({
        "id": "film",
        "format": "short",
        "title": "Trial Film",
        "status": "published",
        "youtube_id": youtube_id,
        "thumb_variants": variants,
        "thumb_path": variants[0]["path"],
    })
    return db.get_video("film")


def test_a_trial_needs_a_live_film_and_two_takes(cfg, db, tmp_path):
    with pytest.raises(thumbtest.NotEligible):
        thumbtest.start(cfg, db, _film(db, tmp_path, youtube_id=""))

    with pytest.raises(thumbtest.NotEligible):
        thumbtest.start(cfg, db, _film(db, tmp_path, takes=1))


def test_trial_rotates_arms_and_crowns_the_winner(cfg, db, tmp_path):
    video = _film(db, tmp_path, takes=2)
    applied: list[str] = []

    def apply(path: str) -> bool:
        applied.append(path)
        return True

    start = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    test = thumbtest.start(cfg, db, video, hours=24, apply=apply, now=start)
    assert test["status"] == "running"
    assert test["arm_seconds"] == 24 * 3600
    assert applied == [video["thumb_variants"][0]["path"]]
    assert db.get_video("film")["thumb_path"] == applied[0]

    early = thumbtest.advance(cfg, db, video, apply=apply, now=start + timedelta(hours=1))
    assert early["samples"] == []

    windows: list[tuple[str, str]] = []

    def fetch(begin: str, end: str) -> dict:
        windows.append((begin, end))
        return {"views": 100 if len(windows) == 1 else 10, "watch_minutes": 50}

    second = thumbtest.advance(
        cfg, db, video, apply=apply, fetch_window=fetch, now=start + timedelta(hours=25),
    )
    assert len(second["samples"]) == 1
    assert applied[-1] == video["thumb_variants"][1]["path"]

    done = thumbtest.advance(
        cfg, db, video, apply=apply, fetch_window=fetch, now=start + timedelta(hours=50),
    )
    assert done["status"] == "concluded"
    assert done["winner"] == "hero"
    assert db.get_video("film")["thumb_path"] == video["thumb_variants"][0]["path"]
    assert len(done["samples"]) == 2

    status = thumbtest.status(db, "film")
    assert status["caveat"] == thumbtest.CAVEAT
    assert "views per equal window" in status["caveat"]


def test_no_views_is_inconclusive_and_keeps_the_studio_pick(cfg, db, tmp_path):
    video = _film(db, tmp_path, takes=2)
    start = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    thumbtest.start(cfg, db, video, hours=24, apply=lambda path: True, now=start)
    thumbtest.advance(cfg, db, video, apply=lambda path: True, fetch_window=lambda a, b: {},
                      now=start + timedelta(hours=25))
    done = thumbtest.advance(cfg, db, video, apply=lambda path: True, fetch_window=lambda a, b: {},
                             now=start + timedelta(hours=50))
    assert done["status"] == "inconclusive"
    assert done["winner"] == ""
    assert db.get_video("film")["thumb_path"] == video["thumb_variants"][0]["path"]


def test_stop_keeps_a_chosen_take_live(cfg, db, tmp_path):
    video = _film(db, tmp_path, takes=2)
    applied: list[str] = []
    start = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    thumbtest.start(cfg, db, video, hours=24, apply=lambda path: applied.append(path) or True, now=start)

    stopped = thumbtest.stop(cfg, db, video, keep="close", apply=lambda path: applied.append(path) or True)
    assert stopped["status"] == "stopped"
    assert stopped["winner"] == "close"
    assert applied[-1] == video["thumb_variants"][1]["path"]
    assert db.get_video("film")["thumb_path"] == video["thumb_variants"][1]["path"]

    with pytest.raises(thumbtest.ThumbTestError):
        thumbtest.stop(cfg, db, video)


def test_trial_api_needs_a_linked_channel(cfg, tmp_path):
    client = TestClient(create_app(cfg))
    _film(Database(cfg.db_path), tmp_path)

    assert client.get("/api/videos/film/thumbnail-test").json()["status"] == "none"
    blocked = client.post("/api/videos/film/thumbnail-test/start", json={})
    assert blocked.status_code == 400
    assert "Google" in blocked.json()["detail"]

    assert client.post("/api/videos/film/thumbnail-test/tick").status_code == 400
    assert client.get("/api/videos/nope/thumbnail-test").status_code == 404
