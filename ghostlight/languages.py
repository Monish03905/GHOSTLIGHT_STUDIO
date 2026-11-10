from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .llm import LLMClient, LLMError
from .publish import load_narration
from .tts import NarrationMaker

# Metadata and captions are translated by the configured model. Audio is only
# produced when a real voice for that language is reachable; otherwise the
# localization is stored as text and says so. Nothing is machine-faked.


class LocalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Language:
    code: str
    label: str
    native: str
    edge_voice: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "label": self.label, "native": self.native}


LANGUAGES: dict[str, Language] = {
    "en": Language("en", "English", "English", "en-US-AndrewNeural"),
    "hi": Language("hi", "Hindi", "हिन्दी", "hi-IN-MadhurNeural"),
    "te": Language("te", "Telugu", "తెలుగు", "te-IN-MohanNeural"),
    "ta": Language("ta", "Tamil", "தமிழ்", "ta-IN-ValluvarNeural"),
    "es": Language("es", "Spanish", "Español", "es-ES-AlvaroNeural"),
    "fr": Language("fr", "French", "Français", "fr-FR-HenriNeural"),
    "de": Language("de", "German", "Deutsch", "de-DE-ConradNeural"),
    "pt": Language("pt", "Portuguese", "Português", "pt-BR-AntonioNeural"),
}

SYSTEM = (
    "You localize a faceless short-film studio's metadata. Translate meaning, "
    "not word order. Keep names, numbers and links intact. Do not add claims, "
    "hashtags or calls to action that are not in the source. Never invent facts. "
    "Return one JSON object only."
)


def options() -> list[dict[str, str]]:
    return [lang.as_dict() for lang in LANGUAGES.values()]


def get_language(code: str) -> Language:
    key = str(code or "").strip().lower()
    if key not in LANGUAGES:
        raise LocalizationError(
            f"Unknown language {code!r}. The desk knows: {', '.join(LANGUAGES)}."
        )
    return LANGUAGES[key]


def voice_available() -> bool:
    return importlib.util.find_spec("edge_tts") is not None


def _translator_callable(cfg: Any, translator: Callable[..., dict[str, Any]] | None) -> tuple[Callable[..., dict[str, Any]], str]:
    if translator is not None:
        return translator, "injected translator"
    client = LLMClient(cfg, timeout=120)
    if client.provider == "offline" or not client.available:
        raise LocalizationError(
            "Localization needs a language model. Set a provider in Settings "
            "(OpenAI, Anthropic, Gemini, or a local Ollama) and try again."
        )

    def call(system: str, user: str) -> dict[str, Any]:
        return client.complete_json(system, user, temperature=0.2)

    return call, f"{client.provider} · {client.model}"


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        tag = _clean_text(item, 60).lower()
        if 1 < len(tag) <= 60 and tag not in out:
            out.append(tag)
    return out[:25]


def translate(cfg: Any, video: dict[str, Any], language: str,
              translator: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Translate title, description, tags and spoken segments. Validated, never guessed."""
    lang = get_language(language)
    source_language = str(video.get("language") or "en").lower()
    if lang.code == source_language:
        raise LocalizationError(f"This film is already in {lang.label}.")

    script = video.get("script") if isinstance(video.get("script"), dict) else {}
    source_segments = [
        str(segment.get("text") or "").strip()
        for segment in (script.get("segments") or [])
        if str(segment.get("text") or "").strip()
    ]
    narration = load_narration(video)
    if not source_segments and isinstance(narration.get("segments"), list):
        source_segments = [
            str(segment.get("text") or "").strip()
            for segment in narration["segments"]
            if str(segment.get("text") or "").strip()
        ]
    source = {
        "title": _clean_text(video.get("title"), 300),
        "hook": _clean_text(video.get("hook"), 600),
        "description": _clean_text(video.get("description"), 4000),
        "tags": _clean_tags(video.get("tags")),
        "segments": source_segments,
    }
    if not source["title"] or not source["segments"]:
        raise LocalizationError("The film has no title or spoken script to translate.")

    call, provider = _translator_callable(cfg, translator)
    user = json.dumps({
        "target_language": {"code": lang.code, "name": lang.label},
        "instructions": (
            "Translate every field into the target language. Keep the title under "
            "90 characters. Keep the description's structure, paragraph breaks and "
            "links. Return exactly the same number of segments, in order, each a "
            "faithful spoken translation. Keep tags short and topical."
        ),
        "source": source,
        "schema": {
            "title": "string",
            "hook": "string",
            "description": "string",
            "tags": ["string"],
            "segments": ["string"],
        },
    }, ensure_ascii=False)
    try:
        data = call(SYSTEM, user)
    except LLMError as exc:
        raise LocalizationError(f"The model could not translate this film: {exc}") from exc
    except Exception as exc:
        raise LocalizationError(f"Translation failed: {exc}") from exc
    if not isinstance(data, dict):
        raise LocalizationError("The model did not return a translation object.")

    title = _clean_text(data.get("title"), 120)
    hook = _clean_text(data.get("hook"), 600)
    description = _clean_text(data.get("description"), 4500)
    tags = _clean_tags(data.get("tags"))
    raw_segments = data.get("segments")
    if not isinstance(raw_segments, list):
        raise LocalizationError("The model returned no translated segments.")
    segments = [_clean_text(text, 1200) for text in raw_segments]
    if len(segments) != len(source_segments) or not all(segments):
        raise LocalizationError(
            f"The model returned {len(segments)} segments for {len(source_segments)} spoken "
            "beats; the translation was discarded rather than guessed."
        )
    if not title:
        raise LocalizationError("The model returned an empty title.")
    if title.strip().lower() == source["title"].strip().lower() and lang.code != "en":
        raise LocalizationError("The model returned the source title unchanged; try another provider.")
    if segments == source_segments:
        raise LocalizationError("The model returned the source script unchanged; try another provider.")
    if not description:
        raise LocalizationError("The model returned an empty description.")

    return {
        "language": lang.code,
        "label": lang.label,
        "native": lang.native,
        "title": title,
        "hook": hook,
        "description": description,
        "tags": tags,
        "segments": segments,
        "provider": provider,
    }


def _timed_segments(video: dict[str, Any], narration: dict[str, Any],
                    texts: list[str]) -> list[dict[str, Any]]:
    raw = narration.get("segments")
    timed: list[dict[str, Any]] = []
    if isinstance(raw, list) and len(raw) == len(texts):
        for segment, text in zip(raw, texts):
            try:
                start = float(segment.get("start") or 0.0)
                end = float(segment.get("end") or start)
            except (TypeError, ValueError, AttributeError):
                start, end = 0.0, 0.0
            timed.append({"start": start, "end": max(start + 0.2, end), "text": text})
        if all(seg["end"] > seg["start"] for seg in timed):
            return timed
    total = float(video.get("duration") or 0.0) or max(4.0, len(texts) * 6.0)
    step = total / max(1, len(texts))
    return [
        {"start": i * step, "end": (i + 1) * step, "text": text}
        for i, text in enumerate(texts)
    ]


def _srt_clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rest = seconds % 60
    whole = int(rest)
    millis = int(round((rest - whole) * 1000))
    if millis >= 1000:
        whole += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def _cues(text: str, limit: int = 84) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?।।])\s+", text) if p.strip()]
    cues: list[str] = []
    current = ""
    for part in parts or [text]:
        if current and len(current) + 1 + len(part) > limit:
            cues.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
        while len(current) > limit:
            cut = current.rfind(" ", 0, limit)
            cut = cut if cut > 20 else limit
            cues.append(current[:cut].strip())
            current = current[cut:].strip()
    if current:
        cues.append(current)
    return cues or [text]


def build_localized_srt(timed: list[dict[str, Any]], out_path: Path) -> Path:
    lines: list[str] = []
    index = 1
    for segment in timed:
        start = float(segment["start"])
        end = float(segment["end"])
        text = str(segment["text"] or "").strip()
        if not text or end <= start:
            continue
        cues = _cues(text)
        weights = [max(1, len(cue)) for cue in cues]
        total_weight = sum(weights)
        cursor = start
        for cue, weight in zip(cues, weights):
            span = (end - start) * (weight / total_weight)
            cue_start = cursor
            cue_end = min(end, cursor + max(0.5, span))
            lines.append(
                f"{index}\n{_srt_clock(cue_start)} --> {_srt_clock(cue_end)}\n{cue}\n"
            )
            index += 1
            cursor = cue_end
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


class _VoiceConfig:
    """A read-only config view with the target language's voice selected."""

    def __init__(self, cfg: Any, overrides: dict[str, Any]):
        self._cfg = cfg
        self._overrides = overrides

    def get(self, dotted: str, default: Any = None) -> Any:
        if dotted in self._overrides:
            return self._overrides[dotted]
        return self._cfg.get(dotted, default)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cfg, name)


def synthesize_voiceover(cfg: Any, language: str, texts: list[str], workdir: Path,
                         *, title: str = "", synthesizer: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Produce a localized narration track. Returns paths and an honest note."""
    lang = get_language(language)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if synthesizer is not None:
        result = synthesizer(texts, lang, workdir)
        path = Path(str(getattr(result, "path", result)))
        return {
            "audio_path": str(path),
            "provider": str(getattr(result, "provider", "injected voice")),
            "voice": str(getattr(result, "voice", lang.edge_voice)),
            "note": "",
        }
    if not voice_available():
        raise LocalizationError(
            "Localized audio needs the edge-tts package and network access. "
            "The translated metadata and captions are still saved."
        )
    voice_dir = workdir / "voice"
    proxy = _VoiceConfig(cfg, {
        "voice.provider": "edge",
        "voice.edge_voice": lang.edge_voice,
        "voice.edge_rate": "+0%",
        "voice.edge_pitch": "+0Hz",
    })
    maker = NarrationMaker(proxy, voice_dir)
    script = {
        "title": title or lang.label,
        "segments": [{"heading": "", "text": text} for text in texts],
    }
    narration = maker.synthesize(script, fmt="short")
    return {
        "audio_path": str(narration.path),
        "provider": narration.provider,
        "voice": narration.voice,
        "note": "Localized voiceover uses a different read length than the original cut.",
    }


def localize_video(
    cfg: Any,
    db: Any,
    video: dict[str, Any],
    language: str,
    *,
    translator: Callable[..., dict[str, Any]] | None = None,
    voice: bool = False,
    synthesizer: Callable[..., Any] | None = None,
    store: bool = True,
) -> dict[str, Any]:
    lang = get_language(language)
    video_id = str(video.get("id") or "")
    if not video_id:
        raise LocalizationError("The film has no id.")
    translation = translate(cfg, video, lang.code, translator=translator)

    narration = load_narration(video)
    timed = _timed_segments(video, narration, translation["segments"])
    workdir = Path(cfg.video_dir(video_id)) / "lang" / lang.code
    srt_path = build_localized_srt(timed, workdir / f"captions.{lang.code}.srt")

    audio_path = ""
    voice_name = ""
    voice_provider = ""
    notes: list[str] = []
    if voice:
        try:
            voice_result = synthesize_voiceover(
                cfg, lang.code, translation["segments"], workdir,
                title=translation["title"], synthesizer=synthesizer,
            )
            audio_path = voice_result["audio_path"]
            voice_name = voice_result["voice"]
            voice_provider = voice_result["provider"]
            if voice_result.get("note"):
                notes.append(voice_result["note"])
        except Exception as exc:  # metadata still ships when the voice is unreachable
            notes.append(f"Voiceover skipped: {exc}")

    record = {
        "status": "ready",
        "title": translation["title"],
        "description": translation["description"],
        "tags": translation["tags"],
        "srt_path": str(srt_path),
        "audio_path": audio_path,
        "provider": translation["provider"],
        "voice": voice_name or voice_provider,
        "note": " · ".join(notes),
    }
    if store:
        stored = db.upsert_localization(video_id, lang.code, record)
    else:
        stored = {"video_id": video_id, "language": lang.code, **record}
    return {
        **stored,
        "language_label": lang.label,
        "native": lang.native,
        "segments": translation["segments"],
        "hook": translation["hook"],
        "voice_available": voice_available(),
    }


def status_for(db: Any, video_id: str) -> dict[str, Any]:
    return {
        "options": options(),
        "items": db.list_localizations(video_id),
        "voice_available": voice_available(),
        "note": (
            "Translations are produced by your configured model and validated before saving. "
            "Localized voiceovers need edge-tts; captions always carry real timings."
        ),
    }
