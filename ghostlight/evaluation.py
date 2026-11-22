from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import editorial, ffmpeg, publish

# A readout of the film's own files: script structure, novelty, narration
# timing, picture, caption sync, gate delivery and rights flags. Nothing here
# calls a model, verifies a fact, or predicts watch time.

WEIGHTS = {
    "script": 0.20,
    "originality": 0.12,
    "voice": 0.16,
    "picture": 0.14,
    "captions": 0.12,
    "delivery": 0.14,
    "rights": 0.12,
}

CAVEAT = (
    "Deterministic reads of this film's own files. No factual verification, "
    "no legal clearance and no prediction of reach."
)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _band(value: float, low: float, high: float, span: float) -> float:
    if low <= value <= high:
        return 100.0
    distance = low - value if value < low else value - high
    return _clamp(100.0 - (distance / span) * 100.0)


def _band_name(score: float | None) -> str:
    if score is None:
        return "waiting"
    if score >= 80:
        return "strong"
    if score >= 65:
        return "solid"
    if score >= 50:
        return "watch"
    return "rework"


def _dimension(key: str, label: str, score: float | None, detail: str, basis: str) -> dict[str, Any]:
    rounded = None if score is None else int(round(_clamp(score)))
    return {
        "key": key,
        "label": label,
        "score": rounded,
        "band": _band_name(rounded),
        "detail": detail,
        "basis": basis,
    }


def _editorial(video: dict[str, Any]) -> dict[str, Any]:
    report = video.get("editorial")
    if isinstance(report, dict) and isinstance(report.get("checks"), list) and report.get("checks"):
        return report
    return editorial.analyze_video(video)


def _narration(video: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    data = publish.load_narration(video)
    words = data.get("words")
    clean = [w for w in words if isinstance(w, dict)] if isinstance(words, list) else []
    span = 0.0
    if clean:
        try:
            starts = [float(w.get("start") or 0.0) for w in clean]
            ends = [float(w.get("end") or w.get("start") or 0.0) for w in clean]
            span = max(ends) - min(starts)
        except (TypeError, ValueError):
            span = 0.0
    return data, clean, max(0.0, span)


def _probe(video: dict[str, Any]) -> dict[str, Any] | None:
    raw = str(video.get("video_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        return None
    try:
        return ffmpeg.probe(path)
    except ffmpeg.FFmpegError:
        return None


def _script_signal(read: dict[str, Any]) -> dict[str, Any]:
    score = read.get("score")
    if score is None:
        return _dimension("script", "Script", None, "No script has been read yet.", "deterministic structural read")
    weak = [c.get("label") for c in read.get("checks", []) if c.get("grade") == "fail"]
    detail = f"Editorial read {score}/100"
    if weak:
        detail += f" · weak: {', '.join(str(w) for w in weak[:4])}"
    else:
        detail += " · no structural failures"
    return _dimension("script", "Script", float(score), detail, "deterministic structural read")


def _voice_signal(video: dict[str, Any], words: list[dict[str, Any]], span: float) -> dict[str, Any]:
    duration = float(video.get("duration") or 0.0)
    if words and span > 0:
        wpm = len(words) / span * 60.0
        coverage = span / duration if duration > 0 else 1.0
        score = _band(wpm, 128.0, 172.0, 55.0) * 0.55 + _band(coverage, 0.90, 1.06, 0.25) * 0.45
        detail = f"{len(words)} timed words at {wpm:.0f} wpm, covering {coverage * 100:.0f}% of the cut"
        return _dimension("voice", "Voice", score, detail, "word timings in narration.json")
    count = int(video.get("words") or 0)
    if count and duration > 0:
        wpm = count / duration * 60.0
        score = _band(wpm, 128.0, 172.0, 55.0)
        detail = f"{count} script words at {wpm:.0f} wpm; this cut has no word timings"
        return _dimension("voice", "Voice", score, detail, "script word count and cut length")
    return _dimension("voice", "Voice", None, "No narration or script word count yet.", "narration or script text")


def _picture_signal(video: dict[str, Any], probed: dict[str, Any] | None) -> dict[str, Any]:
    duration = float(video.get("duration") or 0.0)
    size = int(video.get("bytes") or 0)
    streams = (probed or {}).get("streams") or []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    if not video_streams:
        if video.get("video_path"):
            return _dimension("picture", "Picture", 40.0, "The file is on disk but could not be inspected.", "ffprobe")
        return _dimension("picture", "Picture", None, "No rendered picture yet.", "ffprobe")
    stream = video_streams[0]
    try:
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        fps = float(stream.get("avg_frame_rate", "0/1").split("/")[0] or 0) / max(
            1.0, float(stream.get("avg_frame_rate", "0/1").split("/")[-1] or 1)
        )
    except (TypeError, ValueError, ZeroDivisionError):
        width, height, fps = 0, 0, 0.0
    if duration <= 0:
        try:
            duration = float((probed or {}).get("format", {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
    kbps = (size * 8 / 1000) / duration if size and duration > 0 else 0.0
    short_side = min(width, height)
    resolution = 100.0 if short_side >= 1080 else 85.0 if short_side >= 720 else 55.0 if short_side else 40.0
    bitrate = 100.0 if kbps >= 1800 else 85.0 if kbps >= 900 else 65.0 if kbps >= 350 else 35.0
    motion = 100.0 if fps >= 24 else 70.0
    score = resolution * 0.45 + bitrate * 0.40 + motion * 0.15
    detail = f"{width}×{height} at {fps:.0f} fps, {kbps:.0f} kbps average"
    return _dimension("picture", "Picture", score, detail, "ffprobe of the rendered file")


def _caption_signal(video: dict[str, Any], words: list[dict[str, Any]], span: float) -> dict[str, Any]:
    path = str(video.get("captions_path") or "").strip()
    has_file = bool(path) and Path(path).is_file()
    duration = float(video.get("duration") or 0.0)
    if words and span > 0 and duration > 0:
        drift = abs(span - duration)
        score = _band(drift, 0.0, 2.0, 6.0) * 0.7 + (100.0 if has_file else 40.0) * 0.3
        detail = f"Last cue ends {drift:.1f}s from the {duration:.1f}s cut"
        detail += " · caption file present" if has_file else " · no caption file on disk"
        return _dimension("captions", "Captions", score, detail, "narration timings against the render")
    if has_file:
        return _dimension(
            "captions", "Captions", 70.0,
            "A caption file exists, but this cut has no word timings to verify it against.",
            "caption file only",
        )
    return _dimension("captions", "Captions", None, "No caption track yet.", "caption file and narration timings")


def _delivery_signal(video: dict[str, Any]) -> dict[str, Any]:
    report = video.get("quality")
    if not isinstance(report, dict) or not report.get("checks"):
        return _dimension("delivery", "Delivery", None, "The quality gate has not inspected this cut.", "quality gate")
    if report.get("hard_fail"):
        failed = [c.get("name") for c in report.get("checks", []) if c.get("status") == "fail"]
        return _dimension(
            "delivery", "Delivery", 0.0,
            f"Gate blocked: {', '.join(str(f) for f in failed) or 'unknown'}",
            "quality gate",
        )
    warnings = int(report.get("warnings") or 0)
    score = _clamp(100.0 - warnings * 6.0, 55.0, 100.0)
    detail = "Gate passed" + (f" with {warnings} note{'s' if warnings != 1 else ''}" if warnings else " cleanly")
    return _dimension("delivery", "Delivery", score, detail, "quality gate")


def _rights_signal(read: dict[str, Any]) -> dict[str, Any]:
    risk = read.get("risk") if isinstance(read.get("risk"), dict) else {}
    flags = risk.get("flags") if isinstance(risk.get("flags"), list) else []
    score = _clamp(100.0 - len(flags) * 20.0)
    if flags:
        detail = f"{len(flags)} rights keyword{'s' if len(flags) != 1 else ''} flagged: {', '.join(str(f) for f in flags[:3])}"
    else:
        detail = "No rights keywords flagged"
    return _dimension("rights", "Rights", score, detail, "keyword heuristic, not legal clearance or fact-checking")


def evaluate(video: dict[str, Any]) -> dict[str, Any]:
    read = _editorial(video)
    _, words, span = _narration(video)
    probed = _probe(video)

    dimensions = [
        _script_signal(read),
        _dimension(
            "originality", "Originality",
            _clamp(float(video.get("novelty") or 1.0) * 100.0),
            f"Novelty {float(video.get('novelty') or 1.0):.2f} against the film ledger",
            "novelty ledger",
        ),
        _voice_signal(video, words, span),
        _picture_signal(video, probed),
        _caption_signal(video, words, span),
        _delivery_signal(video),
        _rights_signal(read),
    ]

    scored = [d for d in dimensions if d["score"] is not None]
    weight_total = sum(WEIGHTS.get(d["key"], 0.0) for d in scored)
    overall = None
    if scored and weight_total > 0:
        overall = int(round(sum(d["score"] * WEIGHTS.get(d["key"], 0.0) for d in scored) / weight_total))

    notes: list[str] = []
    report = video.get("quality") if isinstance(video.get("quality"), dict) else {}
    if report.get("hard_fail"):
        notes.append("The gate is blocking this cut; fix that before publishing.")
    for flag in (read.get("risk") or {}).get("flags", [])[:3]:
        notes.append(f"Rights review: {flag}.")
    if float(video.get("novelty") or 1.0) < 0.5:
        notes.append("Novelty is close to the floor; this idea echoes recent films.")
    if words and span > 0 and float(video.get("duration") or 0) > 0:
        drift = abs(span - float(video["duration"]))
        if drift > 2.0:
            notes.append(f"Captions drift {drift:.1f}s from the cut; check the narration timings.")
    weak = [c.get("label") for c in read.get("checks", []) if c.get("grade") == "fail"]
    if weak:
        notes.append("Structural weak spots: " + ", ".join(str(w) for w in weak[:4]) + ".")
    if not notes:
        notes.append("Every available signal is clear. This is a read of the files, not a promise of reach.")

    return {
        "id": str(video.get("id") or ""),
        "overall": overall,
        "band": _band_name(overall),
        "signals": len(scored),
        "signals_total": len(dimensions),
        "dimensions": dimensions,
        "notes": notes[:5],
        "caveat": CAVEAT,
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
