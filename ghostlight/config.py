from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

DEFAULTS: dict[str, Any] = {
    "studio": {
        "name": "Ghostlight Studio",
        "tagline": "one strange idea at a time",
        "host": "127.0.0.1",
        "port": 8787,
    },
    "creator": {
        "niches": [
            "cosmic",
            "deep_sea",
            "forgotten_history",
            "human_mind",
            "quiet_tech",
            "natural_world",
            "liminal_places",
            "everyday_physics",
        ],
        "tone": "cinematic, intimate, curious — never hype, never a listicle",
        "audience": "curious night owls who want one strange, beautiful idea before bed",
        "language": "en",
        "cta": "If this stayed with you, subscribe — one strange idea at a time.",
        "avoid_topics": [],
    },
    "novelty": {"max_similarity": 0.30, "attempts": 4, "recent_for_prompt": 40},
    "script": {
        "provider": "auto",
        "model": "",
        "temperature": 1.0,
        "short_seconds": [28, 46],
        "long_seconds": [200, 380],
        "words_per_minute": 152,
        "max_title_chars": 88,
    },
    "voice": {
        "provider": "auto",
        "edge_voice": "en-US-AndrewNeural",
        "edge_rate": "+3%",
        "edge_pitch": "-3Hz",
        "openai_model": "gpt-4o-mini-tts",
        "openai_voice": "onyx",
        "elevenlabs_voice_id": "",
        "elevenlabs_model": "eleven_multilingual_v2",
        "piper_binary": "piper",
        "piper_model": "",
        "piper_length_scale": 1.02,
        "piper_noise": 0.667,
        "piper_noise_w": 0.8,
        "piper_volume": 1.0,
        "system_voice": "",
        "system_rate": 0,
        "segment_gap": 0.35,
        "intro_pad": 1.5,
        "outro_pad": 1.4,
    },
    "visuals": {
        "style": "auto",
        "grain": True,
        "vignette": True,
        "art_scale": 1.25,
    },
    "music": {"enabled": True, "gain": 0.12, "tempo": 70},
    "render": {
        "fps": 30,
        "crf": 20,
        "preset": "medium",
        "short": [1080, 1920],
        "long": [1920, 1080],
        "keep_work_files": False,
    },
    "youtube": {
        "enabled": False,
        "client_secret": "secrets/client_secret.json",
        "token": "secrets/token.json",
        "privacy": "private",
        "category_id": "27",
        "made_for_kids": False,
        "disclose_ai": True,
        "auto_upload": True,
        "dry_run": False,
        "daily_upload_limit": 5,
        "quota_daily_limit": 10000,
        "upload_cost": 1600,
        "shorts_playlist": "Shorts",
        "long_playlist": "Long Form",
        "create_playlists": True,
        "tags_suffix": ["ghostlight studio"],
        "oauth_redirect": "",
        "auto_captions": True,
        "auto_comment": False,
        "auto_start_schedule": True,
        "analytics_days": 28,
    },
    "autopilot": {
        "enabled": True,
        "target_channels": 3,
        "backlog": 1,
        "backlog_hours": 6,
        "learn_minutes": 180,
        "adapt_schedule": False,
        "explore": 0.18,
        "max_films_per_day": 4,
    },
    "distribution": {
        "enabled": True,
        "webhook_url": "",
        "rss": True,
    },
    "schedule": {
        "enabled": False,
        "paused": True,
        "mode": "rhythm",
        "timezone": "auto",
        "times": ["09:30", "19:30"],
        "formats": ["short", "long", "short"],
        "max_per_day": 2,
        "min_gap_minutes": 240,
        "catch_up_minutes": 45,
        "max_failures_before_pause": 3,
    },
    "storage": {"data_dir": "data"},
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_dotenv(directory: Path) -> None:
    env_path = directory / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


class Config:
    """YAML-backed settings with dotted access and atomic writes."""

    def __init__(self, path: str | Path | None = None):
        explicit = path or os.environ.get("GHOSTLIGHT_CONFIG")
        self.path = Path(explicit).expanduser().resolve() if explicit else (Path.cwd() / "config.yaml")
        self.base_dir = self.path.parent
        self._lock = threading.RLock()
        _load_dotenv(self.base_dir)
        loaded: dict[str, Any] = {}
        if self.path.exists():
            try:
                loaded = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"config.yaml is not valid YAML: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml must contain a mapping at the top level")
        self.data = _deep_merge(DEFAULTS, loaded)
        local = self.path.parent / "config.local.yaml"
        if local.is_file():
            try:
                overlay = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
                if isinstance(overlay, dict):
                    self.data = _deep_merge(self.data, overlay)
            except yaml.YAMLError:
                pass  # a broken local override should never take the studio down

    # -- access ---------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name, {})
        return value if isinstance(value, dict) else {}

    def set(self, dotted: str, value: Any) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self.data
            for part in parts[:-1]:
                if not isinstance(node.get(part), dict):
                    node[part] = {}
                node = node[part]
            node[parts[-1]] = value

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            for key, value in values.items():
                self.set(key, value)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".yaml.tmp")
            tmp.write_text(
                yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True, width=96),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.data)

    # -- paths ----------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        raw = self.get("storage.data_dir", "data")
        p = Path(raw)
        if not p.is_absolute():
            p = self.base_dir / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def videos_dir(self) -> Path:
        p = self.data_dir / "videos"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def secrets_dir(self) -> Path:
        p = self.base_dir / "secrets"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve(self, value: str | Path) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (self.base_dir / p)

    def video_dir(self, video_id: str, create: bool = True) -> Path:
        p = self.videos_dir / video_id
        if create:
            p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.db"

    def timezone(self) -> ZoneInfo:
        name = self.get("schedule.timezone", "auto")
        if not name or name == "auto":
            return ZoneInfo(os.environ.get("TZ", "UTC")) if os.environ.get("TZ") else _system_zone()
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


def _system_zone() -> ZoneInfo:
    try:
        import datetime

        name = datetime.datetime.now().astimezone().tzinfo
        key = getattr(name, "key", None)
        if key:
            return ZoneInfo(key)
    except Exception:
        pass
    return ZoneInfo("UTC")


def load_config(path: str | Path | None = None) -> Config:
    return Config(path)
