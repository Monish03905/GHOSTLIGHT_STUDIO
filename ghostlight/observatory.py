from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import library, llm, tts

RATE_FIELDS = (
    ("writer_per_1k_words", "per 1k words"),
    ("voice_per_minute", "per voiced minute"),
    ("render_per_minute", "per rendered minute"),
    ("storage_per_gb_month", "per GB-month"),
)

STAGE_PIPELINE = (
    ("written", "Written", "words or narration"),
    ("voiced", "Voiced", "narration track"),
    ("scored", "Scored", "music bed"),
    ("cut", "Cut", "rendered film"),
    ("gated", "Gated", "quality review"),
    ("published", "Published", "YouTube id"),
)


def _rate(cfg: Any, key: str) -> float:
    try:
        return max(0.0, float(cfg.get(f"costs.{key}", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _module_ready(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _render_path() -> tuple[bool, str]:
    from .ffmpeg import FFmpegError, ffmpeg_bin

    try:
        return True, ffmpeg_bin()
    except FFmpegError:
        return False, ""


def _gated(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if not value:
        return False
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    return bool(decoded) if isinstance(decoded, dict) else bool(decoded)


def _channels(db: Any) -> dict[str, str]:
    return {str(ch["id"]): str(ch.get("name") or ch["id"]) for ch in db.list_channels()}


def _provider_bench(cfg: Any, db: Any, youtube: Any) -> list[dict[str, Any]]:
    writer = llm.provider_status(cfg).as_dict()
    voice = tts.voice_status(cfg)
    youtube_status = youtube.status()
    render_ok, render_path = _render_path()
    connected = int(youtube_status.get("connected_count") or 0)
    channel_count = int(youtube_status.get("channel_count") or 0)
    quota = youtube_status.get("quota") or {}
    privacy = str(cfg.get("youtube.privacy", "private"))
    if connected:
        publish_detail = (
            f"{connected} of {channel_count} channels connected · uploads stay {privacy} · "
            f"{quota.get('uploads_used', 0)}/{quota.get('upload_limit', 0)} uploads today"
        )
    else:
        publish_detail = (
            "No Google account connected. Publishing waits on a real per-channel OAuth grant; "
            "nothing leaves this machine."
        )

    return [
        {
            "id": "writer",
            "label": "Writer",
            "group": "Words",
            "provider": writer["name"],
            "model": writer["model"],
            "available": bool(writer["available"]),
            "local": writer["name"] in {"offline", "ollama"},
            "network": writer["name"] not in {"offline", "ollama"},
            "requested": str(cfg.get("script.provider", "auto")),
            "detail": writer.get("detail") or "Ready to write.",
        },
        {
            "id": "voice",
            "label": "Voice",
            "group": "Sound",
            "provider": voice["provider"],
            "model": voice.get("voice") or "",
            "available": voice["provider"] != "none",
            "local": voice["provider"] in {"system", "piper", "none"},
            "network": voice["provider"] in {"edge", "openai", "elevenlabs"},
            "requested": voice.get("requested", "auto"),
            "detail": voice.get("note") or "Narration is read locally.",
        },
        {
            "id": "score",
            "label": "Score",
            "group": "Sound",
            "provider": "procedural",
            "model": "numpy additive synth",
            "available": _module_ready("numpy"),
            "local": True,
            "network": False,
            "requested": "auto",
            "detail": "Every music bed is synthesised per film. No samples, no licences.",
        },
        {
            "id": "art",
            "label": "Art",
            "group": "Picture",
            "provider": "procedural",
            "model": "Pillow painter",
            "available": _module_ready("PIL"),
            "local": True,
            "network": False,
            "requested": "auto",
            "detail": "Posters and backdrops painted from the film fingerprint.",
        },
        {
            "id": "render",
            "label": "Render",
            "group": "Picture",
            "provider": "ffmpeg",
            "model": "libx264 · aac",
            "available": render_ok,
            "local": True,
            "network": False,
            "requested": "auto",
            "detail": render_path or "ffmpeg was not found on this machine.",
        },
        {
            "id": "trends",
            "label": "Radar",
            "group": "Signal",
            "provider": "curated catalogue",
            "model": "Google Trends RSS on demand",
            "available": True,
            "local": False,
            "network": True,
            "requested": "curated + live",
            "detail": "The curated radar is always offline. Live signals are fetched only when asked.",
        },
        {
            "id": "publishing",
            "label": "Publishing",
            "group": "Signal",
            "provider": "YouTube Data API v3",
            "model": "private by default" if not bool(cfg.get("youtube.enabled", False)) else "enabled",
            "available": connected > 0,
            "local": False,
            "network": True,
            "requested": "enabled" if bool(cfg.get("youtube.enabled", False)) else "off",
            "detail": publish_detail,
        },
    ]


def _ledger(cfg: Any, db: Any) -> dict[str, Any]:
    rows = db.all_video_rows()
    films = [r for r in rows if (r.get("kind") or "film") == "film"]
    clips = [r for r in rows if r.get("kind") == "clip"]

    words = sum(int(r.get("words") or 0) for r in films)
    voiced_seconds = sum(float(r.get("duration") or 0) for r in films if r.get("narration_path"))
    render_seconds = sum(float(r.get("duration") or 0) for r in films if r.get("video_path"))
    uploads = sum(1 for r in films if r.get("youtube_id"))

    try:
        storage_bytes = int(library.storage_report(cfg, db).get("on_disk_bytes") or 0)
    except OSError:
        storage_bytes = sum(int(r.get("bytes") or 0) for r in rows)

    writer_rate = _rate(cfg, "writer_per_1k_words")
    voice_rate = _rate(cfg, "voice_per_minute")
    render_rate = _rate(cfg, "render_per_minute")
    storage_rate = _rate(cfg, "storage_per_gb_month")

    writer_estimate = (words / 1000.0) * writer_rate
    voice_estimate = (voiced_seconds / 60.0) * voice_rate
    render_estimate = (render_seconds / 60.0) * render_rate
    storage_estimate = (storage_bytes / (1024 ** 3)) * storage_rate
    total = writer_estimate + voice_estimate + render_estimate + storage_estimate

    def line(key: str, label: str, usage: float, unit: str, rate: float, unit_label: str,
             estimate: float, note: str) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "usage": round(usage, 2),
            "unit": unit,
            "rate": round(rate, 4),
            "rate_unit": unit_label,
            "estimate": round(estimate, 2),
            "note": note,
        }

    lines = [
        line("writer", "Writing", words, "words", writer_rate, "per 1k",
             writer_estimate, "Counted from the words in every film script."),
        line("voice", "Voice", round(voiced_seconds / 60.0, 1), "minutes", voice_rate, "per minute",
             voice_estimate, "Measured narration duration, not wall-clock time."),
        line("render", "Render", round(render_seconds / 60.0, 1), "minutes", render_rate, "per minute",
             render_estimate, "Measured finished runtime, not CPU time."),
        line("storage", "Storage", round(storage_bytes / (1024 ** 3), 3), "GB", storage_rate, "per GB-month",
             storage_estimate, "Disk actually used under data/videos."),
    ]

    currency = str(cfg.get("costs.currency", "USD") or "USD")
    channels = _channels(db)
    per_channel: dict[str, dict[str, Any]] = {}
    for row in films:
        key = str(row.get("channel_id") or "")
        name = channels.get(key, "Unassigned")
        bucket = per_channel.setdefault(key, {
            "id": key, "name": name, "films": 0, "words": 0,
            "minutes": 0.0, "uploads": 0, "estimate": 0.0,
        })
        bucket["films"] += 1
        film_words = int(row.get("words") or 0)
        film_minutes = float(row.get("duration") or 0) / 60.0
        bucket["words"] += film_words
        bucket["minutes"] += film_minutes
        bucket["uploads"] += 1 if row.get("youtube_id") else 0
        bucket["estimate"] += (film_words / 1000.0) * writer_rate
        if row.get("narration_path"):
            bucket["estimate"] += film_minutes * voice_rate
        if row.get("video_path"):
            bucket["estimate"] += film_minutes * render_rate

    channel_rows = sorted(per_channel.values(), key=lambda b: b["films"], reverse=True)
    for bucket in channel_rows:
        bucket["minutes"] = round(bucket["minutes"], 1)
        bucket["estimate"] = round(bucket["estimate"], 2)

    return {
        "currency": currency,
        "rates": {
            "writer_per_1k_words": writer_rate,
            "voice_per_minute": voice_rate,
            "render_per_minute": render_rate,
            "storage_per_gb_month": storage_rate,
        },
        "rate_labels": {key: label for key, label in RATE_FIELDS},
        "totals": {
            "films": len(films),
            "clips": len(clips),
            "words": words,
            "voiced_minutes": round(voiced_seconds / 60.0, 1),
            "render_minutes": round(render_seconds / 60.0, 1),
            "uploads": uploads,
            "storage_bytes": storage_bytes,
            "storage_gb": round(storage_bytes / (1024 ** 3), 3),
            "estimate": round(total, 2),
            "recurring": round(storage_estimate, 2),
        },
        "lines": lines,
        "channels": channel_rows,
        "note": (
            "An estimate, not a bill. Ghostlight runs locally by default, so every rate starts at zero; "
            "set a rate card only if you route work through a paid provider."
        ),
    }


def _pipeline(db: Any, limit: int = 5) -> dict[str, Any]:
    rows = db.all_video_rows()
    titles = {str(r["id"]): str(r.get("title") or "Untitled") for r in rows}
    films = [r for r in rows if (r.get("kind") or "film") == "film"][:limit]

    items = []
    for row in films:
        events = db.list_video_events(str(row["id"]), limit=80)
        trail = [
            {
                "ts": e.get("ts"),
                "kind": e.get("kind"),
                "level": e.get("level"),
                "stage": (e.get("data") or {}).get("stage") or e.get("kind"),
                "progress": (e.get("data") or {}).get("progress"),
                "message": e.get("message"),
            }
            for e in events
        ][-14:]
        stages = []
        flags = {
            "written": bool(row.get("words") or row.get("narration_path")),
            "voiced": bool(row.get("narration_path")),
            "scored": bool(row.get("music_path")),
            "cut": bool(row.get("video_path")),
            "gated": _gated(row.get("quality")),
            "published": bool(row.get("youtube_id")),
        }
        for key, label, hint in STAGE_PIPELINE:
            stages.append({"id": key, "label": label, "done": flags[key], "hint": hint})
        done = sum(1 for stage in stages if stage["done"])
        items.append({
            "id": row["id"],
            "title": row.get("title") or "Untitled",
            "kind": row.get("kind") or "film",
            "format": row.get("format") or "short",
            "status": row.get("status") or "unknown",
            "stage": row.get("stage") or "",
            "channel_id": row.get("channel_id") or "",
            "poster_path": row.get("poster_path") or "",
            "created_at": row.get("created_at"),
            "progress": round(100 * done / len(stages)),
            "stages": stages,
            "trail": trail,
        })

    recent_raw = [e for e in db.list_events(limit=120) if e.get("kind") == "stage"]
    recent = []
    for event in recent_raw[-14:][::-1]:
        data = event.get("data") or {}
        video_id = str(event.get("video_id") or "")
        recent.append({
            "id": event.get("id"),
            "ts": event.get("ts"),
            "video_id": video_id,
            "title": titles.get(video_id, ""),
            "stage": data.get("stage") or "stage",
            "progress": data.get("progress"),
            "level": event.get("level"),
            "message": event.get("message"),
        })

    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "films": items,
        "recent": recent,
        "status_counts": status_counts,
    }


def snapshot(cfg: Any, db: Any, youtube: Any) -> dict[str, Any]:
    return {
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "providers": _provider_bench(cfg, db, youtube),
        "ledger": _ledger(cfg, db),
        "pipeline": _pipeline(db),
    }
