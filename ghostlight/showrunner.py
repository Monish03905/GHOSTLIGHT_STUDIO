from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from . import content, trends
from .channels import ensure_lineup
from .config import Config
from .db import Database
from .events import EventBus


class Showrunner:
    """The studio's editorial brain: picks what to make next and learns from results."""

    def __init__(self, cfg: Config, db: Database, bus: EventBus, youtube: Any = None):
        self.cfg = cfg
        self.db = db
        self.bus = bus
        self.youtube = youtube
        self.rng = random.SystemRandom()

    # -- lineup ---------------------------------------------------------
    def ensure_lineup(self) -> list[dict[str, Any]]:
        if not bool(self.cfg.get("autopilot.enabled", True)):
            return self.db.list_channels()
        channels = ensure_lineup(self.cfg, self.db)
        if channels and not self.db.get_pref("autopilot.birth"):
            self.db.set_pref("autopilot.birth", datetime.now(timezone.utc).isoformat(timespec="seconds"))
            self.db.add_journal(
                channels[0]["id"],
                "The network opened with three editorial identities.",
                "Each channel owns a different set of niches, art directions and airtimes, "
                "so the films never compete with themselves.",
                kind="birth",
                data={"channels": [c["name"] for c in channels]},
            )
            self.bus.emit(
                "autopilot",
                f"Network opened: {', '.join(c['name'] for c in channels)}.",
                level="success",
            )
        return channels

    def channel(self, channel_id: str | None) -> dict[str, Any] | None:
        if channel_id:
            found = self.db.get_channel(channel_id)
            if found:
                return found
        channels = self.db.list_channels()
        return channels[0] if channels else None

    # -- choosing -------------------------------------------------------
    def _pick(self, options: list[str], weights: dict[str, float], explore: float) -> str:
        if not options:
            return ""
        if self.rng.random() < max(0.0, min(0.5, explore)):
            return self.rng.choice(options)
        scores = [max(0.05, float(weights.get(option, 1.0))) for option in options]
        return self.rng.choices(options, weights=scores, k=1)[0]

    def niche_for(self, channel: dict[str, Any]) -> str:
        playbook = channel.get("playbook") or {}
        niches = [n for n in (channel.get("niches") or []) if n in content.niche_keys()]
        if not niches:
            return ""
        return self._pick(niches, playbook.get("niches", {}), float(self.cfg.get("autopilot.explore", 0.18)))

    def style_for(self, channel: dict[str, Any]) -> str:
        playbook = channel.get("playbook") or {}
        styles = [s for s in (channel.get("styles") or []) if s in content.STYLE_KEYS]
        if not styles:
            return ""
        return self._pick(styles, playbook.get("styles", {}), float(self.cfg.get("autopilot.explore", 0.18)))

    def choose(self, channel: dict[str, Any], fmt: str | None = None) -> dict[str, Any]:
        playbook = channel.get("playbook") or {}
        niches = [n for n in (channel.get("niches") or []) if n in content.niche_keys()]
        styles = [s for s in (channel.get("styles") or []) if s in content.STYLE_KEYS]
        if not niches:
            niches = [n for n in self.cfg.get("creator.niches", []) if n in content.niche_keys()] or content.niche_keys()
        if not styles:
            styles = list(content.STYLE_KEYS)
        explore = float(self.cfg.get("autopilot.explore", 0.18))
        niche = self._pick(niches, playbook.get("niches", {}), explore)
        style = self._pick(styles, playbook.get("styles", {}), explore)

        known = {"short", "long"}
        formats = [f for f in (channel.get("formats") or []) if f in known] or ["short"]
        if fmt in known:
            chosen_fmt = fmt
            source = "requested"
        else:
            key = f"channel.fmt_index.{channel['id']}"
            index = int(self.db.get_pref(key, 0) or 0)
            chosen_fmt = formats[index % len(formats)]
            self.db.set_pref(key, index + 1)
            source = "playbook" if playbook.get("niches") else "explore"

        persona = channel.get("persona") or {}
        avoid = ", ".join(str(x) for x in persona.get("avoid", []) if str(x).strip())
        cta = channel.get("cta") or self.cfg.get("creator.cta", "")
        lines = [
            f"Editorial identity: {persona.get('voice') or channel.get('tone') or 'a quiet essayist'}.",
            f"Promise to the viewer: {persona.get('promise') or 'one strange idea, fully earned'}.",
            f"Audience: {channel.get('audience') or self.cfg.get('creator.audience', '')}.",
            "Open on a concrete image in the first sentence; earn the abstraction after that.",
            "End on a line a viewer could repeat to someone else.",
        ]
        if avoid:
            lines.append(f"Do not sound like: {avoid}.")
        signal = trends.top_for_channel(channel)
        if signal:
            lines.append(
                f"Radar signal to consider if it fits: {signal['topic']} — {signal.get('angle', '')} "
                f"(opportunity {signal.get('opportunity', 0):.0f}/100). Use it as raw material, never as a headline."
            )
        insight = str(playbook.get("insight") or "").strip()
        if insight:
            lines.append(f"What recent results suggest: {insight}")
        guidance = "\n".join(lines)
        rationale = (
            f"Chose {content.get_niche(niche).label} in the {style} register for "
            f"{channel.get('name')}"
            + (f" because {insight}" if insight else " to build the channel's signature")
        )
        return {
            "channel_id": channel["id"],
            "channel_name": channel.get("name", ""),
            "niche": niche,
            "style": style,
            "palette": channel.get("palette") or "",
            "format": chosen_fmt,
            "guidance": guidance,
            "cta": cta,
            "rationale": rationale,
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def record_decision(self, plan: dict[str, Any]) -> None:
        self.db.add_journal(
            plan["channel_id"],
            f"Next film: {content.get_niche(plan['niche']).label} · {plan['style']} · {plan['format']}.",
            plan["rationale"],
            kind="decision",
            data=plan,
        )
        self.bus.emit(
            "autopilot",
            f"{plan['channel_name']} chose {content.get_niche(plan['niche']).label} in {plan['style']}.",
            level="detail",
        )

    # -- learning -------------------------------------------------------
    def _score(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
        scores: dict[str, dict[str, list[float]]] = {"niches": {}, "styles": {}, "formats": {}, "hours": {}}
        for row in rows:
            views = float(row.get("views") or 0)
            watch = float(row.get("watch_minutes") or 0)
            subs = float(row.get("subs_gained") or 0)
            value = views + watch * 2.0 + subs * 120.0
            if value <= 0:
                continue
            script = row.get("script") or {}
            niche = str(row.get("niche") or script.get("niche") or "")
            style = str(row.get("style") or script.get("visual_style") or "")
            fmt = str(row.get("format") or "")
            if niche:
                scores["niches"].setdefault(niche, []).append(value)
            if style:
                scores["styles"].setdefault(style, []).append(value)
            if fmt:
                scores["formats"].setdefault(fmt, []).append(value)
            published = str(row.get("published_at") or "")
            try:
                hour = datetime.fromisoformat(published).astimezone().hour
                scores["hours"].setdefault(f"{hour:02d}", []).append(value)
            except ValueError:
                pass
        out: dict[str, dict[str, float]] = {}
        for group, buckets in scores.items():
            averages = {key: sum(vals) / len(vals) for key, vals in buckets.items() if vals}
            if not averages:
                continue
            median = sorted(averages.values())[len(averages) // 2] or 1.0
            out[group] = {k: round(max(0.15, min(3.0, v / median)), 3) for k, v in averages.items()}
        return out

    def learn(self, channel: dict[str, Any], force: bool = False) -> dict[str, Any]:
        if not self.youtube:
            return {"status": "no-youtube"}
        account = self.youtube.account(channel["id"]) if hasattr(self.youtube, "account") else self.youtube
        if not getattr(account, "connected", False):
            return {"status": "not-connected"}
        published = self.db.published_videos(channel["id"], limit=60)
        ids = [str(v.get("youtube_id")) for v in published if v.get("youtube_id")]
        if not ids:
            self.db.update_channel(
                channel["id"],
                playbook={
                    "insight": "No published films yet. The first cycle is exploration.",
                    "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "samples": 0,
                },
            )
            return {"status": "no-data", "samples": 0}
        analytics = {}
        try:
            analytics = account.fetch_metrics(ids, days=int(self.cfg.get("youtube.analytics_days", 28) or 28))
        except Exception as exc:
            self.bus.emit("autopilot", f"{channel['name']} analytics unavailable: {exc}", level="warning")
        stats = {}
        try:
            stats = account.fetch_video_stats(ids)
        except Exception:
            stats = {}
        for video in published:
            yid = str(video.get("youtube_id"))
            payload = dict(analytics.get(yid) or {})
            payload.update({k: v for k, v in (stats.get(yid) or {}).items() if k not in payload})
            if payload:
                self.db.upsert_metrics(video["id"], channel["id"], payload)
        rows = self.db.performance(channel["id"], limit=60)
        scores = self._score(rows)
        samples = sum(1 for row in rows if (row.get("views") or 0) > 0)
        playbook = {
            **scores,
            "samples": samples,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if scores.get("niches"):
            best_niche = max(scores["niches"], key=scores["niches"].get)
            playbook["insight"] = (
                f"{content.get_niche(best_niche).label} is travelling furthest for this audience"
                + (f", and the {max(scores['styles'], key=scores['styles'].get)} register holds attention."
                   if scores.get("styles") else ".")
            )
        else:
            playbook["insight"] = "Not enough watch data yet; keep exploring the channel's niches."
        hours = scores.get("hours") or {}
        if bool(self.cfg.get("autopilot.adapt_schedule", False)) and samples >= 4 and len(hours) >= 2:
            best_hours = sorted(hours, key=hours.get, reverse=True)[: min(3, max(1, int(channel.get("max_per_day", 1) or 1)))]
            times = [f"{hour}:00" for hour in sorted(best_hours)]
            if times and times != list(channel.get("times") or []):
                self.db.update_channel(channel["id"], times=times)
                playbook["schedule_note"] = f"moved airtimes to {', '.join(times)}"
        self.db.update_channel(channel["id"], playbook=playbook)
        try:
            info = account.channel_info(refresh=True)
            if info.get("subscribers") is not None:
                self.db.update_channel(channel["id"], subscribers=int(info.get("subscribers", 0) or 0))
        except Exception:
            pass
        self.db.add_journal(
            channel["id"],
            f"Learned from {samples} published film{'s' if samples != 1 else ''}.",
            playbook["insight"] + (f" {playbook.get('schedule_note', '')}" if playbook.get("schedule_note") else ""),
            kind="lesson",
            data={k: v for k, v in playbook.items() if k in {"niches", "styles", "formats", "hours", "samples"}},
        )
        self.bus.emit("autopilot", f"{channel['name']} {playbook['insight']}", level="detail")
        return {"status": "learned", "samples": samples, "playbook": playbook}

    def maybe_think(self, force: bool = False) -> dict[str, Any]:
        if not bool(self.cfg.get("autopilot.enabled", True)):
            return {"status": "off"}
        minutes = int(self.cfg.get("autopilot.learn_minutes", 180) or 180)
        last = str(self.db.get_pref("autopilot.last_learn", "") or "")
        if not force and last:
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
                if elapsed < minutes * 60:
                    return {"status": "recent", "next_in": int(minutes * 60 - elapsed)}
            except ValueError:
                pass
        self.db.set_pref("autopilot.last_learn", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        results = []
        for channel in self.db.list_channels():
            if not channel.get("enabled", 1):
                continue
            results.append(self.learn(channel, force=force))
        return {"status": "ok", "channels": results}

    def think(self, channel_id: str | None = None) -> dict[str, Any]:
        channel = self.channel(channel_id)
        if not channel:
            return {"status": "no-channel"}
        result = self.learn(channel, force=True)
        plan = self.choose(channel)
        self.record_decision(plan)
        return {"status": "ok", "channel": channel["name"], "learning": result, "next": plan}

    def status(self) -> dict[str, Any]:
        last = str(self.db.get_pref("autopilot.last_learn", "") or "")
        return {
            "enabled": bool(self.cfg.get("autopilot.enabled", True)),
            "target_channels": int(self.cfg.get("autopilot.target_channels", 3) or 3),
            "backlog": int(self.cfg.get("autopilot.backlog", 1) or 0),
            "learn_minutes": int(self.cfg.get("autopilot.learn_minutes", 180) or 180),
            "adapt_schedule": bool(self.cfg.get("autopilot.adapt_schedule", False)),
            "last_learn": last,
            "journal": self.db.list_journal(limit=12),
        }
