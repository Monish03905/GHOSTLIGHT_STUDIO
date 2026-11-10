from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .content import PALETTES

MOTIONS = [
    ("in", "center"),
    ("out", "center"),
    ("in", "up"),
    ("out", "down"),
    ("in", "left"),
    ("out", "right"),
]


@dataclass
class Scene:
    path: Path
    motion: str
    direction: str
    mid: Path | None = None
    atmosphere: Path | None = None
    sweep: Path | None = None
    drift: float = 0.0


def _rgb(palette: dict[str, tuple[int, int, int]], key: str) -> np.ndarray:
    return np.array(palette[key], dtype=np.float32) / 255.0


def _fbm(h: int, w: int, rng: np.random.Generator, octaves: int = 5, base: int = 4, persistence: float = 0.55) -> np.ndarray:
    total = np.zeros((h, w), dtype=np.float32)
    amplitude = 1.0
    norm = 0.0
    for octave in range(octaves):
        gh = max(2, base * (2**octave))
        gw = max(2, int(gh * w / max(1, h)))
        grid = rng.random((gh, gw)).astype(np.float32)
        resized = Image.fromarray((grid * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        total += np.asarray(resized, dtype=np.float32) / 255.0 * amplitude
        norm += amplitude
        amplitude *= persistence
    total /= max(norm, 1e-6)
    low, high = float(total.min()), float(total.max())
    return (total - low) / (high - low + 1e-6)


def _colorize(field: np.ndarray, stops: list[tuple[float, np.ndarray]]) -> np.ndarray:
    positions = np.array([s[0] for s in stops], dtype=np.float32)
    out = np.zeros((*field.shape, 3), dtype=np.float32)
    for channel in range(3):
        values = np.array([s[1][channel] for s in stops], dtype=np.float32)
        out[..., channel] = np.interp(field, positions, values)
    return out


def _screen(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    return 1.0 - (1.0 - np.clip(base, 0, 1)) * (1.0 - np.clip(layer, 0, 1))


def _glow(arr: np.ndarray, mask: np.ndarray, color: np.ndarray, radius: float, strength: float) -> np.ndarray:
    alpha = np.clip(mask * strength, 0, 1)
    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius))
    blurred = np.asarray(alpha_img, dtype=np.float32)[..., None] / 255.0
    return _screen(arr, color[None, None, :] * blurred)


def _stars(arr: np.ndarray, rng: np.random.Generator, count: int, top: float = 0.8, strength: float = 1.0) -> np.ndarray:
    h, w = arr.shape[:2]
    overlay = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for _ in range(count):
        x = rng.uniform(0, w)
        y = rng.uniform(0, h * top)
        radius = rng.choice([0.7, 0.9, 1.0, 1.3, 2.0])
        value = int(rng.uniform(90, 255))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(value, value, min(255, value + 10)))
    core = np.asarray(overlay, dtype=np.float32) / 255.0 * 0.75 * strength
    bloom = np.asarray(overlay.filter(ImageFilter.GaussianBlur(4)), dtype=np.float32) / 255.0 * 0.35 * strength
    return _screen(_screen(arr, bloom), core)


def _particles(
    arr: np.ndarray,
    rng: np.random.Generator,
    count: int,
    color: np.ndarray,
    top: float = 1.0,
    strength: float = 0.6,
    size: tuple[float, float] = (0.8, 2.6),
) -> np.ndarray:
    h, w = arr.shape[:2]
    overlay = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    tint = tuple(int(c * 255) for c in color)
    for _ in range(count):
        x = rng.uniform(0, w)
        y = rng.uniform(0, h * top)
        radius = rng.uniform(*size)
        value = rng.uniform(0.35, 1.0)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=tuple(int(v * value) for v in tint))
    core = np.asarray(overlay, dtype=np.float32) / 255.0
    bloom = np.asarray(overlay.filter(ImageFilter.GaussianBlur(6)), dtype=np.float32) / 255.0
    return _screen(arr, (core + bloom * 0.7) * strength)


def _vignette(arr: np.ndarray, strength: float = 0.55) -> np.ndarray:
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2.0, h / 2.0
    radius = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / math.sqrt(2)
    mask = np.clip(1.0 - strength * radius**2.4, 0.0, 1.0)
    return arr * mask[..., None]


def _grain(arr: np.ndarray, rng: np.random.Generator, amount: float = 0.018) -> np.ndarray:
    if amount <= 0:
        return arr
    # Film grain belongs in the midtones. Scaling by luminance keeps flat
    # shadows and night skies from turning into digital speckle at 1:1.
    luma = arr.mean(axis=2, keepdims=True)
    weight = np.clip(luma * 3.2, 0.0, 1.0) * np.clip((1.0 - luma) * 5.0, 0.0, 1.0)
    noise = rng.normal(0, amount, size=arr.shape[:2]).astype(np.float32)
    return np.clip(arr + noise[..., None] * weight, 0, 1)


def _shade(arr: np.ndarray, color: np.ndarray, start: float, strength: float, title_band: bool = False) -> np.ndarray:
    height = arr.shape[0]
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    ramp = np.clip((y - start) / max(1e-4, 1 - start), 0, 1) ** 1.3 * strength
    top = np.clip((0.16 - y) / 0.16, 0, 1) ** 1.4 * 0.34
    if title_band:
        top = top + np.exp(-(((y - 0.30) / 0.13) ** 2)) * 0.20
    alpha = np.clip(ramp + top, 0, 0.92)
    return arr * (1 - alpha) + color[None, None, :] * alpha


def _finish(
    arr: np.ndarray,
    rng: np.random.Generator,
    vignette: bool,
    grain_amount: float = 0.018,
    contrast: float = 1.02,
    shade_color: np.ndarray | None = None,
    shade_start: float = 0.56,
    shade_strength: float = 0.0,
    title_band: bool = False,
) -> Image.Image:
    if vignette:
        arr = _vignette(arr)
    if shade_color is not None and shade_strength > 0:
        arr = _shade(arr, shade_color, shade_start, shade_strength, title_band=title_band)
    arr = _grain(arr, rng, grain_amount)
    arr = np.clip((arr - 0.5) * contrast + 0.5, 0, 1)
    return Image.fromarray((arr * 255).astype(np.uint8), "RGB")


def _base(h: int, w: int, top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    return top[None, None, :] * (1 - y) + bottom[None, None, :] * y + np.zeros((1, w, 1), dtype=np.float32)


# -- styles -------------------------------------------------------------
def _aurora(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> np.ndarray:
    bg, mid = _rgb(palette, "bg"), _rgb(palette, "mid")
    glow, accent = _rgb(palette, "glow"), _rgb(palette, "accent")
    field = _fbm(h, w, rng, octaves=6, base=4, persistence=0.58)
    warp = _fbm(h, w, rng, octaves=4, base=6)
    field = np.clip(field * 0.72 + warp * 0.38, 0, 1) ** 1.25
    arr = _colorize(field, [(0.0, bg), (0.42, mid), (0.72, accent), (0.9, glow), (1.0, glow)])
    mask = np.clip((field - 0.58) * 3.8, 0, 1) ** 2
    arr = _glow(arr, mask, glow, max(6, min(h, w) * 0.035), 0.9)
    arr = _glow(arr, (1 - field) ** 3, accent, max(8, min(h, w) * 0.06), 0.25)
    # a diagonal band of light
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    band = np.exp(-(((xx / w) * 0.7 + (yy / h) * 0.3 - 0.55) ** 2) / 0.02)
    arr = _glow(arr, band * field, glow, max(10, min(h, w) * 0.07), 0.22)
    arr = _stars(arr, rng, count=max(140, (h * w) // 5500), top=0.92, strength=0.9)
    arr = _particles(arr, rng, max(18, (h * w) // 70000), glow, top=0.95, strength=0.35, size=(1.0, 3.4))
    return arr


def _tide(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> np.ndarray:
    bg, mid = _rgb(palette, "bg"), _rgb(palette, "mid")
    glow, accent = _rgb(palette, "glow"), _rgb(palette, "accent")
    warp = _fbm(h, w, rng, octaves=5, base=5)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / w, yy / h
    caustic = 0.5 + 0.5 * np.sin((u * 7.0 + warp * 5.0) * math.tau) * np.cos((v * 5.5 - warp * 4.0) * math.tau)
    caustic = caustic**2.2
    depth = np.clip(v * 1.15, 0, 1)
    field = np.clip(caustic * (1.0 - depth * 0.72) + (1 - depth) * 0.12, 0, 1)
    arr = _colorize(field, [(0.0, bg), (0.35, mid), (0.72, accent), (1.0, glow)])
    arr *= (1.0 - depth[..., None] * 0.35)
    arr = _glow(arr, (caustic**3) * (1 - depth), glow, max(5, min(h, w) * 0.02), 0.45)
    arr = _particles(arr, rng, max(40, (h * w) // 30000), glow, top=0.9, strength=0.5, size=(0.8, 2.2))
    for _ in range(3):
        y = rng.uniform(0.25, 0.8) * h
        band = np.exp(-((yy - y) ** 2) / (2 * (h * 0.03) ** 2))
        arr = _screen(arr, accent[None, None, :] * band[..., None] * 0.08)
    arr = _particles(arr, rng, 30, accent, top=1.0, strength=0.25, size=(1.2, 4.0))
    return arr


def _ember(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> np.ndarray:
    bg, mid = _rgb(palette, "bg"), _rgb(palette, "mid")
    glow, accent = _rgb(palette, "glow"), _rgb(palette, "accent")
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / w, yy / h
    sky = bg[None, None, :] * (1 - v[..., None]) + mid[None, None, :] * v[..., None]
    field = _fbm(h, w, rng, octaves=5, base=5)
    sky += field[..., None] * accent[None, None, :] * 0.16
    arr = sky
    horizon = 0.63
    unit = min(w, h)
    du, dv = (xx - 0.52 * w) / unit, (yy - horizon * h) / unit
    r2 = du**2 + dv**2
    sun = np.exp(-r2 / 0.008)
    arr = _glow(arr, sun, glow, max(10, min(h, w) * 0.05), 1.0)
    disc = r2 < 0.0012
    arr = _screen(arr, disc[..., None] * np.array([1.0, 0.86, 0.62], dtype=np.float32)[None, None, :] * 0.9)
    haze = np.clip(1.6 - ((v - horizon) * 6) ** 2, 0, 1)
    arr = _screen(arr, glow[None, None, :] * (haze * 0.14)[..., None])
    for layer in range(3):
        top = horizon + 0.04 + layer * 0.075
        amp = h * (0.035 + layer * 0.012)
        line = _ridge(w, h * top, amp, rng, smooth=11 + layer * 6)
        mask = (yy > line[None, :]).astype(np.float32)
        shade = bg * (0.45 + layer * 0.1)
        arr = arr * (1 - mask[..., None]) + shade[None, None, :] * mask[..., None]
    arr = _particles(arr, rng, max(80, (h * w) // 14000), glow, top=0.9, strength=0.5, size=(0.7, 2.4))
    arr = _stars(arr, rng, 60, top=0.45, strength=0.45)
    return arr


def _ridge(w: int, base: float, amplitude: float, rng: np.random.Generator, smooth: int = 10) -> np.ndarray:
    # layered sines read as weathered hills rather than sawtooth peaks
    x = np.linspace(0, 1, w, dtype=np.float32)
    line = np.zeros(w, dtype=np.float32)
    octaves = 5 if smooth < 14 else 7
    for k in range(1, octaves + 1):
        frequency = k * rng.uniform(0.8, 1.5)
        phase = rng.uniform(0, math.tau)
        line += np.sin(math.tau * frequency * x + phase) / (k**1.3)
    line += 0.7 * np.sin(math.tau * rng.uniform(0.18, 0.4) * x + rng.uniform(0, math.tau))
    low, high = float(line.min()), float(line.max())
    norm = (line - low) / max(1e-6, high - low)
    return np.array(base - amplitude * (0.12 + 0.88 * norm), dtype=np.float32)


def _ink(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> np.ndarray:
    paper = _rgb(palette, "paper")
    ink = _rgb(palette, "bg")
    accent = _rgb(palette, "glow")
    base = np.ones((h, w, 3), dtype=np.float32) * paper[None, None, :]
    fiber = _fbm(h, w, rng, octaves=3, base=3) - 0.5
    base += fiber[..., None] * 0.05
    image = Image.fromarray((np.clip(base, 0, 1) * 255).astype(np.uint8), "RGB").convert("RGBA")

    stroke_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stroke_layer)
    small_h, small_w = max(8, h // 14), max(8, w // 14)
    angles = _fbm(small_h, small_w, rng, octaves=4, base=3) * math.tau * 2.0
    step = max(4.0, min(w, h) / 260)
    ink_color = tuple(int(c * 255) for c in ink)
    accent_color = tuple(int(c * 255) for c in accent)
    for stroke in range(760):
        x = rng.uniform(-0.05, 1.05) * w
        y = rng.uniform(-0.05, 1.05) * h
        accent_stroke = rng.random() < 0.07
        width = 1 if rng.random() < 0.68 else (2 if rng.random() < 0.8 else 3)
        alpha = int(rng.uniform(34, 96)) if not accent_stroke else int(rng.uniform(30, 72))
        color = accent_color + (alpha,) if accent_stroke else ink_color + (alpha,)
        points = [(x, y)]
        for _ in range(rng.integers(50, 120)):
            ix = int(np.clip(x / w * (small_w - 1), 0, small_w - 1))
            iy = int(np.clip(y / h * (small_h - 1), 0, small_h - 1))
            angle = float(angles[iy, ix]) + (stroke % 7) * 0.1
            x += math.cos(angle) * step
            y += math.sin(angle) * step
            points.append((x, y))
            if x < -w * 0.1 or x > w * 1.1 or y < -h * 0.1 or y > h * 1.1:
                break
        draw.line(points, fill=color, width=width, joint="curve")
    image = Image.alpha_composite(image, stroke_layer)

    bloom_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bloom_layer)
    for _ in range(5):
        cx = rng.uniform(0.02, 0.98) * w
        cy = rng.uniform(0.02, 0.98) * h
        rx = rng.uniform(0.07, 0.24) * w
        ry = rx * rng.uniform(0.55, 1.5)
        bdraw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=ink_color + (int(rng.uniform(48, 92)),))
    bloom_layer = bloom_layer.filter(ImageFilter.GaussianBlur(max(14, min(w, h) * 0.035)))
    image = Image.alpha_composite(image, bloom_layer)

    ring = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(ring)
    cx, cy = rng.uniform(0.35, 0.65) * w, rng.uniform(0.3, 0.5) * h
    radius = rng.uniform(0.16, 0.3) * min(w, h)
    for i in range(3):
        r = radius * (1 + i * 0.1)
        rdraw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink_color + (44 - i * 10,), width=2 + i)
    ring = ring.filter(ImageFilter.GaussianBlur(1.4))
    image = Image.alpha_composite(image, ring)
    arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return arr


def _neon(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> np.ndarray:
    bg, mid = _rgb(palette, "bg"), _rgb(palette, "mid")
    glow, accent = _rgb(palette, "glow"), _rgb(palette, "accent")
    arr = _base(h, w, bg * 0.8, mid * 0.75)
    field = _fbm(h, w, rng, octaves=4, base=5)
    arr += field[..., None] * accent[None, None, :] * 0.05

    rings = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(rings)
    cx, cy = rng.uniform(0.15, 0.85) * w, rng.uniform(0.28, 0.62) * h
    base_r = rng.uniform(0.12, 0.3) * min(w, h)
    tint = tuple(min(255, int(c * 255 * 1.28 + 14)) for c in accent)
    glow_tint = tuple(min(255, int(c * 255 * 1.16 + 10)) for c in glow)
    for i in range(rng.integers(4, 8)):
        radius = base_r * (1 + i * rng.uniform(0.12, 0.22))
        width = rng.choice([1, 2, 3, 5])
        color = tint if i % 2 == 0 else glow_tint
        draw.ellipse((cx - radius, cy - radius * 0.72, cx + radius, cy + radius * 0.72), outline=color, width=int(width))
    halo = np.asarray(rings.filter(ImageFilter.GaussianBlur(max(8, min(w, h) * 0.02))), dtype=np.float32) / 255.0
    core = np.asarray(rings, dtype=np.float32) / 255.0
    arr = _screen(arr, halo * 0.75)
    arr = _screen(arr, core * 0.55)

    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid)
    horizon = int(h * 0.62)
    vanish = (w // 2, horizon)
    grid_color = tint + (30,)
    for i in range(-12, 13):
        x_bottom = int(w / 2 + i * w / 10)
        gdraw.line([vanish, (x_bottom, h)], fill=grid_color, width=1)
    for i in range(1, 12):
        y = horizon + int((h - horizon) * (i / 12) ** 2.2)
        gdraw.line([(0, y), (w, y)], fill=grid_color, width=1)
    arr = _screen(arr, np.asarray(grid.convert("RGB"), dtype=np.float32) / 255.0 * 0.55)

    yy = np.arange(h)[:, None]
    scan = np.ones((h, 1, 1), dtype=np.float32)
    scan[(yy[:, 0] % 3) == 0] = 0.9
    arr *= scan
    arr = _stars(arr, rng, max(80, (h * w) // 9000), top=0.62, strength=0.55)
    arr = _particles(arr, rng, max(12, (h * w) // 90000), glow, top=0.7, strength=0.4, size=(0.8, 2.6))
    return arr


def _paper(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> np.ndarray:
    paper = _rgb(palette, "paper")
    ink = _rgb(palette, "bg")
    accent = _rgb(palette, "glow")
    arr = np.ones((h, w, 3), dtype=np.float32) * paper[None, None, :]
    texture = _fbm(h, w, rng, octaves=4, base=4) - 0.5
    fine = rng.normal(0, 0.012, size=(h, w)).astype(np.float32)
    arr += (texture * 0.045 + fine)[..., None]
    field = _fbm(h, w, rng, octaves=5, base=3, persistence=0.6)
    for level in np.arange(0.28, 0.78, 0.055):
        mask = np.abs(field - level) < 0.0035
        if not mask.any():
            continue
        mask_img = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
        blend = np.asarray(mask_img, dtype=np.float32)[..., None] / 255.0
        arr = arr * (1 - blend * 0.5) + ink[None, None, :] * (blend * 0.5)
    # warm accent contour
    mask = np.abs(field - 0.52) < 0.0024
    mask_img = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0))
    blend = np.asarray(mask_img, dtype=np.float32)[..., None] / 255.0
    arr = arr * (1 - blend * 0.35) + accent[None, None, :] * (blend * 0.35)

    wash = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    wdraw = ImageDraw.Draw(wash)
    for _ in range(2):
        cx = rng.uniform(0, 1) * w
        cy = rng.uniform(0, 1) * h
        rx = rng.uniform(0.12, 0.3) * w
        ry = rng.uniform(0.09, 0.24) * h
        wdraw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=tuple(int(c * 255) for c in ink) + (26,))
    wash = wash.filter(ImageFilter.GaussianBlur(max(24, min(w, h) * 0.06)))
    arr = np.asarray(Image.alpha_composite(Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGB").convert("RGBA"), wash).convert("RGB"), dtype=np.float32) / 255.0

    marks = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mdraw = ImageDraw.Draw(marks)
    line_color = tuple(int(c * 255) for c in ink) + (80,)
    inset = int(min(w, h) * 0.055)
    mdraw.rectangle((inset, inset, w - inset, h - inset), outline=line_color, width=2)
    mdraw.rectangle((inset + 9, inset + 9, w - inset - 9, h - inset - 9), outline=tuple(int(c * 255) for c in accent) + (60,), width=1)
    cx, cy = rng.uniform(0.3, 0.7) * w, rng.uniform(0.25, 0.45) * h
    radius = min(w, h) * 0.035
    mdraw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=line_color, width=2)
    mdraw.line((cx - radius * 1.6, cy, cx + radius * 1.6, cy), fill=line_color, width=1)
    arr = np.asarray(Image.alpha_composite(Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGB").convert("RGBA"), marks).convert("RGB"), dtype=np.float32) / 255.0
    return arr


def _dusk(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> np.ndarray:
    bg, mid = _rgb(palette, "bg"), _rgb(palette, "mid")
    glow, accent = _rgb(palette, "glow"), _rgb(palette, "accent")
    paper = _rgb(palette, "paper")
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / w, yy / h
    sky = bg[None, None, :] * (1 - v[..., None]) + mid[None, None, :] * np.clip(v * 1.5, 0, 1)[..., None]
    horizon = 0.58
    warm = np.exp(-((v - horizon) ** 2) / 0.025)
    sky += glow[None, None, :] * warm[..., None] * 0.42
    arr = sky
    arr = _stars(arr, rng, max(60, (h * w) // 14000), top=0.55, strength=0.55)
    sx, sy = rng.uniform(0.28, 0.72), horizon - 0.06
    unit = min(w, h)
    du, dv = (xx - sx * w) / unit, (yy - sy * h) / unit
    r2 = du**2 + dv**2
    sun_mask = np.exp(-r2 / 0.006)
    arr = _glow(arr, sun_mask, glow, max(8, min(h, w) * 0.04), 0.8)
    disc = r2 < 0.0011
    arr = _screen(arr, disc[..., None] * paper[None, None, :] * 0.85)
    for layer in range(3):
        top = horizon + 0.02 + layer * 0.085
        line = _ridge(w, h * top, h * (0.03 + 0.015 * layer), rng, smooth=13 + layer * 7)
        mask = (yy > line[None, :]).astype(np.float32)
        shade = bg * (0.5 + layer * 0.08)
        arr = arr * (1 - mask[..., None] * 0.85) + shade[None, None, :] * (mask[..., None] * 0.85)
    haze = np.clip(1.4 - ((v - horizon - 0.03) * 8) ** 2, 0, 1)
    arr = _screen(arr, glow[None, None, :] * (haze * 0.08)[..., None])
    arr = _particles(arr, rng, max(15, (h * w) // 150000), glow, top=0.8, strength=0.35, size=(0.8, 2.2))
    return arr


PAINTERS = {
    "aurora": _aurora,
    "tide": _tide,
    "ember": _ember,
    "ink": _ink,
    "neon": _neon,
    "paper": _paper,
    "dusk": _dusk,
}


# -- parallax layers --------------------------------------------------------
def _rgba(color: np.ndarray, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = (int(np.clip(c, 0, 1) * 255) for c in color[:3])
    return (r, g, b, int(np.clip(alpha, 0, 255)))


def _fill_below(draw: ImageDraw.ImageDraw, w: int, h: int, line: np.ndarray, fill: tuple, bottom: float = 1.0) -> None:
    points = [(float(x), float(line[x])) for x in range(w)]
    points += [(w - 1, h * bottom), (0, h * bottom)]
    draw.polygon(points, fill=fill)


def _branch(draw: ImageDraw.ImageDraw, x: float, y: float, angle: float, length: float,
            width: float, depth: int, color: tuple, rng: np.random.Generator) -> None:
    if depth <= 0 or length < 3:
        return
    x2 = x + math.cos(angle) * length
    y2 = y + math.sin(angle) * length
    draw.line((x, y, x2, y2), fill=color, width=max(1, int(round(width))))
    children = 3 if depth > 3 else 2
    for i in range(children):
        spread = rng.uniform(0.35, 0.9) * (1 if i % 2 else -1)
        _branch(draw, x2, y2, angle + spread, length * rng.uniform(0.58, 0.74),
                width * 0.62, depth - 1, color, rng)


def _silhouette(style: str, h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> Image.Image:
    """A midground cut-out that parallax-slides against the painted plate."""
    ink = _rgb(palette, "bg")
    paper = _rgb(palette, "paper")
    accent = _rgb(palette, "glow")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    dark = np.clip(ink * 0.42, 0, 1)
    nearer = np.clip(ink * 0.26, 0, 1)

    if style == "aurora":
        for depth in range(2):
            line = _ridge(w, h * (0.76 + depth * 0.11), h * (0.075 + depth * 0.05), rng, smooth=12 + depth * 6)
            _fill_below(draw, w, h, line, _rgba(dark if depth == 0 else nearer, 255))
            if depth == 1:
                for _ in range(18):
                    x = rng.uniform(0.04, 0.96) * w
                    y = float(line[int(np.clip(x, 0, w - 1))]) - rng.uniform(0, 6)
                    glow = _rgba(np.clip(accent + paper, 0, 1), int(rng.uniform(70, 150)))
                    draw.ellipse((x - 1.6, y - 1.6, x + 1.6, y + 1.6), fill=glow)

    elif style == "tide":
        xx = np.arange(w, dtype=np.float32) / max(1, w - 1)
        for depth, base in enumerate((0.80, 0.89)):
            crest = h * base + h * (0.028 - depth * 0.010) * np.sin(xx * math.tau * (2.2 + depth) + rng.uniform(0, 6))
            crest += h * 0.012 * np.sin(xx * math.tau * (6.5 + depth) + rng.uniform(0, 6))
            _fill_below(draw, w, h, crest, _rgba(dark if depth == 0 else nearer, 250))
            for _ in range(26 if depth else 16):
                x = rng.uniform(0, w)
                y = float(crest[int(x)]) + rng.uniform(0, h * 0.02)
                draw.ellipse((x - 2, y - 1.4, x + 2, y + 1.4), fill=_rgba(paper, int(rng.uniform(45, 105))))

    elif style == "ember":
        for depth in range(2):
            line = _ridge(w, h * (0.79 + depth * 0.10), h * (0.045 + depth * 0.03), rng, smooth=9 + depth * 5)
            _fill_below(draw, w, h, line, _rgba(dark if depth == 0 else nearer, 255))
            if depth == 1:
                for _ in range(12):
                    x = rng.uniform(0, w)
                    y = float(line[int(x)]) - rng.uniform(2, 10)
                    draw.line((x, y, x + rng.uniform(-2, 2), y - rng.uniform(4, 12)), fill=_rgba(accent, int(rng.uniform(90, 180))), width=1)

    elif style == "neon":
        # far skyline, then a near skyline with lit windows
        for depth, base_frac, alpha in ((0, 0.80, 120), (1, 0.90, 255)):
            x = -rng.uniform(0, w * 0.1)
            while x < w:
                bw = rng.uniform(0.025, 0.07) * w
                bh = rng.uniform(0.05, 0.22) * h * (1.0 if depth else 0.7)
                top = h * base_frac - bh
                tone = _rgba(dark, alpha) if depth else _rgba(np.clip(dark + 0.03, 0, 1), alpha)
                draw.rectangle((x, top, x + bw, h), fill=tone)
                if depth:
                    draw.line((x, top, x + bw, top), fill=_rgba(accent, int(rng.uniform(30, 55))), width=1)
                    steps_x = max(1, int(bw / (w * 0.008)))
                    steps_y = max(1, int(bh / (h * 0.014)))
                    for gx in range(steps_x):
                        for gy in range(steps_y):
                            if rng.random() > 0.30:
                                continue
                            wx = x + (gx + 0.35) * (bw / steps_x)
                            wy = top + (gy + 0.3) * (bh / steps_y)
                            lit = paper if rng.random() < 0.22 else accent
                            draw.rectangle((wx, wy, wx + w * 0.0018, wy + h * 0.0026),
                                           fill=_rgba(lit, int(rng.uniform(55, 135))))
                x += bw + rng.uniform(0.002, 0.014) * w

    elif style == "ink":
        inkc = _rgba(ink, 215)
        for _ in range(3):
            cx, cy = rng.uniform(-0.1, 0.35) * w, rng.uniform(0.65, 1.05) * h
            radius = rng.uniform(0.35, 0.7) * w
            start = rng.uniform(-0.4, 0.6)
            points = []
            for i in range(60):
                a = start + i / 59 * rng.uniform(0.7, 1.3)
                points.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
            draw.line(points, fill=inkc, width=int(rng.uniform(6, 20)), joint="curve")
            for _ in range(5):
                px, py = points[int(rng.uniform(0, len(points) - 1))]
                _branch(draw, px, py, rng.uniform(-2.6, -0.5), rng.uniform(0.03, 0.08) * min(w, h),
                        rng.uniform(2, 5), 3, inkc, rng)
        for _ in range(7):
            x, y = rng.uniform(0.1, 0.9) * w, rng.uniform(0.6, 0.95) * h
            r = rng.uniform(2, 7)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=_rgba(accent, 120))

    elif style == "paper":
        edge = []
        for x in range(w + 1):
            n = 0.5 + 0.5 * math.sin(x / w * math.tau * 3.1 + rng.uniform(0, 0.01))
            edge.append(h * 0.80 + h * 0.035 * n + rng.uniform(-h * 0.006, h * 0.006))
        points = [(float(x), float(edge[x])) for x in range(w)] + [(w - 1, h), (0, h)]
        draw.polygon(points, fill=_rgba(paper * 0.94, 255))
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.line([(x, edge[x] - 3) for x in range(w)], fill=_rgba(ink, 40), width=7)
        layer = Image.alpha_composite(layer, shadow.filter(ImageFilter.GaussianBlur(5)))
        draw = ImageDraw.Draw(layer)
        draw.line([(x, edge[x]) for x in range(w)], fill=_rgba(accent, 90), width=2)

    else:  # dusk
        line = _ridge(w, h * 0.82, h * 0.05, rng, smooth=15)
        _fill_below(draw, w, h, line, _rgba(nearer, 255))
        tx = rng.uniform(0.16, 0.84) * w
        ty = float(line[int(np.clip(tx, 0, w - 1))])
        tree = _rgba(dark, 255)
        _branch(draw, tx, ty + h * 0.01, -math.pi / 2 + rng.uniform(-0.16, 0.16),
                h * 0.11, max(2, int(w * 0.006)), 5, tree, rng)
        for _ in range(10):
            x = rng.uniform(0, w)
            y = float(line[int(x)]) - rng.uniform(0, 5)
            draw.ellipse((x - 1.4, y - 1.4, x + 1.4, y + 1.4), fill=_rgba(accent, int(rng.uniform(60, 130))))

    return layer


def _atmosphere(style: str, h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> Image.Image:
    """Foreground motes and bokeh that drift faster than everything behind them."""
    glow = _rgb(palette, "glow")
    paper = _rgb(palette, "paper")
    mid = _rgb(palette, "mid")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bokeh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(bokeh)
    unit = min(w, h)
    for _ in range(max(10, (w * h) // 90000)):
        x = rng.uniform(0, w)
        y = rng.uniform(0, h)
        radius = rng.uniform(0.006, 0.026) * unit
        color = glow if rng.random() < 0.62 else paper
        bdraw.ellipse((x - radius, y - radius, x + radius, y + radius),
                      fill=_rgba(color, int(rng.uniform(9, 30))))
    layer = Image.alpha_composite(layer, bokeh.filter(ImageFilter.GaussianBlur(max(2.0, unit * 0.006))))

    draw = ImageDraw.Draw(layer)
    for _ in range(max(24, (w * h) // 26000)):
        x = rng.uniform(0, w)
        y = rng.uniform(0, h)
        radius = rng.uniform(0.6, 2.2)
        color = glow if rng.random() < 0.7 else paper
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=_rgba(color, int(rng.uniform(40, 120))))

    if style in {"neon", "ink", "tide"}:
        for _ in range(max(6, (w * h) // 220000)):
            y = rng.uniform(0.1, 0.95) * h
            length = rng.uniform(0.06, 0.2) * w
            x = rng.uniform(0, w)
            color = glow if style == "neon" else mid
            draw.line((x, y, x + length, y + rng.uniform(-4, 4)),
                      fill=_rgba(color, int(rng.uniform(14, 36))), width=max(1, int(rng.uniform(1, 2.4))))
    if style == "ember":
        for _ in range(max(10, (w * h) // 80000)):
            x = rng.uniform(0, w)
            y = rng.uniform(0.3, 1.0) * h
            lift = rng.uniform(0.01, 0.04) * h
            draw.line((x, y, x + rng.uniform(-3, 3), y - lift),
                      fill=_rgba(glow, int(rng.uniform(50, 120))), width=1)
    return layer.filter(ImageFilter.GaussianBlur(0.8))


def _sweep(h: int, w: int, palette: dict[str, tuple[int, int, int]], rng: np.random.Generator) -> Image.Image:
    """A soft diagonal beam that travels across the frame during the clip."""
    sw = int(w * 2.2)
    paper = _rgb(palette, "paper")
    glow = _rgb(palette, "glow")
    tint = np.clip(paper * 0.7 + glow * 0.45 + 0.15, 0, 1)
    yy, xx = np.mgrid[0:h, 0:sw].astype(np.float32)
    axis = xx / sw * 0.94 + yy / h * 0.32
    center = rng.uniform(0.32, 0.62)
    alpha = np.exp(-((axis - center) ** 2) / (2 * 0.05**2)) * 0.08
    edge = np.clip(np.minimum(xx, sw - 1 - xx) / (sw * 0.05), 0, 1)
    rgba = np.dstack([np.ones_like(alpha) * tint[0], np.ones_like(alpha) * tint[1],
                      np.ones_like(alpha) * tint[2], alpha * edge])
    return Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), "RGBA")


def generate_scenes(
    style: str,
    palette_name: str,
    width: int,
    height: int,
    count: int,
    seed: int,
    out_dir: str | Path,
    art_scale: float = 1.25,
    grain: bool = True,
    vignette: bool = True,
    layers: bool = True,
) -> list[Scene]:
    style = style if style in PAINTERS else "aurora"
    palette = PALETTES.get(palette_name, PALETTES["cosmic_indigo"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    art_w = int(round(width * max(1.05, art_scale)))
    art_h = int(round(height * max(1.05, art_scale)))
    art_w += art_w % 2
    art_h += art_h % 2
    vertical = height > width
    bg = np.array(palette["bg"], dtype=np.float32) / 255.0
    scenes: list[Scene] = []
    layer_dims = {
        "mid": (int(round(width * 1.55)) + 1, int(round(height * 1.55)) + 1),
        "atmosphere": (int(round(width * 1.7)) + 1, int(round(height * 1.7)) + 1),
    }
    for index in range(count):
        rng = np.random.default_rng((seed + index * 104729) & 0xFFFFFFFF)
        arr = PAINTERS[style](art_h, art_w, palette, rng)
        contrast = 1.05 if style in {"neon", "ink"} else 1.02
        shade = 0.74 if vertical else 0.52
        if style in {"dusk", "ember"}:
            shade *= 0.80
        elif style in {"ink", "paper"}:
            shade *= 0.62
        image = _finish(
            arr,
            rng,
            vignette=vignette,
            grain_amount=0.013 if grain else 0.0,
            contrast=contrast,
            shade_color=bg,
            shade_start=0.54 if vertical else 0.63,
            shade_strength=shade,
            title_band=vertical and index == 0,
        )
        path = out_dir / f"scene_{index:02d}.png"
        image.save(path, "PNG")
        motion, direction = MOTIONS[(seed + index * 3) % len(MOTIONS)]
        scene = Scene(path=path, motion=motion, direction=direction)
        if layers:
            lrng = np.random.default_rng(((seed ^ 0x5EED) + index * 7919) & 0xFFFFFFFF)
            (lw, lh) = layer_dims["mid"]
            mid = _silhouette(style, lh, lw, palette, lrng)
            scene.mid = out_dir / f"scene_{index:02d}_mid.png"
            mid.save(scene.mid, "PNG")
            (aw, ah) = layer_dims["atmosphere"]
            atmosphere = _atmosphere(style, ah, aw, palette, lrng)
            scene.atmosphere = out_dir / f"scene_{index:02d}_air.png"
            atmosphere.save(scene.atmosphere, "PNG")
            if style in {"aurora", "neon", "tide", "paper"}:
                scene.sweep = out_dir / f"scene_{index:02d}_sweep.png"
                _sweep(height, width, palette, lrng).save(scene.sweep, "PNG")
            scene.drift = round(float(lrng.uniform(0, 1)), 4)
        scenes.append(scene)
    return scenes
