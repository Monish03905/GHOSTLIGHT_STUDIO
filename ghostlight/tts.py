from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np

from . import ffmpeg
from .config import Config

SAMPLE_RATE = 44100


class TTSError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class SegmentTiming:
    heading: str
    text: str
    start: float
    end: float


@dataclass
class Narration:
    path: Path
    duration: float
    words: list[Word]
    segments: list[SegmentTiming]
    intro: float
    outro: float
    provider: str
    voice: str
    warnings: list[str] = field(default_factory=list)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "duration": round(self.duration, 3),
            "intro": round(self.intro, 3),
            "outro": round(self.outro, 3),
            "provider": self.provider,
            "voice": self.voice,
            "words": [{"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)} for w in self.words],
            "segments": [
                {
                    "heading": s.heading,
                    "start": round(s.start, 3),
                    "end": round(s.end, 3),
                    "text": s.text,
                }
                for s in self.segments
            ],
        }


def _no_window() -> int:
    return 0x08000000 if os.name == "nt" else 0


_EDGE_BROKEN_UNTIL = 0.0
_PIPER_VOICES: dict[str, Any] = {}


def _edge_available() -> bool:
    if time.time() < _EDGE_BROKEN_UNTIL:
        return False
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        return False


def _piper_model(cfg: Config) -> Path | None:
    configured = str(cfg.get("voice.piper_model", "")).strip()
    if configured:
        path = cfg.resolve(configured)
        if path.is_file():
            return path
    auto_dir = Path(cfg.data_dir) / "models" / "piper"
    if auto_dir.is_dir():
        models = sorted(auto_dir.glob("*.onnx"))
        if models:
            return models[0]
    return None


def _piper_ready(cfg: Config) -> bool:
    if _piper_model(cfg) is None:
        return False
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        binary = str(cfg.get("voice.piper_binary", "piper"))
        return bool(shutil.which(binary) or Path(binary).exists())


@lru_cache(maxsize=1)
def system_voices() -> list[str]:
    try:
        if os.name == "nt":
            powershell = shutil.which("powershell") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
            command = (
                "Add-Type -AssemblyName System.Speech;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }"
            )
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=20,
                creationflags=_no_window(),
            )
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if shutil.which("say"):
            result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, errors="replace", timeout=10)
            names = []
            for line in result.stdout.splitlines():
                match = re.match(r"(.+?)\s{2,}[a-z]{2}_[A-Z]{2}", line)
                if match:
                    names.append(match.group(1).strip())
            return names
        espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        if espeak:
            result = subprocess.run([espeak, "--voices"], capture_output=True, text=True, errors="replace", timeout=10)
            names = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    names.append(parts[3])
            return names
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def _preferred_system_voice(cfg: Config) -> str:
    requested = str(cfg.get("voice.system_voice", "")).strip()
    voices = system_voices()
    if requested and requested in voices:
        return requested
    for candidate in ("David", "Guy", "Ryan", "Mark", "Alex", "Daniel", "Zira", "Aria"):
        for voice in voices:
            if candidate.lower() in voice.lower():
                return voice
    return voices[0] if voices else ""


def resolve_voice_provider(cfg: Config) -> str:
    requested = str(cfg.get("voice.provider", "auto")).lower().strip()
    valid = {"auto", "edge", "system", "openai", "elevenlabs", "piper", "none"}
    if requested not in valid:
        requested = "auto"
    if requested != "auto":
        return requested
    if _edge_available():
        return "edge"
    if _piper_ready(cfg):
        return "piper"
    if system_voices():
        return "system"
    return "none"


def voice_status(cfg: Config) -> dict[str, Any]:
    requested = str(cfg.get("voice.provider", "auto"))
    provider = resolve_voice_provider(cfg)
    voices = system_voices()
    notes = {
        "edge": "Microsoft Edge voices; requires network. Falls back automatically if unavailable.",
        "system": "The operating system's built-in voice. Fully offline, more robotic.",
        "openai": "OpenAI TTS; needs OPENAI_API_KEY.",
        "elevenlabs": "ElevenLabs TTS; needs ELEVENLABS_API_KEY and a voice id.",
        "piper": "Piper neural TTS; fully offline and human-sounding. Voice models live in data/models/piper/.",
        "none": "Silent placeholders. Use for layout tests only.",
    }
    piper_model = _piper_model(cfg)
    return {
        "requested": requested,
        "provider": provider,
        "voice": (
            str(cfg.get("voice.edge_voice", ""))
            if provider == "edge"
            else _preferred_system_voice(cfg)
            if provider == "system"
            else str(cfg.get("voice.openai_voice", ""))
            if provider == "openai"
            else piper_model.stem
            if provider == "piper" and piper_model
            else ""
        ),
        "system_voices": voices,
        "note": notes.get(provider, ""),
    }


class NarrationMaker:
    def __init__(self, cfg: Config, workdir: str | Path, on_event: Callable[[str, str, str], None] | None = None):
        self.cfg = cfg
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.tts_dir = self.workdir / "tts"
        self.tts_dir.mkdir(exist_ok=True)
        self.on_event = on_event or (lambda level, kind, message: None)
        self.provider = resolve_voice_provider(cfg)
        self.voice_label = ""
        self.warnings: list[str] = []

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        self.on_event("warn", "voice", message)

    def synthesize(self, script: dict[str, Any], fmt: str = "short") -> Narration:
        segments = [s for s in script.get("segments", []) if str(s.get("text", "")).strip()]
        if not segments:
            raise TTSError("The script has no spoken segments.")

        chain = self._fallback_chain()
        active = chain[0]
        synth_results: list[tuple[np.ndarray, float, list[tuple[str, float, float]] | None]] = []
        used_providers: list[str] = []
        for index, segment in enumerate(segments):
            text = str(segment["text"]).strip()
            attempts = 0
            while True:
                try:
                    wav_path, boundaries, label = self._synthesize_with(active, text, index)
                    self.voice_label = label
                    used_providers.append(active)
                    break
                except Exception as exc:
                    attempts += 1
                    self._warn(f"Voice '{active}' failed ({_short(exc)}); trying next available voice.")
                    if attempts >= len(chain):
                        raise TTSError(f"All voice providers failed. Last error: {exc}") from exc
                    active = chain[attempts]
            samples, trim_start = _load_and_trim(wav_path)
            if len(samples) < 100:
                raise TTSError("The voice produced an empty audio file.")
            synth_results.append((samples, trim_start, boundaries))
        if len(set(used_providers)) > 1:
            self.warnings.append("Narration uses more than one voice provider in this cut.")

        intro_pad = float(self.cfg.get("voice.intro_pad", 1.5)) * (0.8 if fmt == "short" else 1.2)
        outro_pad = float(self.cfg.get("voice.outro_pad", 1.4)) * (0.8 if fmt == "short" else 1.15)
        gap = float(self.cfg.get("voice.segment_gap", 0.35))
        gap_samples = int(gap * SAMPLE_RATE)

        # layout
        positions: list[tuple[int, int, float]] = []
        cursor = int(intro_pad * SAMPLE_RATE)
        for samples, trim_start, _ in synth_results:
            positions.append((cursor, len(samples), trim_start))
            cursor += len(samples) + gap_samples
        cursor += int(outro_pad * SAMPLE_RATE)
        total_samples = cursor
        audio = np.zeros(total_samples, dtype=np.int16)

        words: list[Word] = []
        timings: list[SegmentTiming] = []
        for (samples, trim_start, boundaries), (offset, _, _), segment in zip(synth_results, positions, segments):
            audio[offset : offset + len(samples)] = samples
            start_sec = offset / SAMPLE_RATE
            end_sec = (offset + len(samples)) / SAMPLE_RATE
            heading = str(segment.get("heading", "") or "")
            timings.append(SegmentTiming(heading=heading, text=str(segment["text"]), start=start_sec, end=end_sec))
            if boundaries:
                for word_text, w_start, w_end in boundaries:
                    word_start = start_sec + max(0.0, w_start - trim_start)
                    word_end = start_sec + max(word_start - start_sec, w_end - trim_start)
                    words.append(Word(text=word_text, start=min(word_start, end_sec), end=min(max(word_end, word_start + 0.04), end_sec)))
            else:
                words.extend(_estimate_words(str(segment["text"]), start_sec, end_sec))

        duration = total_samples / SAMPLE_RATE
        narration_path = self.workdir / "narration.wav"
        _write_wav(narration_path, audio)
        metadata = {
            "provider": active,
            "voice": self.voice_label or self._label_for(active),
            "duration": duration,
            "intro": intro_pad,
            "outro": outro_pad,
            "words": [
                {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)} for w in words
            ],
            "segments": [
                {"heading": t.heading, "start": round(t.start, 3), "end": round(t.end, 3), "text": t.text}
                for t in timings
            ],
        }
        (self.workdir / "narration.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        return Narration(
            path=narration_path,
            duration=duration,
            words=words,
            segments=timings,
            intro=intro_pad,
            outro=outro_pad,
            provider=active,
            voice=metadata["voice"],
            warnings=self.warnings,
        )

    def _fallback_chain(self) -> list[str]:
        primary = self.provider
        fallbacks: dict[str, list[str]] = {
            "edge": ["edge", "piper", "system", "none"],
            "system": ["system", "piper", "none"],
            "openai": ["openai", "piper", "system", "none"],
            "elevenlabs": ["elevenlabs", "piper", "system", "none"],
            "piper": ["piper", "system", "none"],
            "none": ["none"],
        }
        chain = fallbacks.get(primary, ["system", "none"])
        if primary == "openai" and not os.environ.get("OPENAI_API_KEY"):
            self._warn("OPENAI_API_KEY is missing; using the system voice instead.")
            chain = [p for p in chain if p != "openai"]
        if primary == "elevenlabs" and (
            not os.environ.get("ELEVENLABS_API_KEY") or not str(self.cfg.get("voice.elevenlabs_voice_id", "")).strip()
        ):
            self._warn("ElevenLabs needs ELEVENLABS_API_KEY and voice.elevenlabs_voice_id; using the system voice instead.")
            chain = [p for p in chain if p != "elevenlabs"]
        if primary == "piper" and not _piper_ready(self.cfg):
            self._warn("Piper is not configured (voice.piper_model / piper binary); using the system voice instead.")
            chain = [p for p in chain if p != "piper"]
        if "system" in chain and not system_voices():
            chain = [p for p in chain if p != "system"] or ["none"]
        if not chain:
            chain = ["none"]
        return chain

    def _label_for(self, provider: str) -> str:
        if provider == "edge":
            return str(self.cfg.get("voice.edge_voice", ""))
        if provider == "system":
            return _preferred_system_voice(self.cfg) or "system voice"
        if provider == "openai":
            return str(self.cfg.get("voice.openai_voice", "onyx"))
        if provider == "piper":
            model = _piper_model(self.cfg)
            return model.stem if model else "piper"
        if provider == "elevenlabs":
            return str(self.cfg.get("voice.elevenlabs_voice_id", ""))
        return "silent"

    def _synthesize_with(self, provider: str, text: str, index: int) -> tuple[Path, list[tuple[str, float, float]] | None, str]:
        out = self.tts_dir / f"segment_{index:02d}_{provider}.wav"
        if provider == "edge":
            boundaries = self._edge(text, out)
            return out, boundaries, self._label_for("edge")
        if provider == "system":
            self._system(text, out)
            return out, None, self._label_for("system")
        if provider == "openai":
            self._openai(text, out)
            return out, None, self._label_for("openai")
        if provider == "elevenlabs":
            self._elevenlabs(text, out)
            return out, None, self._label_for("elevenlabs")
        if provider == "piper":
            self._piper(text, out)
            return out, None, self._label_for("piper")
        if provider == "none":
            self._silence(text, out)
            return out, None, "silent"
        raise TTSError(f"Unknown voice provider {provider}")

    # -- providers ------------------------------------------------------
    def _edge(self, text: str, out: Path) -> list[tuple[str, float, float]]:
        global _EDGE_BROKEN_UNTIL
        try:
            import edge_tts
        except Exception as exc:
            raise TTSError("edge-tts is not installed") from exc

        async def speak() -> tuple[bytes, list[tuple[str, float, float]]]:
            communicate = edge_tts.Communicate(
                text,
                str(self.cfg.get("voice.edge_voice", "en-US-AndrewNeural")),
                rate=str(self.cfg.get("voice.edge_rate", "+0%")),
                pitch=str(self.cfg.get("voice.edge_pitch", "+0Hz")),
            )
            audio = bytearray()
            boundaries: list[tuple[str, float, float]] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 10_000_000
                    end = (chunk["offset"] + chunk["duration"]) / 10_000_000
                    boundaries.append((chunk["text"], start, end))
            return bytes(audio), boundaries

        try:
            data, boundaries = asyncio.run(speak())
        except Exception as exc:
            # Microsoft's endpoint rejects this handshake in some regions; stop
            # retrying for half an hour so other films fall straight through.
            _EDGE_BROKEN_UNTIL = time.time() + 1800
            raise TTSError(f"edge-tts: {_short(exc)}") from exc
        if not data:
            _EDGE_BROKEN_UNTIL = time.time() + 600
            raise TTSError("edge-tts returned no audio")
        raw = self.tts_dir / f"{out.stem}_raw.mp3"
        raw.write_bytes(data)
        ffmpeg.to_wav(raw, out)
        return boundaries

    def _system(self, text: str, out: Path) -> None:
        text_path = self.tts_dir / f"{out.stem}.txt"
        text_path.write_text(text, encoding="utf-8")
        if os.name == "nt":
            raw = self.tts_dir / f"{out.stem}_raw.wav"
            voice = _preferred_system_voice(self.cfg)
            rate = int(self.cfg.get("voice.system_rate", 0) or 0)
            rate = max(-10, min(10, rate))
            script_path = self.tts_dir / f"{out.stem}.ps1"
            voice_line = f"$s.SelectVoice('{_ps_escape(voice)}')" if voice else ""
            script = (
                "$ErrorActionPreference='Stop'\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                f"{voice_line}\n"
                f"$s.Rate={rate}\n"
                "$s.Volume=100\n"
                f"$s.SetOutputToWaveFile('{_ps_escape(str(raw))}')\n"
                f"$text=[System.IO.File]::ReadAllText('{_ps_escape(str(text_path))}', [System.Text.Encoding]::UTF8)\n"
                "$s.Speak($text)\n"
                "$s.Dispose()\n"
            )
            script_path.write_text(script, encoding="utf-8")
            powershell = shutil.which("powershell") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
            try:
                result = subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=180,
                    creationflags=_no_window(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise TTSError(f"system voice failed: {exc}") from exc
            if result.returncode != 0 or not raw.exists():
                raise TTSError(f"system voice failed: {(result.stderr or '').strip()[:300]}")
            ffmpeg.to_wav(raw, out)
            return
        say = shutil.which("say")
        if say:
            voice = _preferred_system_voice(self.cfg)
            args = [say]
            if voice:
                args += ["-v", voice]
            args += ["-f", str(text_path), "-o", str(out.with_suffix(".aiff"))]
            result = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=180)
            if result.returncode != 0:
                raise TTSError(f"say failed: {result.stderr[:300]}")
            ffmpeg.to_wav(out.with_suffix(".aiff"), out)
            return
        espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        if espeak:
            raw = self.tts_dir / f"{out.stem}_raw.wav"
            args = [espeak, "-v", "en-us", "-s", "152", "-f", str(text_path), "-w", str(raw)]
            result = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=180)
            if result.returncode != 0:
                raise TTSError(f"espeak failed: {result.stderr[:300]}")
            ffmpeg.to_wav(raw, out)
            return
        raise TTSError("no system voice is available")

    def _openai(self, text: str, out: Path) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise TTSError("OPENAI_API_KEY is not set")
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        payload = {
            "model": str(self.cfg.get("voice.openai_model", "gpt-4o-mini-tts")),
            "voice": str(self.cfg.get("voice.openai_voice", "onyx")),
            "input": text,
            "response_format": "wav",
        }
        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{base}/audio/speech",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise TTSError(f"OpenAI TTS error {response.status_code}: {response.text[:200]}")
        raw = self.tts_dir / f"{out.stem}_raw.wav"
        raw.write_bytes(response.content)
        ffmpeg.to_wav(raw, out)

    def _elevenlabs(self, text: str, out: Path) -> None:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        voice_id = str(self.cfg.get("voice.elevenlabs_voice_id", "")).strip()
        if not api_key or not voice_id:
            raise TTSError("ElevenLabs is not configured")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": str(self.cfg.get("voice.elevenlabs_model", "eleven_multilingual_v2")),
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.75},
        }
        with httpx.Client(timeout=180) as client:
            response = client.post(
                url,
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            raise TTSError(f"ElevenLabs error {response.status_code}: {response.text[:200]}")
        raw = self.tts_dir / f"{out.stem}_raw.mp3"
        raw.write_bytes(response.content)
        ffmpeg.to_wav(raw, out)

    def _piper(self, text: str, out: Path) -> None:
        model = _piper_model(self.cfg)
        if model is None:
            raise TTSError(
                "No Piper voice model found. Put a .onnx voice in data/models/piper/."
            )
        try:
            from piper import PiperVoice
            from piper.config import SynthesisConfig
        except Exception as exc:
            raise TTSError("piper-tts is not installed") from exc
        key = str(model)
        voice = _PIPER_VOICES.get(key)
        if voice is None:
            voice = PiperVoice.load(key)
            _PIPER_VOICES[key] = voice
        syn = SynthesisConfig(
            length_scale=float(self.cfg.get("voice.piper_length_scale", 1.0) or 1.0),
            noise_scale=float(self.cfg.get("voice.piper_noise", 0.667) or 0.667),
            noise_w_scale=float(self.cfg.get("voice.piper_noise_w", 0.8) or 0.8),
            volume=float(self.cfg.get("voice.piper_volume", 1.0) or 1.0),
        )
        with wave.open(str(out), "wb") as handle:
            voice.synthesize_wav(text, handle, syn_config=syn)
        raw = self.tts_dir / f"{out.stem}_raw.wav"
        out.replace(raw)
        ffmpeg.to_wav(raw, out)

    def _silence(self, text: str, out: Path) -> None:
        words = max(1, len(re.findall(r"\S+", text)))
        seconds = max(0.9, words / 155.0 * 60.0)
        samples = np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16)
        _write_wav(out, samples)


def _ps_escape(value: str) -> str:
    return value.replace("'", "''")


def _short(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:180] or exc.__class__.__name__


def _estimate_words(text: str, start: float, end: float) -> list[Word]:
    tokens = re.findall(r"\S+", text.strip())
    if not tokens:
        return []
    duration = max(0.2, end - start)
    weights = []
    for token in tokens:
        weight = max(1.0, len(re.sub(r"[^\w]", "", token)))
        if re.search(r"[.!?;:]$", token):
            weight += 2.5
        elif token.endswith(","):
            weight += 1.2
        weights.append(weight)
    total = sum(weights)
    cursor = start
    words = []
    for token, weight in zip(tokens, weights):
        span = duration * weight / total
        words.append(Word(text=token, start=round(cursor, 4), end=round(min(end, cursor + span), 4)))
        cursor += span
    return words


def _read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as reader:
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    if width != 2:
        raise TTSError("voice audio is not 16-bit PCM")
    data = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return data, rate


def _load_and_trim(path: str | Path) -> tuple[np.ndarray, float]:
    samples, rate = _read_wav(path)
    if rate != SAMPLE_RATE:
        converted = Path(str(path) + ".44100.wav")
        ffmpeg.to_wav(path, converted, rate=SAMPLE_RATE)
        samples, rate = _read_wav(converted)
    threshold = 260
    above = np.where(np.abs(samples) > threshold)[0]
    if above.size == 0:
        return samples, 0.0
    start = max(0, int(above[0]) - int(0.045 * SAMPLE_RATE))
    end = min(len(samples), int(above[-1]) + int(0.09 * SAMPLE_RATE))
    return samples[start:end], start / SAMPLE_RATE


def _write_wav(path: str | Path, samples: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(samples, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(clipped.tobytes())
