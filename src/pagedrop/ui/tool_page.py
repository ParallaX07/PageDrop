"""Shared helpers for tool UIs hosted as editor tabs (not top-level windows)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    pass


class StatusFooter(QLabel):
    """QLabel stand-in for ``QMainWindow.statusBar()`` on tool tab pages."""

    def __init__(self, parent: QWidget | None = None, *, initial: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("ToolPageStatus")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._message = initial
        if initial:
            self.setText(initial)

    def showMessage(self, message: str, msecs: int = 0) -> None:  # noqa: N802
        del msecs  # QStatusBar API compat; no timed clear for tab footers.
        self._message = message
        self.setText(message)

    def currentMessage(self) -> str:  # noqa: N802
        return self._message


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
