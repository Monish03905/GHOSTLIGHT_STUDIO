from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone
from typing import Any

from . import content, trends
from .config import Config
from .db import Database


def _idea_id(niche: str, subject: str, seed: int) -> str:
    raw = f"{niche}:{subject}:{seed}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def _used(db: Database) -> set[str]:
    used = {
        content.subject_key(str((row.get("fingerprint") or {}).get("premise_parts", {}).get("subject", "")))
        for row in db.all_fingerprints()
    }
    used.discard("")
    return used


def generate(
    cfg: Config,
    db: Database,
    channel: dict[str, Any] | None = None,
    *,
    niche: str | None = None,
    fmt: str = "short",
    count: int = 4,
    trend: dict[str, Any] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """An idea wall: original, brief-level pitches the director can approve."""
    channel = channel or {}
    if fmt not in {"short", "long"}:
        fmt = "short"
    count = max(1, min(8, int(count)))
    base_seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)

    niches = [n for n in (channel.get("niches") or []) if n in content.NICHES]
    if niche and niche in content.NICHES:
        niches = [niche]
    if not niches:
        niches = [n for n in cfg.get("creator.niches", []) if n in content.NICHES] or content.niche_keys()

    recent = db.recent_titles(int(cfg.get("novelty.recent_for_prompt", 40)))
    used_subjects = _used(db)
    target = cfg.get("script.short_seconds" if fmt == "short" else "script.long_seconds", [28, 46])
    tone = str(channel.get("tone") or cfg.get("creator.tone", ""))
    audience = str(channel.get("audience") or cfg.get("creator.audience", ""))
    palette = str(channel.get("palette") or "") or None

    items: list[dict[str, Any]] = []
    for index in range(count):
        idea_seed = base_seed + index * 104_729
        idea_niche = niches[index % len(niches)] if not niche else niches[0]
        use_trend = trend if index == 0 and trend else None
        style = None
        styles = [s for s in (channel.get("styles") or []) if s in content.STYLE_KEYS]
        if styles:
            style = styles[idea_seed % len(styles)]
        brief = content.make_brief(
            niches,
            fmt=fmt,
            niche_key=idea_niche,
            topic=str(use_trend.get("topic") or "") if use_trend else None,
            used_subjects=used_subjects,
            used_titles=[r.get("title", "") for r in recent],
            style_override=style,
            palette_override=palette,
            tone=tone,
            audience=audience,
            target_seconds=(int(target[0]), int(target[1])),
            seed=idea_seed,
        )
        used_subjects.add(content.subject_key(brief["subject"]))
        draft = content.compose_offline_script(brief, fmt=fmt, words_min=60, words_max=110)
        item = {
            "id": _idea_id(brief["niche"], brief["subject"], idea_seed),
            "title": draft["title"],
            "hook": draft["hook"],
            "subject": brief["subject"],
            "lens": brief["lens"],
            "angle": brief.get("reframe") or brief.get("lens", ""),
            "question": brief.get("question", ""),
            "niche": brief["niche"],
            "niche_label": content.get_niche(brief["niche"]).label,
            "style": brief["style"],
            "palette": brief["palette"],
            "format": fmt,
            "seed": idea_seed,
            "trend": (
                {
                    "topic": use_trend.get("topic", ""),
                    "angle": use_trend.get("angle", ""),
                    "why": use_trend.get("why", ""),
                    "opportunity": use_trend.get("opportunity"),
                }
                if use_trend
                else None
            ),
            "guidance": _guidance(brief, use_trend),
            "channel_id": channel.get("id", ""),
        }
        items.append(item)

    return {
        "items": items,
        "channel_id": channel.get("id", ""),
        "channel_name": channel.get("name", ""),
        "format": fmt,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Pitches only. The writer still builds the full script and the novelty ledger still has to pass it.",
    }


def _guidance(brief: dict[str, Any], trend: dict[str, Any] | None) -> str:
    lines = [
        f"Director's angle: {brief.get('reframe') or brief.get('lens')}.",
        f"Keep the question physical: {brief.get('question')}",
        f"Open on this image, then earn the abstraction: {brief.get('image')}.",
    ]
    if trend:
        lines.insert(0, trends.guidance(trend))
    return "\n".join(lines)
