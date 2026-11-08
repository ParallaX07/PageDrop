"""Generate Windows .ico (or a single PNG) from logo.svg.

Usage:
  uv run python scripts/generate_icons.py
  uv run python scripts/generate_icons.py --png PATH   # one 256 px PNG, no Pillow
"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "src" / "pagedrop" / "assets" / "logo.svg"
ICO_OUT = ROOT / "src" / "pagedrop" / "assets" / "app-icon.ico"

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
PNG_SIZE = 256


def _render_png(size: int) -> bytes:
    """Render the SVG at an exact size and return PNG bytes."""
    renderer = QSvgRenderer(str(LOGO))
    if not renderer.isValid():
        raise SystemExit(f"Invalid logo: {LOGO}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--png", type=Path, help="write one 256 px PNG to this path and exit")
    args = parser.parse_args()

    if not LOGO.is_file():
        raise SystemExit(f"Missing logo: {LOGO}")

    if args.png is not None:
        args.png.parent.mkdir(parents=True, exist_ok=True)
        args.png.write_bytes(_render_png(PNG_SIZE))
        print(f"Wrote {args.png}")
        return

    from PIL import Image

    ico_images = [Image.open(BytesIO(_render_png(s))).convert("RGBA") for s in ICO_SIZES]
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
