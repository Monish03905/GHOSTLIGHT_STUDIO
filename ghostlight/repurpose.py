from __future__ import annotations

import hashlib
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import ffmpeg
from .captions import resolve_fonts

# Turning one long film into vertical cuts. Timing comes from narration.json,
# so a clip always starts and ends on a spoken sentence instead of a guess.

MIN_CLIP = 15.0
MAX_CLIP = 60.0
IDEAL_CLIP = 32.0
VERTICAL = (1080, 1920)

_CURIOSITY = {
    "why", "what", "how", "hidden", "secret", "strange", "impossible", "forgotten",
    "vanished", "beneath", "inside", "never", "last", "only", "missing", "unseen",
}
_PAYOFF = {
    "so", "therefore", "which means", "that's why", "next time", "remember",
    "the trick", "in the end", "turn it", "listen", "here's", "now you",
}
_TERMINAL = re.compile(r"[.!?…]['\"”’)]?$")
_WORD = re.compile(r"[A-Za-z0-9'’\-]+")


class RepurposeError(RuntimeError):
    pass


@dataclass
class Beat:
    text: str
    start: float
    end: float
    words: list[dict[str, Any]]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Candidate:
    start: float
    end: float
    score: int
    title: str
    hook: str
    text: str
    reason: str
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.end - self.start, 2),
            "score": self.score,
            "title": self.title,
            "hook": self.hook,
            "text": self.text,
            "reason": self.reason,
            "digest": self.digest,
        }


@dataclass
class ClipRender:
    path: Path
    thumb: Path | None
    captions: Path | None
    duration: float
    bytes: int


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(str(text or ""))]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _band(value: float, low: float, high: float, span: float) -> float:
    if low <= value <= high:
        return 100.0
    distance = low - value if value < low else value - high
    return _clamp(100.0 - (distance / span) * 100.0)


def _digest(text: str) -> str:
    return hashlib.sha1(" ".join(_tokens(text)).encode("utf-8")).hexdigest()[:16]


def _word(item: dict[str, Any]) -> dict[str, Any] | None:
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    try:
        start = float(item.get("start") or 0.0)
        end = float(item.get("end") or start)
    except (TypeError, ValueError):
        return None
    return {"text": text, "start": start, "end": max(start, end)}


def beats_from_words(words: Iterable[dict[str, Any]], min_words: int = 3) -> list[Beat]:
    clean = [w for w in (_word(item) for item in words) if w]
    beats: list[Beat] = []
    current: list[dict[str, Any]] = []
    for index, word in enumerate(clean):
        current.append(word)
        nxt = clean[index + 1] if index + 1 < len(clean) else None
        gap = (nxt["start"] - word["end"]) if nxt else 99.0
        terminal = bool(_TERMINAL.search(word["text"]))
        long_pause = bool(nxt) and gap > 0.55 and len(current) >= min_words
        if terminal or long_pause or len(current) >= 42 or nxt is None:
            beats.append(_beat(current))
            current = []
    return [b for b in beats if b.text]


def _beat(words: list[dict[str, Any]]) -> Beat:
    return Beat(
        text=" ".join(w["text"] for w in words).strip(),
        start=float(words[0]["start"]),
        end=float(words[-1]["end"]),
        words=list(words),
    )


def _estimate_words(text: str, start: float, end: float) -> list[dict[str, Any]]:
    tokens = _WORD.findall(str(text or ""))
    if not tokens:
        return []
    span = max(0.1, end - start)
    step = span / len(tokens)
    return [
        {"text": token, "start": start + i * step, "end": start + (i + 1) * step}
        for i, token in enumerate(tokens)
    ]


def beats_from_narration(narration: dict[str, Any] | None, duration: float = 0.0) -> list[Beat]:
    data = narration if isinstance(narration, dict) else {}
    words = data.get("words")
    if isinstance(words, list) and words:
        beats = beats_from_words(words)
        if beats:
            return beats
    segments = data.get("segments")
    beats = []
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            try:
                start = float(segment.get("start") or 0.0)
                end = float(segment.get("end") or start)
            except (TypeError, ValueError):
                continue
            beats.append(Beat(text=text, start=start, end=max(start + 0.2, end),
                              words=_estimate_words(text, start, end)))
    if beats:
        return beats
    raise RepurposeError("This film has no narration timings to cut against.")


def _source_title(title: str, text: str) -> str:
    phrase = re.split(r"[—:;,.!?]", text.strip())[0].strip()
    if len(phrase.split()) < 3:
        phrase = str(title or "").strip()
    if not phrase:
        phrase = "A quiet cut"
    phrase = phrase[:1].upper() + phrase[1:]
    return phrase[:88]


def _window_reason(window: list[Beat]) -> str:
    first = window[0].text
    last = window[-1].text
    duration = window[-1].end - window[0].start
    notes = []
    if "?" in first:
        notes.append("opens on a question")
    elif set(_tokens(first)) & _CURIOSITY:
        notes.append("opens on a curiosity")
    if re.search(r"\b\d+\b", first):
        notes.append("has a number in the hook")
    if _TERMINAL.search(last):
        notes.append("ends on a closed thought")
    if any(p in last.lower() for p in _PAYOFF):
        notes.append("carries its own payoff")
    if 28 <= duration <= 40:
        notes.append("sits in the 30-second sweet spot")
    return " · ".join(notes) or "complete thought, clean in and out"


def score_window(beats: list[Beat], start_idx: int, end_idx: int) -> int:
    window = beats[start_idx : end_idx + 1]
    start = window[0].start
    end = window[-1].end
    duration = max(0.1, end - start)
    text = " ".join(b.text for b in window)
    tokens = _tokens(text)
    if not tokens:
        return 0
    wps = len(tokens) / duration
    duration_fit = _clamp(100.0 - (abs(duration - IDEAL_CLIP) / 26.0) * 100.0)

    first = window[0].text
    hook = 52.0
    if "?" in first:
        hook += 16
    if re.search(r"\b\d+\b", first):
        hook += 8
    if set(_tokens(first)) & _CURIOSITY:
        hook += 16
    if len(_tokens(first)) <= 22:
        hook += 8

    complete = 100.0 if _TERMINAL.search(window[-1].text) else 45.0
    pacing = _band(wps, 2.0, 3.2, span=1.3)
    payoff = 100.0 if any(p in window[-1].text.lower() for p in _PAYOFF) else 70.0
    density = 100.0 if re.search(r"\b\d+\b", text) or "?" in text else 70.0
    total = (
        duration_fit * 0.22 + hook * 0.28 + complete * 0.14
        + pacing * 0.16 + payoff * 0.12 + density * 0.08
    )
    return int(round(_clamp(total)))


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def plan(video: dict[str, Any], narration: dict[str, Any] | None, count: int = 3,
         *, min_s: float = MIN_CLIP, max_s: float = MAX_CLIP,
         avoid: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Choose complete-thought windows, avoiding cuts that already exist."""
    count = max(1, min(6, int(count)))
    beats = beats_from_narration(narration, float(video.get("duration") or 0.0))
    if len(beats) < 2:
        return {
            "candidates": [],
            "beats": len(beats),
            "note": "The narration is one continuous thought; there is nothing to cut against.",
        }

    avoid_ranges = []
    avoid_tokens: list[set[str]] = []
    for clip in avoid or []:
        try:
            avoid_ranges.append((float(clip.get("clip_start") or 0), float(clip.get("clip_end") or 0)))
        except (TypeError, ValueError):
            pass
        text = " ".join([str(clip.get("title") or ""), str(clip.get("hook") or "")])
        if text.strip():
            avoid_tokens.append(set(_tokens(text)))

    windows: list[tuple[int, int, int]] = []
    for i in range(len(beats)):
        for j in range(i, len(beats)):
            duration = beats[j].end - beats[i].start
            if duration > max_s:
                break
            if duration < min_s:
                continue
            windows.append((i, j, score_window(beats, i, j)))
    if not windows:
        return {
            "candidates": [],
            "beats": len(beats),
            "note": "No sentence window lands inside the 15–60 second cut range.",
        }

    windows.sort(key=lambda row: row[2], reverse=True)
    chosen: list[tuple[int, int, int]] = []
    for i, j, score in windows:
        if len(chosen) >= count:
            break
        if any(not (j < a or i > b) for a, b, _ in chosen):
            continue
        start, end = beats[i].start, beats[j].end
        if any(not (end <= a or start >= b) for a, b in avoid_ranges):
            continue
        tokens = set(_tokens(" ".join(b.text for b in beats[i : j + 1])))
        if any(_overlap(tokens, prior) > 0.55 for prior in avoid_tokens):
            continue
        if any(_overlap(tokens, set(_tokens(" ".join(b.text for b in beats[x : y + 1])))) > 0.55 for x, y, _ in chosen):
            continue
        chosen.append((i, j, score))

    candidates: list[Candidate] = []
    for i, j, score in chosen:
        window = beats[i : j + 1]
        text = " ".join(b.text for b in window).strip()
        candidates.append(Candidate(
            start=beats[i].start,
            end=beats[j].end,
            score=score,
            title=_source_title(str(video.get("title") or ""), window[0].text),
            hook=window[0].text,
            text=text,
            reason=_window_reason(window),
            digest=_digest(text),
        ))
    candidates.sort(key=lambda c: c.start)
    return {
        "candidates": [c.as_dict() for c in candidates],
        "beats": len(beats),
        "note": (
            "Every cut starts and ends on a spoken sentence. Scores are structural, "
            "not a prediction of watch time."
        ),
    }


def candidate_from_range(video: dict[str, Any], narration: dict[str, Any] | None,
                         start: float, end: float) -> Candidate:
    beats = beats_from_narration(narration, float(video.get("duration") or 0.0))
    total = max(b.end for b in beats)
    start = max(0.0, float(start))
    end = min(total, float(end))
    if end - start < 5.0:
        raise RepurposeError("A clip needs at least five seconds.")
    if end - start > MAX_CLIP:
        raise RepurposeError(f"A clip may run at most {MAX_CLIP:.0f} seconds.")
    window = [b for b in beats if b.start < end and b.end > start]
    if not window:
        raise RepurposeError("That range does not cover any narration.")
    text = " ".join(b.text for b in window).strip()
    return Candidate(
        start=start,
        end=end,
        score=score_window(beats, beats.index(window[0]), beats.index(window[-1])),
        title=_source_title(str(video.get("title") or ""), window[0].text),
        hook=window[0].text,
        text=text,
        reason="Cut by hand from the edit desk",
        digest=_digest(text),
    )


# -- rendering ----------------------------------------------------------

def _ass_clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rest = seconds % 60
    return f"{hours}:{minutes:02d}:{rest:05.2f}"


def _clean_ass(text: str) -> str:
    return " ".join(str(text).replace("\n", " ").split()).replace("{", "(").replace("}", ")")


def build_clip_ass(words: Iterable[dict[str, Any]], start: float, end: float, out_path: Path,
                   *, width: int = VERTICAL[0], height: int = VERTICAL[1]) -> Path:
    fonts = resolve_fonts()
    lines: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for raw in words:
        word = _word(raw)
        if not word or word["end"] <= start or word["start"] >= end:
            continue
        word = {
            "text": word["text"],
            "start": max(start, word["start"]),
            "end": min(end, word["end"]),
        }
        if current:
            span = word["end"] - current[0]["start"]
            length = len(" ".join(w["text"] for w in current)) + len(word["text"]) + 1
            gap = word["start"] - current[-1]["end"]
            if gap > 0.7 or span > 2.1 or len(current) >= 5 or length > 27:
                lines.append(current)
                current = []
        current.append(word)
    if current:
        lines.append(current)

    size = max(46, min(74, int(width * 0.061)))
    header = textwrap.dedent(
        f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clip,{fonts.sans},{size},&H00F2EAD8,&H00F2EAD8,&H00171512,&H99171512,-1,0,0,0,100,100,0,0,1,5,2,2,90,90,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    )
    events = []
    for line in lines:
        text = _clean_ass(" ".join(w["text"] for w in line))
        if not text:
            continue
        events.append(
            f"Dialogue: 0,{_ass_clock(line[0]['start'] - start)},"
            f"{_ass_clock(line[-1]['end'] - start)},Clip,,0,0,0,,{text}"
        )
    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out_path


def render_clip(source: Path, out_path: Path, start: float, end: float,
                *, words: Iterable[dict[str, Any]] | None = None,
                width: int = VERTICAL[0], height: int = VERTICAL[1],
                fps: int = 30, crf: int = 21) -> ClipRender:
    source = Path(source)
    out_path = Path(out_path)
    if not source.is_file():
        raise RepurposeError(f"Missing source film: {source.name}")
    duration = max(0.2, float(end) - float(start))
    workdir = out_path.parent
    workdir.mkdir(parents=True, exist_ok=True)

    caption_path: Path | None = None
    if words:
        caption_path = build_clip_ass(words, start, end, workdir / "clip_subs.ass",
                                      width=width, height=height)

    graph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=42:2,eq=brightness=-0.10:saturation=0.9[bg];"
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )
    if caption_path is not None:
        graph += ",ass=clip_subs.ass"
    graph += "[v]"

    args = [
        "-y",
        "-ss", f"{max(0.0, float(start)):.3f}",
        "-i", str(source.resolve()),
        "-t", f"{duration:.3f}",
        "-filter_complex", graph,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(int(crf)),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-r", str(int(fps)),
        out_path.name,
    ]
    ffmpeg.run(args, cwd=workdir, timeout=1800)

    thumb: Path | None = None
    thumb_path = workdir / "clip_thumb.jpg"
    try:
        ffmpeg.run(
            ["-y", "-ss", "0.6", "-i", out_path.name, "-frames:v", "1", "-q:v", "3", thumb_path.name],
            cwd=workdir,
            timeout=120,
        )
        thumb = thumb_path if thumb_path.is_file() else None
    except ffmpeg.FFmpegError:
        thumb = None

    return ClipRender(
        path=out_path,
        thumb=thumb,
        captions=caption_path,
        duration=duration,
        bytes=out_path.stat().st_size if out_path.is_file() else 0,
    )
