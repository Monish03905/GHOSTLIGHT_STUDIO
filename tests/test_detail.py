from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ghostlight.app import create_app
from ghostlight.channels import ensure_lineup
from ghostlight.db import Database


def test_video_detail_reads_chapters_from_narration(cfg, tmp_path):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    ensure_lineup(cfg, db)

    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"")
    (tmp_path / "narration.json").write_text(json.dumps({
        "segments": [
            {"heading": "Opening", "start": 1.5, "end": 5.0, "text": "the cold open"},
            {"heading": "", "start": 6.0, "end": 9.0, "text": "the quiet machine listens for a signal"},
            {"heading": "Broken", "start": 9.4, "end": 9.0, "text": "ignored"},
        ],
    }), encoding="utf-8")
    db.create_video({
        "id": "with-chapters",
        "format": "long",
        "title": "A Reel",
        "description": "x" * 120,
        "channel_id": "ghostlight",
        "narration_path": str(narration),
    })

    detail = client.get("/api/videos/with-chapters")
    assert detail.status_code == 200
    payload = detail.json()
    labels = [chapter["label"] for chapter in payload["chapters"]]
    assert labels == ["Opening", "the quiet machine listens for a"]
    assert payload["chapters"][0]["start"] == 1.5
    assert payload["chapters"][0]["end"] == 5.0
