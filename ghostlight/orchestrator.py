from __future__ import annotations

import queue
import secrets as pysecrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import content, publish, quality
from .channels import channel_by_id, primary_channel
from .config import Config
from .db import Database
from .events import EventBus
from .music import compose as compose_music
from .render import Renderer, scene_count
from .scriptwriter import ScriptError, ScriptWriter
from .showrunner import Showrunner
from .tts import NarrationMaker
from .visuals import generate_scenes
from .youtube import YouTubeClient, YouTubeError


def new_video_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{pysecrets.token_hex(3)}"


def _youtube_publish_at(value: str, cfg: Config) -> str | None:
    """YouTube wants RFC3339 UTC in the future; anything else releases now."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=cfg.timezone())
    parsed = parsed.astimezone(timezone.utc)
    if parsed < datetime.now(timezone.utc) + timedelta(minutes=5):
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


class Studio:
    """One worker, one queue. Turns briefs into films, films into uploads."""

    def __init__(
        self,
        cfg: Config,
        db: Database,
        bus: EventBus,
        youtube: Any,
        showrunner: Showrunner | None = None,
    ):
        self.cfg = cfg
        self.db = db
        self.bus = bus
        self.youtube = youtube
        self.showrunner = showrunner or Showrunner(cfg, db, bus, youtube)
        self.writer = ScriptWriter(cfg, db, self._on_component_event)
        self.renderer = Renderer(cfg, self._on_component_event)
        self._jobs: "queue.Queue[tuple[str, str, dict[str, Any]]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._current: str | None = None
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        recovered = 0
        for video in self.db.list_videos(limit=200, include_archived=False):
            if video["status"] in {"queued", "drafting"}:
                self._jobs.put(("produce", video["id"], {
                    "fmt": video.get("format") or "short",
                    "channel_id": video.get("channel_id") or "",
                }))
                recovered += 1
        if recovered:
            self.bus.emit("studio", f"Recovered {recovered} unfinished film(s) from the workbench.")
        self._thread = threading.Thread(target=self._run, name="ghostlight-studio", daemon=True)
        self._thread.start()
        self.bus.emit("studio", "Studio desk is open.", level="success")

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(("", "", {}))
        if self._thread:
            self._thread.join(timeout=5)

    def is_busy(self) -> bool:
        with self._lock:
            return self._current is not None

    def queue_size(self) -> int:
        return self._jobs.qsize()

    # -- requests -------------------------------------------------------
    def request(
        self,
        fmt: str = "short",
        niche: str | None = None,
        topic: str | None = None,
        guidance: str = "",
        seed: int | None = None,
        channel_id: str | None = None,
        style: str | None = None,
        palette: str | None = None,
    ) -> dict[str, Any]:
        video_id = new_video_id()
        channel = channel_by_id(self.cfg, self.db, channel_id)
        record = {
            "id": video_id,
            "format": fmt if fmt in {"short", "long"} else "short",
            "niche": niche or "",
            "channel_id": channel["id"] if channel else "",
            "style": style or "",
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "error": "",
        }
        self.db.create_video(record)
        self._jobs.put(("produce", video_id, {
            "fmt": record["format"],
            "niche": niche,
            "topic": topic,
            "guidance": guidance,
            "seed": seed,
            "channel_id": record["channel_id"],
            "style": style,
            "palette": palette,
        }))
        label = f"{channel['name']} · " if channel else ""
        self.bus.emit("studio", f"New commission queued: {label}a {record['format']} film.", video_id=video_id)
        return record

    def publish(self, video_id: str, scheduled_for: str | None = None) -> dict[str, Any]:
        video = self.db.get_video(video_id)
        if not video:
            raise ValueError(f"No film with id {video_id}.")
        if video["status"] not in {"ready", "published"}:
            raise ValueError(f"Film is not ready yet (status: {video['status']}).")
        report = self._gate(video)
        if not quality.passes(report):
            raise ValueError(
                f"The quality gate blocked this film: {quality.summary(report)}. "
                "Retry the render or fix the flagged items first."
            )
        self._jobs.put(("publish", video_id, {"scheduled_for": scheduled_for}))
        return {"id": video_id, "status": "queued for upload"}

    def approve(self, video_id: str, scheduled_for: str | None = None) -> dict[str, Any]:
        """A human lets a review-mode film through to the upload desk."""
        video = self.db.get_video(video_id)
        if not video:
            raise ValueError(f"No film with id {video_id}.")
        if video["status"] not in {"ready", "published"}:
            raise ValueError(f"Film is not ready yet (status: {video['status']}).")
        report = self._gate(video)
        if not quality.passes(report):
            raise ValueError(
                f"The quality gate blocked this film: {quality.summary(report)}."
            )
        channel = channel_by_id(self.cfg, self.db, video.get("channel_id"))
        self.db.update_video(video_id, stage="approved")
        if channel:
            self.db.add_journal(
                channel["id"],
                f"“{video.get('title', 'A film')}” approved by hand.",
                quality.summary(report),
                kind="decision",
            )
        self.bus.emit(
            "approval",
            f"“{video.get('title', 'Film')}” approved for upload.",
            level="success",
            video_id=video_id,
        )
        self._jobs.put(("publish", video_id, {"scheduled_for": scheduled_for}))
        return {"id": video_id, "status": "approved"}

    def _gate(self, video: dict[str, Any]) -> dict[str, Any]:
        """Reuse a stored inspection; re-run it when the film has none."""
        report = video.get("quality")
        if isinstance(report, dict) and report.get("checks"):
            return report
        channel = channel_by_id(self.cfg, self.db, video.get("channel_id"))
        report = quality.inspect(self.cfg, video, channel)
        self.db.update_video(str(video["id"]), quality=report)
        return report


    def retry(self, video_id: str) -> dict[str, Any]:
        video = self.db.get_video(video_id)
        if not video:
            raise ValueError(f"No film with id {video_id}.")
        self.db.update_video(video_id, status="queued", stage="queued", progress=0, error="")
        self._jobs.put(("produce", video_id, {
            "fmt": video.get("format") or "short",
            "channel_id": video.get("channel_id") or "",
        }))
        return {"id": video_id, "status": "requeued"}

    # -- worker ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                kind, video_id, kwargs = self._jobs.get(timeout=1)
            except queue.Empty:
                continue
            if not kind:
                continue
            with self._lock:
                self._current = video_id
            try:
                if kind == "produce":
                    self._produce(video_id, **kwargs)
                elif kind == "publish":
                    self._publish(video_id, **kwargs)
            except YouTubeError as exc:
                # The film itself is fine; only the hand-off failed.
                self.db.update_video(
                    video_id, status="ready", progress=95,
                    error=f"Upload failed: {exc}"[:2000],
                )
                self.bus.emit(
                    "youtube", f"Upload set aside: {exc}", level="warning", video_id=video_id
                )
            except Exception as exc:
                self.db.update_video(video_id, status="failed", error=str(exc)[:2000], progress=100)
                self.bus.emit("studio", f"Film abandoned: {exc}", level="error", video_id=video_id)
                self._record_failure()
            finally:
                with self._lock:
                    self._current = None

    def _produce(
        self,
        video_id: str,
        fmt: str = "short",
        niche: str | None = None,
        topic: str | None = None,
        guidance: str = "",
        seed: int | None = None,
        channel_id: str = "",
        style: str | None = None,
        palette: str | None = None,
    ) -> None:
        short = fmt == "short"
        workdir = self.cfg.video_dir(video_id)
        self.db.update_video(video_id, status="drafting", stage="writing", progress=8, error="")
        self.bus.step(video_id, "writing", "The writer is looking for one strange idea.", 8)
        if niche and niche not in content.niche_keys():
            niche = None

        channel = channel_by_id(self.cfg, self.db, channel_id) if channel_id else primary_channel(self.cfg, self.db)
        if channel:
            channel_id = channel["id"]
        persona = (channel or {}).get("persona") or {}
        if channel:
            if not niche:
                niche = self.showrunner.niche_for(channel)
            if not style:
                style = self.showrunner.style_for(channel)
        result = self.writer.write(
            fmt=fmt,
            niche=niche,
            topic=topic,
            guidance=guidance,
            seed=seed,
            style_override=style or None,
            palette_override=palette or ((channel or {}).get("palette") or None),
            tone_override=(channel or {}).get("tone") or None,
            audience_override=(channel or {}).get("audience") or None,
        )
        script, brief = result.script, result.brief
        if palette:
            brief["palette"] = palette
        self.db.update_video(
            video_id,
            channel_id=channel_id or "",
            title=script["title"],
            hook=script["hook"],
            description=script["description"],
            tags=script["tags"],
            niche=script["niche"],
            style=script.get("visual_style", ""),
            script=script,
            brief=brief,
            fingerprint=result.fingerprint,
            novelty=float(result.novelty.get("novelty", 1.0)),
        )
        self.bus.step(
            video_id, "writing", f"Script locked: “{script['title']}”", 18,
            provider=result.provider, novelty=result.novelty.get("novelty"),
        )

        narration_maker = NarrationMaker(cfg=self.cfg, workdir=workdir, on_event=self._on_component_event)
        self.db.update_video(video_id, stage="narration", progress=25)
        self.bus.step(video_id, "narration", "Recording the voice.", 25)
        narration = narration_maker.synthesize(script, fmt=fmt)
        self.db.update_video(
            video_id,
            narration_path=str(narration.path),
            words=len(narration.words),
            duration=narration.duration,
        )
        self.bus.step(
            video_id, "narration",
            f"Voice recorded ({narration.provider}, {narration.duration:.0f}s).", 32,
            voice=narration.voice,
        )

        music_path: Path | None = None
        if bool(self.cfg.get("music.enabled", True)):
            self.db.update_video(video_id, stage="music", progress=36)
            self.bus.step(video_id, "music", "Scoring the film.", 36)
            music_path = compose_music(
                narration.duration,
                script.get("music_mood", "wonder"),
                workdir / "music.wav",
                seed=int(brief.get("seed", 0) or 0),
            )
            self.bus.step(video_id, "music", "Score laid down.", 40)

        width, height = (self.cfg.get("render.short") if short else self.cfg.get("render.long"))
        count = scene_count(narration.duration, short)
        self.db.update_video(video_id, stage="art", progress=44)
        self.bus.step(video_id, "art", f"Painting {count} plates.", 44)
        scenes = generate_scenes(
            script.get("visual_style", "aurora"),
            brief.get("palette", "cosmic_indigo"),
            int(width),
            int(height),
            count,
            int(brief.get("seed", 0) or 0),
            workdir / "art",
        )
        self.bus.step(video_id, "art", "Plates are on the easel.", 58)

        self.db.update_video(video_id, stage="render", progress=60)
        self.bus.step(video_id, "render", "The camera is rolling.", 60)
        format_label = content.get_format(brief.get("format", fmt)).label
        channel_kicker = str((channel or {}).get("kicker") or content.get_niche(brief["niche"]).kicker)
        kicker = f"{format_label} · {channel_kicker}"
        brand = str((channel or {}).get("name") or self.cfg.get("studio.name", "Ghostlight Studio"))
        rendered = self.renderer.render(
            workdir=workdir,
            out_path=workdir / ("film_short.mp4" if short else "film_long.mp4"),
            scenes=scenes,
            narration=narration,
            title=script["title"],
            short=short,
            kicker=kicker,
            palette_name=brief.get("palette", "cosmic_indigo"),
            music_path=music_path,
            seed=int(brief.get("seed", 0) or 0),
            thumbnail=True,
            brand=brand,
            tagline=str((channel or {}).get("tagline") or ""),
        )
        self.db.update_video(
            video_id,
            video_path=str(rendered.path),
            poster_path=str(rendered.poster),
            thumb_path=str(rendered.thumbnail) if rendered.thumbnail else "",
            thumb_variants=rendered.thumb_variants,
            captions_path=str(rendered.captions),
            duration=rendered.duration,
            words=len(narration.words),
            bytes=rendered.bytes,
            status="ready",
            stage="ready",
            progress=95,
        )
        self.bus.emit(
            "studio",
            f"“{script['title']}” is ready for {brand} — {rendered.duration:.0f}s, {rendered.bytes / 1e6:.1f} MB.",
            level="success",
            video_id=video_id,
        )
        self._reset_failures()

        film = self.db.get_video(video_id) or {}
        report = quality.inspect(self.cfg, film, channel)
        self.db.update_video(video_id, quality=report)
        if not quality.passes(report):
            self.db.update_video(video_id, stage="blocked")
            self.db.add_journal(
                channel_id,
                f"“{script['title']}” was held back by the quality gate.",
                " · ".join(c["detail"] for c in report["checks"] if c["status"] == "fail")[:600],
                kind="decision",
                data={"quality": report},
            )
            self.bus.emit(
                "quality",
                f"“{script['title']}” did not pass the gate: {quality.summary(report)}.",
                level="warning",
                video_id=video_id,
            )
            return
        self.bus.emit(
            "quality",
            f"Quality gate for “{script['title']}”: {quality.summary(report)}.",
            level="info",
            video_id=video_id,
        )

        if str((channel or {}).get("approval") or "auto") == "review":
            self.db.update_video(video_id, stage="review")
            self.db.add_journal(
                channel_id,
                f"“{script['title']}” is waiting for approval.",
                quality.summary(report),
                kind="decision",
                data={"quality": report},
            )
            self.bus.emit(
                "approval",
                f"“{script['title']}” is on the review shelf. Approve it when you are ready.",
                level="warning",
                video_id=video_id,
            )
            return

        account = self._account(channel_id)

        wants_upload = bool(self.cfg.get("youtube.auto_upload", True)) and bool(
            (channel or {}).get("auto_upload", 1)
        )
        if wants_upload and getattr(self.youtube, "enabled", False):
            if account.connected:
                self._publish(video_id)
            else:
                self.bus.emit(
                    "youtube",
                    f"“{script['title']}” is waiting on the shelf — connect {brand} with Google to publish it.",
                    level="warning",
                    video_id=video_id,
                )

    def _account(self, channel_id: str | None) -> Any:
        if hasattr(self.youtube, "account"):
            return self.youtube.account(channel_id)
        return self.youtube

    # -- publish --------------------------------------------------------
    def _publish(self, video_id: str, scheduled_for: str | None = None) -> None:
        video = self.db.get_video(video_id)
        if not video or not video.get("video_path"):
            raise ValueError(f"Film {video_id} has no rendered file.")
        channel = channel_by_id(self.cfg, self.db, video.get("channel_id")) or primary_channel(self.cfg, self.db)
        account = self._account(channel["id"] if channel else None)
        self.db.update_video(video_id, status="uploading", stage="uploading", progress=97)
        self.bus.step(video_id, "uploading", f"Handing the film to {account.label()}.", 97)

        narration = publish.load_narration(video)
        meta = publish.build_metadata(self.cfg, video, channel or {}, narration)
        workdir = Path(str(video.get("narration_path") or self.cfg.video_dir(video_id))).parent
        srt = publish.write_srt(video, workdir) if bool(self.cfg.get("youtube.auto_captions", True)) else None
        if scheduled_for:
            scheduled_for = _youtube_publish_at(scheduled_for, self.cfg)

        result = account.upload(
            Path(video["video_path"]),
            title=meta["title"],
            description=meta["description"],
            tags=meta["tags"],
            short=meta["short"],
            thumbnail=Path(video["thumb_path"]) if video.get("thumb_path") else None,
            publish_at=scheduled_for,
            captions=srt,
            comment=meta["comment"],
            privacy=(channel or {}).get("privacy") or None,
        )
        upload_meta = {
            **result,
            "title": meta["title"],
            "hashtags": meta["hashtags"],
            "chapters": meta["chapters"],
            "share_text": meta["share_text"],
            "description_chars": len(meta["description"]),
            "auto_captions": bool(result.get("captions_uploaded")),
        }
        self.db.update_video(
            video_id,
            status="published",
            stage="published",
            progress=100,
            youtube_id=result["youtube_id"],
            youtube_url=result["youtube_url"],
            privacy=result.get("privacy", ""),
            upload_meta=upload_meta,
            published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        if result.get("youtube_id") and not result.get("dry_run"):
            self.db.upsert_metrics(video_id, channel["id"] if channel else "", {"views": 0})
        channel_name = (channel or {}).get("name", "the studio")
        self.db.add_journal(
            channel["id"] if channel else "",
            f"Published “{meta['title']}” on {channel_name}.",
            meta["description"][:600],
            kind="publication",
            data={"url": result["youtube_url"], "hashtags": meta["hashtags"], "privacy": result.get("privacy")},
        )
        publish.dispatch(
            self.cfg, self.db, {**video, "youtube_url": result["youtube_url"]}, channel or {}, meta,
            on_event=lambda level, kind, message: self.bus.emit(kind, message, level=level),
        )
        self.bus.emit(
            "youtube",
            f"“{video.get('title', 'Film')}” is on {channel_name}: {result['youtube_url']}",
            level="success",
            video_id=video_id,
        )

    # -- failure bookkeeping --------------------------------------------
    def _record_failure(self) -> None:
        streak = int(self.db.get_pref("schedule.failure_streak", 0) or 0) + 1
        self.db.set_pref("schedule.failure_streak", streak)
        limit = int(self.cfg.get("schedule.max_failures_before_pause", 3))
        if streak >= limit and bool(self.cfg.get("schedule.enabled", False)):
            self.cfg.set("schedule.paused", True)
            self.cfg.save()
            self.bus.emit(
                "schedule",
                f"{streak} films in a row have failed — the schedule paused itself. "
                "Check the log, then resume when ready.",
                level="warning",
            )

    def _reset_failures(self) -> None:
        self.db.set_pref("schedule.failure_streak", 0)

    # -- plumbing -------------------------------------------------------
    def _on_component_event(self, level: str, kind: str, message: str) -> None:
        if level == "detail":
            return
        level_map = {"info": "info", "ok": "success", "warn": "warning", "error": "error"}
        self.bus.emit(kind, message, level=level_map.get(level, "info"))

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = self._current
        return {
            "busy": current is not None,
            "current": current,
            "queued": self.queue_size(),
        }
