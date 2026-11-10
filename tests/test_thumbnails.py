from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ghostlight.app import create_app
from ghostlight.channels import ensure_lineup
from ghostlight.db import Database
from ghostlight.render import make_thumbnail_variants


def _plate(path: Path, colour: tuple[int, int, int]) -> Path:
    Image.new("RGB", (640, 360), colour).save(path, "JPEG")
    return path


def test_three_treatments_with_one_recommendation(tmp_path):
    sources = [
        _plate(tmp_path / "a.jpg", (20, 24, 42)),
        _plate(tmp_path / "b.jpg", (80, 40, 20)),
        _plate(tmp_path / "c.jpg", (12, 12, 12)),
    ]
    variants = make_thumbnail_variants(
        sources,
        tmp_path / "thumbs",
        title="The Sound of a Black Hole",
        kicker="Short · Cosmic",
        palette_name="cosmic_indigo",
        brand="Ghostlight",
    )

    assert [v["id"] for v in variants] == ["hero", "close", "quiet"]
    assert sum(1 for v in variants if v["recommended"]) == 1
    assert all(Path(str(v["path"])).is_file() for v in variants)
    assert all(float(v["contrast"]) >= 0 for v in variants)
    assert all(v["rationale"] for v in variants)

    sizes = {Image.open(str(v["path"])).size for v in variants}
    assert sizes == {(1280, 720)}


def test_thumbnail_choice_round_trips(cfg, tmp_path):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    ensure_lineup(cfg, db)

    hero = _plate(tmp_path / "hero.jpg", (30, 30, 60))
    close = _plate(tmp_path / "close.jpg", (90, 60, 30))
    db.create_video({
        "id": "thumbs",
        "format": "short",
        "title": "Thumb Test",
        "channel_id": "ghostlight",
        "thumb_variants": [
            {"id": "hero", "label": "Hero plate", "path": str(hero), "recommended": True},
            {"id": "close", "label": "Close-up", "path": str(close), "recommended": False},
        ],
    })

    chosen = client.post("/api/videos/thumbs/thumbnail", json={"variant": "close"})
    assert chosen.status_code == 200
    assert chosen.json()["thumb_path"] == str(close)
    stored = db.get_video("thumbs")
    assert stored["thumb_path"] == str(close)
    flags = {v["id"]: v["recommended"] for v in stored["thumb_variants"]}
    assert flags == {"hero": False, "close": True}

    served = client.get("/api/videos/thumbs/file/thumb", params={"variant": "hero"})
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/jpeg")

    assert client.post("/api/videos/thumbs/thumbnail", json={"variant": "nope"}).status_code == 404
