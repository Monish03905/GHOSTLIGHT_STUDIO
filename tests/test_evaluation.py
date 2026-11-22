from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ghostlight import evaluation
from ghostlight.app import create_app
from ghostlight.db import Database


def _narration(tmp_path: Path, count: int = 75, span: float = 30.0) -> str:
    work = tmp_path / "work"
    work.mkdir()
    step = span / count
    words = [
        {"text": f"w{i}", "start": round(i * step, 3), "end": round((i + 1) * step, 3)}
        for i in range(count)
    ]
    (work / "narration.json").write_text(json.dumps({"words": words}), encoding="utf-8")
    path = work / "narration.wav"
    path.write_bytes(b"RIFF")
    return str(path)


def _film(tmp_path: Path, **overrides) -> dict:
    captions = tmp_path / "captions.ass"
    captions.write_text("[Script Info]\n", encoding="utf-8")
    record = {
        "id": "film-readout",
        "title": "The Quiet Signal",
        "format": "short",
        "duration": 34.0,
        "words": 75,
        "novelty": 0.9,
        "narration_path": _narration(tmp_path),
        "captions_path": str(captions),
        "video_path": "",
        "script": {
            "hook": "Why does the signal arrive before it is sent?",
            "segments": [
                {"text": "The signal arrives before anyone sends it."},
                {"text": "Here is what that means for the quiet machine."},
            ],
        },
        "quality": {
            "ok": True,
            "hard_fail": False,
            "warnings": 1,
            "checks": [{"name": "file", "status": "pass", "detail": "ok"}],
        },
    }
    record.update(overrides)
    return record


def test_readout_scores_the_files_it_actually_has(tmp_path, cfg, db):
    report = evaluation.evaluate(_film(tmp_path))

    dims = {d["key"]: d for d in report["dimensions"]}
    assert dims["originality"]["score"] == 90
    assert dims["voice"]["score"] >= 90
    assert dims["captions"]["score"] < 100  # four seconds of drift
    assert dims["delivery"]["score"] == 94
    assert report["signals"] == 6
    assert report["signals_total"] == 7
    assert report["overall"] is not None
    assert "predict" in report["caveat"]
    assert any("drift" in note for note in report["notes"])


def test_readout_waits_for_an_unrendered_film(tmp_path):
    report = evaluation.evaluate(_film(tmp_path, narration_path="", captions_path="", quality={}))

    dims = {d["key"]: d for d in report["dimensions"]}
    assert dims["picture"]["score"] is None
    assert dims["captions"]["score"] is None
    assert dims["delivery"]["score"] is None
    assert dims["script"]["score"] is not None
    assert "voice" in {d["key"] for d in report["dimensions"]}


def test_readout_flags_rights_keywords_without_claiming_a_fact_check(tmp_path):
    film = _film(tmp_path)
    film["script"]["segments"].append({"text": "This is adapted from the book by a famous author."})
    report = evaluation.evaluate(film)

    rights = next(d for d in report["dimensions"] if d["key"] == "rights")
    assert rights["score"] < 100
    assert "heuristic" in rights["basis"]
    assert any("Rights review" in note for note in report["notes"])


def test_readout_endpoint_returns_and_404s(cfg):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    db.create_video({
        "id": "readout-api",
        "title": "A Film",
        "format": "short",
        "duration": 30.0,
        "novelty": 0.8,
        "script": {"hook": "What is this?", "segments": [{"text": "A quiet test of the readout."}]},
    })

    ok = client.get("/api/videos/readout-api/evaluation")
    assert ok.status_code == 200
    assert ok.json()["id"] == "readout-api"
    assert len(ok.json()["dimensions"]) == 7

    missing = client.get("/api/videos/nope/evaluation")
    assert missing.status_code == 404
