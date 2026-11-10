from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

VIDEO_COLUMNS = {
    "id",
    "created_at",
    "updated_at",
    "channel_id",
    "format",
    "niche",
    "style",
    "title",
    "description",
    "tags",
    "hook",
    "script",
    "brief",
    "fingerprint",
    "novelty",
    "duration",
    "words",
    "status",
    "stage",
    "progress",
    "narration_path",
    "music_path",
    "video_path",
    "thumb_path",
    "poster_path",
    "captions_path",
    "scheduled_for",
    "youtube_id",
    "youtube_url",
    "privacy",
    "published_at",
    "upload_meta",
    "bytes",
    "error",
    "archived",
    "quality",
    "thumb_variants",
    "kind",
    "parent_id",
    "language",
    "editorial",
    "clip_start",
    "clip_end",
}

JSON_COLUMNS = {
    "tags", "script", "brief", "fingerprint", "upload_meta", "quality",
    "thumb_variants", "editorial",
}

CHANNEL_COLUMNS = {
    "id", "created_at", "updated_at", "name", "slug", "tagline", "persona",
    "niches", "formats", "styles", "palette", "tone", "audience", "cta", "kicker",
    "times", "max_per_day", "mode", "enabled", "auto_upload", "privacy", "approval",
    "youtube_id", "youtube_name", "subscribers", "views", "token_path",
    "client_secret_path", "playbook", "last_run", "error",
}

CHANNEL_JSON = {"persona", "niches", "formats", "styles", "times", "playbook"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    channel_id TEXT DEFAULT '',
    format TEXT NOT NULL DEFAULT 'short',
    niche TEXT DEFAULT '',
    style TEXT DEFAULT '',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    hook TEXT DEFAULT '',
    script TEXT DEFAULT '{}',
    brief TEXT DEFAULT '{}',
    fingerprint TEXT DEFAULT '{}',
    novelty REAL DEFAULT 1.0,
    duration REAL DEFAULT 0,
    words INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT DEFAULT '',
    progress INTEGER DEFAULT 0,
    narration_path TEXT DEFAULT '',
    music_path TEXT DEFAULT '',
    video_path TEXT DEFAULT '',
    thumb_path TEXT DEFAULT '',
    poster_path TEXT DEFAULT '',
    captions_path TEXT DEFAULT '',
    scheduled_for TEXT DEFAULT '',
    youtube_id TEXT DEFAULT '',
    youtube_url TEXT DEFAULT '',
    privacy TEXT DEFAULT '',
    published_at TEXT DEFAULT '',
    upload_meta TEXT DEFAULT '{}',
    bytes INTEGER DEFAULT 0,
    error TEXT DEFAULT '',
    archived INTEGER DEFAULT 0,
    quality TEXT DEFAULT '{}',
    thumb_variants TEXT DEFAULT '[]',
    kind TEXT DEFAULT 'film',
    parent_id TEXT DEFAULT '',
    language TEXT DEFAULT 'en',
    editorial TEXT DEFAULT '{}',
    clip_start REAL DEFAULT 0,
    clip_end REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota (
    day TEXT PRIMARY KEY,
    units INTEGER NOT NULL DEFAULT 0,
    uploads INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    kind TEXT NOT NULL DEFAULT 'note',
    message TEXT NOT NULL,
    video_id TEXT DEFAULT '',
    data TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    text TEXT NOT NULL,
    action TEXT DEFAULT '{}',
    reply TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT DEFAULT '',
    tagline TEXT DEFAULT '',
    persona TEXT DEFAULT '{}',
    niches TEXT DEFAULT '[]',
    formats TEXT DEFAULT '[]',
    styles TEXT DEFAULT '[]',
    palette TEXT DEFAULT '',
    tone TEXT DEFAULT '',
    audience TEXT DEFAULT '',
    cta TEXT DEFAULT '',
    kicker TEXT DEFAULT '',
    times TEXT DEFAULT '[]',
    max_per_day INTEGER DEFAULT 1,
    mode TEXT DEFAULT 'rhythm',
    enabled INTEGER DEFAULT 1,
    auto_upload INTEGER DEFAULT 1,
    privacy TEXT DEFAULT '',
    approval TEXT DEFAULT 'auto',
    youtube_id TEXT DEFAULT '',
    youtube_name TEXT DEFAULT '',
    subscribers INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    token_path TEXT DEFAULT '',
    client_secret_path TEXT DEFAULT '',
    playbook TEXT DEFAULT '{}',
    last_run TEXT DEFAULT '',
    error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS video_metrics (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT DEFAULT '',
    fetched_at TEXT DEFAULT '',
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    watch_minutes REAL DEFAULT 0,
    avg_view_seconds REAL DEFAULT 0,
    subs_gained INTEGER DEFAULT 0,
    revenue REAL DEFAULT 0,
    raw TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    channel_id TEXT DEFAULT '',
    kind TEXT DEFAULT 'note',
    headline TEXT NOT NULL DEFAULT '',
    body TEXT DEFAULT '',
    data TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    level TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    video_id TEXT DEFAULT '',
    link TEXT DEFAULT '',
    read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read, id DESC);

CREATE TABLE IF NOT EXISTS localizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    srt_path TEXT DEFAULT '',
    audio_path TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    voice TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(video_id, language)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, (set, tuple)):
        return list(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _decode_row(row: sqlite3.Row | None, full: bool = True) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for col in JSON_COLUMNS:
        if col in item and isinstance(item[col], str):
            try:
                item[col] = json.loads(item[col])
            except json.JSONDecodeError:
                item[col] = {} if col != "tags" else []
    if not full:
        item.pop("script", None)
        item.pop("brief", None)
        item.pop("fingerprint", None)
    return item


def _decode_localization(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    try:
        item["tags"] = json.loads(item.get("tags") or "[]")
    except json.JSONDecodeError:
        item["tags"] = []
    return item


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._ensure_columns(conn)
            self._ensure_channel_columns(conn)
            # Indexes after migration: older databases gain these columns above.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_parent ON videos(parent_id)")

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(videos)")}
        additions = {
            "poster_path": "TEXT DEFAULT ''",
            "published_at": "TEXT DEFAULT ''",
            "upload_meta": "TEXT DEFAULT '{}'",
            "channel_id": "TEXT DEFAULT ''",
            "quality": "TEXT DEFAULT '{}'",
            "thumb_variants": "TEXT DEFAULT '[]'",
            "kind": "TEXT DEFAULT 'film'",
            "parent_id": "TEXT DEFAULT ''",
            "language": "TEXT DEFAULT 'en'",
            "editorial": "TEXT DEFAULT '{}'",
            "clip_start": "REAL DEFAULT 0",
            "clip_end": "REAL DEFAULT 0",
        }
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE videos ADD COLUMN {name} {ddl}")

    @staticmethod
    def _ensure_channel_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(channels)")}
        additions = {
            "approval": "TEXT DEFAULT 'auto'",
        }
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE channels ADD COLUMN {name} {ddl}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- videos ---------------------------------------------------------
    def create_video(self, record: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        data = {k: v for k, v in record.items() if k in VIDEO_COLUMNS}
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        for col in JSON_COLUMNS:
            if col in data and not isinstance(data[col], str):
                data[col] = _encode(data[col])
        cols = ", ".join(data)
        marks = ", ".join(["?"] * len(data))
        with self._write_lock, self._connect() as conn:
            conn.execute(f"INSERT OR REPLACE INTO videos ({cols}) VALUES ({marks})", tuple(data.values()))
        return self.get_video(str(data["id"])) or data

    def update_video(self, video_id: str, **fields: Any) -> None:
        clean = {k: v for k, v in fields.items() if k in VIDEO_COLUMNS and k != "id"}
        if not clean:
            return
        clean["updated_at"] = utcnow()
        for col in JSON_COLUMNS:
            if col in clean and not isinstance(clean[col], str):
                clean[col] = _encode(clean[col])
        assignments = ", ".join(f"{col} = ?" for col in clean)
        with self._write_lock, self._connect() as conn:
            conn.execute(
                f"UPDATE videos SET {assignments} WHERE id = ?",
                (*clean.values(), video_id),
            )

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return _decode_row(row, full=True)

    def list_videos(
        self,
        limit: int = 60,
        offset: int = 0,
        fmt: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        channel_id: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        parent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if fmt:
            clauses.append("format = ?")
            params.append(fmt)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if channel_id:
            clauses.append("channel_id = ?")
            params.append(channel_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if language:
            clauses.append("language = ?")
            params.append(language)
        if parent_id:
            clauses.append("parent_id = ?")
            params.append(parent_id)
        if not include_archived:
            clauses.append("archived = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(limit, 200)), max(0, offset)])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM videos {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                tuple(params),
            ).fetchall()
        return [_decode_row(r, full=False) for r in rows if r is not None]  # type: ignore[misc]

    def archive_video(self, video_id: str, archived: bool = True) -> None:
        self.update_video(video_id, archived=1 if archived else 0)

    def delete_video(self, video_id: str) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
            conn.execute("DELETE FROM video_metrics WHERE video_id = ?", (video_id,))
            conn.execute("DELETE FROM localizations WHERE video_id = ?", (video_id,))

    def all_video_rows(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Every film row, archived included, for the library and maintenance desk."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, parent_id, kind, language, title, status, stage, format, niche, "
                "channel_id, duration, bytes, archived, created_at, updated_at, published_at, "
                "video_path, poster_path, thumb_path, captions_path, narration_path, music_path, "
                "youtube_url FROM videos ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 20000)),),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_clips(self, parent_id: str, include_archived: bool = True) -> list[dict[str, Any]]:
        return self.list_videos(
            limit=60, parent_id=parent_id, kind="clip", include_archived=include_archived
        )

    def all_fingerprints(self, limit: int = 5000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, fingerprint, niche, created_at FROM videos "
                "WHERE fingerprint IS NOT NULL AND fingerprint != '{}' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["fingerprint"] = json.loads(item["fingerprint"] or "{}")
            except json.JSONDecodeError:
                continue
            if item["fingerprint"]:
                result.append(item)
        return result

    def recent_titles(self, limit: int = 40) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title, niche, hook FROM videos WHERE status != 'failed' "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- channels -------------------------------------------------------
    def create_channel(self, record: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        data = {k: v for k, v in record.items() if k in CHANNEL_COLUMNS}
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        for col in CHANNEL_JSON:
            if col in data and not isinstance(data[col], str):
                data[col] = _encode(data[col])
        cols = ", ".join(data)
        marks = ", ".join(["?"] * len(data))
        with self._write_lock, self._connect() as conn:
            conn.execute(f"INSERT OR REPLACE INTO channels ({cols}) VALUES ({marks})", tuple(data.values()))
        return self.get_channel(str(data["id"])) or data

    def update_channel(self, channel_id: str, **fields: Any) -> None:
        clean = {k: v for k, v in fields.items() if k in CHANNEL_COLUMNS and k != "id"}
        if not clean:
            return
        clean["updated_at"] = utcnow()
        for col in CHANNEL_JSON:
            if col in clean and not isinstance(clean[col], str):
                clean[col] = _encode(clean[col])
        assignments = ", ".join(f"{col} = ?" for col in clean)
        with self._write_lock, self._connect() as conn:
            conn.execute(
                f"UPDATE channels SET {assignments} WHERE id = ?",
                (*clean.values(), channel_id),
            )

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        for col in CHANNEL_JSON:
            try:
                item[col] = json.loads(item[col] or ("[]" if col != "persona" and col != "playbook" else "{}"))
            except json.JSONDecodeError:
                item[col] = [] if col not in {"persona", "playbook"} else {}
        return item

    def list_channels(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else "WHERE enabled = 1"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM channels {where} ORDER BY created_at ASC"
            ).fetchall()
        out = []
        for row in rows:
            item = self.get_channel(row["id"])
            if item:
                out.append(item)
        return out

    def delete_channel(self, channel_id: str) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            conn.execute("DELETE FROM journal WHERE channel_id = ?", (channel_id,))
            conn.execute("UPDATE videos SET channel_id = '' WHERE channel_id = ?", (channel_id,))

    def assign_orphans(self, channel_id: str) -> int:
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE videos SET channel_id = ? WHERE channel_id IS NULL OR channel_id = ''",
                (channel_id,),
            )
            return int(cur.rowcount or 0)

    def channel_stats(self, channel_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            videos = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(duration), 0) AS seconds "
                "FROM videos WHERE channel_id = ? AND status != 'failed'",
                (channel_id,),
            ).fetchone()
            published = conn.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE channel_id = ? AND status = 'published'",
                (channel_id,),
            ).fetchone()
            ready = conn.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE channel_id = ? AND status = 'ready'",
                (channel_id,),
            ).fetchone()
            in_flight = conn.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE channel_id = ? "
                "AND status IN ('queued','drafting','uploading')",
                (channel_id,),
            ).fetchone()
            metrics = conn.execute(
                "SELECT COALESCE(SUM(views), 0) AS views, COALESCE(SUM(watch_minutes), 0) AS minutes, "
                "COALESCE(SUM(subs_gained), 0) AS subs, COALESCE(SUM(revenue), 0) AS revenue "
                "FROM video_metrics WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
            last = conn.execute(
                "SELECT youtube_url, updated_at FROM videos WHERE channel_id = ? AND status = 'published' "
                "ORDER BY updated_at DESC LIMIT 1",
                (channel_id,),
            ).fetchone()
        return {
            "films": int(videos["n"] or 0) if videos else 0,
            "seconds": round(float(videos["seconds"] or 0), 1) if videos else 0.0,
            "published": int(published["n"] or 0) if published else 0,
            "ready": int(ready["n"] or 0) if ready else 0,
            "in_flight": int(in_flight["n"] or 0) if in_flight else 0,
            "views": int(metrics["views"] or 0) if metrics else 0,
            "watch_minutes": round(float(metrics["minutes"] or 0), 1) if metrics else 0.0,
            "subs_gained": int(metrics["subs"] or 0) if metrics else 0,
            "revenue": round(float(metrics["revenue"] or 0), 2) if metrics else 0.0,
            "last_url": last["youtube_url"] if last else "",
            "last_published_at": last["updated_at"] if last else "",
        }

    # -- metrics & journal ---------------------------------------------
    def upsert_metrics(self, video_id: str, channel_id: str, values: dict[str, Any]) -> None:
        payload = (
            video_id, channel_id, utcnow(),
            int(values.get("views", 0) or 0),
            int(values.get("likes", 0) or 0),
            int(values.get("comments", 0) or 0),
            float(values.get("watch_minutes", 0) or 0),
            float(values.get("avg_view_seconds", 0) or 0),
            int(values.get("subs_gained", 0) or 0),
            float(values.get("revenue", 0) or 0),
            _encode(values.get("raw") or {}),
        )
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO video_metrics (video_id, channel_id, fetched_at, views, likes, comments, "
                "watch_minutes, avg_view_seconds, subs_gained, revenue, raw) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET "
                "channel_id=excluded.channel_id, fetched_at=excluded.fetched_at, views=excluded.views, "
                "likes=excluded.likes, comments=excluded.comments, watch_minutes=excluded.watch_minutes, "
                "avg_view_seconds=excluded.avg_view_seconds, subs_gained=excluded.subs_gained, "
                "revenue=excluded.revenue, raw=excluded.raw",
                payload,
            )

    def get_metrics(self, video_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM video_metrics WHERE video_id = ?", (video_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["raw"] = json.loads(item.get("raw") or "{}")
        except json.JSONDecodeError:
            item["raw"] = {}
        return item

    def published_videos(self, channel_id: str, limit: int = 60) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, youtube_id, published_at FROM videos "
                "WHERE channel_id = ? AND status = 'published' AND youtube_id != '' "
                "ORDER BY updated_at DESC LIMIT ?",
                (channel_id, max(1, min(limit, 200))),
            ).fetchall()
        return [dict(r) for r in rows]

    def performance(self, channel_id: str, limit: int = 40) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT v.id, v.title, v.format, v.niche, v.style, v.published_at, v.youtube_url, "
                "v.script, m.views, m.likes, m.comments, m.watch_minutes, m.subs_gained, m.revenue "
                "FROM videos v LEFT JOIN video_metrics m ON m.video_id = v.id "
                "WHERE v.channel_id = ? AND v.status = 'published' "
                "ORDER BY COALESCE(m.views, 0) DESC, v.updated_at DESC LIMIT ?",
                (channel_id, max(1, min(limit, 200))),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["script"] = json.loads(item["script"] or "{}")
            except json.JSONDecodeError:
                item["script"] = {}
            out.append(item)
        return out

    def add_journal(
        self,
        channel_id: str,
        headline: str,
        body: str = "",
        kind: str = "note",
        data: dict[str, Any] | None = None,
    ) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO journal (ts, channel_id, kind, headline, body, data) VALUES (?,?,?,?,?,?)",
                (utcnow(), channel_id, kind, headline[:200], body[:4000], _encode(data or {})),
            )

    def list_journal(self, limit: int = 40, channel_id: str | None = None) -> list[dict[str, Any]]:
        if channel_id:
            clause, params = "WHERE channel_id = ?", (channel_id, limit)
        else:
            # A channel removed before journal cleanup existed should not
            # keep narrating in the network feed.
            clause = "WHERE channel_id = '' OR channel_id IN (SELECT id FROM channels)"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM journal {clause} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["data"] = json.loads(item.pop("data") or "{}")
            except json.JSONDecodeError:
                item["data"] = {}
            out.append(item)
        return out

    # -- notifications --------------------------------------------------
    def add_notification(
        self,
        title: str,
        body: str = "",
        kind: str = "note",
        level: str = "info",
        video_id: str = "",
        link: str = "",
    ) -> dict[str, Any]:
        ts = utcnow()
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notifications (ts, kind, level, title, body, video_id, link) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, kind, level, title[:200], body[:1000], video_id, link),
            )
            notification_id = int(cur.lastrowid or 0)
        return {
            "id": notification_id, "ts": ts, "kind": kind, "level": level,
            "title": title, "body": body, "video_id": video_id, "link": link, "read": 0,
        }

    def list_notifications(self, limit: int = 40, unread_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE read = 0" if unread_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM notifications {where} ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(r) for r in rows]

    def unread_notifications(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM notifications WHERE read = 0").fetchone()
        return int(row["n"]) if row else 0

    def mark_notification(self, notification_id: int) -> int:
        with self._write_lock, self._connect() as conn:
            if notification_id:
                cur = conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,))
            else:
                cur = conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
            return int(cur.rowcount or 0)

    # -- localizations --------------------------------------------------
    def upsert_localization(self, video_id: str, language: str, values: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        payload = {
            "video_id": video_id,
            "language": language,
            "status": str(values.get("status") or "ready"),
            "title": str(values.get("title") or ""),
            "description": str(values.get("description") or ""),
            "tags": _encode(values.get("tags") or []),
            "srt_path": str(values.get("srt_path") or ""),
            "audio_path": str(values.get("audio_path") or ""),
            "provider": str(values.get("provider") or ""),
            "voice": str(values.get("voice") or ""),
            "note": str(values.get("note") or "")[:1000],
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO localizations (video_id, language, status, title, description, tags, "
                "srt_path, audio_path, provider, voice, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(video_id, language) DO UPDATE SET status=excluded.status, "
                "title=excluded.title, description=excluded.description, tags=excluded.tags, "
                "srt_path=excluded.srt_path, audio_path=excluded.audio_path, "
                "provider=excluded.provider, voice=excluded.voice, note=excluded.note, "
                "updated_at=excluded.updated_at",
                (
                    payload["video_id"], payload["language"], payload["status"], payload["title"],
                    payload["description"], payload["tags"], payload["srt_path"], payload["audio_path"],
                    payload["provider"], payload["voice"], payload["note"], now, now,
                ),
            )
        return self.get_localization(video_id, language) or {}

    def get_localization(self, video_id: str, language: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM localizations WHERE video_id = ? AND language = ?",
                (video_id, language),
            ).fetchone()
        return _decode_localization(row)

    def list_localizations(self, video_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM localizations WHERE video_id = ? ORDER BY language ASC",
                (video_id,),
            ).fetchall()
        return [item for item in (_decode_localization(r) for r in rows) if item]

    def delete_localization(self, video_id: str, language: str) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM localizations WHERE video_id = ? AND language = ?",
                (video_id, language),
            )

    # -- preferences ----------------------------------------------------
    def set_pref(self, key: str, value: Any) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO preferences (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, _encode(value)),
            )

    def get_pref(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def all_prefs(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM preferences").fetchall()
        out: dict[str, Any] = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                continue
        return out

    # -- quota ----------------------------------------------------------
    def quota(self, day: str) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute("SELECT units, uploads FROM quota WHERE day = ?", (day,)).fetchone()
        return {"units": int(row["units"]) if row else 0, "uploads": int(row["uploads"]) if row else 0}

    def add_quota(self, day: str, units: int, uploads: int = 0) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO quota (day, units, uploads) VALUES (?, ?, ?) "
                "ON CONFLICT(day) DO UPDATE SET units = units + excluded.units, "
                "uploads = uploads + excluded.uploads",
                (day, max(0, units), max(0, uploads)),
            )

    # -- events ---------------------------------------------------------
    def log_event(
        self,
        level: str,
        kind: str,
        message: str,
        video_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ts = utcnow()
        payload = _encode(data or {})
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO events (ts, level, kind, message, video_id, data) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, level, kind, message, video_id, payload),
            )
            event_id = int(cur.lastrowid or 0)
        return {
            "id": event_id,
            "ts": ts,
            "level": level,
            "kind": kind,
            "message": message,
            "video_id": video_id,
            "data": data or {},
        }

    def list_events(self, limit: int = 80, since_id: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if since_id:
                rows = conn.execute(
                    "SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (since_id, max(1, min(limit, 500))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                    (max(1, min(limit, 500)),),
                ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            try:
                item["data"] = json.loads(item.pop("data") or "{}")
            except json.JSONDecodeError:
                item["data"] = {}
            events.append(item)
        if not since_id:
            events.reverse()
        return events

    # -- directives -----------------------------------------------------
    def log_directive(self, text: str, action: dict[str, Any] | None, reply: str) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO directives (ts, text, action, reply) VALUES (?, ?, ?, ?)",
                (utcnow(), text, _encode(action or {}), reply),
            )

    # -- reporting ------------------------------------------------------
    def count_since(self, iso: str, channel_id: str | None = None) -> int:
        if channel_id:
            sql = "SELECT COUNT(*) AS n FROM videos WHERE created_at >= ? AND channel_id = ?"
            params: tuple[Any, ...] = (iso, channel_id)
        else:
            sql = "SELECT COUNT(*) AS n FROM videos WHERE created_at >= ?"
            params = (iso,)
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row["n"]) if row else 0

    def count_published_between(self, start_iso: str, end_iso: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE status = 'published' "
                "AND updated_at >= ? AND updated_at < ?",
                (start_iso, end_iso),
            ).fetchone()
        return int(row["n"]) if row else 0

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            by_status = {
                row["status"]: int(row["n"])
                for row in conn.execute("SELECT status, COUNT(*) AS n FROM videos GROUP BY status")
            }
            totals = conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(duration), 0) AS seconds, "
                "COALESCE(SUM(words), 0) AS words, COALESCE(AVG(novelty), 1) AS novelty "
                "FROM videos WHERE status != 'failed'"
            ).fetchone()
            formats = {
                row["format"]: int(row["n"])
                for row in conn.execute("SELECT format, COUNT(*) AS n FROM videos GROUP BY format")
            }
            kinds = {
                (row["kind"] or "film"): int(row["n"])
                for row in conn.execute("SELECT COALESCE(kind, 'film') AS kind, COUNT(*) AS n FROM videos GROUP BY kind")
            }
            last = conn.execute(
                "SELECT youtube_url, updated_at FROM videos WHERE status = 'published' "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        total = int(totals["total"] or 0)
        return {
            "total": total,
            "by_status": by_status,
            "by_format": formats,
            "by_kind": kinds,
            "clips": kinds.get("clip", 0),
            "seconds": round(float(totals["seconds"] or 0), 1),
            "minutes": round(float(totals["seconds"] or 0) / 60, 1),
            "words": int(totals["words"] or 0),
            "avg_novelty": round(float(totals["novelty"] or 1), 3),
            "published": by_status.get("published", 0),
            "ready": by_status.get("ready", 0),
            "failed": by_status.get("failed", 0),
            "last_published_url": last["youtube_url"] if last else "",
            "last_published_at": last["updated_at"] if last else "",
        }
