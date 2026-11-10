"""Draw the PWA icons. Run: python scripts/make_icons.py"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

INK = (23, 21, 18)
CREAM = (242, 234, 216)
AMBER = (217, 164, 65)

ROOT = Path(__file__).resolve().parent.parent / "web" / "icons"


def flame(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float, colour: tuple[int, int, int]) -> None:
    draw.polygon(
        [
            (cx, cy - 150 * scale),
            (cx - 78 * scale, cy + 40 * scale),
            (cx + 78 * scale, cy + 40 * scale),
        ],
        fill=colour,
    )
    r = 92 * scale
    draw.ellipse((cx - r, cy + 40 * scale - r, cx + r, cy + 40 * scale + r), fill=colour)


def icon(size: int, *, maskable: bool = False) -> Image.Image:
    canvas = 1024
    image = Image.new("RGB", (canvas, canvas), INK)
    draw = ImageDraw.Draw(image)
    inset = 0.72 if maskable else 0.84
    ring = image.width * inset / 2
    cx = cy = canvas / 2
    draw.ellipse(
        (cx - ring, cy - ring, cx + ring, cy + ring),
        outline=CREAM,
        width=max(2, int(canvas * 0.006)),
    )
    scale = 0.86 if maskable else 1.0
    flame(draw, cx, cy - 10, scale, AMBER)
    inner = 52 * scale
    draw.ellipse(
        (cx - inner, cy + 66 * scale - inner, cx + inner, cy + 66 * scale + inner),
        fill=CREAM,
    )
    draw.ellipse(
        (cx - 320 * scale, cy - 330 * scale, cx + 320 * scale, cy + 330 * scale),
        outline=AMBER,
        width=max(1, int(canvas * 0.0025)),
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    icon(192).save(ROOT / "icon-192.png", "PNG", optimize=True)
    icon(512).save(ROOT / "icon-512.png", "PNG", optimize=True)
    icon(512, maskable=True).save(ROOT / "icon-maskable-512.png", "PNG", optimize=True)
    print(f"wrote {len(list(ROOT.glob('*.png')))} icons to {ROOT}")


if __name__ == "__main__":
    main()
