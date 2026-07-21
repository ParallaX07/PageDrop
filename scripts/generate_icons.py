"""Generate Windows .ico from logo.png.

Usage:
  uv run --with pillow python scripts/generate_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "src" / "pagedrop" / "assets" / "logo.png"
ICO_OUT = ROOT / "src" / "pagedrop" / "assets" / "app-icon.ico"

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _fit_square(src: Image.Image, size: int) -> Image.Image:
    """Contain logo in a transparent square canvas."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fitted = src.copy()
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    x = (size - fitted.width) // 2
    y = (size - fitted.height) // 2
    canvas.paste(fitted, (x, y), fitted)
    return canvas


def main() -> None:
    if not LOGO.is_file():
        raise SystemExit(f"Missing logo: {LOGO}")

    src = Image.open(LOGO).convert("RGBA")

    ico_images = [_fit_square(src, s) for s in ICO_SIZES]
    ICO_OUT.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes multi-size ICO from the largest; sizes= selects embedded sizes
    ico_images[-1].save(
        ICO_OUT,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=ico_images[:-1],
    )
    print(f"Wrote {ICO_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
