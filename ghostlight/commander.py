from __future__ import annotations

import re
from typing import Any

from . import content
from .config import Config
from .db import Database
from .events import EventBus
from .llm import direct
from .orchestrator import Studio
from .scheduler import Scheduler
from .youtube import YouTubeClient

SETTING_ALIASES = {
    "tone": "creator.tone",
    "audience": "creator.audience",
    "cta": "creator.cta",
    "niches": "creator.niches",
    "style": "visuals.style",
    "music": "music.enabled",
    "privacy": "youtube.privacy",
    "times": "schedule.times",
    "formats": "schedule.formats",
    "max per day": "schedule.max_per_day",
    "max_per_day": "schedule.max_per_day",
    "min gap": "schedule.min_gap_minutes",
    "min_gap_minutes": "schedule.min_gap_minutes",
    "similarity": "novelty.max_similarity",
    "max_similarity": "novelty.max_similarity",
    "fps": "render.fps",
    "gap": "schedule.min_gap_minutes",
}

ALLOWED_SETTING_PATHS = {
    "creator.niches", "creator.tone", "creator.audience", "creator.cta",
    "script.provider", "script.temperature", "voice.provider", "voice.edge_voice",
    "voice.edge_rate", "visuals.style", "music.enabled", "music.gain",
    "youtube.privacy", "youtube.enabled", "schedule.times", "schedule.formats",
    "schedule.max_per_day", "schedule.mode", "schedule.min_gap_minutes",
    "novelty.max_similarity", "render.fps",
}


class Commander:
    """Takes the director's plain-language notes and runs the studio."""

    def __init__(
        self,
        cfg: Config,
        db: Database,
        bus: EventBus,
        studio: Studio,
        scheduler: Scheduler,
        youtube: YouTubeClient,
    ):
        self.cfg = cfg
        self.db = db
        self.bus = bus
        self.studio = studio
        self.scheduler = scheduler
        self.youtube = youtube

    def handle(self, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"action": "noop", "args": {}, "reply": "Say the word and I'll get to work."}
        action = self._rule_parse(text)
        if action is None:
            action = self._llm_parse(text)
        reply = self._execute(action, text)
        self.db.log_directive(text, action, reply)
        return {"action": action.get("action", "noop"), "args": action.get("args", {}), "reply": reply}

    # -- parsing --------------------------------------------------------
    def _rule_parse(self, text: str) -> dict[str, Any] | None:
        low = text.lower()

        if re.search(r"\b(paused?|hold|stop|freeze|halt)\b", low) and not re.search(
            r"\b(resume|unpause|continue|restart)\b", low
        ):
            return {"action": "pause", "args": {}}

        if re.search(r"\b(resume|unpause|continue|restart|go again)\b", low):
            return {"action": "resume", "args": {}}

        if re.search(r"\b(status|state of the studio|how are we doing|report|what'?s happening|health)\b", low):
            return {"action": "status", "args": {}}

        if re.search(r"\b(upload|publish|post|put (it|this|them) (up|online|on youtube)|send (it|them) (up|to youtube))\b", low):
            count = self._count(low)
            return {"action": "upload", "args": {"count": count or 1}}

        if re.search(r"\b(connect|link|authori[sz]e|sign in|log ?in)\b.*\byoutube\b|\byoutube\b.*\b(connect|link|authori[sz]e)\b", low):
            return {"action": "connect", "args": {}}
        if re.search(r"\bdisconnect\b|\bunlink\b", low) and "youtube" in low:
            return {"action": "disconnect", "args": {}}

        if re.search(r"\b(make|create|generate|write|produce|start|film|shoot|draft|new video|another one|next film)\b", low):
            args: dict[str, Any] = {}
            if re.search(r"\blong\b", low) and not re.search(r"\bshort\b", low):
                args["format"] = "long"
            elif re.search(r"\bshort\b", low):
                args["format"] = "short"
            count = self._count(low)
            if count:
                args["count"] = count
            niche = self._niche(low)
            if niche:
                args["niche"] = niche
            topic = self._topic(text)
            if topic:
                args["topic"] = topic
            return {"action": "generate", "args": args}

        if re.search(r"\bset\b|\bchange\b|\bswitch\b|\bturn\b", low):
            match = re.search(r"\bset\b|\bchange\b|\bswitch\b|\bturn\b", low)
            return {"action": "set_setting", "args": {"raw": text[match.end():].strip()}}

        return None

    def _llm_parse(self, text: str) -> dict[str, Any]:
        try:
            data = direct(self.cfg, text)
        except Exception:
            data = {"action": "noop", "args": {}, "reply": ""}
        if data.get("action") == "noop" and not data.get("reply"):
            return {
                "action": "noop",
                "args": {},
                "reply": (
                    "I didn't quite catch that. Try things like “make a short about deep sea light”, "
                    "“upload the latest film”, “pause the schedule”, or “status”."
                ),
            }
        return data

    def _count(self, low: str) -> int | None:
        words = {
            "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        }
        match = re.search(r"\b(\d+)\b", low)
        if match:
            return max(1, min(3, int(match.group(1))))
        for word, value in words.items():
            if re.search(rf"\b{word}\b", low):
                return value
        return None

    def _niche(self, low: str) -> str | None:
        for key in content.niche_keys():
            if key.replace("_", " ") in low or key in low:
                return key
        return None

    def _topic(self, text: str) -> str | None:
        match = re.search(r"\babout\s+(.{4,120})", text.strip(), flags=re.IGNORECASE)
        if not match:
            return None
        topic = match.group(1).strip(" .!?\"'")
        return topic or None

    # -- execution ------------------------------------------------------
    def _execute(self, action: dict[str, Any], original: str) -> str:
        kind = str(action.get("action", "noop"))
        args = action.get("args") or {}

        if kind == "generate":
            return self._do_generate(args)
        if kind == "upload":
            return self._do_upload(int(args.get("count", 1) or 1))
        if kind == "pause":
            self.scheduler.pause()
            return "Consider it paused. Nothing new starts until you say go."
        if kind == "resume":
            self.scheduler.resume()
            return "Back on the clock. I'll keep the cadence."
        if kind == "status":
            return self._do_status()
        if kind == "connect":
            return self._do_connect()
        if kind == "disconnect":
            self.youtube.disconnect()
            return "Channel unlinked. Your films stay on the shelf."
        if kind == "set_setting":
            return self._do_setting(args)
        reply = str(action.get("reply") or "").strip()
        return reply or "Noted."

    def _do_generate(self, args: dict[str, Any]) -> str:
        fmt = str(args.get("format", "short"))
        if fmt not in {"short", "long"}:
            fmt = "short"
        count = max(1, min(3, int(args.get("count", 1) or 1)))
        niche = args.get("niche")
        if niche and niche not in content.niche_keys():
            niche = None
        topic = str(args.get("topic") or "").strip() or None
        made = []
        for _ in range(count):
            record = self.studio.request(fmt=fmt, niche=niche, topic=topic)
            made.append(record["id"])
        label = "short" if fmt == "short" else "long-form film"
        if count == 1:
            suffix = f" about {topic}" if topic else ""
            return f"On it — one {label}{suffix} is on the bench. I'll show you when it's ready."
        return f"{count} {label}s queued. The desk takes them one at a time."

    def _do_upload(self, count: int) -> str:
        ready = self.db.list_videos(limit=60, status="ready")
        if not ready:
            return "Nothing is ready to publish yet. Ask me to make a film first."
        if not self.youtube.enabled:
            return (
                "YouTube uploads are switched off in the settings. Flip youtube.enabled on "
                "(and connect the channel) and I'll take it from there."
            )
        picked = ready[:max(1, min(3, count))]
        for video in picked:
            self.studio.publish(video["id"])
        names = ", ".join(f"“{v.get('title') or v['id']}”" for v in picked)
        if len(picked) == 1:
            return f"{names} is going up now."
        return f"{names} are going up now, one at a time."

    def _do_status(self) -> str:
        stats = self.db.stats()
        sched = self.scheduler.status()
        bench = self.studio.status()
        youtube = self.youtube.status()
        parts = [
            f"{stats['total']} films made ({stats['published']} published, {stats['ready']} ready on the shelf)",
            f"{stats['minutes']:.0f} minutes of runtime, {stats['words']:,} words spoken",
        ]
        if sched["enabled"]:
            state = "paused" if sched["paused"] else "running"
            parts.append(f"schedule {state} — {self.scheduler.describe()}, {sched['produced_today']} made today")
        else:
            parts.append("schedule switched off")
        if bench["busy"]:
            parts.append("a film is on the bench right now")
        elif bench["queued"]:
            parts.append(f"{bench['queued']} waiting in the queue")
        if youtube["connected"]:
            name = youtube["channel"].get("name") or "your channel"
            quota = youtube["quota"]
            parts.append(
                f"linked to {name} · {quota['uploads_used']}/{quota['upload_limit']} uploads today"
            )
        else:
            parts.append("no YouTube channel linked")
        return ". ".join(parts[:4]) + "."

    def _do_connect(self) -> str:
        if not self.youtube.configured:
            return (
                "I need your Google client secret first — drop client_secret.json into the "
                f"{self.youtube.secrets_dir()} folder (or upload it on the Settings page), then ask me to connect again."
            )
        if self.youtube.connected:
            return "The channel is already linked. Ask me to upload whenever you like."
        import threading

        def _run_flow() -> None:
            try:
                self.youtube.authorize()
            except Exception as exc:
                self.bus.emit("youtube", f"Sign-in failed: {exc}", level="warning")

        threading.Thread(target=_run_flow, name="ghostlight-oauth", daemon=True).start()
        self.bus.emit("youtube", "Starting the sign-in flow in a new browser tab.")
        return (
            "Opening the sign-in page now — pick the channel, approve, and come back. "
            "I'll keep working while you click."
        )

    def _do_setting(self, args: dict[str, Any]) -> str:
        if "path" in args and "value" in args:
            return self._apply_setting(str(args["path"]), args["value"])
        raw = str(args.get("raw") or "").strip()
        if not raw:
            return "Set what, exactly? Try “set privacy to public” or “set times 9:30, 19:30”."
        raw = re.sub(r"^(the\s+)?", "", raw, flags=re.IGNORECASE)

        time_match = re.match(r"^times?\s+(?:to\s+)?((?:\d{1,2}:\d{2}[\s,]*)+)$", raw, flags=re.IGNORECASE)
        if time_match:
            times = re.findall(r"\d{1,2}:\d{2}", time_match.group(1))
            return self._apply_setting("schedule.times", times)

        key_match = re.search(
            r"\b(niches|tone|audience|cta|style|music|privacy|times|formats|max_per_day|"
            r"max per day|min gap|min_gap_minutes|gap|similarity|max_similarity|fps)\b",
            raw,
            flags=re.IGNORECASE,
        )
        if not key_match:
            return (
                "I know the usual knobs — niches, tone, style, music, privacy, times, formats, "
                "max per day, min gap, similarity. Which one did you mean?"
            )
        path = SETTING_ALIASES[key_match.group(1).lower()]
        tail = raw[key_match.end():]
        tail = re.sub(r"^\s*(?:to|=|:)\s*", "", tail, flags=re.IGNORECASE).strip().strip('"\'')
        if not tail:
            current = self.cfg.get(path)
            return f"{path} is currently {current if current is not None else 'unset'}. Set it to what?"

        if path in {"creator.niches", "schedule.times", "schedule.formats"}:
            value: Any = [v.strip() for v in re.split(r"[,]", tail) if v.strip()]
        elif re.fullmatch(r"\b(on|true|yes|enable[d]?)\b", tail, flags=re.IGNORECASE):
            value = True
        elif re.fullmatch(r"\b(off|false|no|disable[d]?)\b", tail, flags=re.IGNORECASE):
            value = False
        else:
            number = re.fullmatch(r"-?\d+(?:\.\d+)?", tail)
            if number:
                value = float(tail)
                if value.is_integer():
                    value = int(value)
            else:
                value = tail
        return self._apply_setting(path, value)

    def _apply_setting(self, path: str, value: Any) -> str:
        if path not in ALLOWED_SETTING_PATHS:
            return (
                "That one's outside what I'm allowed to change. "
                "The Settings page has the full list."
            )
        if path in {"creator.niches", "schedule.times", "schedule.formats"} and isinstance(value, str):
            value = [v.strip() for v in re.split(r"[,]", value) if v.strip()]
        if path == "creator.niches" and isinstance(value, list):
            value = [v.replace(" ", "_") for v in value]
            known = set(content.niche_keys())
            unknown = [n for n in value if n not in known]
            if unknown:
                return (
                    f"I don't know the niche(s) {', '.join(unknown)}. The ones I know: "
                    f"{', '.join(content.niche_keys())}."
                )
        old = self.cfg.get(path)
        self.cfg.set(path, value)
        self.cfg.save()
        if path == "schedule.times" or path.startswith("schedule."):
            self.scheduler.restart()
        shown = value if isinstance(value, (bool, int, float)) else str(value)
        return f"Done — {path} is now {shown} (was {old if old is not None else 'unset'})."
