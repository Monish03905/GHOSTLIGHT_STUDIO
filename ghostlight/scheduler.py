from __future__ import annotations

import threading
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any

from . import content
from .channels import count_today, next_airtime, slot_datetimes
from .config import Config
from .db import Database
from .events import EventBus
from .orchestrator import Studio
from .showrunner import Showrunner

TICK_SECONDS = 20


class Scheduler:
    """Decides when each channel should start a new film on its own."""

    def __init__(
        self,
        cfg: Config,
        db: Database,
        bus: EventBus,
        studio: Studio,
        showrunner: Showrunner | None = None,
    ):
        self.cfg = cfg
        self.db = db
        self.bus = bus
        self.studio = studio
        self.showrunner = showrunner or Showrunner(cfg, db, bus, getattr(studio, "youtube", None))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_fire: datetime | None = None

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if not self.enabled:
            self.bus.emit("schedule", "The schedule is switched off.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ghostlight-schedule", daemon=True)
        self._thread.start()
        state = "paused" if self.paused else "running"
        self.bus.emit("schedule", f"Schedule is {state}: {self.describe()}.")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("schedule.enabled", False))

    @property
    def paused(self) -> bool:
        return bool(self.cfg.get("schedule.paused", False))

    def describe(self) -> str:
        channels = self.db.list_channels(include_disabled=False)
        if channels:
            airtimes = []
            for channel in channels:
                times = ", ".join(str(t) for t in (channel.get("times") or []))
                airtimes.append(f"{channel['name']} at {times or 'unscheduled'}")
            return "; ".join(airtimes)
        mode = str(self.cfg.get("schedule.mode", "rhythm"))
        if mode == "continuous":
            gap = int(self.cfg.get("schedule.min_gap_minutes", 240))
            return f"continuous, one film every {gap} minutes"
        times = ", ".join(str(t) for t in self.cfg.get("schedule.times", []))
        return f"daily at {times or '(no times set)'}"

    def status(self) -> dict[str, Any]:
        now = datetime.now(self.cfg.timezone())
        channels = []
        for channel in self.db.list_channels():
            linked = self._linked(channel["id"])
            channels.append({
                **{k: channel[k] for k in (
                    "id", "name", "tagline", "kicker", "niches", "formats", "styles",
                    "palette", "times", "max_per_day", "enabled", "auto_upload",
                    "youtube_id", "youtube_name", "subscribers", "views",
                ) if k in channel},
                "linked": linked,
                "next": next_airtime(channel, now).isoformat(timespec="minutes") if channel.get("enabled", 1) else "",
                "produced_today": count_today(self.db, channel["id"], now),
                "last_run": str(self.db.get_pref(f"schedule.last_run.{channel['id']}", "") or ""),
            })
        return {
            "enabled": self.enabled,
            "paused": self.paused,
            "mode": str(self.cfg.get("schedule.mode", "rhythm")),
            "times": list(self.cfg.get("schedule.times", [])),
            "formats": list(self.cfg.get("schedule.formats", [])),
            "max_per_day": int(self.cfg.get("schedule.max_per_day", 2)),
            "min_gap_minutes": int(self.cfg.get("schedule.min_gap_minutes", 240)),
            "failure_streak": int(self.db.get_pref("schedule.failure_streak", 0) or 0),
            "produced_today": self._produced_today(),
            "running": bool(self._thread and self._thread.is_alive()),
            "channels": channels,
            "network_max_per_day": int(self.cfg.get("autopilot.max_films_per_day", 4) or 4),
        }

    def pause(self) -> dict[str, Any]:
        self.cfg.set("schedule.paused", True)
        self.cfg.save()
        self.bus.emit("schedule", "Schedule paused. The studio waits.")
        return self.status()

    def resume(self) -> dict[str, Any]:
        self.cfg.set("schedule.enabled", True)
        self.cfg.set("schedule.paused", False)
        self.cfg.save()
        self.db.set_pref("schedule.failure_streak", 0)
        self.restart()
        self.bus.emit("schedule", "Schedule resumed.", level="success")
        return self.status()

    def go_live(self) -> dict[str, Any]:
        """Called after a channel is linked: pick the plan up automatically."""
        if not bool(self.cfg.get("youtube.auto_start_schedule", True)):
            return self.status()
        if bool(self.cfg.get("autopilot.enabled", True)):
            return self.resume()
        return self.status()

    def _linked(self, channel_id: str) -> bool:
        youtube = getattr(self.studio, "youtube", None)
        if not youtube:
            return False
        if hasattr(youtube, "account"):
            return bool(youtube.account(channel_id).connected)
        return bool(getattr(youtube, "connected", False))

    # -- loop -----------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                self.bus.emit("schedule", f"Schedule hiccup: {exc}", level="warning")
            self._stop.wait(TICK_SECONDS)

    def _tick(self) -> None:
        if not self.enabled or self.paused:
            return
        if bool(self.cfg.get("autopilot.enabled", True)):
            try:
                self.showrunner.maybe_think()
            except Exception as exc:
                self.bus.emit("autopilot", f"Thinking paused: {exc}", level="warning")
        now = datetime.now(self.cfg.timezone())
        limit = min(
            int(self.cfg.get("schedule.max_per_day", 2) or 2),
            int(self.cfg.get("autopilot.max_films_per_day", 4) or 4),
        )
        if self._produced_today() >= limit:
            return
        channels = self.db.list_channels(include_disabled=False)
        if self.studio.is_busy() or self.studio.queue_size() > 0:
            return
        if channels:
            self._tick_channels(now, channels, limit)
        else:
            mode = str(self.cfg.get("schedule.mode", "rhythm"))
            if mode == "continuous":
                self._tick_continuous(now)
            else:
                self._tick_rhythm(now)

    def _produced_today(self) -> int:
        zone = self.cfg.timezone()
        midnight = datetime.combine(datetime.now(zone).date(), dtime.min, tzinfo=zone)
        return self.db.count_since(midnight.astimezone(timezone.utc).isoformat(timespec="seconds"))

    # -- multi-channel --------------------------------------------------
    def _tick_channels(self, now: datetime, channels: list[dict[str, Any]], limit: int) -> None:
        catch_up = timedelta(minutes=int(self.cfg.get("schedule.catch_up_minutes", 45)))
        candidates: list[tuple[datetime, dict[str, Any], str]] = []
        for channel in channels:
            if not channel.get("enabled", 1):
                continue
            if not self._linked(channel["id"]):
                continue
            if count_today(self.db, channel["id"], now) >= max(1, int(channel.get("max_per_day", 1) or 1)):
                continue
            last = str(self.db.get_pref(f"schedule.last_run.{channel['id']}", "") or "")
            if last:
                try:
                    if now - datetime.fromisoformat(last) < timedelta(
                        minutes=int(self.cfg.get("schedule.min_gap_minutes", 240))
                    ):
                        continue
                except ValueError:
                    pass
            for index, slot in enumerate(slot_datetimes(channel, now)):
                if slot <= now <= slot + catch_up:
                    key = f"{now.date().isoformat()}#{index}"
                    if self.db.get_pref(f"schedule.slot.{channel['id']}") == key:
                        continue
                    candidates.append((slot, channel, key))
                    break
        if not candidates:
            self._tick_backlog(now, channels)
            return
        _, channel, key = sorted(candidates, key=lambda item: item[0])[0]
        self.db.set_pref(f"schedule.slot.{channel['id']}", key)
        self._fire_channel(channel, now)

    def _tick_backlog(self, now: datetime, channels: list[dict[str, Any]]) -> None:
        """Keep one film warm for the next slot so a live channel never goes dark."""
        lookahead = timedelta(hours=float(self.cfg.get("autopilot.backlog_hours", 6) or 6))
        for channel in channels:
            if not channel.get("enabled", 1):
                continue
            if not self._linked(channel["id"]):
                continue
            upcoming = [slot for slot in slot_datetimes(channel, now) if now < slot <= now + lookahead]
            if not upcoming:
                continue
            ready = len(self.db.list_videos(limit=10, status="ready", channel_id=channel["id"]))
            if ready > 0:
                continue
            if count_today(self.db, channel["id"], now) >= max(1, int(channel.get("max_per_day", 1) or 1)):
                continue
            self._fire_channel(channel, now)
            return

    def _fire_channel(self, channel: dict[str, Any], now: datetime) -> None:
        plan = self.showrunner.choose(channel)
        self.db.set_pref(f"schedule.last_run.{channel['id']}", now.isoformat(timespec="seconds"))
        self.db.set_pref("schedule.last_run", now.isoformat(timespec="seconds"))
        self.showrunner.record_decision(plan)
        self.bus.emit(
            "schedule",
            f"{channel['name']} starts a {plan['format']} film · "
            f"{content.get_niche(plan['niche']).label} in {plan['style']}.",
        )
        self.studio.request(
            fmt=plan["format"],
            niche=plan["niche"],
            guidance=plan["guidance"],
            channel_id=channel["id"],
            style=plan["style"],
            palette=plan["palette"] or None,
        )

    # -- legacy single-channel -----------------------------------------
    def _tick_continuous(self, now: datetime) -> None:
        gap = timedelta(minutes=int(self.cfg.get("schedule.min_gap_minutes", 240)))
        last = self.db.get_pref("schedule.last_run")
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last))
                if now - last_dt < gap:
                    return
            except ValueError:
                pass
        if self.studio.is_busy() or self.studio.queue_size() > 0:
            return
        self._fire(now)

    def _tick_rhythm(self, now: datetime) -> None:
        catch_up = timedelta(minutes=int(self.cfg.get("schedule.catch_up_minutes", 45)))
        times = [str(t) for t in self.cfg.get("schedule.times", []) if str(t)]
        for index, raw in enumerate(times):
            try:
                hour, minute = raw.split(":")[:2]
                slot = datetime.combine(now.date(), dtime(int(hour), int(minute)), tzinfo=now.tzinfo)
            except ValueError:
                continue
            if slot <= now <= slot + catch_up:
                key = f"{now.date().isoformat()}#{index}"
                if self.db.get_pref("schedule.last_slot") == key:
                    continue
                self.db.set_pref("schedule.last_slot", key)
                self._fire(now)
                return

    def _fire(self, now: datetime) -> None:
        formats = [f for f in self.cfg.get("schedule.formats", ["short"]) if f in {"short", "long"}]
        if not formats:
            formats = ["short"]
        index = int(self.db.get_pref("schedule.format_index", 0) or 0)
        fmt = formats[index % len(formats)]
        self.db.set_pref("schedule.format_index", index + 1)
        self.db.set_pref("schedule.last_run", now.isoformat(timespec="seconds"))
        self.bus.emit("schedule", f"Autonomy engaged: starting today's {fmt} film.")
        channel = self.db.list_channels()
        self.studio.request(fmt=fmt, channel_id=channel[0]["id"] if channel else None)
