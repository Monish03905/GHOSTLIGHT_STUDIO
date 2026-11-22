from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from . import ffmpeg, net
from .config import Config

OPENAI_HOST = "https://api.openai.com"
REPLICATE_HOST = "https://api.replicate.com"
PROVIDERS = ("openai", "replicate")
GUARDRAIL = (
    "Faceless documentary plate: no people, no faces, no on-screen text, no logos, no watermark. "
    "Subtle natural motion, cinematic light, one continuous shot."
)


class VideoError(Exception):
    pass


def provider(cfg: Config) -> str:
    name = str(cfg.get("ai_video.provider") or "none").strip().lower()
    if name in {"sora", "gpt-video"}:
        return "openai"
    return name if name in PROVIDERS else "none"


def _token(name: str) -> str:
    env = "OPENAI_API_KEY" if name == "openai" else "REPLICATE_API_TOKEN"
    return str(os.environ.get(env) or "").strip()


def model_for(cfg: Config) -> str:
    configured = str(cfg.get("ai_video.model") or "").strip()
    if configured:
        return configured
    return "sora-2" if provider(cfg) == "openai" else "minimax/video-01"


def readiness(cfg: Config) -> dict[str, Any]:
    name = provider(cfg)
    enabled = bool(cfg.get("ai_video.enabled", False))
    if not enabled:
        return {"enabled": False, "provider": name, "ready": False,
                "reason": "AI video is switched off; the studio paints its own plates."}
    if name == "none":
        return {"enabled": True, "provider": name, "ready": False,
                "reason": "Set ai_video.provider to openai or replicate."}
    if not _token(name):
        env = "OPENAI_API_KEY" if name == "openai" else "REPLICATE_API_TOKEN"
        return {"enabled": True, "provider": name, "ready": False,
                "reason": f"Set {env} in the environment to authorise {name}."}
    return {"enabled": True, "provider": name, "ready": True, "reason": "",
            "model": model_for(cfg)}


def _size_for(width: int, height: int) -> str:
    return "720x1280" if height > width else "1280x720"


def build_prompts(cfg: Config, script: dict[str, Any], brief: dict[str, Any],
                  count: int, width: int, height: int) -> list[str]:
    segments = script.get("segments") or []
    texts = [str(s.get("text") or "").strip() for s in segments if isinstance(s, dict)]
    texts = [t for t in texts if t]
    if not texts:
        narration = str(script.get("narration") or script.get("description") or script.get("title") or "")
        texts = [part.strip() for part in narration.replace("\n", " ").split(". ") if part.strip()]
    style = str(script.get("visual_style") or cfg.get("visuals.style") or "aurora")
    palette = str(brief.get("palette") or "cosmic_indigo").replace("_", " ")
    subject = str(brief.get("subject") or brief.get("concept") or script.get("title") or "").strip()
    orientation = "Vertical 9:16 composition. " if height > width else "Wide 16:9 composition. "
    prompts: list[str] = []
    for index in range(max(1, count)):
        seed_text = texts[(index * max(1, len(texts) - 1)) // max(1, count - 1) % len(texts)] if texts else ""
        seed_text = " ".join(seed_text.split()[:24])
        prompt = (
            f"{orientation}{GUARDRAIL} Subject: {subject or seed_text}. "
            f"Scene cue: {seed_text}. Style: {style}, {palette} palette."
        )
        prompts.append(prompt[:900])
    return prompts


def _poll_seconds(cfg: Config) -> float:
    return max(0.0, float(cfg.get("ai_video.poll_seconds", 5) or 0))


def _max_wait(cfg: Config) -> float:
    return max(10.0, float(cfg.get("ai_video.max_wait_seconds", 600) or 600))


def _openai_clip(cfg: Config, prompt: str, index: int, size: str, dest: Path) -> Path:
    token = _token("openai")
    headers = {"Authorization": f"Bearer {token}"}
    model = model_for(cfg)
    body = {"model": model, "prompt": prompt, "size": size, "seconds": str(int(cfg.get("ai_video.seconds", 4) or 4))}
    try:
        with net.client(timeout=60.0, headers=headers) as http:
            created = http.post(f"{OPENAI_HOST}/v1/videos", json=body)
    except httpx.HTTPError as exc:
        raise VideoError(f"OpenAI did not answer: {exc}") from exc
    payload = _json(created)
    if created.status_code >= 400:
        raise VideoError(f"OpenAI refused the shot: {_error(payload, created.status_code)}")
    video_id = str(payload.get("id") or "")
    if not video_id:
        raise VideoError("OpenAI did not return a video id.")

    deadline = time.monotonic() + _max_wait(cfg)
    while time.monotonic() < deadline:
        try:
            with net.client(timeout=60.0, headers=headers) as http:
                reply = http.get(f"{OPENAI_HOST}/v1/videos/{video_id}")
        except httpx.HTTPError as exc:
            raise VideoError(f"OpenAI status check failed: {exc}") from exc
        data = _json(reply)
        state = str(data.get("status") or "")
        if state == "completed":
            net.download(
                f"{OPENAI_HOST}/v1/videos/{video_id}/content", dest,
                headers={**headers, "Accept": "video/mp4"}, timeout=300.0,
            )
            return dest
        if state in {"failed", "cancelled"}:
            raise VideoError(f"OpenAI could not render the shot: {_error(data, 'failed')}")
        time.sleep(_poll_seconds(cfg))
    raise VideoError("OpenAI timed out before the shot finished.")


def _replicate_clip(cfg: Config, prompt: str, index: int, size: str, dest: Path) -> Path:
    token = _token("replicate")
    headers = {"Authorization": f"Bearer {token}"}
    model = model_for(cfg)
    if "/" not in model:
        raise VideoError("ai_video.model must be owner/name for Replicate (e.g. minimax/video-01).")
    # Replicate models disagree on dimension inputs; the prompt already
    # carries the orientation, so only the universal fields are sent.
    inputs: dict[str, Any] = {"prompt": prompt, "prompt_optimizer": True}
    try:
        with net.client(timeout=60.0, headers=headers) as http:
            created = http.post(f"{REPLICATE_HOST}/v1/models/{model}/predictions", json={"input": inputs})
    except httpx.HTTPError as exc:
        raise VideoError(f"Replicate did not answer: {exc}") from exc
    payload = _json(created)
    if created.status_code >= 400:
        raise VideoError(f"Replicate refused the shot: {_error(payload, created.status_code)}")
    prediction_id = str(payload.get("id") or "")
    if not prediction_id:
        raise VideoError("Replicate did not return a prediction id.")

    deadline = time.monotonic() + _max_wait(cfg)
    while time.monotonic() < deadline:
        try:
            with net.client(timeout=60.0, headers=headers) as http:
                reply = http.get(f"{REPLICATE_HOST}/v1/predictions/{prediction_id}")
        except httpx.HTTPError as exc:
            raise VideoError(f"Replicate status check failed: {exc}") from exc
        data = _json(reply)
        state = str(data.get("status") or "")
        if state == "succeeded":
            output = data.get("output")
            url = output[0] if isinstance(output, list) and output else output
            if not isinstance(url, str) or not url:
                raise VideoError("Replicate finished without a video URL.")
            net.download(url, dest, timeout=300.0)
            return dest
        if state in {"failed", "canceled"}:
            raise VideoError(f"Replicate could not render the shot: {_error(data, state)}")
        time.sleep(_poll_seconds(cfg))
    raise VideoError("Replicate timed out before the shot finished.")


def _json(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error(payload: Any, fallback: Any) -> str:
    if isinstance(payload, dict):
        for key in ("error", "detail", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value[:400]
            if isinstance(value, dict) and value.get("message"):
                return str(value["message"])[:400]
    return f"HTTP {fallback}"


def still_from(clip: Path, dest: Path) -> Path | None:
    try:
        ffmpeg.run([
            "-y", "-ss", "1", "-i", str(clip), "-frames:v", "1", "-q:v", "3", str(dest),
        ], timeout=180)
    except ffmpeg.FFmpegError:
        return None
    return dest if dest.is_file() else None


Generator = Callable[[str, int, Path], Path]


def generate_for_film(
    cfg: Config,
    script: dict[str, Any],
    brief: dict[str, Any],
    count: int,
    width: int,
    height: int,
    workdir: str | Path,
    *,
    generator: Generator | None = None,
    on_event: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any] | None:
    """Return AI shot metadata, or None when the film keeps its painted plates."""
    if not bool(cfg.get("ai_video.enabled", False)):
        return None
    readiness_report = readiness(cfg)
    if generator is None and not readiness_report["ready"]:
        raise VideoError(str(readiness_report["reason"]))

    wanted = max(0, min(int(count), int(cfg.get("ai_video.max_clips", 3) or 0)))
    if wanted == 0:
        return None
    cost = max(0.0, float(cfg.get("ai_video.cost_per_clip_usd", 0) or 0))
    budget = max(0.0, float(cfg.get("ai_video.budget_usd", 0) or 0))
    notes: list[str] = []
    if cost and budget:
        affordable = int(budget // cost)
        if affordable < wanted:
            wanted = affordable
            notes.append(f"Budget {budget:.2f} covers {wanted} of the requested shots at {cost:.2f} each.")
        if wanted == 0:
            notes.append("The AI-video budget is too small for even one shot; the painted plates stayed.")
            return {"provider": readiness_report.get("provider", "none"), "clips": [], "count": 0,
                    "estimated_usd": 0.0, "notes": notes}
    size = _size_for(width, height)
    prompts = build_prompts(cfg, script, brief, wanted, width, height)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    name = readiness_report.get("provider") if generator is None else "injected"
    clips: list[dict[str, Any]] = []
    for index, prompt in enumerate(prompts):
        dest = workdir / f"ai_{index:02d}.mp4"
        if on_event:
            on_event("info", "art", f"AI shot {index + 1} of {len(prompts)} is rendering.")
        if generator is not None:
            clip = Path(generator(prompt, index, workdir))
        elif name == "openai":
            clip = _openai_clip(cfg, prompt, index, size, dest)
        elif name == "replicate":
            clip = _replicate_clip(cfg, prompt, index, size, dest)
        else:
            raise VideoError(f"Unknown AI-video provider {name!r}.")
        if not clip.is_file():
            raise VideoError("The provider reported success but no clip landed on disk.")
        still = still_from(clip, workdir / f"ai_{index:02d}.jpg")
        if still is None:
            notes.append(f"Shot {index + 1} has no extracted still; it will stay a painted plate.")
            continue
        clips.append({"clip": str(clip), "still": str(still), "prompt": prompt})
        if on_event:
            on_event("detail", "art", f"AI shot {index + 1} is in the can.")
    if not clips:
        return None
    if len(clips) < len(prompts):
        notes.append(f"{len(clips)} of {len(prompts)} AI shots made it into the cut.")
    notes.append("AI clips arrive silent; the studio's narration and score remain the soundtrack.")
    notes.append("The upload keeps its AI disclosure.")
    if not cost:
        notes.append("No per-clip rate is set, so the spend is recorded as unpriced, not zero.")
    return {
        "provider": name,
        "model": model_for(cfg) if generator is None else "injected",
        "size": size,
        "clips": clips,
        "count": len(clips),
        "estimated_usd": round(cost * len(clips), 2),
        "priced": bool(cost),
        "notes": notes,
    }
