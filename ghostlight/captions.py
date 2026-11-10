from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from pathlib import Path

from .content import PALETTES
from .tts import Narration, Word

CREAM_FALLBACK = (240, 233, 220)


@dataclass(frozen=True)
class Fonts:
    serif: str
    sans: str


def resolve_fonts() -> Fonts:
    if os.name == "nt":
        root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        serif = "Georgia" if (root / "georgia.ttf").exists() else "Times New Roman"
        sans = "Arial" if (root / "arial.ttf").exists() else "Segoe UI"
        return Fonts(serif, sans)
    candidates = [
        (Path("/System/Library/Fonts/Supplemental/Georgia.ttf"), "Georgia", "Arial"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"), "DejaVu Serif", "DejaVu Sans"),
        (Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"), "Liberation Serif", "Liberation Sans"),
        (Path("/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf"), "Noto Serif", "Noto Sans"),
    ]
    for path, serif, sans in candidates:
        if path.exists():
            return Fonts(serif, sans)
    return Fonts("DejaVu Serif", "DejaVu Sans")


def _ass_color(rgb: tuple[int, int, int], alpha: int = 0) -> str:
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    remainder = seconds % 60
    return f"{hours}:{minutes:02d}:{remainder:05.2f}"


def _clean(text: str) -> str:
    text = " ".join(str(text).replace("\n", " ").split())
    text = text.replace("{", "(").replace("}", ")")
    return text


def _fit_title(title: str, width: int, short: bool) -> tuple[int, int]:
    """Largest size that keeps the opening title within four balanced lines."""
    base = 64 if short else 56
    usable = width * 0.84
    clean = _clean(title)
    for size in range(base, 33, -2):
        chars = max(8, int(usable / (size * 0.55)))
        lines = textwrap.wrap(clean, chars)
        if len(lines) <= 4:
            return size, max(1, len(lines))
    chars = max(8, int(usable / (34 * 0.55)))
    return 34, len(textwrap.wrap(clean, chars))


def _group_words(words: list[Word], max_chars: int, max_words: int, max_span: float) -> list[list[Word]]:
    lines: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current:
            gap = word.start - current[-1].end
            span = word.end - current[0].start
            length = len(" ".join(w.text for w in current)) + len(word.text) + 1
            if gap > 0.85 or span > max_span or len(current) >= max_words or length > max_chars:
                lines.append(current)
                current = []
        current.append(word)
    if current:
        lines.append(current)
    return lines


def _karaoke(words: list[Word]) -> str:
    parts: list[str] = []
    for index, word in enumerate(words):
        boundary = words[index + 1].start if index + 1 < len(words) else word.end
        centis = max(1, int(round((boundary - word.start) * 100)))
        parts.append(f"{{\\kf{centis}}}{_clean(word.text)}")
    return " ".join(parts)


def build_ass(
    narration: Narration,
    out_path: str | Path,
    *,
    title: str,
    width: int,
    height: int,
    short: bool,
    palette_name: str = "cosmic_indigo",
    kicker: str = "",
    end_line: str = "one strange idea at a time",
    wordmark: str = "GHOSTLIGHT STUDIO",
    fonts: Fonts | None = None,
) -> Path:
    fonts = fonts or resolve_fonts()
    palette = PALETTES.get(palette_name, PALETTES["cosmic_indigo"])
    cream = palette.get("paper", CREAM_FALLBACK)
    accent = palette.get("glow", (232, 177, 76))
    ink = palette.get("bg", (10, 10, 14))
    duration = max(1.0, narration.duration)

    cap_size = 56 if short else 46
    cap_margin_v = int(height * (0.175 if short else 0.10))
    side_margin = int(width * (0.085 if short else 0.075))
    title_size, title_lines = _fit_title(title, width, short)
    end_size = 46 if short else 38
    word_size = 24 if short else 21

    styles = [
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{fonts.serif},{cap_size},{_ass_color(cream)},{_ass_color(cream, 0x50)},"
        f"{_ass_color(ink, 0x2E)},{_ass_color(ink, 0x7A)},0,0,0,0,100,100,0.4,0,1,2.6,2.6,2,"
        f"{side_margin},{side_margin},{cap_margin_v},1",
        f"Style: Title,{fonts.serif},{title_size},{_ass_color(cream)},{_ass_color(cream)},"
        f"{_ass_color(ink, 0x18)},{_ass_color(ink, 0x50)},-1,0,0,0,100,100,0,0,1,3.2,2.2,5,60,60,60,1",
        f"Style: Kicker,{fonts.sans},{30 if short else 26},{_ass_color(accent)},{_ass_color(accent)},"
        f"{_ass_color(ink, 0x30)},{_ass_color(ink, 0x40)},-1,0,0,0,100,100,4,0,1,2.0,1.2,5,60,60,60,1",
        f"Style: Chapter,{fonts.sans},{26 if short else 23},{_ass_color(accent)},{_ass_color(accent)},"
        f"{_ass_color(ink, 0x30)},{_ass_color(ink, 0x68)},-1,0,0,0,100,100,3,0,1,1.6,1.0,5,60,60,60,1",
        f"Style: ChapterName,{fonts.serif},{56 if short else 50},{_ass_color(cream)},{_ass_color(cream)},"
        f"{_ass_color(ink, 0x20)},{_ass_color(ink, 0x68)},-1,0,0,0,100,100,0,0,1,2.4,1.6,5,60,60,60,1",
        f"Style: Wordmark,{fonts.sans},{word_size},{_ass_color(cream, 0x58)},{_ass_color(cream, 0x58)},"
        f"{_ass_color(ink, 0x40)},{_ass_color(ink, 0x70)},-1,0,0,0,100,100,3.5,0,1,1.4,0,7,"
        f"{int(width * 0.06)},{int(width * 0.06)},{int(height * 0.055) if short else int(height * 0.06)},1",
        f"Style: EndCard,{fonts.serif},{end_size},{_ass_color(cream)},{_ass_color(cream)},"
        f"{_ass_color(ink, 0x18)},{_ass_color(ink, 0x60)},-1,0,0,0,100,100,0,0,1,2.8,1.6,5,80,80,80,1",
    ]

    events: list[str] = []

    # wordmark, quietly present for the whole film
    word_text = f"{{\\fad(900,600)\\fsp3.5}}{_clean(wordmark.upper())}"
    events.append(f"Dialogue: 1,{_clock(0.3)},{_clock(duration)},Wordmark,,0,0,0,,{word_text}")

    # opening title card: it lives over the silent intro, then hands off to the voice
    title_start = 0.15
    first_spoken = narration.words[0].start if narration.words else narration.intro
    title_end = max(1.4, first_spoken + 0.45)
    block_h = title_lines * title_size * 1.16
    card_y = int(height * (0.34 if short else 0.31))
    kicker_y = int(max(height * 0.115, card_y - block_h / 2 - title_size * 0.95))
    if kicker:
        kicker_text = f"{{\\fad(500,400)\\fsp3}}{_clean(kicker.upper())}"
        events.append(
            f"Dialogue: 2,{_clock(title_start)},{_clock(title_end)},Kicker,,0,0,0,,"
            f"{{\\an5\\pos({width // 2},{kicker_y})}}{kicker_text}"
        )
    title_text = f"{{\\fad(500,420)\\blur0.4}}{_clean(title)}"
    events.append(
        f"Dialogue: 2,{_clock(title_start)},{_clock(title_end)},Title,,0,0,0,,"
        f"{{\\an5\\pos({width // 2},{card_y})\\q0}}{title_text}"
    )

    # chapter marks (long form only; the opening title occupies the first slot)
    if not short and len(narration.segments) > 1:
        for index, segment in enumerate(narration.segments[1:], start=1):
            heading = _clean(segment.heading or "")
            if not heading:
                continue
            start = max(title_end + 0.4, segment.start + 0.35)
            end = min(start + 3.8, duration - 1.0)
            if end - start < 1.2:
                continue
            y = int(height * 0.19)
            label = f"{{\\fad(320,420)\\fsp4}}PART {index:02d}"
            events.append(
                f"Dialogue: 2,{_clock(start)},{_clock(end)},Chapter,,0,0,0,,"
                f"{{\\an5\\pos({width // 2},{y})}}{label}"
            )
            events.append(
                f"Dialogue: 2,{_clock(start)},{_clock(end)},ChapterName,,0,0,0,,"
                f"{{\\an5\\pos({width // 2},{y + int((28 if short else 25) * 2.1)})\\q0}}{heading.upper() if len(heading) < 34 else heading}"
            )

    # karaoke captions
    max_chars = 30 if short else 54
    max_words = 6 if short else 9
    max_span = 3.3 if short else 4.2
    for line in _group_words(narration.words, max_chars, max_words, max_span):
        if not line:
            continue
        start = max(0.0, line[0].start - 0.02)
        end = min(duration, line[-1].end + 0.14)
        if end - start < 0.2:
            end = start + 0.4
        text = f"{{\\fad(70,110)\\q0}}{_karaoke(line)}"
        events.append(f"Dialogue: 3,{_clock(start)},{_clock(end)},Caption,,0,0,0,,{text}")

    # end card, only once the last word has actually landed
    last_word_end = narration.words[-1].end if narration.words else max(
        [s.end for s in narration.segments] + [duration - narration.outro]
    )
    end_start = max(title_end + 1.0, last_word_end + 0.22)
    end_y = int(height * (0.72 if short else 0.74))
    end_text = (
        f"{{\\fad(600,500)\\fsp1.5}}{_clean(end_line)}\\N"
        f"{{\\fs{int(end_size * 0.52)}\\fsp4\\1c&H{cream[2]:02X}{cream[1]:02X}{cream[0]:02X}&\\1a&H28&}}"
        f"{_clean(wordmark.upper())}"
    )
    if end_start <= duration - 0.45:
        events.append(
            f"Dialogue: 2,{_clock(end_start)},{_clock(duration)},EndCard,,0,0,0,,"
            f"{{\\an5\\pos({width // 2},{end_y})\\q0}}{end_text}"
        )

    header = [
        "[Script Info]",
        "; generated by Ghostlight Studio",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
    ]
    body = "\n".join(styles)
    content = "\n".join(header + [body, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events, ""])
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
