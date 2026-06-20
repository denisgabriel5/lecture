"""Generate PWA icons. Run once at Docker build time."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "static" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

# Brand palette
BG = (100, 82, 219)      # indigo-violet
WHITE = (255, 255, 255)


def _draw_waveform(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    """Draw a minimal 5-bar audio waveform centred at (cx, cy)."""
    heights_frac = [0.30, 0.60, 1.00, 0.60, 0.30]
    n = len(heights_frac)
    bar_w = max(2, size // 18)
    gap = max(2, size // 24)
    total_w = n * bar_w + (n - 1) * gap
    x0 = cx - total_w // 2

    max_h = size * 0.45
    for i, frac in enumerate(heights_frac):
        bh = int(max_h * frac)
        x = x0 + i * (bar_w + gap)
        r = bar_w // 2
        draw.rounded_rectangle(
            [x, cy - bh // 2, x + bar_w, cy + bh // 2],
            radius=r,
            fill=WHITE,
        )


def make(size: int, name: str) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded square background (corner radius ~22 % like iOS)
    r = int(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    _draw_waveform(draw, size // 2, size // 2, size)

    # iOS requires opaque apple-touch-icon
    flat = Image.new("RGB", (size, size), BG)
    flat.paste(img, mask=img.split()[3])
    flat.save(OUT / name, "PNG")
    print(f"  wrote {OUT / name}")


if __name__ == "__main__":
    make(192, "icon-192.png")
    make(512, "icon-512.png")
    make(180, "apple-touch-icon.png")
    print("Icons generated.")
