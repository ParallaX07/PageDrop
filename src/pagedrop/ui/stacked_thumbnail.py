"""Stacked multi-page thumbnail rendering."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen, QPixmap

from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_service import render_ref_png
from pagedrop.ui.theme import border_hover_qcolor

MAX_STACK_PAGES = 3
DEFAULT_PAGE_WIDTH_PX = 40
DEFAULT_STACK_OFFSET = 4
MIN_STACK_OFFSET = 8


def stack_thumbnail_layout(
    target_width_px: int,
    page_count: int,
) -> tuple[int, int, int]:
    """Return ``(layer_count, stack_offset_px, page_render_width_px)``."""
    layers = min(max(page_count, 0), MAX_STACK_PAGES)
    if layers <= 1:
        return layers, 0, target_width_px

    stack_offset = max(MIN_STACK_OFFSET, round(target_width_px / 14))
    page_width = target_width_px - stack_offset * (layers - 1)
    page_width = max(page_width, target_width_px // 3)
    return layers, stack_offset, page_width


def _page_border_width(page_width: int) -> int:
    return max(1, round(page_width / 80))


def _stroke_page_border(
    painter: QPainter,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    pen_width: int,
) -> None:
    # Live theme color — not the dark-only BORDER_HOVER hex token.
    pen = QPen(border_hover_qcolor())
    pen.setWidth(pen_width)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = pen_width // 2
    painter.drawRect(
        x + inset,
        y + inset,
        width - pen_width,
        height - pen_width,
    )


def _frame_pixmap(pixmap: QPixmap) -> QPixmap:
    pen_width = _page_border_width(pixmap.width())
    canvas = QPixmap(pixmap.size())
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, pixmap)
    _stroke_page_border(
        painter,
        0,
        0,
        pixmap.width(),
        pixmap.height(),
        pen_width=pen_width,
    )
    painter.end()
    return canvas


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
        return _frame_pixmap(scaled[0])

    layers = len(scaled)
    width = scaled[0].width() + stack_offset * (layers - 1)
    height = scaled[0].height() + stack_offset * (layers - 1)
    pen_width = _page_border_width(scaled[0].width())

    canvas = QPixmap(width, height)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Draw back-to-front so page 1 sits on top (offset 0) and later pages peek behind.
    for layer in range(layers - 1, -1, -1):
        pixmap = scaled[layer]
        offset = layer * stack_offset
        painter.drawPixmap(offset, offset, pixmap)
        _stroke_page_border(
            painter,
            offset,
            offset,
            pixmap.width(),
            pixmap.height(),
            pen_width=pen_width,
        )
    painter.end()
    return canvas


def render_stacked_page_pngs(
    path: str,
    page_count: int,
    *,
    width_px: int = DEFAULT_PAGE_WIDTH_PX,
    should_cancel: Callable[[], bool] | None = None,
    password: str | None = None,
) -> list[bytes]:
    """Render the first 1–3 pages of a PDF to PNG bytes.

    Per-page ``render_ref_png`` so the doc-cache LRU warms and the lock
    releases between pages (matches O15 thumb baseline).
    """
    pages_to_render = min(max(page_count, 0), MAX_STACK_PAGES)
    if pages_to_render == 0:
        return []

    passwords = {path: password} if password is not None else None
    pngs: list[bytes] = []
    for page_index in range(pages_to_render):
        if should_cancel and should_cancel():
            return []
        pngs.append(
            render_ref_png(
                PageRef(path, page_index),
                width_px,
                passwords=passwords,
            )
        )
    return pngs


def render_stacked_pdf_thumbnail(
    path: str,
    page_count: int,
    *,
    width_px: int = DEFAULT_PAGE_WIDTH_PX,
    stack_offset: int | None = None,
    password: str | None = None,
) -> QPixmap:
    """Render the first 1–3 pages of a PDF as a stacked thumbnail."""
    _layers, auto_offset, page_render_width = stack_thumbnail_layout(width_px, page_count)
    if stack_offset is None:
        stack_offset = auto_offset
    page_pngs = render_stacked_page_pngs(
        path,
        page_count,
        width_px=page_render_width,
        password=password,
    )
    if not page_pngs:
        return QPixmap()

    pixmaps: list[QPixmap] = []
    for png in page_pngs:
        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        pixmaps.append(pixmap)
    return build_stacked_pixmap(pixmaps, stack_offset=stack_offset)
