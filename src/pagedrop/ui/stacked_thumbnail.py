"""Stacked multi-page thumbnail rendering."""

from __future__ import annotations

import fitz
from collections.abc import Callable
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap

from pagedrop.core.pdf_loader import render_page_png
from pagedrop.ui.theme import BORDER_DEFAULT

MAX_STACK_PAGES = 3
DEFAULT_PAGE_WIDTH_PX = 40
DEFAULT_STACK_OFFSET = 4


def build_stacked_pixmap(
    page_pixmaps: list[QPixmap],
    *,
    stack_offset: int = DEFAULT_STACK_OFFSET,
) -> QPixmap:
    """Compose up to three page thumbnails into a diagonal stack."""
    if not page_pixmaps:
        return QPixmap()

    target_width = page_pixmaps[0].width()
    scaled = [
        pixmap.scaledToWidth(
            target_width,
            Qt.TransformationMode.SmoothTransformation,
        )
        for pixmap in page_pixmaps
    ]

    if len(scaled) == 1:
        return scaled[0]

    layers = len(scaled)
    width = scaled[0].width() + stack_offset * (layers - 1)
    height = scaled[0].height() + stack_offset * (layers - 1)

    canvas = QPixmap(width, height)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for layer, pixmap in enumerate(scaled):
        offset = (layers - 1 - layer) * stack_offset
        painter.setPen(QColor(BORDER_DEFAULT))
        painter.drawRect(offset, offset, pixmap.width() - 1, pixmap.height() - 1)
        painter.drawPixmap(offset, offset, pixmap)
    painter.end()
    return canvas


def render_stacked_page_pngs(
    path: str,
    page_count: int,
    *,
    width_px: int = DEFAULT_PAGE_WIDTH_PX,
    should_cancel: Callable[[], bool] | None = None,
) -> list[bytes]:
    """Render the first 1–3 pages of a PDF to PNG bytes (safe for worker threads)."""
    pages_to_render = min(max(page_count, 0), MAX_STACK_PAGES)
    if pages_to_render == 0:
        return []

    doc = fitz.open(path)
    try:
        pngs: list[bytes] = []
        for page_index in range(pages_to_render):
            if should_cancel and should_cancel():
                return []
            pngs.append(render_page_png(doc, page_index, width_px=width_px))
        return pngs
    finally:
        doc.close()


def render_stacked_pdf_thumbnail(
    path: str,
    page_count: int,
    *,
    width_px: int = DEFAULT_PAGE_WIDTH_PX,
    stack_offset: int = DEFAULT_STACK_OFFSET,
) -> QPixmap:
    """Render the first 1–3 pages of a PDF as a stacked thumbnail."""
    page_pngs = render_stacked_page_pngs(path, page_count, width_px=width_px)
    if not page_pngs:
        return QPixmap()

    pixmaps: list[QPixmap] = []
    for png in page_pngs:
        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        pixmaps.append(pixmap)
    return build_stacked_pixmap(pixmaps, stack_offset=stack_offset)
