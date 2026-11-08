"""Shared helpers for tool UIs hosted as editor tabs (not top-level windows)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from pagedrop.ui.theme import SPACE_2, SPACE_4, tabular_font

if TYPE_CHECKING:
    pass


class _PageScrollArea(QScrollArea):
    """Frameless scroll area whose body is exactly as big as the page lets it be.

    The body fills the viewport, and grows past it only to its own minimum size.
    ``setWidgetResizable`` would ask the body for its height-for-width instead,
    which is its preferred height and would scroll pages that already fit.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

    def setWidget(self, widget: QWidget | None) -> None:  # noqa: N802
        super().setWidget(widget)
        if widget is not None:
            widget.installEventFilter(self)

    def sizeHint(self) -> QSize:  # noqa: N802
        widget = self.widget()
        return widget.sizeHint() if widget is not None else super().sizeHint()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.widget() and event.type() == QEvent.Type.LayoutRequest:
            self._fit_body()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_body()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit_body()

    def _fit_body(self) -> None:
        body = self.widget()
        if body is None:
            return
        need = body.minimumSizeHint()
        room = self.maximumViewportSize()
        bar_w = self.verticalScrollBar().sizeHint().width()
        bar_h = self.horizontalScrollBar().sizeHint().height()
        vertical = need.height() > room.height()
        horizontal = need.width() > room.width() - (bar_w if vertical else 0)
        if horizontal and not vertical:
            vertical = need.height() > room.height() - bar_h
        width = room.width() - (bar_w if vertical else 0)
        height = room.height() - (bar_h if horizontal else 0)
        body.resize(max(width, need.width()), max(height, need.height()))


def scrollable_page_body(page: QWidget) -> QWidget:
    """Make *page* a frameless scroll area around a new body widget and return it.

    A page built this way no longer sets its parent's minimum size: when the
    window is smaller than the content, the page scrolls (keyboard focus
    scrolls the focused control into view) instead of clipping. Above the
    content's minimum nothing differs: no scroll bars, and the page's own
    background shows through. Build the page's layout on the returned body.
    """
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    scroll = _PageScrollArea(page)
    scroll.setObjectName("ToolPageScroll")
    body = QWidget()
    body.setObjectName("ToolPageBody")
    scroll.setWidget(body)
    # QScrollArea paints both opaquely; let the page's background show.
    scroll.viewport().setAutoFillBackground(False)
    body.setAutoFillBackground(False)
    outer.addWidget(scroll)
    return body


class StatusFooter(QLabel):
    """QLabel stand-in for ``QMainWindow.statusBar()`` on tool tab pages.

    Idle / empty messages stay hidden so the footer does not reserve a full-width
    strip for placeholder copy like "Add a file to begin".
    """

    def __init__(self, parent: QWidget | None = None, *, initial: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("ToolPageStatus")
        self.setFont(tabular_font())
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._message = ""
        self.showMessage(initial)

    def showMessage(self, message: str, msecs: int = 0) -> None:  # noqa: N802
        del msecs  # QStatusBar API compat; no timed clear for tab footers.
        text = message or ""
        self._message = text
        self.setText(text)
        self.setVisible(bool(text.strip()))

    def currentMessage(self) -> str:  # noqa: N802
        return self._message


class ToolWorkflowHeader(QWidget):
    """Shared title and purpose block for tool input workflows."""

    def __init__(self, title: str, purpose: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToolWorkflowHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_2)
        layout.setSpacing(SPACE_2)
        heading = QLabel(title)
        heading.setObjectName("ToolWorkflowTitle")
        layout.addWidget(heading)
        description = QLabel(purpose)
        description.setObjectName("ToolWorkflowPurpose")
        description.setWordWrap(True)
        layout.addWidget(description)


def attach_status_footer(
    root: QVBoxLayout,
    *,
    initial: str = "",
) -> StatusFooter:
    """Add a status footer row to *root* and return it."""
    footer = StatusFooter(initial=initial)
    root.addWidget(footer)
    return footer


def tool_shell_store(tools: QWidget) -> dict[str, QWidget]:
    """Prefer the editor's shell cache so closing the Tools hub keeps shells."""
    editor = getattr(tools, "editor", None)
    if editor is not None:
        store = getattr(editor, "_tool_shells", None)
        if isinstance(store, dict):
            return store
        store = {}
        editor._tool_shells = store  # type: ignore[attr-defined]
        return store
    store = getattr(tools, "_tool_shells", None)
    if isinstance(store, dict):
        return store
    store = {}
    tools._tool_shells = store  # type: ignore[attr-defined]
    return store


def present_tool_page(
    editor: QWidget | None,
    page: QWidget,
    *,
    page_id: str,
) -> None:
    """Host *page* in the editor tab strip, or ``show()`` when no editor host."""
    open_fn = getattr(editor, "open_tool_page", None)
    if callable(open_fn):
        open_fn(page, page_id=page_id)
        return
    page.show()
    page.raise_()
    page.activateWindow()
