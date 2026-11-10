from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from functools import lru_cache
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def _find(name: str, env_var: str, extra: list[str]) -> str | None:
    override = os.environ.get(env_var, "").strip()
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    for candidate in extra:
        if Path(candidate).exists():
            return candidate
    return None


_EXTRA_FFMPEG = [
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
]


def ffmpeg_bin() -> str:
    path = _find("ffmpeg", "FFMPEG_BIN", _EXTRA_FFMPEG)
    if not path:
        raise FFmpegError("ffmpeg was not found. Install it and make sure it is on PATH.")
    return path


def ffprobe_bin() -> str:
    extras = []
    for candidate in _EXTRA_FFMPEG:
        directory = Path(candidate).parent
        extras.append(str(directory / ("ffprobe.exe" if candidate.endswith(".exe") else "ffprobe")))
    path = _find("ffprobe", "FFPROBE_BIN", extras)
    if not path:
        raise FFmpegError("ffprobe was not found. Install ffmpeg with ffprobe on PATH.")
    return path


def _no_window() -> int:
    return 0x08000000 if os.name == "nt" else 0


def run(args: list[str], cwd: str | Path | None = None, timeout: float = 3600) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_no_window(),
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"ffmpeg timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise FFmpegError("ffmpeg could not be started") from exc
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-2400:]
        raise FFmpegError(tail or f"ffmpeg failed with code {result.returncode}")
    return result


def run_probe(args: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    cmd = [ffprobe_bin(), "-hide_banner", "-loglevel", "error", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_no_window(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise FFmpegError("ffprobe could not be started") from exc
    if result.returncode != 0:
        raise FFmpegError((result.stderr or "").strip()[-1200:] or "ffprobe failed")
    return result


def probe(path: str | Path) -> dict:
    result = run_probe(["-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(result.stdout or "{}")


def duration(path: str | Path) -> float:
    data = probe(path)
    try:
        return float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        for stream in data.get("streams", []):
            if stream.get("duration"):
                return float(stream["duration"])
    return 0.0


@lru_cache(maxsize=1)
def capabilities() -> dict:
    info = {"available": False, "version": "", "filters": [], "encoders": []}
    try:
        version = subprocess.run(
            [ffmpeg_bin(), "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
            creationflags=_no_window(),
        )
        info["available"] = version.returncode == 0
        info["version"] = (version.stdout or "").splitlines()[0] if version.stdout else ""
        filters = subprocess.run(
            [ffmpeg_bin(), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            creationflags=_no_window(),
        )
        names = set()
        for line in (filters.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 3 and not line.startswith("Filters:"):
                names.add(parts[1])
        info["filters"] = sorted(names)
        encoders = subprocess.run(
            [ffmpeg_bin(), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            creationflags=_no_window(),
        )
        info["encoders"] = [ln.split()[1] for ln in (encoders.stdout or "").splitlines() if ln.startswith(" V") or ln.startswith(" A")]
    except (FFmpegError, OSError, subprocess.SubprocessError):
        pass
    return info


def has_filter(name: str) -> bool:
    return name in capabilities().get("filters", [])


def has_encoder(name: str) -> bool:
    return name in capabilities().get("encoders", [])


def to_wav(source: str | Path, target: str | Path, rate: int = 44100, mono: bool = True) -> None:
    run([
        "-y",
        "-i",
        str(source),
        *(["-ac", "1"] if mono else []),
        "-ar",
        str(rate),
        "-acodec",
        "pcm_s16le",
        str(target),
    ])


def wav_duration(path: str | Path) -> float:
    return duration(path)
