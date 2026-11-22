from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from ghostlight import net, research
from ghostlight.app import create_app
from ghostlight.db import Database


@pytest.fixture(autouse=True)
def _clean_transport():
    net.reset_transport()
    yield
    net.reset_transport()


def test_allowlist_accepts_known_hosts_only():
    allow = ["wikipedia.org", "nasa.gov", "edu"]
    assert research.note_allowed("https://en.wikipedia.org/wiki/Trench", allow)
    assert research.note_allowed("https://www.nasa.gov/story", allow)
    assert research.note_allowed("https://deepsea.mit.edu/notes", allow)
    assert not research.note_allowed("https://nature.com.evil.example/x", allow)
    assert not research.note_allowed("https://example.com/x", allow)


def test_claims_need_numbers_names_or_superlatives():
    video = {
        "script": {
            "narration": (
                "The sea is quiet. The Mariana Trench is 10,994 metres deep. "
                "In 1960, Piccard and Walsh reached the bottom. It is dark down there."
            )
        }
    }
    claims = research.extract_claims(video, limit=3)
    texts = [c["text"] for c in claims]
    assert any("10,994" in text for text in texts)
    assert any("Piccard" in text for text in texts)
    assert not any(text == "The sea is quiet." for text in texts)


def test_repeated_narration_and_segments_yield_one_claim():
    claims = research.extract_claims(_video(), limit=5)
    assert len(claims) == 1


def _video():
    return {
        "id": "trench",
        "title": "The Trench",
        "script": {
            "narration": "The Mariana Trench is 10,994 metres deep.",
            "segments": [{"text": "The Mariana Trench is 10,994 metres deep."}],
        },
    }


def test_analyze_matches_sources_and_keeps_the_caveat(cfg):
    cfg.set("research.max_claims", 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/w/api.php"):
            return httpx.Response(200, json={"query": {"search": [{"title": "Mariana Trench", "snippet": "deepest"}]}})
        if "/api/rest_v1/page/summary/" in request.url.path:
            return httpx.Response(200, json={
                "title": "Mariana Trench",
                "extract": "The Mariana Trench is the deepest oceanic trench, about 10,994 metres deep.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Mariana_Trench"}},
            })
        if "api.openalex.org" in request.url.host:
            return httpx.Response(200, json={"results": [{
                "display_name": "Mariana Trench bathymetry",
                "publication_year": 2019,
                "doi": "https://doi.org/10.1000/example",
                "primary_location": {"source": {"display_name": "Deep Sea Journal"}},
            }]})
        return httpx.Response(404, json={})

    net.set_transport(httpx.MockTransport(handler))
    report = research.analyze(cfg, _video())

    assert report["enabled"] is True
    assert report["counts"]["claims"] == 1
    assert report["claims"][0]["status"] in {"supported", "related"}
    assert report["claims"][0]["sources"]
    assert "not verification" in report["caveat"]
    assert "wikipedia" in report["provider"]


def test_research_api_stores_the_report(cfg):
    client = TestClient(create_app(cfg))
    db = Database(cfg.db_path)
    db.create_video(_video())
    cfg.set("research.max_claims", 1)
    net.set_transport(httpx.MockTransport(lambda request: httpx.Response(500, json={})))

    response = client.post("/api/videos/trench/research")
    assert response.status_code == 200
    assert response.json()["research"]["caveat"] == research.CAVEAT

    stored = client.get("/api/videos/trench/research").json()["research"]
    assert stored["claims"]
    assert stored["counts"]["claims"] == 1
