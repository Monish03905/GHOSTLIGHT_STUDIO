from __future__ import annotations

import hashlib
import hmac
import json
import secrets as pysecrets
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlparse

import httpx

from . import net
from .config import Config
from .db import Database

GRAPH_HOST = "https://graph.facebook.com"
TIKTOK_HOST = "https://open.tiktokapis.com"
SIGNING_FILE = "signing.key"
TARGETS = ("instagram", "tiktok")


class SocialError(Exception):
    pass


class NotConfigured(SocialError):
    pass


def _secret(cfg: Config, target: str) -> dict[str, Any]:
    raw = str(cfg.get(f"social.{target}.secret_path") or "").strip()
    if not raw:
        return {}
    path = cfg.resolve(raw)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _https_base(cfg: Config) -> str:
    base = str(cfg.get("social.public_url") or "").strip().rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return base


def signing_key(cfg: Config) -> bytes:
    path = Path(cfg.secrets_dir) / "social" / SIGNING_FILE
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = pysecrets.token_hex(32)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return text.encode("utf-8")


def sign_media(cfg: Config, video_id: str, expires: int) -> str:
    message = f"{video_id}:{int(expires)}".encode("utf-8")
    return hmac.new(signing_key(cfg), message, hashlib.sha256).hexdigest()


def verify_media(cfg: Config, video_id: str, expires: int, signature: str) -> bool:
    try:
        expires = int(expires)
    except (TypeError, ValueError):
        return False
    if expires < int(time.time()):
        return False
    return hmac.compare_digest(sign_media(cfg, video_id, expires), str(signature or ""))


def media_url(cfg: Config, video_id: str) -> str:
    base = _https_base(cfg)
    if not base:
        raise NotConfigured(
            "Set social.public_url to the public HTTPS address of this studio "
            "(a reverse proxy or tunnel) so Instagram and TikTok can fetch the film."
        )
    ttl = int(cfg.get("social.media_ttl_seconds", 3600) or 3600)
    expires = int(time.time()) + max(300, ttl)
    query = urlencode({"expires": expires, "sig": sign_media(cfg, video_id, expires)})
    return f"{base}/api/social/media/{quote(video_id)}?{query}"


def status(cfg: Config, db: Database | None = None) -> dict[str, Any]:
    enabled = bool(cfg.get("social.enabled", False))
    base = _https_base(cfg)
    ig = _secret(cfg, "instagram")
    tt = _secret(cfg, "tiktok")
    account = str(cfg.get("social.instagram.account_id") or ig.get("account_id") or "").strip()

    def target(ready_bits: list[tuple[bool, str]], off: bool, label: str) -> dict[str, Any]:
        if not enabled:
            return {"ready": False, "label": label, "reason": "Social publishing is switched off in The knobs."}
        if not base:
            return {"ready": False, "label": label,
                    "reason": "Set social.public_url to this studio's public HTTPS address."}
        if off:
            return {"ready": False, "label": label, "reason": f"{label} is switched off."}
        for ok, reason in ready_bits:
            if not ok:
                return {"ready": False, "label": label, "reason": reason}
        return {"ready": True, "label": label, "reason": ""}

    targets = {
        "instagram": target(
            [
                (bool(ig.get("access_token")), "Drop the Instagram access token in secrets/social/instagram.json."),
                (bool(account), "Set social.instagram.account_id (the IG business account id)."),
            ],
            not bool(cfg.get("social.instagram.enabled", False)),
            "Instagram",
        ),
        "tiktok": target(
            [
                (bool(tt.get("access_token")), "Drop the TikTok access token in secrets/social/tiktok.json."),
                (bool(str(cfg.get("social.tiktok.client_key") or "").strip()),
                 "Set social.tiktok.client_key (the TikTok app client key)."),
            ],
            not bool(cfg.get("social.tiktok.enabled", False)),
            "TikTok",
        ),
    }
    return {
        "enabled": enabled,
        "public_url": base,
        "targets": targets,
        "instagram": {"account_id": account, "graph_version": cfg.get("social.instagram.graph_version", "v21.0")},
        "tiktok": {"privacy": cfg.get("social.tiktok.privacy", "SELF_ONLY")},
        "posts": db.list_social_posts(limit=12) if db else [],
    }


def _graph(cfg: Config, path: str) -> str:
    version = str(cfg.get("social.instagram.graph_version") or "v21.0").strip().lstrip("/")
    return f"{GRAPH_HOST}/{version}/{path.lstrip('/')}"


def _error(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:400]
        if isinstance(err, str) and err:
            return err[:400]
        if payload.get("message"):
            return str(payload["message"])[:400]
    if isinstance(payload, str) and payload.strip():
        return payload.strip()[:400]
    return fallback


def _form(cfg: Config, method: str, url: str, data: dict[str, Any], timeout: float) -> Any:
    try:
        with net.client(timeout=timeout) as http:
            response = http.request(method, url, data=data)
    except httpx.HTTPError as exc:
        raise SocialError(f"Instagram did not answer: {exc}") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = response.text[:600]
    if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("error")):
        raise SocialError(f"Instagram refused the request: {_error(payload, f'HTTP {response.status_code}')}")
    return payload


def _caption(meta: dict[str, Any]) -> str:
    text = str(meta.get("description") or meta.get("share_text") or meta.get("title") or "").strip()
    return text[:2200]


def publish_instagram(
    cfg: Config,
    video: dict[str, Any],
    meta: dict[str, Any],
    *,
    timeout: float = 60.0,
    poll_seconds: float = 5.0,
    max_wait_seconds: float = 300.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    creds = _secret(cfg, "instagram")
    token = str(creds.get("access_token") or "").strip()
    account = str(cfg.get("social.instagram.account_id") or creds.get("account_id") or "").strip()
    if not token or not account:
        raise NotConfigured("Instagram is not connected yet.")
    url = media_url(cfg, str(video["id"]))
    payload = _form(cfg, "POST", _graph(cfg, f"{account}/media"), {
        "media_type": "REELS",
        "video_url": url,
        "caption": _caption(meta),
        "share_to_feed": "true" if bool(cfg.get("social.instagram.share_to_feed", True)) else "false",
        "access_token": token,
    }, timeout)
    creation_id = str((payload or {}).get("id") or "")
    if not creation_id:
        raise SocialError("Instagram did not return a media container id.")

    deadline = time.monotonic() + max(30.0, max_wait_seconds)
    state = "IN_PROGRESS"
    while time.monotonic() < deadline:
        status_body = _form(
            cfg, "GET", _graph(cfg, creation_id),
            {"fields": "status_code,status", "access_token": token}, timeout,
        )
        state = str((status_body or {}).get("status_code") or "IN_PROGRESS")
        if state == "FINISHED":
            break
        if state in {"ERROR", "EXPIRED"}:
            detail = str((status_body or {}).get("status") or state)
            raise SocialError(f"Instagram could not process the film: {detail}")
        sleeper(max(0.0, poll_seconds))
    else:
        return {
            "target": "instagram", "status": "pending", "remote_id": creation_id, "url": "",
            "container_id": creation_id,
            "note": "Instagram is still processing this container. The studio recorded it; "
                    "check the app before publishing again.",
        }

    published = _form(cfg, "POST", _graph(cfg, f"{account}/media_publish"), {
        "creation_id": creation_id,
        "access_token": token,
    }, timeout)
    media_id = str((published or {}).get("id") or "")
    if not media_id:
        raise SocialError("Instagram published nothing; no media id came back.")
    notes = ["Instagram Reels prefers 9:16; this film is rendered as "
             + ("9:16." if str(video.get("format")) == "short" else "16:9 and may be letterboxed.")]
    return {
        "target": "instagram", "status": "published", "remote_id": media_id, "url": "",
        "container_id": creation_id, "notes": notes,
    }


def publish_tiktok(
    cfg: Config,
    video: dict[str, Any],
    meta: dict[str, Any],
    *,
    timeout: float = 60.0,
    poll_seconds: float = 5.0,
    max_wait_seconds: float | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    creds = _secret(cfg, "tiktok")
    token = str(creds.get("access_token") or "").strip()
    if not token:
        raise NotConfigured("TikTok is not connected yet.")
    url = media_url(cfg, str(video["id"]))
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    title = str(meta.get("share_text") or meta.get("title") or "").strip()[:2200]
    body = {
        "post_info": {
            "title": title,
            "privacy_level": str(cfg.get("social.tiktok.privacy") or "SELF_ONLY"),
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {"source": "PULL_FROM_URL", "video_url": url},
    }
    code, payload = _json_request("POST", f"{TIKTOK_HOST}/v2/post/publish/video/init/", body, headers, timeout)
    error = (payload or {}).get("error") if isinstance(payload, dict) else None
    if code >= 400 or (isinstance(error, dict) and error.get("code") not in (None, "", "ok")):
        raise SocialError(f"TikTok refused the post: {_error(payload, f'HTTP {code}')}")
    publish_id = str(((payload or {}).get("data") or {}).get("publish_id") or "")
    if not publish_id:
        raise SocialError("TikTok did not return a publish id.")

    if max_wait_seconds is None:
        max_wait_seconds = float(cfg.get("social.tiktok.max_wait_seconds", 180) or 180)
    deadline = time.monotonic() + max(30.0, max_wait_seconds)
    state = "PROCESSING_UPLOAD"
    detail = ""
    while time.monotonic() < deadline:
        code, payload = _json_request(
            "POST", f"{TIKTOK_HOST}/v2/post/publish/status/fetch/",
            {"publish_id": publish_id}, headers, timeout,
        )
        data = (payload or {}).get("data") if isinstance(payload, dict) else {}
        state = str((data or {}).get("status") or state)
        detail = str((data or {}).get("fail_reason") or "")
        if state == "PUBLISH_COMPLETE":
            break
        if state in {"FAILED", "CANCELLED"}:
            raise SocialError(f"TikTok could not publish the film: {detail or state}")
        sleeper(max(0.0, poll_seconds))
    else:
        return {
            "target": "tiktok", "status": "pending", "remote_id": publish_id, "url": "",
            "note": "TikTok is still processing the post. The studio recorded the publish id; "
                    "check the app before retrying.",
        }

    notes = []
    if str(cfg.get("social.tiktok.privacy") or "SELF_ONLY") == "SELF_ONLY":
        notes.append("TikTok privacy is SELF_ONLY — only you can see it until you change that in the app.")
    notes.append("Set TikTok's own AI-generated label in the app; the caption carries the disclosure text.")
    return {
        "target": "tiktok", "status": "published", "remote_id": publish_id, "url": "", "notes": notes,
    }


def _json_request(method: str, url: str, body: Any, headers: dict[str, str], timeout: float) -> tuple[int, Any]:
    try:
        with net.client(timeout=timeout, headers=headers) as http:
            response = http.request(method, url, json=body)
    except httpx.HTTPError as exc:
        raise SocialError(f"TikTok did not answer: {exc}") from exc
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text[:600]


def publish(
    cfg: Config,
    db: Database,
    target: str,
    video: dict[str, Any],
    meta: dict[str, Any],
    *,
    on_event: Callable[[str, str], None] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Publish one film to one social target, recording exactly what happened."""
    target = str(target or "").strip().lower()
    if target not in TARGETS:
        raise SocialError(f"Unknown target {target!r}; use instagram or tiktok.")
    if not bool(cfg.get("social.enabled", False)):
        raise NotConfigured("Social publishing is switched off in The knobs.")
    if not Path(str(video.get("video_path") or "")).is_file():
        raise SocialError("This film has no rendered file on disk.")
    ready = status(cfg)["targets"][target]
    if not ready["ready"]:
        raise NotConfigured(str(ready["reason"]))
    if target == "instagram":
        result = publish_instagram(cfg, video, meta, **kwargs)
    else:
        result = publish_tiktok(cfg, video, meta, **kwargs)
    db.add_social_post(
        str(video["id"]), target,
        remote_id=str(result.get("remote_id") or ""),
        url=str(result.get("url") or ""),
        status=str(result.get("status") or "published"),
        detail=result,
    )
    if on_event:
        label = ready["label"]
        if result.get("status") == "published":
            on_event("success", f"“{video.get('title', 'Film')}” was sent to {label}.")
        else:
            on_event("info", f"{label} is still processing “{video.get('title', 'Film')}”.")
    return result
