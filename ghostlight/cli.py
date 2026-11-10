from __future__ import annotations

import argparse
import sys
from typing import Any

from . import __version__
from .config import Config, load_config
from .db import Database
from .events import EventBus
from .orchestrator import Studio
from .scheduler import Scheduler
from .showrunner import Showrunner
from .youtube import YouTubeHub


def _build(cfg: Config) -> tuple[Database, EventBus, Studio, Scheduler, YouTubeHub]:
    db = Database(cfg.db_path)
    bus = EventBus(db)
    youtube = YouTubeHub(
        cfg, db, on_event=lambda level, kind, message: bus.emit(kind, message, level=level)
    )
    showrunner = Showrunner(cfg, db, bus, youtube)
    showrunner.ensure_lineup()
    studio = Studio(cfg, db, bus, youtube, showrunner=showrunner)
    scheduler = Scheduler(cfg, db, bus, studio, showrunner=showrunner)
    return db, bus, studio, scheduler, youtube


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghostlight",
        description="Ghostlight Studio — a faceless, autonomous generative video studio.",
    )
    parser.add_argument("--config", default=None, help="path to config.yaml")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the studio desk (web dashboard + autonomy)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    make = sub.add_parser("make", help="produce one film now and watch the desk")
    make.add_argument("--format", choices=["short", "long"], default="short")
    make.add_argument("--niche", default=None)
    make.add_argument("--topic", default=None)

    upload = sub.add_parser("upload", help="publish the newest ready film")
    upload.add_argument("--id", default=None, help="specific film id")

    status = sub.add_parser("status", help="report the state of the studio")
    log = sub.add_parser("log", help="tail the studio log")
    log.add_argument("-n", type=int, default=40)

    connect = sub.add_parser("connect", help="link your YouTube channel")

    clips = sub.add_parser("clips", help="cut vertical clips from a finished film")
    clips.add_argument("--id", default=None, help="source film id")
    clips.add_argument("--count", type=int, default=3)
    clips.add_argument("--dry-run", action="store_true", help="only show the plan")

    sub.add_parser("backup", help="write a safe SQLite backup and keep the last ten")

    sub.add_parser("version", help="print version")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    if args.command == "version":
        print(f"Ghostlight Studio {__version__}")
        return 0

    cfg = load_config(args.config)

    if args.command == "serve":
        import uvicorn

        from .app import create_app

        host = args.host or str(cfg.get("studio.host", "127.0.0.1"))
        port = args.port or int(cfg.get("studio.port", 8787))
        app = create_app(cfg)
        print(f"The desk is open at http://{host}:{port}")
        uvicorn.run(app, host=host, port=port, log_level="warning")
        return 0

    db, bus, studio, scheduler, youtube = _build(cfg)

    if args.command == "make":
        studio.start()
        record = studio.request(fmt=args.format, niche=args.niche, topic=args.topic)
        print(f"Commissioning {record['id']} ({args.format})")
        import time

        for _ in range(2400):
            time.sleep(1)
            video = db.get_video(record["id"])
            if video and video["status"] in {"ready", "failed", "published"}:
                break
        video = db.get_video(record["id"]) or {}
        print(f"Final status: {video.get('status')} — {video.get('title', '')}")
        if video.get("video_path"):
            print(f"Film: {video['video_path']}")
        if video.get("error"):
            print(f"Error: {video['error'][:500]}")
        studio.stop()
        return 0 if video.get("status") in {"ready", "published"} else 1

    if args.command == "upload":
        if args.id:
            video = db.get_video(args.id)
        else:
            ready = db.list_videos(limit=1, status="ready")
            video = ready[0] if ready else None
        if not video:
            print("Nothing ready to upload.")
            return 1
        studio.start()
        result = studio.publish(video["id"])
        print(result)
        import time

        for _ in range(600):
            time.sleep(1)
            current = db.get_video(video["id"]) or {}
            if current.get("status") in {"published", "ready"}:
                break
        current = db.get_video(video["id"]) or {}
        print(f"Status: {current.get('status')} {current.get('youtube_url', '')}")
        if current.get("error"):
            print(f"Error: {current['error'][:500]}")
        studio.stop()
        return 0 if current.get("status") == "published" else 1

    if args.command == "clips":
        video = db.get_video(args.id) if args.id else None
        if not video:
            ready = [v for v in db.list_videos(limit=20, status="ready") if (v.get("kind") or "film") == "film"]
            video = db.get_video(ready[0]["id"]) if ready else None
        if not video:
            print("No finished film to cut from.")
            return 1
        result = studio.repurpose(video["id"], count=args.count, dry_run=args.dry_run)
        print(f"“{video.get('title', 'Film')}” — {len(result['clips'])} candidate cut(s)")
        for clip in result["clips"]:
            print(
                f"  · {clip['start']:6.1f}–{clip['end']:6.1f}s  score {clip['score']:>3}  "
                f"{clip['title']}"
            )
        if result.get("note"):
            print(f"  {result['note']}")
        if args.dry_run or not result.get("queued"):
            return 0
        before = len(db.list_clips(video["id"]))
        studio.start()
        import time

        for _ in range(1800):
            time.sleep(1)
            if len(db.list_clips(video["id"])) > before:
                break
        made = db.list_clips(video["id"])
        studio.stop()
        print(f"Clips on the shelf: {len(made)}")
        for clip in made:
            print(f"  · {clip.get('title')} — {clip.get('video_path')}")
        return 0 if made else 1

    if args.command == "backup":
        from . import library

        result = library.backup_database(cfg, db)
        print(f"Backup written: {result['path']} ({result['human']})")
        if result["removed"]:
            print(f"Removed {result['removed']} older backup(s), kept {result['kept']}.")
        return 0

    if args.command == "status":
        stats = db.stats()
        sched = scheduler.status()
        yt = youtube.status()
        print(f"Films made:     {stats['total']} ({stats['published']} published, {stats['ready']} ready)")
        print(f"Runtime:        {stats['minutes']:.0f} minutes, {stats['words']:,} words")
        print(f"Schedule:       {'paused' if sched['paused'] else 'on' if sched['enabled'] else 'off'} — {scheduler.describe()}")
        print(f"Made today:     {sched['produced_today']}/{sched['max_per_day']}")
        print(f"YouTube:        {'linked: ' + (yt['channel'].get('name') or '?') if yt['connected'] else 'not linked'}")
        print(f"Quota:          {yt['quota']['units_used']}/{yt['quota']['units_limit']} units, "
              f"{yt['quota']['uploads_used']}/{yt['quota']['upload_limit']} uploads today")
        for channel in sched.get("channels", []):
            linked = "linked" if channel.get("linked") else "waiting for Google sign-in"
            print(
                f"  · {channel['name']:<28} {channel.get('produced_today', 0)}/"
                f"{channel.get('max_per_day', 1)} today · next {channel.get('next', '—')} · {linked}"
            )
        return 0

    if args.command == "log":
        events = db.list_events(limit=args.n)
        for event in events:
            print(f"[{event['ts'][11:19]}] {event['level']:>7} {event['kind']:<10} {event['message']}")
        return 0

    if args.command == "connect":
        try:
            result = youtube.authorize()
            channel = result.get("channel") or {}
            if not bool(cfg.get("youtube.enabled", False)):
                cfg.set("youtube.enabled", True)
                cfg.save()
            scheduler.go_live()
            print(f"Connected: {channel.get('name') or '(channel)'}")
            return 0
        except Exception as exc:
            print(f"Could not connect: {exc}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
