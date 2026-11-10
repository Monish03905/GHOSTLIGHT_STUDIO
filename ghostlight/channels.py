from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database

# Three distinct editorial identities so the network never publishes the same
# voice twice. Each one owns its niches, art direction and cadence.
CHANNEL_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "ghostlight",
        "name": "Ghostlight",
        "tagline": "one strange idea at a time",
        "kicker": "GHOSTLIGHT",
        "niches": ["cosmic", "deep_sea", "liminal_places"],
        "styles": ["aurora", "tide", "dusk"],
        "palette": "",
        "formats": ["short", "long", "short"],
        "times": ["09:30", "19:30"],
        "max_per_day": 2,
        "tone": "cinematic, intimate, curious — never hype, never a listicle",
        "audience": "curious night owls who want one strange, beautiful idea before bed",
        "cta": "If this stayed with you, subscribe — one strange idea at a time.",
        "persona": {
            "voice": "a late-night radio host speaking to one listener",
            "promise": "an essay that makes the ordinary feel uncanny",
            "avoid": ["listicles", "hype", "motivational quotes"],
        },
    },
    {
        "id": "quiet-machine",
        "name": "The Quiet Machine",
        "tagline": "small machines, large questions",
        "kicker": "THE QUIET MACHINE",
        "niches": ["quiet_tech", "human_mind", "everyday_physics"],
        "styles": ["neon", "ink", "paper"],
        "palette": "",
        "formats": ["short", "short", "long"],
        "times": ["12:30"],
        "max_per_day": 1,
        "tone": "precise, wry, quietly unsettling — explain the mechanism, then the feeling",
        "audience": "engineers, designers and insomniacs who like their tech with a philosophy chaser",
        "cta": "Subscribe if you want the next mechanism explained before it arrives.",
        "persona": {
            "voice": "a calm engineer thinking out loud at a kitchen table",
            "promise": "take a machine apart and find a human fear inside it",
            "avoid": ["gadget reviews", "spec sheets", "hype"],
        },
    },
    {
        "id": "field-notes",
        "name": "Field Notes from Elsewhere",
        "tagline": "the past is a foreign country",
        "kicker": "FIELD NOTES",
        "niches": ["forgotten_history", "natural_world"],
        "styles": ["paper", "ink", "ember"],
        "palette": "",
        "formats": ["short", "long"],
        "times": ["17:00"],
        "max_per_day": 1,
        "tone": "archival, tactile, unhurried — a letter from a place that no longer exists",
        "audience": "armchair historians and walkers who collect abandoned places",
        "cta": "Subscribe for one lost place at a time.",
        "persona": {
            "voice": "a field researcher reading from a water-stained notebook",
            "promise": "recover one small, true thing the record forgot",
            "avoid": ["conspiracy", "true crime gore", "nationalist myth"],
        },
    },
]


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in value.lower()).strip("-") or "channel"


def ensure_lineup(cfg: Config, db: Database) -> list[dict[str, Any]]:
    """Create the default editorial lineup once, and adopt old films."""
    existing = db.list_channels()
    if existing:
        primary = db.get_pref("channels.primary") or existing[0]["id"]
        if not db.get_pref("channels.primary"):
            db.set_pref("channels.primary", primary)
        db.assign_orphans(primary)
        return existing

    target = max(1, min(len(CHANNEL_TEMPLATES), int(cfg.get("autopilot.target_channels", 3) or 3)))
    for template in CHANNEL_TEMPLATES[:target]:
        record = dict(template)
        record["slug"] = _slug(str(record["name"]))
        record["enabled"] = 1
        record["auto_upload"] = 1
        record["privacy"] = str(cfg.get("youtube.privacy", "private"))
        record["playbook"] = {}
        db.create_channel(record)
    primary_id = CHANNEL_TEMPLATES[0]["id"]
    db.set_pref("channels.primary", primary_id)
    db.assign_orphans(primary_id)
    # A studio that was already signed in keeps its old credentials on the
    # first channel instead of asking for a second sign-in.
    legacy_token = Path(cfg.secrets_dir) / "token.json"
    if legacy_token.is_file():
        db.update_channel(primary_id, token_path=str(legacy_token))
    return db.list_channels()


def primary_channel(cfg: Config, db: Database) -> dict[str, Any] | None:
    channels = db.list_channels()
    if not channels:
        return None
    wanted = db.get_pref("channels.primary")
    for channel in channels:
        if channel["id"] == wanted:
            return channel
    return channels[0]


def channel_by_id(cfg: Config, db: Database, channel_id: str | None) -> dict[str, Any] | None:
    if channel_id:
        found = db.get_channel(channel_id)
        if found:
            return found
    return primary_channel(cfg, db)


def slot_datetimes(channel: dict[str, Any], now: datetime) -> list[datetime]:
    times = [str(t) for t in (channel.get("times") or []) if str(t).strip()]
    if not times:
        return []
    out: list[datetime] = []
    for raw in times:
        try:
            hour, minute = raw.split(":")[:2]
            out.append(datetime.combine(now.date(), dtime(int(hour), int(minute)), tzinfo=now.tzinfo))
        except ValueError:
            continue
    return sorted(out)


def next_airtime(channel: dict[str, Any], now: datetime) -> datetime | None:
    slots = slot_datetimes(channel, now)
    future = [s for s in slots if s > now]
    if future:
        return future[0]
    return slots[0] + timedelta(days=1) if slots else None


def count_today(db: Database, channel_id: str, now: datetime) -> int:
    midnight = datetime.combine(now.date(), dtime.min, tzinfo=now.tzinfo)
    from datetime import timezone

    return db.count_since(midnight.astimezone(timezone.utc).isoformat(timespec="seconds"), channel_id)


def channel_public(channel: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in channel.items() if k not in {"token_path", "client_secret_path"}}
