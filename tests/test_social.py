from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from ghostlight import net, social
from ghostlight.app import create_app
from ghostlight.db import Database


@pytest.fixture(autouse=True)
def _clean_transport():
    net.reset_transport()
    yield
    net.reset_transport()


def _connect(cfg):
    cfg.set("social.enabled", True)
    cfg.set("social.public_url", "https://studio.test")
    cfg.set("social.instagram.enabled", True)
    cfg.set("social.instagram.account_id", "ig-123")
    cfg.set("social.tiktok.enabled", True)
    cfg.set("social.tiktok.client_key", "tt-key")
    folder = cfg.secrets_dir / "social"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "instagram.json").write_text('{"access_token": "ig-token"}', encoding="utf-8")
    (folder / "tiktok.json").write_text('{"access_token": "tt-token"}', encoding="utf-8")


def _video(tmp_path, **overrides):
    path = tmp_path / "film.mp4"
    path.write_bytes(b"0" * 2048)
    record = {
        "id": "film-1",
        "format": "short",
        "title": "A Small Signal",
        "description": "A film about listening.",
        "video_path": str(path),
    }
    record.update(overrides)
    return record


def _meta():
    return {"title": "A Small Signal", "description": "A film about listening. #signal", "share_text": "A Small Signal #signal"}


def test_status_says_why_a_target_is_not_ready(cfg, db):
    off = social.status(cfg, db)
    assert off["enabled"] is False
    assert off["targets"]["instagram"]["ready"] is False
    assert "switched off" in off["targets"]["instagram"]["reason"]

    _connect(cfg)
    ready = social.status(cfg, db)
    assert ready["targets"]["instagram"]["ready"] is True
    assert ready["targets"]["tiktok"]["ready"] is True
    assert "ig-token" not in str(ready)


def test_media_links_are_signed_and_expire(cfg):
    _connect(cfg)
    url = social.media_url(cfg, "film-1")
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://studio.test/api/social/media/film-1?")
    assert social.verify_media(cfg, "film-1", int(query["expires"][0]), query["sig"][0])
    assert not social.verify_media(cfg, "film-2", int(query["expires"][0]), query["sig"][0])
    assert not social.verify_media(cfg, "film-1", int(query["expires"][0]), "nope")


def test_media_url_needs_a_public_https_address(cfg):
    cfg.set("social.public_url", "http://localhost:8787")
    with pytest.raises(social.NotConfigured):
        social.media_url(cfg, "film-1")


def test_instagram_container_then_publish(cfg, db, tmp_path):
    _connect(cfg)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if request.method == "POST" and path.endswith("/ig-123/media"):
            body = request.content.decode()
            assert "media_type=REELS" in body
            assert "video_url=https%3A%2F%2Fstudio.test" in body
            return httpx.Response(200, json={"id": "container-1"})
        if path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if path.endswith("/ig-123/media_publish"):
            return httpx.Response(200, json={"id": "media-9"})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    net.set_transport(httpx.MockTransport(handler))
    db.create_video(_video(tmp_path))
    result = social.publish(cfg, db, "instagram", _video(tmp_path), _meta(), poll_seconds=0)

    assert result["status"] == "published"
    assert result["remote_id"] == "media-9"
    assert len(seen) == 3
    assert db.list_social_posts("film-1")[0]["target"] == "instagram"


def test_tiktok_pulls_the_signed_media_url(cfg, db, tmp_path):
    _connect(cfg)
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request)
        if request.url.path.endswith("/video/init/"):
            return httpx.Response(200, json={
                "data": {"publish_id": "p-1"}, "error": {"code": "ok", "message": ""},
            })
        if request.url.path.endswith("/status/fetch/"):
            return httpx.Response(200, json={
                "data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok", "message": ""},
            })
        return httpx.Response(404, json={"error": {"code": "not_found"}})

    net.set_transport(httpx.MockTransport(handler))
    db.create_video(_video(tmp_path))
    result = social.publish(cfg, db, "tiktok", _video(tmp_path), _meta(), poll_seconds=0)

    assert result["status"] == "published"
    init = bodies[0]
    assert init.headers["authorization"] == "Bearer tt-token"
    payload = json.loads(init.read())
    assert payload["source_info"]["source"] == "PULL_FROM_URL"
    assert payload["post_info"]["privacy_level"] == "SELF_ONLY"
    assert payload["source_info"]["video_url"].startswith("https://studio.test/api/social/media/film-1")
    assert any("only you can see it" in note for note in result["notes"])


def test_publish_refuses_when_switched_off(cfg, db, tmp_path):
    db.create_video(_video(tmp_path))
    with pytest.raises(social.NotConfigured):
        social.publish(cfg, db, "instagram", _video(tmp_path), _meta())


def test_social_api_needs_confirm_and_a_clean_gate(cfg, tmp_path):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    db.create_video(_video(tmp_path, quality={
        "checks": [{"name": "file", "status": "pass", "detail": "fine"}],
        "hard_fail": False,
    }))

    assert client.post("/api/videos/film-1/social/instagram", json={}).status_code == 400

    _connect(cfg)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ig-123/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if request.url.path.endswith("/ig-123/media_publish"):
            return httpx.Response(200, json={"id": "media-7"})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    net.set_transport(httpx.MockTransport(handler))
    response = client.post("/api/videos/film-1/social/instagram", json={"confirm": True})
    assert response.status_code == 200
    assert response.json()["remote_id"] == "media-7"
