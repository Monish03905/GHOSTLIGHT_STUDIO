from __future__ import annotations

import re
from datetime import datetime, time as dtime, timedelta
from typing import Any

from . import content
from .config import Config
from .db import Database

MAX_CADENCE_DAYS = 7
MAX_EPISODES = 365


class SeriesError(Exception):
    pass


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "series"


def _parse_time(raw: Any) -> dtime:
    try:
        hour, minute = (int(part) for part in str(raw or "").split(":")[:2])
    except ValueError as exc:
        raise SeriesError(f"Time {raw!r} is not HH:MM.") from exc
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise SeriesError(f"Time {raw!r} is outside a 24-hour day.")
    return dtime(hour, minute)


def first_slot(series: dict[str, Any], now: datetime) -> datetime:
    run_time = _parse_time(series.get("time"))
    slot = datetime.combine(now.date(), run_time, tzinfo=now.tzinfo)
    if slot <= now:
        slot += timedelta(days=1)
    return slot


def next_after(series: dict[str, Any], fired: datetime) -> datetime:
    cadence = max(1, min(MAX_CADENCE_DAYS, int(series.get("cadence_days") or 1)))
    day = fired.date() + timedelta(days=cadence)
    return datetime.combine(day, _parse_time(series.get("time")), tzinfo=fired.tzinfo)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="minutes")


def validate(db: Database, fields: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    if "title" in fields:
        title = " ".join(str(fields.get("title") or "").split())
        if not title:
            raise SeriesError("A series needs a title.")
        clean["title"] = title[:90]
    if "premise" in fields:
        clean["premise"] = " ".join(str(fields.get("premise") or "").split())[:600]
    if "channel_id" in fields:
        channel_id = str(fields.get("channel_id") or "").strip()
        if channel_id and not db.get_channel(channel_id):
            raise SeriesError("That channel does not exist.")
        clean["channel_id"] = channel_id
    if "niche" in fields:
        niche = str(fields.get("niche") or "").strip()
        if niche and niche not in content.niche_keys():
            raise SeriesError(f"Unknown niche {niche!r}.")
        clean["niche"] = niche
    if "style" in fields:
        style = str(fields.get("style") or "").strip()
        if style and style not in content.STYLE_KEYS:
            raise SeriesError(f"Unknown style {style!r}.")
        clean["style"] = style
    if "cadence_days" in fields:
        try:
            clean["cadence_days"] = max(1, min(MAX_CADENCE_DAYS, int(fields.get("cadence_days") or 1)))
        except (TypeError, ValueError):
            raise SeriesError("Cadence must be a whole number of days.")
    if "time" in fields:
        _parse_time(fields.get("time"))
        raw = str(fields.get("time"))
        hour, minute = (int(part) for part in raw.split(":")[:2])
        clean["time"] = f"{hour:02d}:{minute:02d}"
    if "max_episodes" in fields:
        try:
            clean["max_episodes"] = max(0, min(MAX_EPISODES, int(fields.get("max_episodes") or 0)))
        except (TypeError, ValueError):
            raise SeriesError("Episode cap must be a whole number (0 means no cap).")
    if "enabled" in fields:
        clean["enabled"] = 1 if fields.get("enabled") else 0
    if "note" in fields:
        clean["note"] = str(fields.get("note") or "")[:300]
    return clean


def create(cfg: Config, db: Database, fields: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    clean = validate(db, fields)
    if not clean.get("title"):
        raise SeriesError("A series needs a title.")
    base = _slug(clean["title"])
    series_id = base
    suffix = 2
    while db.get_series(series_id):
        series_id = f"{base}-{suffix}"
        suffix += 1
    moment = now or datetime.now(cfg.timezone())
    record = {
        "id": series_id,
        "channel_id": clean.get("channel_id", ""),
        "title": clean["title"],
        "premise": clean.get("premise", ""),
        "niche": clean.get("niche", ""),
        "style": clean.get("style", ""),
        "cadence_days": clean.get("cadence_days", 1),
        "time": clean.get("time", "18:00"),
        "enabled": 1,
        "max_episodes": clean.get("max_episodes", 0),
        "episodes": 0,
        "next_at": "",
        "note": clean.get("note", ""),
    }
    record["next_at"] = _iso(first_slot(record, moment))
    return db.create_series(record)


def update(cfg: Config, db: Database, series_id: str,
           fields: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    series = db.get_series(series_id)
    if not series:
        raise KeyError(series_id)
    clean = validate(db, fields)
    if "title" in fields and not clean.get("title"):
        raise SeriesError("A series needs a title.")
    if clean:
        db.update_series(series_id, **clean)
    merged = {**series, **clean}
    if merged.get("enabled") and ("time" in clean or "cadence_days" in clean):
        moment = now or datetime.now(cfg.timezone())
        db.update_series(series_id, next_at=_iso(first_slot(merged, moment)))
    return db.get_series(series_id) or merged


def guidance(series: dict[str, Any], episode: int) -> str:
    premise = str(series.get("premise") or "").strip()
    head = f"Episode {episode} of “{series.get('title')}”."
    if premise:
        head += f" The series premise: {premise}"
    return (
        f"{head} This is a standalone Short: build one complete idea from the premise, "
        "with its own opening and payoff. Do not continue or reference any earlier episode."
    )


def due(db: Database, now: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for series in db.list_series(include_disabled=False):
        cap = int(series.get("max_episodes") or 0)
        if cap and int(series.get("episodes") or 0) >= cap:
            continue
        try:
            next_at = datetime.fromisoformat(str(series.get("next_at") or ""))
        except ValueError:
            continue
        if next_at.tzinfo is None:
            next_at = next_at.replace(tzinfo=now.tzinfo)
        if next_at <= now:
            out.append(series)
    return out


def advance(db: Database, series: dict[str, Any], episode_id: str,
            fired: datetime) -> dict[str, Any]:
    episode = int(series.get("episodes") or 0) + 1
    cap = int(series.get("max_episodes") or 0)
    done = bool(cap and episode >= cap)
    fields: dict[str, Any] = {
        "episodes": episode,
        "last_episode_id": episode_id,
        "next_at": _iso(next_after(series, fired)),
    }
    if done:
        fields["enabled"] = 0
        fields["note"] = f"Finished after {episode} episodes."
    db.update_series(str(series["id"]), **fields)
    return db.get_series(str(series["id"])) or {**series, **fields}


def public(series: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    item = dict(series)
    cap = int(item.get("max_episodes") or 0)
    item["remaining"] = max(0, cap - int(item.get("episodes") or 0)) if cap else None
    item["complete"] = bool(cap and int(item.get("episodes") or 0) >= cap)
    if now is not None and item.get("next_at"):
        try:
            next_at = datetime.fromisoformat(str(item["next_at"]))
            if next_at.tzinfo is None:
                next_at = next_at.replace(tzinfo=now.tzinfo)
            item["due"] = bool(item.get("enabled")) and next_at <= now
        except ValueError:
            item["due"] = False
    return item
