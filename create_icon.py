#!/usr/bin/env python3
"""Generate AutoKeyboard app icon (requires Pillow: pip install pillow)."""

from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Please install Pillow first:  pip install pillow")


# ── colour palette ──────────────────────────────────────────────────────────
BG_DARK   = (18,  42,  80, 255)   # deep navy
BG_LIGHT  = (28,  68, 130, 255)   # mid-blue  (gradient fake via polygon fill)
KEY_FACE  = (72, 190, 240, 255)   # sky-blue key face
KEY_SIDE  = (30, 110, 170, 255)   # key bevel / shadow
BOLT_FILL = (255, 210,  30, 255)  # gold lightning bolt
BOLT_GLOW = (255, 240, 120, 128)  # soft glow around bolt


def _round_rect(draw: ImageDraw.ImageDraw,
                bbox: tuple[float, float, float, float],
                radius: float,
                fill: tuple) -> None:
    """Draw a filled rounded rectangle."""
    x0, y0, x1, y1 = bbox
    r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.ellipse([x0, y0, x0 + 2 * r, y0 + 2 * r], fill=fill)
    draw.ellipse([x1 - 2 * r, y0, x1, y0 + 2 * r], fill=fill)
    draw.ellipse([x0, y1 - 2 * r, x0 + 2 * r, y1], fill=fill)
    draw.ellipse([x1 - 2 * r, y1 - 2 * r, x1, y1], fill=fill)


def _draw_keyboard_key(draw: ImageDraw.ImageDraw,
                       x0: float, y0: float,
                       x1: float, y1: float,
                       radius: float) -> None:
    """Draw a single keyboard key with a bevel effect."""
    _round_rect(draw, (x0, y0 + radius * 0.8, x1, y1 + radius * 0.8), radius, KEY_SIDE)
    _round_rect(draw, (x0, y0, x1, y1), radius, KEY_FACE)


def _lightning_bolt(cx: float, cy: float, size: float) -> list[tuple[int, int]]:
    """Return polygon points for a centred lightning bolt."""
    s = size
    pts = [
        (cx + s * 0.08,  cy - s * 0.52),
        (cx - s * 0.22,  cy + s * 0.04),
        (cx + s * 0.02,  cy + s * 0.04),
        (cx - s * 0.08,  cy + s * 0.52),
        (cx + s * 0.22,  cy - s * 0.04),
        (cx + s * 0.02,  cy - s * 0.04),
    ]
    return [(int(x), int(y)) for x, y in pts]


def create_icon_image(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    p = size * 0.06
    r_bg = size * 0.22

    # ── background: fake gradient with two layered rounded rects ───────────
    _round_rect(draw, (p, p, size - p, size - p), r_bg, BG_LIGHT)
    _round_rect(draw, (p, p, size - p, size * 0.60), r_bg, BG_DARK)

    # ── keyboard keys (3 rows, proportional to size) ──────────────────────
    rows: list[tuple[float, int]] = [
        (0.26, 7),   # top row
        (0.44, 6),   # middle row
        (0.62, 5),   # bottom row
    ]
    margin_x = size * 0.13
    key_h     = size * 0.11
    key_gap   = size * 0.025
    key_r     = size * 0.025

    for row_y_ratio, n_keys in rows:
        row_cy = size * row_y_ratio
        avail_w = (size - 2 * margin_x) - key_gap * (n_keys - 1)
        key_w   = avail_w / n_keys
        start_x = margin_x

        for i in range(n_keys):
            kx0 = start_x + i * (key_w + key_gap)
            kx1 = kx0 + key_w
            ky0 = row_cy - key_h / 2
            ky1 = row_cy + key_h / 2
            _draw_keyboard_key(draw, kx0, ky0, kx1, ky1, key_r)

    # ── lightning bolt (glow pass + solid fill) ────────────────────────────
    cx = size * 0.50
    cy = size * 0.72
    bolt_size = size * 0.28

    # glow (slightly larger, semi-transparent)
    glow_pts = _lightning_bolt(cx, cy, bolt_size * 1.25)
    draw.polygon(glow_pts, fill=BOLT_GLOW)

    # solid bolt
    bolt_pts = _lightning_bolt(cx, cy, bolt_size)
    draw.polygon(bolt_pts, fill=BOLT_FILL)

    return img


def main() -> None:
    assets_dir = Path(__file__).parent / "assets"
    assets_dir.mkdir(exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [create_icon_image(s) for s in sizes]

    ico_path = assets_dir / "icon.ico"
    images[0].save(
        str(ico_path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Created {ico_path}")

    png_path = assets_dir / "icon.png"
    images[-1].save(str(png_path))
    print(f"Created {png_path}")

    print("Done! Run PyInstaller after generating the icon.")


if __name__ == "__main__":
    main()
