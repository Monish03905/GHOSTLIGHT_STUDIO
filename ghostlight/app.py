from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, content, ideas, publish, quality, trends
from .channels import (
    CHANNEL_TEMPLATES,
    _slug,
    channel_by_id,
    channel_public,
    next_airtime,
    slot_datetimes,
)
from .commander import Commander
from .config import Config
from .db import Database
from .events import EventBus
from .orchestrator import Studio
from .scheduler import Scheduler
from .showrunner import Showrunner
from .youtube import NotConfiguredError, YouTubeError, YouTubeHub

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

CHANNEL_EDITABLE = {
    "name", "tagline", "kicker", "niches", "formats", "styles", "palette",
    "times", "max_per_day", "enabled", "auto_upload", "persona", "tone",
    "audience", "cta", "privacy", "approval",
}


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _validate_channel(fields: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in CHANNEL_EDITABLE:
            continue
        if key in {"niches", "formats", "styles", "times"}:
            clean[key] = _clean_list(value)
        elif key == "max_per_day":
            clean[key] = max(1, min(8, int(value)))
        elif key in {"enabled", "auto_upload"}:
            clean[key] = 1 if value else 0
        elif key == "persona":
            clean[key] = value if isinstance(value, dict) else {}
        else:
            clean[key] = str(value).strip()

    if "niches" in clean:
        bad = [n for n in clean["niches"] if n not in content.niche_keys()]
        if bad:
            raise HTTPException(400, f"Unknown niche(s): {', '.join(bad)}")
        if not clean["niches"]:
            raise HTTPException(400, "A channel needs at least one niche.")
    if "styles" in clean:
        bad = [s for s in clean["styles"] if s not in content.STYLE_KEYS]
        if bad:
            raise HTTPException(400, f"Unknown style(s): {', '.join(bad)}")
    if "formats" in clean:
        clean["formats"] = [f for f in clean["formats"] if f in {"short", "long"}] or ["short"]
    if "times" in clean:
        times = []
        for raw in clean["times"]:
            try:
                hour, minute = (int(part) for part in raw.split(":")[:2])
            except ValueError:
                raise HTTPException(400, f"Time {raw!r} is not HH:MM.")
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise HTTPException(400, f"Time {raw!r} is outside a 24-hour day.")
            times.append(f"{hour:02d}:{minute:02d}")
        clean["times"] = sorted(times)
    if "name" in clean and not clean["name"]:
        raise HTTPException(400, "A channel needs a name.")
    if "privacy" in clean:
        if clean["privacy"] not in {"private", "unlisted", "public"}:
            raise HTTPException(400, "Privacy must be private, unlisted or public.")
    if "approval" in clean:
        if clean["approval"] not in {"auto", "review"}:
            raise HTTPException(400, "Approval must be auto or review.")
    return clean


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config()
    db = Database(cfg.db_path)
    bus = EventBus(db)
    youtube = YouTubeHub(
        cfg, db, on_event=lambda level, kind, message: bus.emit(kind, message, level=level)
    )
    showrunner = Showrunner(cfg, db, bus, youtube)
    studio = Studio(cfg, db, bus, youtube, showrunner=showrunner)
    scheduler = Scheduler(cfg, db, bus, studio, showrunner=showrunner)
    commander = Commander(cfg, db, bus, studio, scheduler, youtube)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind_loop(asyncio.get_running_loop())
        showrunner.ensure_lineup()
        studio.start()
        scheduler.start()
        yield
        scheduler.stop()
        studio.stop()

    app = FastAPI(title="Ghostlight Studio", version=__version__, lifespan=lifespan)

    # -- status ---------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {
            "studio": studio.status(),
            "schedule": scheduler.status(),
            "youtube": youtube.status(),
            "channels": [channel_public(c) for c in db.list_channels()],
            "autopilot": showrunner.status(),
            "growth": _growth_summary(),
            "stats": db.stats(),
            "desk": {
                "name": cfg.get("studio.name"),
                "tagline": cfg.get("studio.tagline"),
            },
        }

    def _growth_summary() -> dict[str, Any]:
        totals = {"views": 0, "watch_minutes": 0.0, "subs_gained": 0, "revenue": 0.0, "published": 0}
        rows = []
        for channel in db.list_channels():
            stats = db.channel_stats(channel["id"])
            totals["views"] += stats["views"]
            totals["watch_minutes"] += stats["watch_minutes"]
            totals["subs_gained"] += stats["subs_gained"]
            totals["revenue"] += stats["revenue"]
            totals["published"] += stats["published"]
            rows.append({
                "id": channel["id"],
                "name": channel["name"],
                "subscribers": int(channel.get("subscribers", 0) or 0),
                "views": stats["views"],
                "revenue": stats["revenue"],
                "published": stats["published"],
            })
        return {"totals": totals, "channels": rows}

    # -- command --------------------------------------------------------
    @app.post("/api/command")
    async def command(request: Request) -> dict[str, Any]:
        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(400, "text is required")
        return commander.handle(text)

    @app.post("/api/generate")
    async def generate(request: Request) -> dict[str, Any]:
        body = await request.json()
        return studio.request(
            fmt=str(body.get("format", "short")),
            niche=str(body.get("niche")) if body.get("niche") else None,
            topic=str(body.get("topic")) if body.get("topic") else None,
            guidance=str(body.get("guidance", "")),
            channel_id=str(body.get("channel_id")) if body.get("channel_id") else None,
            style=str(body.get("style")) if body.get("style") else None,
        )

    # -- radar & ideas --------------------------------------------------
    @app.get("/api/trends")
    def radar(
        channel_id: str | None = None,
        niche: str = "",
        live: bool = False,
        geo: str = "US",
        limit: int = 14,
    ) -> dict[str, Any]:
        channel = db.get_channel(channel_id) if channel_id else None
        wanted = [n.strip() for n in niche.split(",") if n.strip()] or None
        if not wanted and channel:
            wanted = list(channel.get("niches") or [])
        return trends.radar(channel, niches=wanted, live=live, geo=geo, limit=limit)

    @app.post("/api/ideas")
    async def idea_wall(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        channel_id = str(body.get("channel_id") or "") or None
        channel = db.get_channel(channel_id) if channel_id else None
        if channel_id and not channel:
            raise HTTPException(404, "no such channel")
        if not channel:
            channel = channel_by_id(cfg, db, None) or {}
        return ideas.generate(
            cfg,
            db,
            channel,
            niche=str(body.get("niche") or "") or None,
            fmt=str(body.get("format") or "short"),
            count=int(body.get("count") or 4),
            trend=body.get("trend") if isinstance(body.get("trend"), dict) else None,
            seed=int(body["seed"]) if str(body.get("seed") or "").isdigit() else None,
        )

    @app.post("/api/ideas/queue")
    async def queue_idea(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        channel_id = str(body.get("channel_id") or "") or None
        if channel_id and not db.get_channel(channel_id):
            raise HTTPException(404, "no such channel")
        title = str(body.get("title") or "an idea").strip()
        fmt = str(body.get("format") or "short")
        record = studio.request(
            fmt=fmt if fmt in {"short", "long"} else "short",
            niche=str(body.get("niche") or "") or None,
            topic=str(body.get("subject") or body.get("topic") or "") or None,
            guidance=str(body.get("guidance") or ""),
            channel_id=channel_id,
            style=str(body.get("style") or "") or None,
            palette=str(body.get("palette") or "") or None,
        )
        target = channel_id or str(record.get("channel_id") or "")
        db.add_journal(
            target,
            f"Idea approved: “{title}”.",
            "Queued from the idea wall. The writer and the novelty ledger still decide whether it ships.",
            kind="decision",
            data={"idea": title, "video_id": record.get("id")},
        )
        bus.emit("studio", f"Idea approved from the radar: “{title}”.", level="success", video_id=record.get("id"))
        return record

    # -- calendar & brain ----------------------------------------------
    def _local_dt(raw: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(cfg.timezone())

    @app.get("/api/calendar")
    def calendar(days: int = 7, channel_id: str | None = None) -> dict[str, Any]:
        span = max(1, min(21, int(days)))
        now = datetime.now(cfg.timezone())
        if channel_id:
            selected = db.get_channel(channel_id)
            if not selected:
                raise HTTPException(404, "no such channel")
            channels = [selected]
        else:
            channels = db.list_channels(include_disabled=False)

        videos = db.list_videos(limit=400, include_archived=False)
        by_channel: dict[str, list[dict[str, Any]]] = {}
        for video in videos:
            by_channel.setdefault(str(video.get("channel_id") or ""), []).append(video)

        used_ready: set[str] = set()
        used_flight: set[str] = set()
        out_days: list[dict[str, Any]] = []
        for offset in range(span):
            day = (now + timedelta(days=offset)).date()
            day_start = datetime.combine(day, dtime.min, tzinfo=now.tzinfo)
            day_end = day_start + timedelta(days=1)
            entries: list[dict[str, Any]] = []
            for channel in channels:
                times: list[dtime] = []
                for raw in channel.get("times") or []:
                    try:
                        hour, minute = (int(part) for part in str(raw).split(":")[:2])
                    except ValueError:
                        continue
                    if 0 <= hour < 24 and 0 <= minute < 60:
                        times.append(dtime(hour, minute))
                times.sort()

                scheduled = set()
                for slot in times:
                    scheduled.add(slot.strftime("%H:%M"))
                published: list[tuple[str, dict[str, Any]]] = []
                for video in by_channel.get(channel["id"], []):
                    if video.get("status") != "published" or not video.get("published_at"):
                        continue
                    stamp = _local_dt(str(video["published_at"]))
                    if stamp and day_start <= stamp < day_end:
                        published.append((stamp.strftime("%H:%M"), video))

                ready = next(
                    (v for v in by_channel.get(channel["id"], [])
                     if v.get("status") == "ready" and v["id"] not in used_ready),
                    None,
                )
                producing = next(
                    (v for v in by_channel.get(channel["id"], [])
                     if v.get("status") in {"queued", "drafting", "uploading"} and v["id"] not in used_flight),
                    None,
                )

                if not times and not published:
                    entries.append({
                        "time": "—", "channel_id": channel["id"], "channel_name": channel.get("name", ""),
                        "state": "empty", "title": "", "note": "no airtime",
                    })
                    continue

                for slot in times:
                    clock = slot.strftime("%H:%M")
                    state, title, note = "planned", "", "new film"
                    match = next((v for stamp, v in published if stamp == clock), None)
                    if match:
                        state, title, note = "published", match.get("title") or "Untitled", "on YouTube"
                    elif offset == 0 and slot < now.time():
                        state, title, note = "done", "", "airtime passed"
                    elif ready is not None:
                        note = {
                            "review": "waiting for approval",
                            "blocked": "held by the quality gate",
                        }.get(str(ready.get("stage") or ""), "on the shelf")
                        state, title = "ready", ready.get("title") or "Untitled"
                        used_ready.add(ready["id"])
                        ready = None
                    elif producing is not None:
                        state, title, note = "producing", producing.get("title") or "in the works", "in production"
                        used_flight.add(producing["id"])
                        producing = None
                    entries.append({
                        "time": clock, "channel_id": channel["id"], "channel_name": channel.get("name", ""),
                        "state": state, "title": title, "note": note,
                    })
                for clock, video in published:
                    if clock in scheduled:
                        continue
                    entries.append({
                        "time": clock, "channel_id": channel["id"], "channel_name": channel.get("name", ""),
                        "state": "published", "title": video.get("title") or "Untitled", "note": "on YouTube",
                    })

            entries.sort(key=lambda row: row["time"])
            out_days.append({
                "date": day.isoformat(),
                "weekday": day.strftime("%a"),
                "label": day.strftime("%b %d"),
                "is_today": offset == 0,
                "slots": entries,
            })

        return {
            "days": out_days,
            "channels": [channel_public(c) for c in channels],
            "timezone": str(cfg.timezone()),
            "generated_at": now.isoformat(timespec="minutes"),
            "note": "Airtimes are local to the studio. A ready film is shown once, at the next slot that can carry it.",
        }

    @app.get("/api/brain")
    def brain(channel_id: str | None = None) -> dict[str, Any]:
        if channel_id:
            selected = db.get_channel(channel_id)
            if not selected:
                raise HTTPException(404, "no such channel")
            channels = [selected]
        else:
            channels = db.list_channels()

        out: list[dict[str, Any]] = []
        for channel in channels:
            playbook = channel.get("playbook") or {}
            stats = db.channel_stats(channel["id"])
            niches = playbook.get("niches") or {}
            styles = playbook.get("styles") or {}
            hours = playbook.get("hours") or {}
            best_niche = max(niches, key=niches.get) if niches else ""
            best_style = max(styles, key=styles.get) if styles else ""
            best_hour = max(hours, key=hours.get) if hours else ""
            samples = int(playbook.get("samples") or stats["published"] or 0)
            lessons = [j for j in db.list_journal(limit=30, channel_id=channel["id"]) if j.get("kind") == "lesson"]
            signal = trends.top_for_channel(channel)
            if samples == 0:
                recommendation = "No watch data yet. Run one film in each niche before trusting any score."
            elif best_niche:
                recommendation = (
                    f"Double down gently on {content.get_niche(best_niche).label}"
                    + (f" in the {best_style} register" if best_style else "")
                    + (f", around {best_hour}:00" if best_hour else "")
                    + "."
                )
            else:
                recommendation = "Keep exploring; the ledger needs a few more published films."
            out.append({
                "id": channel["id"],
                "name": channel.get("name", ""),
                "samples": samples,
                "insight": playbook.get("insight") or "",
                "best_niche": best_niche,
                "best_niche_label": content.get_niche(best_niche).label if best_niche in content.NICHES else "",
                "best_style": best_style,
                "best_hour": f"{best_hour}:00" if best_hour else "",
                "next_film": (
                    f"{content.get_niche(best_niche).label} · {best_style or 'unexplored'}"
                    if best_niche else "exploration cycle"
                ),
                "recommendation": recommendation,
                "last_lesson": lessons[0] if lessons else None,
                "signal": (
                    {"topic": signal["topic"], "opportunity": signal["opportunity"], "angle": signal.get("angle", "")}
                    if signal else None
                ),
                "stats": stats,
                "updated": playbook.get("updated") or "",
            })

        return {
            "channels": out,
            "generated_at": datetime.now(cfg.timezone()).isoformat(timespec="minutes"),
            "note": (
                "The brain only reports what the ledger has actually seen. Scores improve as published "
                "films accumulate watch time; nothing here is a forecast."
            ),
        }

    # -- videos ---------------------------------------------------------
    @app.get("/api/videos")
    def videos(
        limit: int = 60,
        offset: int = 0,
        format: str | None = None,
        status: str | None = None,
        archived: bool = False,
        channel_id: str | None = None,
    ) -> dict[str, Any]:
        items = db.list_videos(
            limit=limit, offset=offset, fmt=format, status=status,
            include_archived=archived, channel_id=channel_id,
        )
        return {"items": items, "count": len(items)}

    @app.get("/api/videos/{video_id}")
    def video_detail(video_id: str) -> dict[str, Any]:
        item = db.get_video(video_id)
        if not item:
            raise HTTPException(404, "no such film")
        channel = channel_by_id(cfg, db, item.get("channel_id")) or {}
        item["channel_name"] = channel.get("name", "")
        item["metrics"] = db.get_metrics(video_id)
        return item

    @app.post("/api/videos/{video_id}/publish")
    async def publish_film(video_id: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            return studio.publish(video_id, scheduled_for=str(body.get("scheduled_for") or "") or None)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/videos/{video_id}/quality")
    def video_quality(video_id: str, refresh: bool = False) -> dict[str, Any]:
        item = db.get_video(video_id)
        if not item:
            raise HTTPException(404, "no such film")
        channel = channel_by_id(cfg, db, item.get("channel_id"))
        report = item.get("quality")
        if refresh or not isinstance(report, dict) or not report.get("checks"):
            report = quality.inspect(cfg, item, channel)
            db.update_video(video_id, quality=report)
        return {"id": video_id, "quality": report, "summary": quality.summary(report)}

    @app.post("/api/videos/{video_id}/approve")
    async def approve_film(video_id: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            return studio.approve(video_id, scheduled_for=str(body.get("scheduled_for") or "") or None)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/videos/{video_id}/retry")
    def retry(video_id: str) -> dict[str, Any]:
        try:
            return studio.retry(video_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/videos/{video_id}/archive")
    async def archive(video_id: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        db.archive_video(video_id, bool(body.get("archived", True)))
        return {"id": video_id, "archived": bool(body.get("archived", True))}

    @app.get("/api/videos/{video_id}/share")
    def share(video_id: str) -> dict[str, Any]:
        video = db.get_video(video_id)
        if not video:
            raise HTTPException(404, "no such film")
        channel = channel_by_id(cfg, db, video.get("channel_id")) or {}
        narration = publish.load_narration(video)
        meta = publish.build_metadata(cfg, video, channel, narration)
        kit = publish.share_kit(video, channel, meta)
        kit["srt"] = publish.build_srt(narration) if narration.get("words") else ""
        kit["title"] = meta["title"]
        kit["description"] = meta["description"]
        return kit

    @app.post("/api/videos/{video_id}/thumbnail")
    async def choose_thumbnail(video_id: str, request: Request) -> dict[str, Any]:
        item = db.get_video(video_id)
        if not item:
            raise HTTPException(404, "no such film")
        try:
            body = await request.json()
        except Exception:
            body = {}
        variant_id = str((body or {}).get("variant") or "").strip()
        variants = item.get("thumb_variants") or []
        chosen = next((v for v in variants if v.get("id") == variant_id), None)
        if chosen is None:
            raise HTTPException(404, "no such thumbnail take")
        path = Path(str(chosen.get("path") or ""))
        if not path.is_file():
            raise HTTPException(404, "that thumbnail file is missing on disk")
        updated = [{**v, "recommended": v.get("id") == variant_id} for v in variants]
        db.update_video(video_id, thumb_path=str(path), thumb_variants=updated)
        bus.emit(
            "render",
            f"Thumbnail switched to “{chosen.get('label', variant_id)}” for “{item.get('title', 'a film')}”.",
            video_id=video_id,
        )
        return {"id": video_id, "thumb_path": str(path), "variants": updated}

    @app.get("/api/videos/{video_id}/file/{kind}")
    def video_file(video_id: str, kind: str, variant: str | None = None) -> FileResponse:
        item = db.get_video(video_id)
        if not item:
            raise HTTPException(404, "no such film")
        key = {
            "video": "video_path", "poster": "poster_path",
            "thumb": "thumb_path", "captions": "captions_path",
        }.get(kind)
        if not key:
            raise HTTPException(404, f"no {kind} for this film")
        path = Path(item[key]) if item.get(key) else None
        if kind == "thumb" and variant:
            chosen = next(
                (v for v in (item.get("thumb_variants") or []) if v.get("id") == variant), None
            )
            path = Path(str(chosen.get("path"))) if chosen and chosen.get("path") else None
        if not path:
            raise HTTPException(404, f"no {kind} for this film")
        if not path.is_file():
            raise HTTPException(404, "file missing on disk")
        media_types = {
            "video": "video/mp4", "poster": "image/jpeg",
            "thumb": "image/jpeg", "captions": "text/plain; charset=utf-8",
        }
        return FileResponse(path, media_type=media_types[kind])

    # -- channels -------------------------------------------------------
    @app.get("/api/channels")
    def channels() -> dict[str, Any]:
        now = datetime.now(cfg.timezone())
        out = []
        for channel in db.list_channels():
            account = youtube.account(channel["id"])
            state = account.status()
            public = channel_public(channel)
            public.update({
                "connected": state["connected"],
                "configured": state["configured"],
                "quota": state["quota"],
                "channel": state["channel"],
                "stats": db.channel_stats(channel["id"]),
                "next": (
                    next_airtime(channel, now).isoformat(timespec="minutes")
                    if channel.get("enabled", 1) else ""
                ),
            })
            out.append(public)
        return {
            "items": out,
            "templates": CHANNEL_TEMPLATES,
            "options": {
                "niches": [
                    {"id": key, "label": content.get_niche(key).label}
                    for key in content.niche_keys()
                ],
                "styles": [{"id": key, "label": key.title()} for key in content.STYLE_KEYS],
            },
            "count": len(out),
        }

    @app.post("/api/channels")
    async def create_channel(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "expected a channel object")
        fields = _validate_channel(body)
        if not fields.get("name"):
            raise HTTPException(400, "A channel needs a name.")
        base = _slug(str(body.get("id") or fields["name"]))
        channel_id = base
        suffix = 2
        while db.get_channel(channel_id):
            channel_id = f"{base}-{suffix}"
            suffix += 1
        record = {
            "id": channel_id,
            "slug": base,
            "name": fields.pop("name"),
            "tagline": fields.pop("tagline", ""),
            "kicker": fields.pop("kicker", str(body.get("name", "")).upper()),
            "niches": fields.pop("niches", [content.niche_keys()[0]]),
            "styles": fields.pop("styles", list(content.STYLE_KEYS)[:3]),
            "formats": fields.pop("formats", ["short"]),
            "times": fields.pop("times", ["12:00"]),
            "max_per_day": fields.pop("max_per_day", 1),
            "enabled": fields.pop("enabled", 1),
            "auto_upload": fields.pop("auto_upload", 1),
            "palette": fields.pop("palette", ""),
            "tone": fields.pop("tone", ""),
            "audience": fields.pop("audience", ""),
            "cta": fields.pop("cta", ""),
            "persona": fields.pop("persona", {}),
            "privacy": fields.pop("privacy", str(cfg.get("youtube.privacy", "private"))),
            "approval": fields.pop("approval", "auto"),
            "playbook": {},
            **fields,
        }
        db.create_channel(record)
        db.add_journal(
            channel_id,
            f"{record['name']} joined the network.",
            f"Niches: {', '.join(record['niches'])} · airtimes {', '.join(record['times'])}.",
            kind="birth",
        )
        bus.emit("autopilot", f"New channel on the network: {record['name']}.", level="success")
        scheduler.restart()
        return channel_public(db.get_channel(channel_id) or record)

    @app.patch("/api/channels/{channel_id}")
    async def edit_channel(channel_id: str, request: Request) -> dict[str, Any]:
        if not db.get_channel(channel_id):
            raise HTTPException(404, "no such channel")
        body = await request.json()
        fields = _validate_channel(body if isinstance(body, dict) else {})
        if not fields:
            raise HTTPException(400, "nothing to change")
        db.update_channel(channel_id, **fields)
        scheduler.restart()
        return channel_public(db.get_channel(channel_id) or {})

    @app.delete("/api/channels/{channel_id}")
    def remove_channel(channel_id: str) -> dict[str, Any]:
        channel = db.get_channel(channel_id)
        if not channel:
            raise HTTPException(404, "no such channel")
        if len(db.list_channels()) <= 1:
            raise HTTPException(400, "The network needs at least one channel.")
        db.delete_channel(channel_id)
        if db.get_pref("channels.primary") == channel_id:
            remaining = db.list_channels()
            db.set_pref("channels.primary", remaining[0]["id"] if remaining else "")
        bus.emit("autopilot", f"{channel['name']} left the network. Its films stayed on the shelf.", level="warning")
        scheduler.restart()
        return {"deleted": channel_id}

    @app.post("/api/channels/{channel_id}/generate")
    async def channel_generate(channel_id: str, request: Request) -> dict[str, Any]:
        channel = db.get_channel(channel_id)
        if not channel:
            raise HTTPException(404, "no such channel")
        try:
            body = await request.json()
        except Exception:
            body = {}
        fmt = str(body.get("format") or "") or None
        plan = showrunner.choose(channel, fmt=fmt)
        showrunner.record_decision(plan)
        record = studio.request(
            fmt=plan["format"],
            niche=str(body.get("niche") or plan["niche"]),
            topic=str(body.get("topic") or "") or None,
            guidance=plan["guidance"],
            channel_id=channel_id,
            style=plan["style"],
            palette=plan["palette"] or None,
        )
        return {"video": record, "plan": plan}

    @app.post("/api/channels/{channel_id}/pause")
    def channel_pause(channel_id: str) -> dict[str, Any]:
        if not db.get_channel(channel_id):
            raise HTTPException(404, "no such channel")
        db.update_channel(channel_id, enabled=0)
        scheduler.restart()
        return channel_public(db.get_channel(channel_id) or {})

    @app.post("/api/channels/{channel_id}/resume")
    def channel_resume(channel_id: str) -> dict[str, Any]:
        if not db.get_channel(channel_id):
            raise HTTPException(404, "no such channel")
        db.update_channel(channel_id, enabled=1)
        scheduler.restart()
        return channel_public(db.get_channel(channel_id) or {})

    # -- autopilot & growth ---------------------------------------------
    @app.post("/api/autopilot/think")
    async def autopilot_think(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        channel_id = str(body.get("channel_id") or "") or None

        def _think() -> dict[str, Any]:
            return showrunner.think(channel_id) if channel_id else showrunner.maybe_think(force=True)

        if bool(body.get("wait", False)):
            return await asyncio.to_thread(_think)

        def _background() -> None:
            try:
                _think()
            except Exception as exc:
                bus.emit("autopilot", f"Thinking failed: {exc}", level="warning")

        threading.Thread(target=_background, name="ghostlight-think", daemon=True).start()
        return {"status": "thinking", "channel_id": channel_id or "all"}

    @app.post("/api/autopilot/toggle")
    async def autopilot_toggle(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        enabled = bool(body.get("enabled", not bool(cfg.get("autopilot.enabled", True))))
        cfg.set("autopilot.enabled", enabled)
        cfg.save()
        bus.emit("autopilot", f"Autopilot {'engaged' if enabled else 'stood down'}.", level="success" if enabled else "warning")
        return showrunner.status()

    @app.get("/api/growth")
    def growth(limit: int = 10) -> dict[str, Any]:
        now = datetime.now(cfg.timezone())
        channels = []
        for channel in db.list_channels():
            account = youtube.account(channel["id"])
            state = account.status()
            rows = []
            for row in db.performance(channel["id"], limit=limit):
                rows.append({
                    "id": row["id"],
                    "title": row["title"],
                    "format": row["format"],
                    "published_at": row.get("published_at"),
                    "views": int(row.get("views") or 0),
                    "watch_minutes": float(row.get("watch_minutes") or 0),
                    "subs_gained": int(row.get("subs_gained") or 0),
                    "revenue": float(row.get("revenue") or 0),
                    "youtube_url": row.get("youtube_url") or "",
                })
            channels.append({
                **(channel_public(channel)),
                "connected": state["connected"],
                "configured": state["configured"],
                "youtube_channel": state["channel"],
                "quota": state["quota"],
                "stats": db.channel_stats(channel["id"]),
                "next": (
                    next_airtime(channel, now).isoformat(timespec="minutes")
                    if channel.get("enabled", 1) else ""
                ),
                "top_films": rows,
                "journal": db.list_journal(limit=6, channel_id=channel["id"]),
            })
        return {
            "summary": _growth_summary(),
            "channels": channels,
            "journal": db.list_journal(limit=24),
            "autopilot": showrunner.status(),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    @app.get("/api/journal")
    def journal(limit: int = 40, channel_id: str | None = None) -> dict[str, Any]:
        return {"items": db.list_journal(limit=limit, channel_id=channel_id)}

    @app.get("/feed.xml")
    def feed(limit: int = 40) -> Response:
        return Response(content=publish.rss(db, cfg, limit=limit), media_type="application/rss+xml")

    # -- events ---------------------------------------------------------
    @app.get("/api/events")
    def events(limit: int = 80, since: int = 0) -> dict[str, Any]:
        return {"items": db.list_events(limit=limit, since_id=since)}

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        queue = bus.subscribe()

        async def gen():
            try:
                yield "retry: 15000\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=20)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    payload = json.dumps(event, ensure_ascii=False, default=str)
                    yield f"data: {payload}\n\n"
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # -- schedule -------------------------------------------------------
    @app.post("/api/schedule/pause")
    def schedule_pause() -> dict[str, Any]:
        return scheduler.pause()

    @app.post("/api/schedule/resume")
    def schedule_resume() -> dict[str, Any]:
        return scheduler.resume()

    @app.post("/api/schedule/tick")
    def schedule_tick() -> dict[str, Any]:
        scheduler._tick()
        return scheduler.status()

    # -- settings -------------------------------------------------------
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return cfg.snapshot()

    @app.patch("/api/settings")
    async def update_settings(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict) or not body:
            raise HTTPException(400, "expected an object of dotted-path values")
        for dotted, value in body.items():
            cfg.set(str(dotted), value)
        cfg.save()
        scheduler.restart()
        return cfg.snapshot()

    # -- youtube --------------------------------------------------------
    def _base_url(request: Request) -> str:
        return str(cfg.get("youtube.oauth_redirect", "") or "").strip() or str(request.base_url).rstrip("/")

    def _start_oauth(channel_id: str | None, request: Request) -> dict[str, Any]:
        account = youtube.account(channel_id)
        if not account.configured:
            raise HTTPException(
                400,
                f"No Google OAuth client for {account.label()} yet. Upload client_secret.json "
                f"for this channel, then press connect again.",
            )
        try:
            flow = account.auth_url(redirect_uri=account.redirect_uri(_base_url(request)))
        except NotConfiguredError as exc:
            raise HTTPException(400, str(exc))
        except YouTubeError as exc:
            raise HTTPException(502, str(exc))
        db.add_journal(
            account.channel_id,
            f"Waiting for Google sign-in for {account.label()}.",
            "Approve the consent screen to let the studio upload, caption and read analytics.",
            kind="connection",
        )
        bus.emit("youtube", f"Google sign-in opened for {account.label()}.", level="info")
        return {"status": "authorizing", "url": flow["url"], "state": flow["state"],
                "redirect_uri": flow["redirect_uri"], "channel_id": account.channel_id}

    @app.post("/api/youtube/oauth/start")
    async def oauth_start(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        return await asyncio.to_thread(_start_oauth, str(body.get("channel_id") or "") or None, request)

    @app.get("/api/youtube/oauth/callback")
    def oauth_callback(request: Request) -> RedirectResponse:
        params = request.query_params
        state = str(params.get("state") or "")
        code = str(params.get("code") or "")
        if params.get("error"):
            return RedirectResponse(url=f"/?youtube=error&reason={params.get('error')}", status_code=302)
        pending = youtube.pending(state) if state else None
        if not pending:
            return RedirectResponse(url="/?youtube=error&reason=state", status_code=302)
        account = youtube.account(pending.get("channel_id"))
        try:
            account.complete_auth(code, state, pending.get("redirect_uri"))
        except Exception as exc:
            bus.emit("youtube", f"Sign-in failed for {account.label()}: {exc}", level="error")
            return RedirectResponse(url="/?youtube=error&reason=exchange", status_code=302)
        if not bool(cfg.get("youtube.enabled", False)):
            # Completing Google's consent screen is the explicit go-ahead.
            cfg.set("youtube.enabled", True)
            cfg.save()
            bus.emit("youtube", "Uploads switched on after the channel sign-in.", level="success")
        scheduler.go_live()
        return RedirectResponse(
            url=f"/?youtube=connected&channel={account.channel_id}", status_code=302
        )

    @app.post("/api/channels/{channel_id}/connect")
    def channel_connect(channel_id: str, request: Request) -> dict[str, Any]:
        if not db.get_channel(channel_id):
            raise HTTPException(404, "no such channel")
        return _start_oauth(channel_id, request)

    @app.post("/api/channels/{channel_id}/disconnect")
    def channel_disconnect(channel_id: str) -> dict[str, Any]:
        if not db.get_channel(channel_id):
            raise HTTPException(404, "no such channel")
        return youtube.account(channel_id).disconnect()

    @app.post("/api/youtube/client-secret")
    async def upload_client_secret(request: Request, channel_id: str = "") -> dict[str, Any]:
        raw = await request.body()
        if not raw:
            raise HTTPException(400, "empty upload")
        if len(raw) > 400_000:
            raise HTTPException(400, "that file is larger than an OAuth client should be")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(400, "client_secret.json is not valid JSON")
        if not isinstance(data, dict) or not ({"installed", "web"} & set(data)):
            raise HTTPException(400, "that does not look like a Google OAuth client file")
        account = youtube.account(channel_id or None)
        target = account.client_secret_target()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        db.add_journal(
            account.channel_id,
            f"OAuth client installed for {account.label()}.",
            "One click on Connect opens the Google consent screen.",
            kind="connection",
        )
        bus.emit("youtube", f"OAuth client installed for {account.label()}.", level="success")
        return {"ok": True, "channel_id": account.channel_id, "path": str(target)}

    @app.get("/api/youtube/secrets-dir")
    def secrets_dir() -> dict[str, Any]:
        return {"path": str(youtube.secrets_dir())}

    # Legacy single-channel buttons: both now answer with a Google URL.
    @app.post("/api/youtube/connect")
    def youtube_connect(request: Request) -> dict[str, Any]:
        return _start_oauth(None, request)

    @app.post("/api/youtube/disconnect")
    async def youtube_disconnect(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        channel_id = str(body.get("channel_id") or "") or None
        if channel_id:
            if not db.get_channel(channel_id):
                raise HTTPException(404, "no such channel")
            return youtube.account(channel_id).disconnect()
        return youtube.disconnect()

    @app.exception_handler(YouTubeError)
    async def youtube_error_handler(request: Request, exc: YouTubeError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app
