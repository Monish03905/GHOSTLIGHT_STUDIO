from __future__ import annotations

import json
import re
import urllib.request
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database

HASHTAG_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "your", "about"}


def _tag(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    return f"#{cleaned}" if cleaned else ""


def _short_title(title: str, limit: int = 70) -> str:
    title = str(title or "").strip()
    if len(title) <= limit:
        return title
    cut = title[:limit].rsplit(" ", 1)[0].strip(" .-—|,;:")
    return cut or title[:limit]


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        secs, millis = secs + 1, 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(narration: dict[str, Any], width: int = 38) -> str:
    """Word-timed SRT for YouTube's caption track."""
    words = narration.get("words") or []
    cues: list[tuple[float, float, str]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        current.append(word)
        text = " ".join(str(w.get("text", "")) for w in current)
        long_enough = len(current) >= 6 or len(text) >= width * 2
        ends_sentence = str(word.get("text", "")).endswith((".", "?", "!", "…"))
        if long_enough or ends_sentence or len(current) >= 14:
            cues.append((float(current[0]["start"]), float(current[-1]["end"]), text))
            current = []
    if current:
        cues.append((float(current[0]["start"]), float(current[-1]["end"]),
                     " ".join(str(w.get("text", "")) for w in current)))
    blocks = []
    for index, (start, end, text) in enumerate(cues, 1):
        wrapped = _wrap(text, max(18, width))
        blocks.append(f"{index}\n{_srt_time(start)} --> {_srt_time(max(end, start + 0.4))}\n{wrapped}\n")
    return "\n".join(blocks)


def _wrap(text: str, width: int) -> str:
    words = text.split()
    lines: list[str] = []
    line: list[str] = []
    for word in words:
        if line and len(" ".join(line + [word])) > width:
            lines.append(" ".join(line))
            line = [word]
        else:
            line.append(word)
    if line:
        lines.append(" ".join(line))
    if len(lines) > 2:
        # keep cues readable: rebalance into at most two lines
        mid = max(1, len(words) // 2)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    return "\n".join(lines)


def _chapters(narration: dict[str, Any]) -> list[str]:
    segments = narration.get("segments") or []
    if len(segments) < 4:
        return []
    chapters = ["0:00 Cold open"]
    seen = {0}
    for segment in segments[1:]:
        start = int(float(segment.get("start", 0)))
        if start < 10 or start in seen:
            continue
        seen.add(start)
        heading = str(segment.get("heading") or "").strip()
        if not heading:
            heading = " ".join(str(segment.get("text", "")).split()[:5]).strip(" .,;:")
        stamp = f"{start // 60}:{start % 60:02d}"
        chapters.append(f"{stamp} {heading[:48]}")
    return chapters if len(chapters) >= 3 else []


def _hashtags(video: dict[str, Any], short: bool) -> list[str]:
    tags: list[str] = []
    niche = str(video.get("niche") or "").replace("_", " ")
    candidates = [niche, "shorts"] if short else [niche]
    brief = video.get("brief") or {}
    for value in (brief.get("subject"), brief.get("concept"), brief.get("lens")):
        candidates.append(str(value or ""))
    for candidate in candidates:
        words = [w for w in re.findall(r"[a-z0-9]+", candidate.lower()) if w not in HASHTAG_STOP]
        for word in words[:1]:
            tag = _tag(word)
            if tag and tag not in tags:
                tags.append(tag)
        if len(tags) >= 3:
            break
    return tags[:3]


def build_metadata(cfg: Config, video: dict[str, Any], channel: dict[str, Any],
                   narration: dict[str, Any] | None = None) -> dict[str, Any]:
    script = video.get("script") or {}
    brief = video.get("brief") or {}
    short = str(video.get("format")) == "short"
    narration = narration or {}
    author = str(channel.get("name") or cfg.get("studio.name", "Ghostlight Studio"))
    cta = str(channel.get("cta") or cfg.get("creator.cta", "")).strip()
    title = _short_title(str(video.get("title") or script.get("title") or "Untitled"))
    hook = str(video.get("hook") or script.get("hook") or "").strip()
    summary = str(script.get("description") or "").strip()
    hashtags = _hashtags(video, short)

    parts: list[str] = []
    if hook:
        parts.append(hook)
    if summary and summary != hook:
        parts.append(summary)
    chapters = [] if short else _chapters(narration)
    if chapters:
        parts.append("\n".join(chapters))
    if cta:
        parts.append(cta)
    if bool(cfg.get("youtube.disclose_ai", True)):
        parts.append(
            f"Made with {author} — narration, music and images are computer-generated. "
            "No human appears in this film."
        )
    if hashtags:
        parts.append(" ".join(hashtags))
    description = "\n\n".join(p for p in parts if p)[:5000]

    tags: list[str] = []
    for tag in list(script.get("tags") or []) + [brief.get("niche", ""), channel.get("name", "")] + list(
        cfg.get("youtube.tags_suffix", [])
    ):
        cleaned = str(tag or "").strip().lower()
        if 2 < len(cleaned) <= 60 and cleaned not in tags:
            tags.append(cleaned)

    question = str(brief.get("question") or "").strip()
    comment = ""
    if bool(cfg.get("youtube.auto_comment", False)):
        if question:
            comment = f"One question before you go: {question}"
        elif hook:
            comment = f"{hook}\n\nWhat did this make you notice?"

    share = " ".join([title] + hashtags).strip()
    return {
        "title": title,
        "description": description,
        "tags": tags[:25],
        "hashtags": hashtags,
        "chapters": chapters,
        "comment": comment,
        "share_text": share,
        "short": short,
    }


def load_narration(video: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(video.get("narration_path") or ""))
    meta = path.with_name("narration.json")
    if not meta.is_file():
        return {}
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_srt(video: dict[str, Any], workdir: Path) -> Path | None:
    narration = load_narration(video)
    if not narration.get("words"):
        return None
    path = workdir / "captions.srt"
    path.write_text(build_srt(narration), encoding="utf-8")
    return path


def share_kit(video: dict[str, Any], channel: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    url = str(video.get("youtube_url") or "")
    caption = meta.get("share_text") or str(video.get("title") or "")
    if url:
        caption = f"{caption}\n{url}"
    return {
        "channel": channel.get("name", ""),
        "caption": caption,
        "url": url,
        "hashtags": meta.get("hashtags", []),
    }


def dispatch(cfg: Config, db: Database, video: dict[str, Any], channel: dict[str, Any],
             meta: dict[str, Any], on_event: Any = None) -> bool:
    """Push the upload into an optional Discord-compatible webhook."""
    if not bool(cfg.get("distribution.enabled", True)):
        return False
    url = str(cfg.get("distribution.webhook_url", "") or "").strip()
    if not url:
        return False
    kit = share_kit(video, channel, meta)
    payload = json.dumps({"content": kit["caption"][:1900]}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "GhostlightStudio/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            ok = 200 <= response.status < 300
    except Exception as exc:
        if on_event:
            on_event("warning", "distribution", f"Share webhook skipped: {exc}")
        return False
    if ok and on_event:
        on_event("success", "distribution", f"{kit['channel']} share dispatched.")
    return ok


def rss(db: Database, cfg: Config, limit: int = 40) -> str:
    base = str(cfg.get("studio.public_url", "") or "").rstrip("/")
    items = []
    for video in db.list_videos(limit=limit, status="published"):
        title = saxutils.escape(str(video.get("title") or "Untitled"))
        url = saxutils.escape(str(video.get("youtube_url") or ""))
        published = str(video.get("published_at") or video.get("updated_at") or "")
        try:
            stamp = datetime.fromisoformat(published).astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        except ValueError:
            stamp = ""
        desc = saxutils.escape(str(video.get("hook") or ""))
        items.append(
            f"<item><title>{title}</title><link>{url}</link><guid>{url}</guid>"
            f"<pubDate>{stamp}</pubDate><description>{desc}</description></item>"
        )
    channel_title = saxutils.escape(str(cfg.get("studio.name", "Ghostlight Studio")))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{channel_title}</title><link>{saxutils.escape(base)}</link>"
        f"<description>{saxutils.escape(str(cfg.get('studio.tagline', '')))}</description>"
        + "".join(items)
        + "</channel></rss>"
    )
