from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ffmpeg

# The gate is deliberately blunt: a hard fail stops an upload, a warning is
# only a note for the operator. Everything here must stay deterministic so a
# film that passes once does not flip on the next inspect.
SHORT_MIN, SHORT_MAX = 8.0, 75.0
LONG_MIN, LONG_MAX = 90.0, 3600.0
MIN_BYTES = 40_000
MIN_BITRATE_KBPS = 350


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _probe(video_path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        return ffmpeg.probe(video_path), ""
    except ffmpeg.FFmpegError as exc:
        return None, str(exc)[:400]


def inspect(cfg: Any, video: dict[str, Any], channel: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inspect a finished film. Never raises: a broken probe is a warning."""
    checks: list[dict[str, str]] = []
    hard_fail = False
    warnings = 0

    def fail(name: str, detail: str) -> None:
        nonlocal hard_fail
        hard_fail = True
        checks.append(_check(name, "fail", detail))

    def warn(name: str, detail: str) -> None:
        nonlocal warnings
        warnings += 1
        checks.append(_check(name, "warn", detail))

    def ok(name: str, detail: str) -> None:
        checks.append(_check(name, "pass", detail))

    title = str(video.get("title") or "").strip()
    if title:
        ok("title", f"{len(title)} characters")
    else:
        fail("title", "The film has no title.")

    fmt = str(video.get("format") or "short")
    duration = float(video.get("duration") or 0.0)
    video_path = Path(str(video.get("video_path") or ""))
    size = 0

    if not video.get("video_path"):
        fail("file", "There is no rendered file on disk.")
    elif not video_path.is_file():
        fail("file", f"Missing render: {video_path.name}")
    else:
        size = video_path.stat().st_size
        if size < MIN_BYTES:
            fail("file", f"Render is only {size / 1000:.0f} KB — likely truncated.")
        else:
            ok("file", f"{size / 1e6:.1f} MB at {video_path.name}")

    probed, probe_error = (None, "")
    if video_path.is_file():
        probed, probe_error = _probe(video_path)

    streams = (probed or {}).get("streams") or []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if probed is not None:
        if not video_streams:
            fail("picture", "The container has no video stream.")
        else:
            width = int(video_streams[0].get("width") or 0)
            height = int(video_streams[0].get("height") or 0)
            if width < 720 or height < 720:
                warn("picture", f"{width}×{height} is below the 720p floor.")
            else:
                ok("picture", f"{width}×{height}")
        if not audio_streams:
            fail("sound", "The film has no audio stream.")
        else:
            rate = int(audio_streams[0].get("sample_rate") or 0)
            ok("sound", f"Audio stream at {rate or 'unknown'} Hz")
        probed_duration = 0.0
        try:
            probed_duration = float((probed.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            probed_duration = 0.0
        if probed_duration <= 0:
            warn("clock", "The container does not report a duration.")
        elif duration <= 0:
            duration = probed_duration
    elif probe_error:
        warn("probe", f"Could not inspect the file: {probe_error}")

    low, high = (SHORT_MIN, SHORT_MAX) if fmt == "short" else (LONG_MIN, LONG_MAX)
    if duration <= 0:
        fail("duration", "The film has no measurable length.")
    elif duration < low:
        warn("duration", f"{duration:.0f}s is shorter than the {low:.0f}s floor for a {fmt}.")
    elif duration > high:
        warn("duration", f"{duration:.0f}s is longer than the {high:.0f}s ceiling for a {fmt}.")
    else:
        ok("duration", f"{duration:.0f}s of a {fmt}")

    if size and duration > 0:
        kbps = (size * 8 / 1000) / duration
        if kbps < MIN_BITRATE_KBPS:
            warn("bitrate", f"{kbps:.0f} kbps is thin for this length.")
        else:
            ok("bitrate", f"{kbps:.0f} kbps average")

    if video.get("captions_path") and Path(str(video["captions_path"])).is_file():
        ok("captions", "Caption track written.")
    else:
        warn("captions", "No caption file — uploads lose the subtitle pass.")

    if video.get("thumb_path") and Path(str(video["thumb_path"])).is_file():
        ok("thumbnail", "Thumbnail on disk.")
    else:
        warn("thumbnail", "No thumbnail; YouTube will pick an arbitrary frame.")

    description = str(video.get("description") or "").strip()
    if len(description) < 120:
        warn("description", f"Only {len(description)} characters — search has little to chew on.")
    else:
        ok("description", f"{len(description)} characters")

    novelty = float(video.get("novelty") or 1.0)
    if novelty < 0.35:
        warn("novelty", f"Novelty {novelty:.2f} is close to the floor; the idea echoes recent films.")
    else:
        ok("novelty", f"Novelty {novelty:.2f}")

    if channel:
        if str(channel.get("id") or "") == str(video.get("channel_id") or ""):
            ok("channel", f"Belongs to {channel.get('name', channel.get('id'))}")
        else:
            warn("channel", "The film is not attached to a channel.")
    else:
        warn("channel", "No channel owns this film.")

    return {
        "ok": not hard_fail,
        "hard_fail": hard_fail,
        "warnings": warnings,
        "checks": checks,
        "duration": round(duration, 2),
        "bytes": size,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def summary(quality: dict[str, Any] | None) -> str:
    if not quality:
        return "Not inspected"
    if quality.get("hard_fail"):
        failed = [c["name"] for c in quality.get("checks", []) if c.get("status") == "fail"]
        return f"Gate blocked: {', '.join(failed) or 'unknown'}"
    warnings = int(quality.get("warnings") or 0)
    return "Gate passed" if not warnings else f"Gate passed · {warnings} note(s)"


def passes(quality: dict[str, Any] | None) -> bool:
    """Publishing requires an inspection and no hard failure."""
    if not quality:
        return False
    return not bool(quality.get("hard_fail"))
