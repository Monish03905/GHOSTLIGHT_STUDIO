from __future__ import annotations

import io
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Config
from .db import Database

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]
TOKEN_FILE = "token.json"
CLIENT_SECRET_FILE = "client_secret.json"
UPLOAD_CHUNK = 8 * 1024 * 1024
PACIFIC = ZoneInfo("America/Los_Angeles")

# state -> {channel_id, redirect_uri, created}. OAuth callbacks arrive in the
# same process, so an in-memory map is enough; it also survives a page reload.
_PENDING: dict[str, dict[str, Any]] = {}
_PENDING_LOCK = threading.Lock()


class YouTubeError(Exception):
    pass


class NotConfiguredError(YouTubeError):
    pass


class NotConnectedError(YouTubeError):
    pass


class QuotaError(YouTubeError):
    pass


def _try_import() -> tuple[Any, Any, Any, Any, Any] | None:
    try:
        from google_auth_oauthlib.flow import Flow, InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return None
    return InstalledAppFlow, Flow, build, HttpError, MediaFileUpload


def _dedupe_notes(exc: Exception) -> str:
    text = str(exc)
    if "insufficient" in text.lower() or "scope" in text.lower():
        return "reconnect the channel to grant analytics access"
    return text[:240]


class YouTubeClient:
    """One YouTube channel's credentials, quota, uploads and analytics."""

    def __init__(
        self,
        cfg: Config,
        db: Database,
        on_event: Callable[..., None] | None = None,
        channel: dict[str, Any] | None = None,
    ):
        self.cfg = cfg
        self.db = db
        self.on_event = on_event or (lambda *a, **k: None)
        self.channel = channel or {}
        self.channel_id = str(self.channel.get("id", "") or "")
        self._service: Any = None
        self._analytics: Any = None
        self._lock = threading.Lock()
        self._flow: Any = None
        self._auth_thread: threading.Thread | None = None

    # -- state ----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("youtube.enabled", False)) and bool(self.channel.get("enabled", 1))

    def label(self) -> str:
        return str(self.channel.get("name") or "the channel")

    def secrets_dir(self) -> Path:
        return Path(self.cfg.secrets_dir)

    def _channel_dir(self) -> Path:
        if not self.channel_id:
            return self.secrets_dir()
        return self.secrets_dir() / "channels" / self.channel_id

    def _client_secret_path(self) -> Path:
        explicit = str(self.channel.get("client_secret_path") or "").strip()
        if explicit:
            return self.cfg.resolve(explicit)
        local = self._channel_dir() / CLIENT_SECRET_FILE
        if local.is_file():
            return local
        return self.secrets_dir() / CLIENT_SECRET_FILE

    def _token_path(self) -> Path:
        explicit = str(self.channel.get("token_path") or "").strip()
        if explicit:
            return self.cfg.resolve(explicit)
        if self.channel_id:
            return self._channel_dir() / TOKEN_FILE
        return self.secrets_dir() / TOKEN_FILE

    def client_secret_target(self) -> Path:
        return self._channel_dir() / CLIENT_SECRET_FILE

    @property
    def configured(self) -> bool:
        return self._client_secret_path().is_file()

    @property
    def connected(self) -> bool:
        return self._token_path().is_file()

    def redirect_uri(self, request_base: str | None = None) -> str:
        explicit = str(self.cfg.get("youtube.oauth_redirect", "") or "").strip()
        if explicit:
            return explicit
        if request_base:
            return request_base.rstrip("/") + "/api/youtube/oauth/callback"
        host = str(self.cfg.get("studio.host", "127.0.0.1"))
        port = int(self.cfg.get("studio.port", 8787) or 8787)
        return f"http://{host}:{port}/api/youtube/oauth/callback"

    def status(self) -> dict[str, Any]:
        return {
            "id": self.channel_id,
            "name": self.label(),
            "enabled": self.enabled,
            "configured": self.configured,
            "connected": self.connected,
            "authorizing": self._flow is not None or bool(self._auth_thread and self._auth_thread.is_alive()),
            "dry_run": bool(self.cfg.get("youtube.dry_run", False)),
            "channel": self.channel_info(),
            "quota": self.quota_snapshot(),
        }

    # -- quota ----------------------------------------------------------
    def quota_day(self) -> str:
        return datetime.now(PACIFIC).strftime("%Y-%m-%d")

    def _project_key(self) -> str:
        return f"project|{self.quota_day()}"

    def _channel_key(self) -> str:
        return f"channel:{self.channel_id or 'main'}|{self.quota_day()}"

    def quota_snapshot(self) -> dict[str, Any]:
        project = self.db.quota(self._project_key())
        scoped = self.db.quota(self._channel_key())
        # Older installs logged the project quota under the bare Pacific date.
        legacy = self.db.quota(self.quota_day())
        return {
            "day": self.quota_day(),
            "units_used": project["units"] + legacy["units"],
            "units_limit": int(self.cfg.get("youtube.quota_daily_limit", 10000)),
            "uploads_used": scoped["uploads"],
            "upload_limit": int(self.cfg.get("youtube.daily_upload_limit", 5)),
            "upload_cost": int(self.cfg.get("youtube.upload_cost", 1600)),
            "channel_units": scoped["units"],
        }

    def _check_quota(self) -> None:
        snap = self.quota_snapshot()
        cost = snap["upload_cost"]
        if snap["units_used"] + cost > snap["units_limit"]:
            raise QuotaError(
                f"Daily project quota would be exceeded: {snap['units_used']} + {cost} > {snap['units_limit']} units."
            )
        if snap["uploads_used"] >= snap["upload_limit"]:
            raise QuotaError(
                f"Daily upload limit reached for {self.label()}: {snap['uploads_used']}/{snap['upload_limit']}."
            )

    def _record_cost(self, units: int, uploads: int = 0) -> None:
        self.db.add_quota(self._project_key(), units=units, uploads=uploads)
        if self.channel_id:
            self.db.add_quota(self._channel_key(), units=units, uploads=uploads)

    # -- auth -----------------------------------------------------------
    def _credentials(self) -> Any:
        if not self.configured:
            raise NotConfiguredError(
                f"No client secret for {self.label()}. Add one on the Network page or drop "
                f"{CLIENT_SECRET_FILE} into {self._channel_dir()}."
            )
        if not self.connected:
            raise NotConnectedError(f"{self.label()} is not signed in yet. Use ‘Connect Google’ on the Network page.")
        creds = _load_credentials(self._token_path(), SCOPES)
        if creds is None:
            raise NotConnectedError("Saved credentials are invalid. Reconnect the channel.")
        return creds

    def _build_service(self) -> Any:
        mods = _try_import()
        if mods is None:
            raise YouTubeError("Install google libraries: pip install google-api-python-client google-auth-oauthlib")
        _, _, build, _, _ = mods
        return build("youtube", "v3", credentials=self._credentials(), cache_discovery=False)

    def service(self) -> Any:
        with self._lock:
            if self._service is None:
                self._service = self._build_service()
            return self._service

    def _analytics_service(self) -> Any:
        with self._lock:
            if self._analytics is None:
                mods = _try_import()
                if mods is None:
                    raise YouTubeError("Install google libraries first.")
                _, _, build, _, _ = mods
                self._analytics = build("youtubeAnalytics", "v2", credentials=self._credentials(), cache_discovery=False)
            return self._analytics

    def _clear_service(self) -> None:
        with self._lock:
            self._service = None
            self._analytics = None

    def auth_url(self, redirect_uri: str | None = None, state: str | None = None) -> dict[str, Any]:
        """Build a Google consent URL for the website flow (no browser spawn)."""
        if not self.configured:
            raise NotConfiguredError(
                f"No OAuth client for {self.label()}. Upload client_secret.json first."
            )
        mods = _try_import()
        if mods is None:
            raise YouTubeError("Install google libraries: pip install google-api-python-client google-auth-oauthlib")
        _, Flow, _, _, _ = mods
        redirect = redirect_uri or self.redirect_uri()
        try:
            flow = Flow.from_client_secrets_file(str(self._client_secret_path()), SCOPES, redirect_uri=redirect)
        except Exception as exc:
            raise YouTubeError(f"OAuth client is not usable: {exc}") from exc
        url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        with _PENDING_LOCK:
            now = time.time()
            for key in [k for k, v in _PENDING.items() if now - float(v.get("created", 0)) > 3600]:
                _PENDING.pop(key, None)
            _PENDING[returned_state] = {
                "channel_id": self.channel_id,
                "redirect_uri": redirect,
                "created": now,
            }
        return {"url": url, "state": returned_state, "redirect_uri": redirect}

    def complete_auth(self, code: str, state: str, redirect_uri: str | None = None) -> dict[str, Any]:
        mods = _try_import()
        if mods is None:
            raise YouTubeError("Install google libraries: pip install google-api-python-client google-auth-oauthlib")
        _, Flow, _, _, _ = mods
        with _PENDING_LOCK:
            pending = _PENDING.pop(state, None)
        redirect = (pending or {}).get("redirect_uri") or redirect_uri or self.redirect_uri()
        if pending and pending.get("channel_id") and pending["channel_id"] != self.channel_id:
            self.channel_id = pending["channel_id"]
        if not self.configured:
            raise NotConfiguredError("No OAuth client for this channel.")
        flow = Flow.from_client_secrets_file(str(self._client_secret_path()), SCOPES, redirect_uri=redirect)
        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            raise YouTubeError(f"Google rejected the sign-in: {exc}") from exc
        self._save_token(flow.credentials)
        self._clear_service()
        info = self.channel_info(refresh=True)
        if info.get("id"):
            self.db.update_channel(
                self.channel_id,
                youtube_id=info["id"],
                youtube_name=info.get("name", ""),
                subscribers=int(info.get("subscribers", 0) or 0),
                token_path=str(self._token_path()),
                error="",
            )
        self.on_event("success", "youtube", f"{self.label()} connected to YouTube.")
        self.db.add_journal(
            self.channel_id,
            f"Signed in to YouTube as {info.get('name') or self.label()}.",
            "The studio can now upload, caption, schedule and read analytics for this channel.",
            kind="connection",
        )
        return info

    def authorize(self, open_browser: bool = True) -> dict[str, Any]:
        """Desktop/CLI fallback using a local loopback server."""
        if not self.configured:
            raise NotConfiguredError(
                f"No client secret for {self.label()}. Add {CLIENT_SECRET_FILE} to {self._channel_dir()}."
            )
        mods = _try_import()
        if mods is None:
            raise YouTubeError("Install google libraries: pip install google-api-python-client google-auth-oauthlib")
        InstalledAppFlow, _, _, _, _ = mods
        if self._flow is None:
            self._flow = InstalledAppFlow.from_client_secrets_file(str(self._client_secret_path()), SCOPES)
        self.on_event("info", "youtube", f"Opening Google sign-in for {self.label()}.")
        creds = self._flow.run_local_server(port=0, open_browser=open_browser, access_type="offline", prompt="consent")
        self._save_token(creds)
        self._flow = None
        self._clear_service()
        info = self.channel_info(refresh=True)
        if info.get("id"):
            self.db.update_channel(
                self.channel_id,
                youtube_id=info["id"],
                youtube_name=info.get("name", ""),
                subscribers=int(info.get("subscribers", 0) or 0),
                token_path=str(self._token_path()),
            )
        self.on_event("success", "youtube", f"{self.label()} connected.")
        return self.status()

    def _save_token(self, creds: Any) -> None:
        token_path = self._token_path()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(json.loads(creds.to_json()), indent=2), encoding="utf-8")
        os.replace(tmp, token_path)

    def disconnect(self) -> dict[str, Any]:
        self._token_path().unlink(missing_ok=True)
        self._clear_service()
        if self.channel_id:
            self.db.update_channel(self.channel_id, youtube_id="", youtube_name="", subscribers=0)
            self.db.set_pref(f"youtube.channel.{self.channel_id}", None)
            self.db.set_pref(f"youtube.playlists.{self.channel_id}", {})
            self.db.add_journal(
                self.channel_id,
                "YouTube sign-in removed.",
                "Films keep being made and wait on the shelf until a channel is linked again.",
                kind="connection",
            )
        self.on_event("info", "youtube", f"{self.label()} disconnected.")
        return self.status()

    def channel_info(self, refresh: bool = False) -> dict[str, Any]:
        key = f"youtube.channel.{self.channel_id}" if self.channel_id else "youtube.channel"
        cached = self.db.get_pref(key)
        if cached and not refresh:
            return cached
        if not self.connected:
            return {"name": "", "id": "", "subscribers": 0}
        try:
            svc = self.service()
            resp = svc.channels().list(part="snippet,statistics", mine=True).execute()
            items = resp.get("items", [])
            if not items:
                return {"name": "", "id": "", "subscribers": 0}
            item = items[0]
            info = {
                "name": item.get("snippet", {}).get("title", ""),
                "id": item.get("id", ""),
                "subscribers": int(item.get("statistics", {}).get("subscriberCount", 0) or 0),
                "views": int(item.get("statistics", {}).get("viewCount", 0) or 0),
                "videos": int(item.get("statistics", {}).get("videoCount", 0) or 0),
            }
            self.db.set_pref(key, info)
            if self.channel_id:
                self.db.update_channel(
                    self.channel_id,
                    youtube_id=info["id"],
                    youtube_name=info["name"],
                    subscribers=info["subscribers"],
                    views=info["views"],
                )
            return info
        except YouTubeError:
            return {"name": "", "id": "", "subscribers": 0}
        except Exception as exc:
            self.on_event("warning", "youtube", f"Channel lookup failed for {self.label()}: {_dedupe_notes(exc)}")
            return {"name": "", "id": "", "subscribers": 0}

    def fetch_metrics(self, video_ids: list[str], days: int = 28) -> dict[str, dict[str, Any]]:
        """Views/watch time/revenue per video. Requires analytics scopes."""
        ids = [v for v in dict.fromkeys(video_ids) if v][:200]
        if not ids:
            return {}
        end = datetime.now(PACIFIC).date()
        start = end - timedelta(days=max(1, days))
        filters = "video==" + ",".join(ids)
        metrics = "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,estimatedRevenue"
        rows: list[list[Any]] = []
        try:
            report = self._analytics_service().reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics=metrics,
                dimensions="video",
                filters=filters,
                maxResults=200,
            )
            rows = report.execute().get("rows", [])
        except Exception as exc:
            self.on_event("warning", "analytics", f"{self.label()} analytics: {_dedupe_notes(exc)}")
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            if len(row) < 6:
                continue
            out[str(row[0])] = {
                "views": int(row[1] or 0),
                "watch_minutes": round(float(row[2] or 0), 2),
                "avg_view_seconds": round(float(row[3] or 0), 2),
                "subs_gained": int(row[4] or 0),
                "revenue": round(float(row[5] or 0), 4),
            }
        return out

    def fetch_video_stats(self, video_ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = [v for v in dict.fromkeys(video_ids) if v][:50]
        if not ids:
            return {}
        try:
            resp = self.service().videos().list(part="statistics", id=",".join(ids), maxResults=50).execute()
        except Exception:
            return {}
        out = {}
        for item in resp.get("items", []):
            stats = item.get("statistics", {})
            out[item.get("id", "")] = {
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
            }
        return out

    # -- playlists ------------------------------------------------------
    def _playlist_id(self, short: bool) -> str | None:
        if short:
            title = self.cfg.get("youtube.shorts_playlist", "Shorts")
        else:
            title = self.cfg.get("youtube.long_playlist", "Long Form")
        if not title:
            return None
        key = f"youtube.playlists.{self.channel_id}" if self.channel_id else "youtube.playlists"
        cached = self.db.get_pref(key) or {}
        if title in cached:
            return cached[title]
        try:
            svc = self.service()
            playlists: list[dict[str, Any]] = []
            token: str | None = None
            for _ in range(3):
                resp = (
                    svc.playlists()
                    .list(part="snippet", mine=True, maxResults=50, pageToken=token)
                    .execute()
                )
                playlists.extend(resp.get("items", []))
                token = resp.get("nextPageToken")
                if not token:
                    break
            for pl in playlists:
                if pl.get("snippet", {}).get("title", "").strip().lower() == title.strip().lower():
                    cached[title] = pl["id"]
                    self.db.set_pref(key, cached)
                    return pl["id"]
            body = {
                "snippet": {"title": title},
                "status": {"privacyStatus": self.cfg.get("youtube.privacy", "private")},
            }
            created = svc.playlists().insert(part="snippet,status", body=body).execute()
            cached[title] = created["id"]
            self.db.set_pref(key, cached)
            self._record_cost(50)
            return created["id"]
        except QuotaError:
            raise
        except Exception as exc:
            self.on_event("warning", "youtube", f"Playlist resolution failed: {exc}")
            return None

    # -- upload ---------------------------------------------------------
    def upload(
        self,
        video_path: str | Path,
        *,
        title: str,
        description: str,
        tags: list[str] | None = None,
        short: bool = False,
        thumbnail: str | Path | None = None,
        publish_at: str | None = None,
        captions: str | Path | None = None,
        comment: str = "",
        privacy: str | None = None,
    ) -> dict[str, Any]:
        video_path = Path(video_path)
        if not video_path.is_file():
            raise YouTubeError(f"Video file not found: {video_path}")
        if bool(self.cfg.get("youtube.dry_run", False)):
            self.on_event("info", "youtube", f"Dry run: would upload '{title}' for {self.label()}.")
            return {
                "youtube_id": f"dryrun-{int(time.time())}",
                "youtube_url": "",
                "dry_run": True,
                "channel_id": self.channel_id,
            }
        self._check_quota()
        mods = _try_import()
        if mods is None:
            raise YouTubeError("Install google libraries: pip install google-api-python-client google-auth-oauthlib")
        _, _, _, HttpError, MediaFileUpload = mods
        svc = self.service()

        privacy = privacy or str(self.channel.get("privacy") or self.cfg.get("youtube.privacy", "private")) or "private"
        if publish_at:
            privacy = "private"  # scheduled releases flip public at publish time
        status_body: dict[str, Any] = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(self.cfg.get("youtube.made_for_kids", False)),
            "embeddable": True,
            "publicStatsViewable": True,
        }
        if publish_at:
            status_body["publishAt"] = publish_at
        if bool(self.cfg.get("youtube.disclose_ai", True)):
            status_body["containsSyntheticMedia"] = True

        snippet: dict[str, Any] = {
            "title": title[:100],
            "description": description[:5000],
            "tags": [t[:100] for t in (tags or [])][:30],
            "categoryId": str(self.cfg.get("youtube.category_id", "27")),
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        }

        media = MediaFileUpload(str(video_path), chunksize=UPLOAD_CHUNK, resumable=True, mimetype="video/mp4")
        request = svc.videos().insert(
            part="snippet,status", body={"snippet": snippet, "status": status_body}, media_body=media
        )
        response = None
        retries = 0
        backoff = 5.0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    self.on_event(
                        "info",
                        "upload",
                        f"Uploading '{title[:48]}' to {self.label()}: {int(status.progress() * 100)}%",
                        data={"progress": int(status.progress() * 100), "channel_id": self.channel_id},
                    )
            except HttpError as exc:
                if exc.resp.status in (500, 502, 503, 429) and retries < 5:
                    retries += 1
                    self.on_event("warning", "upload", f"Upload retry {retries}/5 after HTTP {exc.resp.status}.")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)
                    continue
                raise YouTubeError(f"YouTube upload failed: {exc}") from exc
        video_id = response.get("id", "")
        if not video_id:
            raise YouTubeError("YouTube did not return a video id.")
        self._record_cost(int(self.cfg.get("youtube.upload_cost", 1600)), uploads=1)
        url = f"https://www.youtube.com/shorts/{video_id}" if short else f"https://www.youtube.com/watch?v={video_id}"

        thumb_set = self._set_thumbnail(video_id, thumbnail, HttpError)
        playlist_id = self._add_to_playlist(video_id, short)
        captions_ok = self._upload_captions(video_id, captions, HttpError, MediaFileUpload) if captions else False
        comment_id = self._post_comment(video_id, comment) if comment else ""
        return {
            "youtube_id": video_id,
            "youtube_url": url,
            "channel_id": self.channel_id,
            "channel_name": self.channel.get("name", ""),
            "privacy": status_body["privacyStatus"],
            "publish_at": publish_at or "",
            "contains_synthetic_media": bool(status_body.get("containsSyntheticMedia", False)),
            "thumbnail_set": thumb_set,
            "playlist_id": playlist_id or "",
            "captions_uploaded": captions_ok,
            "comment_id": comment_id,
            "dry_run": False,
        }

    def _set_thumbnail(self, video_id: str, thumbnail: str | Path | None, HttpError: Any) -> bool:
        if not thumbnail:
            return False
        thumbnail = Path(thumbnail)
        if not thumbnail.is_file():
            self.on_event("warning", "youtube", f"Thumbnail missing: {thumbnail}")
            return False
        try:
            mods = _try_import()
            if mods is None:
                return False
            _, _, _, _, MediaFileUpload = mods
            up = MediaFileUpload(str(thumbnail), mimetype="image/jpeg", resumable=False)
            self.service().thumbnails().set(videoId=video_id, media_body=up).execute()
            self._record_cost(50)
            return True
        except QuotaError:
            raise
        except Exception as exc:
            self.on_event("warning", "youtube", f"Thumbnail upload skipped: {exc}")
            return False

    def _upload_captions(
        self, video_id: str, captions: str | Path, HttpError: Any, MediaFileUpload: Any
    ) -> bool:
        captions = Path(captions)
        if not captions.is_file():
            return False
        try:
            media = MediaFileUpload(str(captions), mimetype="text/plain", resumable=False)
            self.service().captions().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "language": "en",
                        "name": "English",
                        "isDraft": False,
                    }
                },
                media_body=media,
            ).execute()
            self._record_cost(400)
            return True
        except QuotaError:
            raise
        except Exception as exc:
            self.on_event("warning", "youtube", f"Caption upload skipped: {exc}")
            return False

    def _post_comment(self, video_id: str, text: str) -> str:
        text = str(text or "").strip()
        if not text:
            return ""
        try:
            resp = self.service().commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {"snippet": {"textOriginal": text[:9000]}},
                    }
                },
            ).execute()
            self._record_cost(50)
            return str(resp.get("id", ""))
        except QuotaError:
            raise
        except Exception as exc:
            self.on_event("warning", "youtube", f"Opening comment skipped: {exc}")
            return ""

    def _add_to_playlist(self, video_id: str, short: bool) -> str | None:
        if not bool(self.cfg.get("youtube.create_playlists", True)):
            return None
        try:
            playlist_id = self._playlist_id(short)
            if not playlist_id:
                return None
            self.service().playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            self._record_cost(50)
            return playlist_id
        except QuotaError:
            raise
        except Exception as exc:
            self.on_event("warning", "youtube", f"Playlist add skipped: {exc}")
            return None


class YouTubeHub:
    """Lazily builds one account per channel and answers for the whole network."""

    def __init__(self, cfg: Config, db: Database, on_event: Callable[..., None] | None = None):
        self.cfg = cfg
        self.db = db
        self.on_event = on_event or (lambda *a, **k: None)
        self._accounts: dict[str, YouTubeClient] = {}
        self._lock = threading.Lock()

    def account(self, channel_id: str | None = None) -> YouTubeClient:
        from .channels import channel_by_id

        channel = channel_by_id(self.cfg, self.db, channel_id) or {}
        key = str(channel.get("id", "") or "main")
        with self._lock:
            account = self._accounts.get(key)
            if account is None or account.channel != channel:
                account = YouTubeClient(self.cfg, self.db, self.on_event, channel=channel)
                self._accounts[key] = account
            return account

    def primary(self) -> YouTubeClient:
        return self.account(None)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("youtube.enabled", False))

    @property
    def configured(self) -> bool:
        return self.primary().configured

    @property
    def connected(self) -> bool:
        return any(self.account(ch["id"]).connected for ch in self.db.list_channels())

    def status(self) -> dict[str, Any]:
        channels = self.db.list_channels()
        accounts = [self.account(ch["id"]) for ch in channels]
        primary = accounts[0] if accounts else self.primary()
        quotas = [a.quota_snapshot() for a in accounts]
        base = primary.status()
        base["channels"] = [a.status() for a in accounts]
        base["connected_count"] = sum(1 for a in accounts if a.connected)
        base["channel_count"] = len(accounts)
        if quotas:
            base["quota"]["uploads_used"] = sum(q["uploads_used"] for q in quotas)
            base["quota"]["upload_limit"] = sum(q["upload_limit"] for q in quotas)
        return base

    def authorize(self, open_browser: bool = True) -> dict[str, Any]:
        return self.primary().authorize(open_browser)

    def disconnect(self) -> dict[str, Any]:
        return self.primary().disconnect()

    def secrets_dir(self) -> Path:
        return self.primary().secrets_dir()

    def pending(self, state: str) -> dict[str, Any] | None:
        with _PENDING_LOCK:
            pending = _PENDING.get(state)
            return dict(pending) if pending else None


def _load_credentials(token_path: Path, scopes: list[str]) -> Any | None:
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    except Exception:
        # Tokens made before analytics scopes still upload fine; load with the
        # original youtube scope so existing links do not break.
        try:
            creds = Credentials.from_authorized_user_file(
                str(token_path), ["https://www.googleapis.com/auth/youtube.force-ssl"]
            )
        except Exception:
            return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tmp = token_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(json.loads(creds.to_json()), indent=2), encoding="utf-8")
            os.replace(tmp, token_path)
        except Exception:
            return None
    return creds if creds and creds.valid else None
