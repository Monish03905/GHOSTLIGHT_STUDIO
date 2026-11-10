from __future__ import annotations

from fastapi.testclient import TestClient

from ghostlight.app import create_app
from ghostlight.db import Database  # noqa: F401


def _observatory(cfg) -> dict:
    response = TestClient(create_app(cfg)).get("/api/observatory")
    assert response.status_code == 200
    return response.json()


def test_observatory_provider_bench_is_honest(cfg, db):
    cfg.set("script.provider", "offline")
    payload = _observatory(cfg)

    providers = {row["id"]: row for row in payload["providers"]}
    assert set(providers) == {"writer", "voice", "score", "art", "render", "trends", "publishing"}
    assert providers["writer"]["available"] is True
    assert providers["writer"]["provider"] == "offline"
    assert providers["writer"]["local"] is True
    assert providers["score"]["local"] is True
    assert providers["art"]["local"] is True
    assert providers["publishing"]["available"] is False
    assert "OAuth" in providers["publishing"]["detail"]
    assert payload["as_of"].endswith("+00:00")


def test_observatory_ledger_counts_measured_usage(cfg, db):
    cfg.set("costs.writer_per_1k_words", 2.0)
    cfg.set("costs.voice_per_minute", 0.5)
    cfg.set("costs.render_per_minute", 1.0)
    cfg.set("costs.storage_per_gb_month", 0.0)

    db.create_video({
        "id": "film-one",
        "title": "A Long Film",
        "channel_id": "ghostlight",
        "words": 1500,
        "duration": 120,
        "narration_path": "data/videos/film-one/narration.wav",
        "video_path": "data/videos/film-one/film.mp4",
        "youtube_id": "abc123",
        "status": "published",
    })
    db.create_video({
        "id": "film-two",
        "title": "A Draft",
        "words": 500,
        "duration": 60,
        "narration_path": "",
        "status": "drafting",
    })
    db.create_video({
        "id": "clip-one",
        "title": "A Clip",
        "kind": "clip",
        "parent_id": "film-one",
        "words": 120,
        "duration": 20,
    })

    ledger = _observatory(cfg)["ledger"]
    totals = ledger["totals"]
    assert totals["films"] == 2
    assert totals["clips"] == 1
    assert totals["words"] == 2000
    assert totals["voiced_minutes"] == 2.0
    assert totals["render_minutes"] == 2.0
    assert totals["uploads"] == 1
    assert totals["estimate"] == 7.0
    assert totals["recurring"] == 0.0

    lines = {line["key"]: line for line in ledger["lines"]}
    assert lines["writer"]["usage"] == 2000
    assert lines["writer"]["estimate"] == 4.0
    assert lines["voice"]["estimate"] == 1.0
    assert lines["render"]["estimate"] == 2.0

    channels = {row["id"]: row for row in ledger["channels"]}
    assert channels["ghostlight"]["films"] == 1
    assert channels["ghostlight"]["uploads"] == 1
    assert channels["ghostlight"]["estimate"] == 6.0
    assert channels[""]["name"] == "Unassigned"
    assert channels[""]["films"] == 1
    assert channels[""]["estimate"] == 1.0
    assert "not a bill" in ledger["note"]


def test_observatory_pipeline_reads_artifacts_and_stage_trail(cfg, db):
    db.create_video({
        "id": "film-one",
        "title": "A Long Film",
        "words": 900,
        "duration": 180,
        "narration_path": "narration.wav",
        "music_path": "music.wav",
        "video_path": "film.mp4",
        "quality": {"score": 88},
        "youtube_id": "abc123",
        "status": "published",
    })
    db.create_video({
        "id": "film-two",
        "title": "A Draft",
        "words": 300,
        "status": "drafting",
    })
    db.log_event("info", "stage", "Voice recorded.", "film-one",
                 {"stage": "narration", "progress": 25})
    db.log_event("info", "stage", "Film is ready.", "film-one",
                 {"stage": "ready", "progress": 95})

    pipeline = _observatory(cfg)["pipeline"]

    films = {row["id"]: row for row in pipeline["films"]}
    assert films["film-one"]["progress"] == 100
    assert all(stage["done"] for stage in films["film-one"]["stages"])
    assert films["film-two"]["progress"] == 17
    assert [stage["done"] for stage in films["film-two"]["stages"]] == [
        True, False, False, False, False, False,
    ]

    trail = films["film-one"]["trail"]
    assert [item["stage"] for item in trail] == ["narration", "ready"]
    assert trail[0]["progress"] == 25

    recent = pipeline["recent"]
    assert recent[0]["stage"] == "ready"
    assert recent[0]["title"] == "A Long Film"
    assert recent[1]["stage"] == "narration"
    assert pipeline["status_counts"]["published"] == 1
    assert pipeline["status_counts"]["drafting"] == 1
