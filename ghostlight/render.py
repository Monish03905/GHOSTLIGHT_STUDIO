from __future__ import annotations

import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import ffmpeg
from .captions import Fonts, build_ass, resolve_fonts
from .config import Config
from .content import PALETTES
from .tts import Narration
from .visuals import Scene

# xfade's "dissolve" swaps pixels in random order, which reads as static
# across smooth skies and moons. These all blend cleanly at film scale.
TRANSITION_POOL = (
    "fade", "hblur", "fade", "smoothleft", "fadegrays", "fade",
    "smoothright", "wipeup", "hblur", "fade", "smoothleft", "fadeblack",
)


def _transition_for(seed: int, index: int) -> str:
    return TRANSITION_POOL[(seed * 7 + index * 5) % len(TRANSITION_POOL)]


@dataclass
class RenderResult:
    path: Path
    poster: Path
    thumbnail: Path | None
    captions: Path
    duration: float
    width: int
    height: int
    bytes: int
    thumb_variants: list[dict[str, Any]] = field(default_factory=list)


def scene_count(duration: float, short: bool) -> int:
    per_scene = 6.6 if short else 11.5
    low, high = (4, 9) if short else (8, 28)
    return int(max(low, min(high, round(duration / per_scene))))


class Renderer:
    def __init__(self, cfg: Config, on_event: Callable[[str, str, str], None] | None = None):
        self.cfg = cfg
        self.on_event = on_event or (lambda level, kind, message: None)

    def _emit(self, message: str, level: str = "info", kind: str = "render") -> None:
        self.on_event(level, kind, message)

    def render(
        self,
        *,
        workdir: str | Path,
        out_path: str | Path,
        scenes: list[Scene],
        narration: Narration,
        title: str,
        short: bool,
        kicker: str = "",
        palette_name: str = "cosmic_indigo",
        music_path: str | Path | None = None,
        seed: int = 0,
        thumbnail: bool | None = None,
        brand: str = "",
        tagline: str = "",
    ) -> RenderResult:
        if not scenes:
            raise ValueError("render needs at least one scene")
        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if music_path:
            music_path = Path(music_path).resolve()

        width, height = (self.cfg.get("render.short") if short else self.cfg.get("render.long"))
        width, height = int(width), int(height)
        fps = int(self.cfg.get("render.fps", 30) or 30)
        crf = int(self.cfg.get("render.crf", 20) or 20)
        preset = str(self.cfg.get("render.preset", "medium") or "medium")
        overlap = 0.7 if short else 1.1
        count = len(scenes)
        tail = 0.25
        target = max(1.0, narration.duration)
        total = target + tail + overlap * (count - 1)
        frames = max(fps, int(round(total / count * fps)))
        clip_duration = frames / fps
        video_length = count * clip_duration - overlap * (count - 1)

        clips_dir = workdir / "clips"
        if clips_dir.exists():
            shutil.rmtree(clips_dir)
        clips_dir.mkdir(parents=True)
        self._emit(f"Setting {count} plates in slow motion.", kind="render")

        clips: list[Path] = []
        for index, scene in enumerate(scenes):
            clip = clips_dir / f"clip_{index:02d}.mp4"
            self._render_clip(scene, clip, frames, fps, width, height, seed=seed, index=index)
            clips.append(clip)
            self._emit(f"Camera move {index + 1} of {count} is in the can.", level="detail")

        fonts = resolve_fonts()
        captions_path = build_ass(
            narration,
            workdir / "captions.ass",
            title=title,
            width=width,
            height=height,
            short=short,
            palette_name=palette_name,
            kicker=kicker,
            wordmark=str(brand or self.cfg.get("studio.name", "Ghostlight Studio")).upper(),
            fonts=fonts,
        )
        self._emit("Lettering the film.", kind="render")

        self._compose(
            clips=clips,
            captions=captions_path,
            narration=narration,
            music_path=Path(music_path) if music_path else None,
            out_path=out_path,
            video_length=video_length,
            fps=fps,
            width=width,
            height=height,
            crf=crf,
            preset=preset,
            overlap=overlap,
            clip_duration=clip_duration,
            title=title,
            seed=seed,
        )
        self._emit("The cut is finished.", kind="render")

        poster = make_poster(
            scenes[0].path,
            workdir / "poster.jpg",
            title=title,
            kicker=kicker,
            palette_name=palette_name,
            width=width,
            height=height,
            short=short,
            fonts=fonts,
            brand=brand,
            tagline=tagline,
        )
        thumb = None
        thumb_variants: list[dict[str, Any]] = []
        if thumbnail is None:
            thumbnail = not short
        if thumbnail:
            picks = [
                scenes[min(len(scenes) - 1, max(0, len(scenes) // 3))].path,
                scenes[min(len(scenes) - 1, max(0, len(scenes) // 2))].path,
                scenes[-1].path,
            ]
            thumb_variants = make_thumbnail_variants(
                picks,
                workdir / "thumbs",
                title=title,
                kicker=kicker,
                palette_name=palette_name,
                fonts=fonts,
                brand=brand,
            )
            champion = next(
                (v for v in thumb_variants if v.get("recommended")), thumb_variants[0]
            )
            thumb = Path(str(champion["path"]))

        if not bool(self.cfg.get("render.keep_work_files", False)):
            shutil.rmtree(clips_dir, ignore_errors=True)

        data = ffmpeg.probe(out_path)
        duration = float(data.get("format", {}).get("duration", video_length) or video_length)
        return RenderResult(
            path=out_path,
            poster=poster,
            thumbnail=thumb,
            captions=captions_path,
            duration=duration,
            width=width,
            height=height,
            bytes=out_path.stat().st_size,
            thumb_variants=thumb_variants,
        )

    def _render_clip(
        self,
        scene: Scene,
        path: Path,
        frames: int,
        fps: int,
        width: int,
        height: int,
        seed: int = 0,
        index: int = 0,
    ) -> None:
        denom = max(1, frames - 1)
        progress = f"(on/{denom})"
        span = 0.11 + ((seed + index * 13) % 5) * 0.012
        start = 1.045
        if scene.motion == "in":
            zoom = f"{start}+{span:.3f}*{progress}"
        else:
            zoom = f"{start + span:.3f}-{span:.3f}*{progress}"
        sway_x = f"iw*0.007*sin(6.2832*{progress})"
        sway_y = f"ih*0.005*sin(6.2832*{progress}+1.4)"
        if scene.direction == "up":
            x = f"(iw-iw/zoom)/2+{sway_x}"
            y = f"(ih-ih/zoom)*(1-{progress})+{sway_y}"
        elif scene.direction == "down":
            x = f"(iw-iw/zoom)/2+{sway_x}"
            y = f"(ih-ih/zoom)*{progress}+{sway_y}"
        elif scene.direction == "left":
            x = f"(iw-iw/zoom)*(1-{progress})+{sway_x}"
            y = f"(ih-ih/zoom)/2+{sway_y}"
        elif scene.direction == "right":
            x = f"(iw-iw/zoom)*{progress}+{sway_x}"
            y = f"(ih-ih/zoom)/2+{sway_y}"
        else:
            x = f"(iw-iw/zoom)/2+{sway_x}"
            y = f"(ih-ih/zoom)/2+{sway_y}"

        duration = frames / fps
        phase = scene.drift * 6.2832
        layers: list[Path] = []
        graph: list[str] = [
            f"[0:v]scale=iw*1.5:ih*1.5:flags=lanczos,"
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps}[bg]"
        ]
        last = "[bg]"

        if scene.mid and scene.mid.exists():
            sx, sy = width * 0.55, height * 0.55
            mx = f"{sx:.1f}*(0.5+0.34*sin(6.2832*(t/{duration:.3f})+{phase:.3f}))"
            my = f"{sy:.1f}*(0.58-0.32*(t/{duration:.3f}))"
            graph.append(f"[{len(layers) + 1}:v]crop={width}:{height}:x='{mx}':y='{my}',format=rgba[midraw]")
            graph.append(f"{last}[midraw]overlay=0:0:format=auto[mid]")
            last = "[mid]"
            layers.append(scene.mid)

        if scene.atmosphere and scene.atmosphere.exists():
            sx, sy = width * 0.7, height * 0.7
            ax = f"{sx:.1f}*(0.5-0.40*(t/{duration:.3f}))"
            ay = f"{sy:.1f}*(0.45+0.20*sin(6.2832*(t/{duration:.3f})+{phase + 1.2:.3f}))"
            graph.append(f"[{len(layers) + 1}:v]crop={width}:{height}:x='{ax}':y='{ay}',format=rgba[airraw]")
            graph.append(f"{last}[airraw]overlay=0:0:format=auto[air]")
            last = "[air]"
            layers.append(scene.atmosphere)

        if scene.sweep and scene.sweep.exists():
            graph.append(
                f"[{len(layers) + 1}:v]format=rgba[sweepraw]"
            )
            graph.append(
                f"{last}[sweepraw]overlay=x='-w+(W+w)*(t/{duration:.3f})':y=0:format=auto[lit]"
            )
            last = "[lit]"
            layers.append(scene.sweep)

        graph.append(f"{last}format=yuv420p[v]")

        args: list[str] = ["-y", "-i", str(scene.path)]
        for layer in layers:
            args += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", str(layer)]

        ffmpeg.run(
            args
            + [
                "-filter_complex",
                ";".join(graph),
                "-map",
                "[v]",
                "-frames:v",
                str(frames),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                str(path),
            ],
            timeout=1800,
        )

    def _compose(
        self,
        *,
        clips: list[Path],
        captions: Path,
        narration: Narration,
        music_path: Path | None,
        out_path: Path,
        video_length: float,
        fps: int,
        width: int,
        height: int,
        crf: int,
        preset: str,
        overlap: float,
        clip_duration: float,
        title: str,
        seed: int = 0,
    ) -> None:
        args: list[str] = ["-y"]
        for clip in clips:
            args += ["-i", str(clip)]
        args += ["-i", str(Path(narration.path).resolve())]
        if music_path and music_path.exists():
            args += ["-i", str(music_path)]

        graph: list[str] = []
        if len(clips) == 1:
            graph.append(f"[0:v]fps={fps},format=yuv420p[bg]")
        else:
            previous = "[0:v]"
            offset = 0.0
            for index in range(1, len(clips)):
                offset += clip_duration - overlap
                transition = _transition_for(seed, index)
                label = f"[x{index}]" if index < len(clips) - 1 else "[bg]"
                graph.append(
                    f"{previous}[{index}:v]xfade=transition={transition}:duration={overlap:.3f}:"
                    f"offset={offset:.3f}{label}"
                )
                previous = label if label != "[bg]" else "[bg]"

        # The film breathes: a slow exposure lift over every cut.
        graph.append(
            "[bg]eq=brightness='0.012*sin(6.2832*t/11)':saturation=1.03:eval=frame,"
            "ass=captions.ass,format=yuv420p[v]"
        )

        voice_index = len(clips)
        music_index = len(clips) + 1
        gain = float(self.cfg.get("music.gain", 0.12) or 0.12)
        fade_out = max(0.5, min(3.5, video_length * 0.06))
        # Clean the room out of the voice, then add air and hold it level.
        vox_chain = (
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            "highpass=f=74,"
            "equalizer=f=190:t=q:w=1.0:g=-2.0,"
            "equalizer=f=3100:t=q:w=1.3:g=2.4,"
            "acompressor=threshold=0.10:ratio=2.5:attack=8:release=170:makeup=1.3,"
            "loudnorm=I=-15.5:TP=-1.5:LRA=10"
        )
        if music_path and music_path.exists():
            graph.append(
                f"[{voice_index}:a]{vox_chain},apad=whole_dur={video_length:.3f}[vox]"
            )
            graph.append(
                f"[{music_index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={gain:.3f},afade=t=in:st=0:d=2.2,"
                f"afade=t=out:st={max(0.0, video_length - fade_out):.3f}:d={fade_out:.3f}[mus]"
            )
            graph.append("[vox]asplit=2[voxmix][voxsc]")
            graph.append(
                "[mus][voxsc]sidechaincompress=threshold=0.045:ratio=7:attack=18:release=420:makeup=1[duck]"
            )
            graph.append(
                "[voxmix][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                f"alimiter=limit=0.97,loudnorm=I=-14:TP=-1.5:LRA=11,apad=whole_dur={video_length:.3f},"
                "aresample=48000[a]"
            )
        else:
            graph.append(
                f"[{voice_index}:a]{vox_chain},apad=whole_dur={video_length:.3f},aresample=48000[a]"
            )

        args += [
            "-filter_complex",
            ";".join(graph),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{video_length:.3f}",
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "high",
            "-level",
            "4.2",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-metadata",
            f"title={title}",
            "-metadata",
            f"artist={self.cfg.get('studio.name', 'Ghostlight Studio')}",
            "-metadata",
            "comment=Generated by Ghostlight Studio. No footage, no faces, no repeats.",
            str(out_path),
        ]
        self._emit("Mixing voice and score.", kind="render")
        ffmpeg.run(args, cwd=captions.parent, timeout=7200)


# -- stills -----------------------------------------------------------------


def _font_path(serif: bool, bold: bool, fonts: Fonts) -> Path | None:
    windows = Path("C:/Windows/Fonts")
    mac = Path("/System/Library/Fonts/Supplemental")
    linux = Path("/usr/share/fonts/truetype")
    names = {
        (True, True): ["georgiab.ttf", "DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "NotoSerif-Bold.ttf"],
        (True, False): ["georgia.ttf", "DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "NotoSerif-Regular.ttf"],
        (False, True): ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf"],
        (False, False): ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf"],
    }[(serif, bold)]
    roots = [windows, mac, linux / "dejavu", linux / "liberation", linux / "noto"]
    for name in names:
        for root in roots:
            candidate = root / name
            if candidate.exists():
                return candidate
    return None


def _font(size: int, *, serif: bool = True, bold: bool = True, fonts: Fonts | None = None) -> ImageFont.ImageFont:
    fonts = fonts or resolve_fonts()
    path = _font_path(serif, bold, fonts)
    if path:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _shade(image: Image.Image, bg: tuple[int, int, int], top: float, bottom_alpha: float, exponent: float = 1.35) -> Image.Image:
    arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    height, width = arr.shape[:2]
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    ramp = np.clip((y - top) / max(1e-4, 1 - top), 0, 1) ** exponent * bottom_alpha
    ink = np.array(bg, dtype=np.float32) / 255.0
    arr = arr * (1 - ramp) + ink[None, None, :] * ramp
    top_ramp = np.clip((0.16 - y) / 0.16, 0, 1) ** 1.3 * 0.30
    arr = arr * (1 - top_ramp) + ink[None, None, :] * top_ramp
    return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGB")


def _tracked(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill: tuple, spacing: int) -> None:
    x, y = xy
    for character in text:
        draw.text((x, y), character, font=font, fill=fill)
        x += draw.textlength(character, font=font) + spacing


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, limit: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= limit or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_title(draw: ImageDraw.ImageDraw, title: str, size: int, limit: int, max_lines: int, fonts: Fonts) -> tuple[ImageFont.ImageFont, list[str]]:
    while size > 26:
        font = _font(size, fonts=fonts)
        lines = _wrap(draw, title, font, limit)
        if len(lines) <= max_lines and all(draw.textlength(line, font=font) <= limit for line in lines):
            return font, lines
        size -= 4
    font = _font(26, fonts=fonts)
    return font, _wrap(draw, title, font, limit)


def make_poster(
    scene_path: str | Path,
    out_path: str | Path,
    *,
    title: str,
    kicker: str,
    palette_name: str,
    width: int,
    height: int,
    short: bool,
    fonts: Fonts | None = None,
    brand: str = "",
    tagline: str = "",
) -> Path:
    fonts = fonts or resolve_fonts()
    palette = PALETTES.get(palette_name, PALETTES["cosmic_indigo"])
    art = Image.open(scene_path).convert("RGB")
    image = ImageOps.fit(art, (width, height), Image.Resampling.LANCZOS)
    image = _shade(image, palette["bg"], 0.30 if short else 0.22, 0.86)
    draw = ImageDraw.Draw(image)
    margin = int(width * 0.075)
    accent = palette["glow"]
    cream = palette["paper"]

    word_font = _font(int(width * 0.021), serif=False, bold=True, fonts=fonts)
    wordmark = str(brand or "Ghostlight Studio").upper()
    _tracked(draw, (margin, int(height * 0.052)), wordmark, word_font, cream, max(2, int(width * 0.0035)))

    if kicker:
        kick_font = _font(int(width * 0.026), serif=False, bold=True, fonts=fonts)
        ky = int(height * (0.585 if short else 0.52))
        _tracked(draw, (margin, ky), kicker.upper(), kick_font, accent, max(2, int(width * 0.003)))

    limit = width - margin * 2
    title_font, lines = _fit_title(draw, title, int(width * 0.082 if short else width * 0.062), limit, 4, fonts)
    line_height = int(title_font.size * 1.16)
    total = line_height * len(lines)
    start_y = int(height * (0.66 if short else 0.62))
    if start_y + total > height - int(height * 0.10):
        start_y = height - int(height * 0.10) - total
    rule_y = start_y - int(line_height * 0.52)
    draw.line((margin, rule_y, margin + int(width * 0.11), rule_y), fill=accent, width=max(2, width // 400))
    for index, line in enumerate(lines):
        y = start_y + index * line_height
        draw.text((margin + 2, y + 3), line, font=title_font, fill=(0, 0, 0))
        draw.text((margin, y), line, font=title_font, fill=cream)

    tag_font = _font(int(width * 0.021), serif=True, bold=False, fonts=fonts)
    tag = str(tagline or "one strange idea at a time")
    tag_width = draw.textlength(tag, font=tag_font)
    draw.text((margin, height - int(height * 0.055)), tag, font=tag_font, fill=tuple(int(c * 0.82) for c in cream))
    draw.text((width - margin - tag_width, height - int(height * 0.055)), "AUTONOMOUS EDITION", font=_font(int(width * 0.016), serif=False, bold=True, fonts=fonts), fill=accent)

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=92, optimize=True)
    return path


def _zoom_crop(image: Image.Image, factor: float) -> Image.Image:
    width, height = image.size
    crop_w, crop_h = int(width / factor), int(height / factor)
    left = (width - crop_w) // 2
    top = int((height - crop_h) * 0.42)
    return image.crop((left, top, left + crop_w, top + crop_h)).resize(
        (width, height), Image.Resampling.LANCZOS
    )


def _band_contrast(image: Image.Image, top: float, bottom: float) -> float:
    arr = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
    band = arr[int(arr.shape[0] * top):int(arr.shape[0] * bottom)]
    return float(band.std()) if band.size else 0.0


def _centered_y(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.ImageFont, width: int) -> int:
    widest = max((draw.textlength(line, font=font) for line in lines), default=0)
    return int((width - widest) / 2)


def make_thumbnail_variants(
    scene_paths: list[str | Path],
    out_dir: str | Path,
    *,
    title: str,
    kicker: str,
    palette_name: str,
    fonts: Fonts | None = None,
    brand: str = "",
) -> list[dict[str, object]]:
    """Three thumbnail treatments with a measured recommendation."""
    fonts = fonts or resolve_fonts()
    palette = PALETTES.get(palette_name, PALETTES["cosmic_indigo"])
    width, height = 1280, 720
    accent = palette["glow"]
    cream = palette["paper"]
    margin = 62
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = [Path(p) for p in scene_paths if Path(p).is_file()]
    if not sources:
        raise ValueError("thumbnail variants need at least one scene plate")

    def plate(index: int) -> Image.Image:
        art = Image.open(sources[index % len(sources)]).convert("RGB")
        return ImageOps.fit(art, (width, height), Image.Resampling.LANCZOS)

    variants: list[dict[str, object]] = []

    # 1. hero — the house layout
    image = _shade(plate(0), palette["bg"], 0.18, 0.90, exponent=1.5)
    draw = ImageDraw.Draw(image)
    _tracked(draw, (margin, 46), str(brand or "Ghostlight Studio").upper(),
             _font(24, serif=False, bold=True, fonts=fonts), cream, 3)
    if kicker:
        _tracked(draw, (margin, 392), kicker.upper(),
                 _font(26, serif=False, bold=True, fonts=fonts), accent, 3)
    title_font, lines = _fit_title(draw, title, 68, width - margin * 2 - 40, 3, fonts)
    line_height = int(title_font.size * 1.12)
    start_y = height - margin - line_height * len(lines)
    draw.line((margin, start_y - 32, margin + 120, start_y - 32), fill=accent, width=3)
    for index, line in enumerate(lines):
        y = start_y + index * line_height
        draw.text((margin + 2, y + 3), line, font=title_font, fill=(0, 0, 0))
        draw.text((margin, y), line, font=title_font, fill=cream)
    hero_path = out_dir / "hero.jpg"
    image.save(hero_path, "JPEG", quality=90, optimize=True)
    variants.append({
        "id": "hero",
        "label": "Hero plate",
        "path": str(hero_path),
        "rationale": "Full plate, brand top-left, headline in the lower third.",
        "contrast": round(_band_contrast(image, 0.55, 0.94), 3),
    })

    # 2. close-up — tighter crop, larger lettering
    image = _shade(_zoom_crop(plate(1), 1.38), palette["bg"], 0.04, 0.96, exponent=1.15)
    draw = ImageDraw.Draw(image)
    _tracked(draw, (margin, 44), str(brand or "Ghostlight Studio").upper(),
             _font(22, serif=False, bold=True, fonts=fonts), cream, 3)
    title_font, lines = _fit_title(draw, title, 86, width - margin * 2 - 20, 3, fonts)
    line_height = int(title_font.size * 1.06)
    start_y = height - 74 - line_height * len(lines)
    if kicker:
        _tracked(draw, (margin, start_y - 48), kicker.upper(),
                 _font(24, serif=False, bold=True, fonts=fonts), accent, 3)
    for index, line in enumerate(lines):
        y = start_y + index * line_height
        draw.text((margin + 3, y + 4), line, font=title_font, fill=(0, 0, 0))
        draw.text((margin, y), line, font=title_font, fill=cream)
    close_path = out_dir / "close.jpg"
    image.save(close_path, "JPEG", quality=90, optimize=True)
    variants.append({
        "id": "close",
        "label": "Close-up",
        "path": str(close_path),
        "rationale": "Crop pulled in 38%, heavier title — built for a busy feed.",
        "contrast": round(_band_contrast(image, 0.50, 0.96), 3),
    })

    # 3. quiet — centred, low-contrast, editorial
    image = _shade(plate(2), palette["bg"], 0.02, 0.86, exponent=1.0)
    draw = ImageDraw.Draw(image)
    if kicker:
        _tracked(draw, (margin, 58), kicker.upper(),
                 _font(24, serif=False, bold=True, fonts=fonts), accent, 3)
    title_font, lines = _fit_title(draw, title, 60, width - margin * 2 - 120, 3, fonts)
    line_height = int(title_font.size * 1.14)
    block_top = (height - line_height * len(lines)) // 2
    left = _centered_y(draw, lines, title_font, width)
    rule_w = int(width * 0.08)
    draw.line((width // 2 - rule_w, block_top - 46, width // 2 + rule_w, block_top - 46),
              fill=accent, width=3)
    for index, line in enumerate(lines):
        y = block_top + index * line_height
        draw.text((left + 2, y + 3), line, font=title_font, fill=(0, 0, 0))
        draw.text((left, y), line, font=title_font, fill=cream)
    _tracked(draw, (width // 2 - 96, height - 74), str(brand or "Ghostlight Studio").upper(),
             _font(18, serif=False, bold=True, fonts=fonts), cream, 3)
    quiet_path = out_dir / "quiet.jpg"
    image.save(quiet_path, "JPEG", quality=90, optimize=True)
    variants.append({
        "id": "quiet",
        "label": "Quiet frame",
        "path": str(quiet_path),
        "rationale": "Centred headline on a dark plate — the essayist's choice.",
        "contrast": round(_band_contrast(image, 0.32, 0.76), 3),
    })

    best = max(variants, key=lambda item: (float(item["contrast"]), item["id"] == "hero"))
    for variant in variants:
        variant["recommended"] = variant["id"] == best["id"]
    return variants
