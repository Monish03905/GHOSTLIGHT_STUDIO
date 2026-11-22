from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from ghostlight import aivideo, ffmpeg, net
from ghostlight.render import Renderer
from ghostlight.visuals import Scene


@pytest.fixture(autouse=True)
def _clean_transport():
    net.reset_transport()
    yield
    net.reset_transport()


def _clip(tmp_path):
    path = tmp_path / "source.mp4"
    ffmpeg.run([
        "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ])
    return path


def _script():
    return {
        "title": "A Quiet Orbit",
        "visual_style": "aurora",
        "segments": [
            {"text": "A station turns slowly above the clouds."},
            {"text": "Instruments listen for a signal that never comes."},
            {"text": "The dark outside is not empty; it is patient."},
        ],
    }


def test_disabled_ai_video_leaves_the_painted_plates_alone(cfg, tmp_path):
    assert aivideo.generate_for_film(cfg, _script(), {}, 4, 1080, 1920, tmp_path) is None


def test_readiness_names_the_missing_key(cfg, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg.set("ai_video.enabled", True)
    cfg.set("ai_video.provider", "openai")
    report = aivideo.readiness(cfg)
    assert report["ready"] is False
    assert "OPENAI_API_KEY" in report["reason"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert aivideo.readiness(cfg)["ready"] is True


def test_prompts_keep_the_faceless_guardrail(cfg):
    prompts = aivideo.build_prompts(cfg, _script(), {"palette": "deep_teal"}, 2, 1080, 1920)
    assert len(prompts) == 2
    assert all("no people" in prompt for prompt in prompts)
    assert all("Vertical 9:16" in prompt for prompt in prompts)


def test_budget_caps_the_shots_and_stills_are_extracted(cfg, tmp_path):
    source = _clip(tmp_path)
    cfg.set("ai_video.enabled", True)
    cfg.set("ai_video.provider", "openai")
    cfg.set("ai_video.max_clips", 4)
    cfg.set("ai_video.cost_per_clip_usd", 0.5)
    cfg.set("ai_video.budget_usd", 1.0)

    def generator(prompt, index, workdir):
        dest = workdir / f"generated_{index}.mp4"
        shutil.copy(source, dest)
        return dest

    report = aivideo.generate_for_film(
        cfg, _script(), {"palette": "deep_teal"}, 5, 320, 180, tmp_path / "ai", generator=generator
    )
    assert report is not None
    assert report["count"] == 2
    assert report["estimated_usd"] == 1.0
    assert all(shot["still"].endswith(".jpg") for shot in report["clips"])
    assert all(Path(shot["still"]).is_file() for shot in report["clips"])
    assert any("covers 2" in note for note in report["notes"])


def test_openai_video_is_created_polled_and_downloaded(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg.set("ai_video.enabled", True)
    cfg.set("ai_video.provider", "openai")
    cfg.set("ai_video.poll_seconds", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/videos":
            return httpx.Response(200, json={"id": "video-1", "status": "queued"})
        if request.method == "GET" and request.url.path == "/v1/videos/video-1":
            return httpx.Response(200, json={"id": "video-1", "status": "completed"})
        if request.method == "GET" and request.url.path == "/v1/videos/video-1/content":
            return httpx.Response(200, content=b"mp4-bytes")
        return httpx.Response(404, json={"error": "unexpected"})

    net.set_transport(httpx.MockTransport(handler))
    dest = aivideo._openai_clip(cfg, "a slow orbit", 0, "1280x720", tmp_path / "shot.mp4")
    assert dest.read_bytes() == b"mp4-bytes"


def test_replicate_prediction_output_is_downloaded(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8-test")
    cfg.set("ai_video.enabled", True)
    cfg.set("ai_video.provider", "replicate")
    cfg.set("ai_video.model", "minimax/video-01")
    cfg.set("ai_video.poll_seconds", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/predictions"):
            return httpx.Response(200, json={"id": "pred-1", "status": "starting"})
        if request.method == "GET" and request.url.path == "/v1/predictions/pred-1":
            return httpx.Response(200, json={
                "id": "pred-1", "status": "succeeded",
                "output": "https://replicate.delivery/example/shot.mp4",
            })
        if request.url.host == "replicate.delivery":
            return httpx.Response(200, content=b"rep-bytes")
        return httpx.Response(404, json={"detail": "unexpected"})

    net.set_transport(httpx.MockTransport(handler))
    dest = aivideo._replicate_clip(cfg, "a slow orbit", 0, "1280x720", tmp_path / "rep.mp4")
    assert dest.read_bytes() == b"rep-bytes"


def test_renderer_uses_the_generated_clip_as_a_moving_base(cfg, tmp_path):
    clip = _clip(tmp_path)
    still = aivideo.still_from(clip, tmp_path / "still.jpg")
    assert still is not None and still.is_file()
    scene = Scene(path=still, motion="in", direction="center", video=clip)
    out = tmp_path / "ai_clip.mp4"
    Renderer(cfg)._render_clip(scene, out, frames=24, fps=12, width=320, height=180)
    probe = ffmpeg.probe(out)
    assert probe["streams"]
