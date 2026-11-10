from __future__ import annotations

from fastapi.testclient import TestClient

from ghostlight import quality
from ghostlight.app import create_app
from ghostlight.channels import ensure_lineup
from ghostlight.db import Database


def _bare_video(**overrides):
    record = {
        "id": "film-1",
        "format": "short",
        "title": "A Test Film",
        "description": "x" * 200,
        "video_path": "",
        "duration": 30.0,
        "novelty": 0.9,
        "channel_id": "ghostlight",
    }
    record.update(overrides)
    return record


def test_gate_blocks_when_the_render_is_missing(cfg, db):
    channel = {"id": "ghostlight", "name": "Ghostlight"}
    report = quality.inspect(cfg, _bare_video(), channel)

    assert report["hard_fail"] is True
    assert report["ok"] is False
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert statuses["file"] == "fail"
    assert "Gate blocked" in quality.summary(report)
    assert quality.passes(report) is False


def test_gate_passes_hard_checks_without_a_probe(tmp_path, cfg):
    # A file too small is a hard fail; a plausible one only gets notes when
    # ffprobe is unavailable or the container looks thin.
    small = tmp_path / "tiny.mp4"
    small.write_bytes(b"0" * 1000)
    report = quality.inspect(cfg, _bare_video(video_path=str(small)), None)
    assert report["hard_fail"] is True
    assert any(c["name"] == "file" and c["status"] == "fail" for c in report["checks"])


def test_channel_approval_round_trips_through_the_api(cfg):
    client = TestClient(create_app(cfg))
    ensure_lineup(cfg, Database(cfg.db_path))

    listed = client.get("/api/channels").json()["items"]
    assert all(c["approval"] == "auto" for c in listed)

    patched = client.patch("/api/channels/ghostlight", json={"approval": "review"})
    assert patched.status_code == 200
    assert patched.json()["approval"] == "review"

    bad = client.patch("/api/channels/ghostlight", json={"approval": "sometimes"})
    assert bad.status_code == 400

    created = client.post("/api/channels", json={
        "name": "Review Voice",
        "niches": ["cosmic"],
        "styles": ["aurora"],
        "formats": ["short"],
        "times": ["21:00"],
        "approval": "review",
    })
    assert created.status_code == 200
    assert created.json()["approval"] == "review"


def test_quality_endpoint_reports_and_stores(cfg):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    ensure_lineup(cfg, db)
    db.create_video({
        "id": "no-file",
        "format": "short",
        "title": "Nothing Rendered",
        "description": "short",
        "channel_id": "ghostlight",
    })

    assert client.get("/api/videos/missing/quality").status_code == 404

    resp = client.get("/api/videos/no-file/quality")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["quality"]["hard_fail"] is True
    assert "Gate blocked" in payload["summary"]
    assert db.get_video("no-file")["quality"]["hard_fail"] is True


def test_publish_and_approve_refuse_a_blocked_film(cfg):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    ensure_lineup(cfg, db)
    db.create_video({
        "id": "blocked",
        "format": "short",
        "title": "Blocked Film",
        "channel_id": "ghostlight",
        "status": "ready",
    })

    published = client.post("/api/videos/blocked/publish", json={})
    assert published.status_code == 400
    assert "quality gate" in published.json()["detail"]

    approved = client.post("/api/videos/blocked/approve", json={})
    assert approved.status_code == 400
