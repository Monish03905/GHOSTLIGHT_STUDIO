from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ghostlight.app import create_app
from ghostlight.db import Database


def _thumb(path: Path) -> Path:
    Image.new("RGB", (320, 180), (30, 40, 70)).save(path, "JPEG")
    return path


def _film(db: Database, **overrides) -> dict:
    record = {
        "id": "public-film",
        "format": "short",
        "title": "The Quiet Signal",
        "status": "published",
        "hook": "A radio that only plays tomorrow.",
        "description": "A film about waiting.\n\nAnd about listening.",
        "tags": ["quiet_tech", "radio"],
        "duration": 42,
        "published_at": "2026-11-05T18:30:00+00:00",
        **overrides,
    }
    db.create_video(record)
    return db.get_video(str(record["id"]))


def test_show_lists_only_published_films(cfg, db):
    _film(db)
    db.create_video({"id": "draft", "format": "short", "title": "A Draft", "status": "ready"})
    db.create_video({
        "id": "gone", "format": "short", "title": "An Archived Film",
        "status": "published", "archived": 1,
    })

    client = TestClient(create_app(cfg))
    page = client.get("/show")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "The Quiet Signal" in page.text
    assert "/show/public-film" in page.text
    assert "A Draft" not in page.text
    assert "An Archived Film" not in page.text
    assert "/feed.xml" in page.text
    assert "No faces. No repeats." in page.text


def test_empty_show_has_a_curtain(cfg):
    page = TestClient(create_app(cfg)).get("/show")
    assert page.status_code == 200
    assert "The curtain is still down." in page.text


def test_film_page_escapes_copy_and_hides_drafts(cfg, db):
    _film(db, title="<script>alert(1)</script>", description="Line one\n\nLine <b>two</b>")
    db.create_video({"id": "draft", "format": "short", "title": "A Draft", "status": "ready"})

    client = TestClient(create_app(cfg))
    page = client.get("/show/public-film")
    assert page.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert "Line one" in page.text
    assert "Line &lt;b&gt;two&lt;/b&gt;" in page.text

    assert client.get("/show/draft").status_code == 404
    assert client.get("/show/missing").status_code == 404


def test_open_graph_uses_the_public_address(cfg, db, tmp_path):
    cfg.set("social.public_url", "https://films.example.com/")
    thumb = _thumb(tmp_path / "thumb.jpg")
    _film(db, thumb_path=str(thumb))

    page = TestClient(create_app(cfg)).get("/show")
    assert 'property="og:image"' in page.text
    assert "https://films.example.com/api/videos/public-film/file/thumb" in page.text
    assert 'property="og:url" content="https://films.example.com/show"' in page.text
