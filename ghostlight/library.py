from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__

# Housekeeping for the shelf: what is on disk, what can be exported, and what
# may be pruned. Deletion only ever touches archived or failed films, only
# inside the studio's own video directory, and only with an explicit confirm.


class LibraryError(RuntimeError):
    pass


def _size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _human_bytes(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def storage_report(cfg: Any, db: Any) -> dict[str, Any]:
    rows = db.all_video_rows()
    videos_root = Path(cfg.videos_dir)
    ids = {str(row["id"]) for row in rows}
    known_dirs = {p.name: _size(p) for p in videos_root.iterdir() if p.is_dir()} if videos_root.is_dir() else {}
    orphans = [name for name in known_dirs if name not in ids]

    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_language: dict[str, int] = {}
    for row in rows:
        kind = str(row.get("kind") or "film")
        status = str(row.get("status") or "unknown")
        language = str(row.get("language") or "en")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        by_language[language] = by_language.get(language, 0) + 1

    tracked = sum(int(row.get("bytes") or 0) for row in rows)
    on_disk = sum(known_dirs.values())
    largest = sorted(
        (
            {
                "id": row["id"], "title": row.get("title") or "Untitled",
                "kind": row.get("kind") or "film", "bytes": int(row.get("bytes") or 0),
            }
            for row in rows
        ),
        key=lambda row: row["bytes"],
        reverse=True,
    )[:6]

    data_dir = Path(cfg.data_dir)
    try:
        free = shutil.disk_usage(data_dir).free
    except OSError:
        free = 0
    exports = data_dir / "exports"
    backups = data_dir / "backups"

    return {
        "films": len([r for r in rows if (r.get("kind") or "film") == "film"]),
        "clips": len([r for r in rows if r.get("kind") == "clip"]),
        "records": len(rows),
        "tracked_bytes": tracked,
        "on_disk_bytes": on_disk,
        "tracked_human": _human_bytes(tracked),
        "on_disk_human": _human_bytes(on_disk),
        "database_bytes": _size(Path(cfg.db_path)),
        "exports_bytes": _size(exports),
        "backups_bytes": _size(backups),
        "free_bytes": free,
        "free_human": _human_bytes(free),
        "by_kind": by_kind,
        "by_status": by_status,
        "by_language": by_language,
        "largest": largest,
        "orphan_dirs": orphans,
        "orphan_bytes": sum(known_dirs[name] for name in orphans),
        "videos_dir": str(videos_root),
        "note": (
            "Orphan folders are artwork left behind by an interrupted render. "
            "They are reported, never deleted automatically."
        ),
    }


def export_catalogue(cfg: Any, db: Any, *, include_media: bool = False,
                     video_ids: list[str] | None = None) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    exports = Path(cfg.videos_dir).parent / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    target = exports / f"ghostlight-export-{stamp}.zip"

    rows = db.all_video_rows()
    if video_ids:
        wanted = set(video_ids)
        rows = [row for row in rows if str(row["id"]) in wanted]
    films = [db.get_video(str(row["id"])) or row for row in rows]

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "id", "kind", "parent_id", "language", "created_at", "title", "status", "format",
        "niche", "channel_id", "duration", "bytes", "published_at", "youtube_url",
    ])
    for film in films:
        writer.writerow([
            film.get("id", ""), film.get("kind") or "film", film.get("parent_id", ""),
            film.get("language") or "en", film.get("created_at", ""), film.get("title", ""),
            film.get("status", ""), film.get("format", ""), film.get("niche", ""),
            film.get("channel_id", ""), film.get("duration", 0), film.get("bytes", 0),
            film.get("published_at", ""), film.get("youtube_url", ""),
        ])

    manifest = {
        "studio": cfg.get("studio.name", "Ghostlight Studio"),
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "films": len(films),
        "include_media": bool(include_media),
        "note": "Exported by Ghostlight Studio. Localizations are included when present.",
    }

    media_files = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        archive.writestr("films.json", json.dumps(films, indent=2, ensure_ascii=False, default=str))
        archive.writestr("films.csv", buffer.getvalue())
        localizations: dict[str, Any] = {}
        for film in films:
            video_id = str(film.get("id") or "")
            items = db.list_localizations(video_id)
            if items:
                localizations[video_id] = items
        if localizations:
            archive.writestr("localizations.json", json.dumps(localizations, indent=2, ensure_ascii=False))
        if include_media:
            for film in films:
                video_id = str(film.get("id") or "")
                entries = [
                    ("video", film.get("video_path")),
                    ("thumb", film.get("thumb_path")),
                    ("poster", film.get("poster_path")),
                    ("captions", film.get("captions_path")),
                    ("narration", film.get("narration_path")),
                    ("music", film.get("music_path")),
                ]
                narration = Path(str(film.get("narration_path") or ""))
                if narration.name:
                    entries.append(("narration.json", str(narration.with_name("narration.json"))))
                for label, raw in entries:
                    source = Path(str(raw or ""))
                    if not raw or not source.is_file():
                        continue
                    arcname = f"media/{video_id}/{label}{source.suffix}"
                    archive.write(source, arcname)
                    media_files += 1
            for video_id, items in localizations.items():
                for item in items:
                    for label, key in (("captions", "srt_path"), ("voice", "audio_path")):
                        source = Path(str(item.get(key) or ""))
                        if source.is_file():
                            archive.write(source, f"media/{video_id}/lang/{item['language']}/{label}{source.suffix}")
                            media_files += 1

    return {
        "path": str(target),
        "bytes": target.stat().st_size,
        "human": _human_bytes(target.stat().st_size),
        "films": len(films),
        "media_files": media_files,
        "include_media": bool(include_media),
    }


def backup_database(cfg: Any, db: Any, keep: int = 10) -> dict[str, Any]:
    backups = Path(cfg.data_dir) / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backups / f"studio-{stamp}.db"
    source = sqlite3.connect(str(cfg.db_path))
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
            destination.execute("PRAGMA wal_checkpoint(FULL)")
        finally:
            destination.close()
    finally:
        source.close()

    removed = 0
    keep = max(1, int(keep))
    existing = sorted(backups.glob("studio-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in existing[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            continue
    return {
        "path": str(target),
        "bytes": target.stat().st_size if target.is_file() else 0,
        "human": _human_bytes(target.stat().st_size if target.is_file() else 0),
        "removed": removed,
        "kept": min(len(existing), keep),
    }


def _film_files(cfg: Any, row: dict[str, Any]) -> list[Path]:
    root = Path(cfg.videos_dir).resolve()
    video_dir = (Path(cfg.videos_dir) / str(row["id"])).resolve()
    files: list[Path] = []
    if video_dir.is_dir() and root in video_dir.parents:
        files = [p for p in video_dir.rglob("*") if p.is_file()]
    return files


def prune_plan(cfg: Any, db: Any, days: int = 60) -> dict[str, Any]:
    days = max(1, min(3650, int(days)))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    candidates = []
    total = 0
    for row in db.all_video_rows():
        status = str(row.get("status") or "")
        archived = bool(row.get("archived"))
        if not archived and status != "failed":
            continue
        try:
            touched = datetime.fromisoformat(str(row.get("updated_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if touched.tzinfo is None:
            touched = touched.replace(tzinfo=timezone.utc)
        if touched > cutoff:
            continue
        files = _film_files(cfg, row)
        size = sum(p.stat().st_size for p in files if p.exists())
        total += size
        candidates.append({
            "id": row["id"],
            "title": row.get("title") or "Untitled",
            "kind": row.get("kind") or "film",
            "status": status or "unknown",
            "archived": archived,
            "updated_at": row.get("updated_at") or "",
            "files": len(files),
            "bytes": size,
            "human": _human_bytes(size),
        })
    return {
        "days": days,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "candidates": candidates,
        "count": len(candidates),
        "total_bytes": total,
        "total_human": _human_bytes(total),
        "note": (
            "Only archived or failed films older than the cutoff are listed. "
            "Nothing is removed until you confirm."
        ),
    }


def apply_prune(cfg: Any, db: Any, video_ids: list[str], *, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise LibraryError("Pruning needs an explicit confirmation.")
    root = Path(cfg.videos_dir).resolve()
    known = {str(row["id"]): row for row in db.all_video_rows()}
    removed_files = 0
    removed_bytes = 0
    removed_records = 0
    skipped: list[str] = []
    for raw in video_ids or []:
        video_id = str(raw)
        row = known.get(video_id)
        if row is None:
            skipped.append(video_id)
            continue
        if not bool(row.get("archived")) and str(row.get("status") or "") != "failed":
            skipped.append(video_id)
            continue
        video_dir = (Path(cfg.videos_dir) / video_id).resolve()
        if root not in video_dir.parents:
            skipped.append(video_id)
            continue
        if video_dir.is_dir():
            for item in video_dir.rglob("*"):
                try:
                    if item.is_file():
                        removed_bytes += item.stat().st_size
                        removed_files += 1
                except OSError:
                    continue
            try:
                shutil.rmtree(video_dir)
            except OSError:
                skipped.append(video_id)
                continue
        db.delete_video(video_id)
        removed_records += 1
    return {
        "removed_records": removed_records,
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "removed_human": _human_bytes(removed_bytes),
        "skipped": skipped,
    }
