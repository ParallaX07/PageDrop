"""Explicit post-job result actions — never auto-open tool outputs."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.pdf_loader import PdfEmptyError, PdfLoadError, PdfLoader
from pagedrop.core.pdf_service import FITZ_LOCK
from pagedrop.core.supported_formats import is_pdf_path
from pagedrop.ui.page_preview import PagePreviewWidget


class ResultActionsBar(QWidget):
    """Preview / Open in editor / Show in folder for a finished job output."""

    preview_requested = pyqtSignal(str)
    open_in_editor_requested = pyqtSignal(str)
    show_in_folder_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ResultActionsBar")
        self._path: str | None = None
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._label = QLabel()
        self._label.setObjectName("ResultActionsLabel")
        self._label.setWordWrap(True)
        layout.addWidget(self._label, stretch=1)

        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setObjectName("ResultActionsPreview")
        self._preview_btn.clicked.connect(self._emit_preview)
        layout.addWidget(self._preview_btn)

        self._open_btn = QPushButton("Open in editor")
        self._open_btn.setObjectName("ResultActionsOpen")
        self._open_btn.clicked.connect(self._emit_open)
        layout.addWidget(self._open_btn)

        self._folder_btn = QPushButton("Show in folder")
        self._folder_btn.setObjectName("ResultActionsFolder")
        self._folder_btn.clicked.connect(self._emit_folder)
        layout.addWidget(self._folder_btn)

    def show_for(self, path: str | Path, *, message: str | None = None) -> None:
        resolved = str(Path(path))
        self._path = resolved
        name = Path(resolved).name
        status = message or f"Saved {name}"
        self._label.setText(status)
        self.setAccessibleName(status)
        self._preview_btn.setEnabled(is_pdf_path(resolved))
        self._open_btn.setEnabled(is_pdf_path(resolved))
        self.show()

    def clear(self) -> None:
        self._path = None
        self.setAccessibleName("")
        self.hide()

    def _emit_preview(self) -> None:
        if self._path:
            self.preview_requested.emit(self._path)

    def _emit_open(self) -> None:
        if self._path:
            self.open_in_editor_requested.emit(self._path)

    def _emit_folder(self) -> None:
        if self._path:
            self.show_in_folder_requested.emit(self._path)


def show_in_folder(path: str | Path) -> bool:
    """Open the containing folder in the system file manager. Returns success."""
    target = Path(path).resolve()
    folder = target if target.is_dir() else target.parent
    if not folder.is_dir():
        return False

    # Prefer select-in-folder on platforms that support it; fall back to folder.
    if sys.platform == "win32" and target.is_file():
        from PyQt6.QtCore import QProcess

        return QProcess.startDetached("explorer", ["/select,", str(target)])
    if sys.platform == "darwin" and target.is_file():
        from PyQt6.QtCore import QProcess

        return QProcess.startDetached("open", ["-R", str(target)])
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def open_in_editor(path: str | Path, editor: QWidget) -> None:
    """Load *path* into a MainWindow-like editor (``_open_single_pdf``)."""
    open_fn = getattr(editor, "_open_single_pdf", None)
    if not callable(open_fn):
        raise TypeError("editor does not support opening PDFs")
    open_fn(str(Path(path)))


def preview_pdf(path: str | Path, parent: QWidget | None = None) -> bool:
    """Show a modeless single-document preview dialog. Returns False on load failure."""
    resolved = Path(path)
    filename = resolved.name
    try:
        # Initial open under FITZ_LOCK (O17-c); dialog keeps the long-lived loader.
        with FITZ_LOCK:
            loader = PdfLoader(str(resolved))
    except PdfEmptyError:
        QMessageBox.warning(
            parent,
            "Preview",
            f"{filename} has no pages.",
        )
        return False
    except PdfLoadError as exc:
        QMessageBox.critical(
            parent,
            "Preview",
            f"Could not open {filename}:\n{exc}",
        )
        return False

    dialog = QDialog(parent)
    dialog.setObjectName("ResultPreviewDialog")
    dialog.setWindowTitle(f"Preview: {filename}")
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.resize(720, 900)

    # Keep dialog on-screen when parent is a compact Tools window.
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        dialog.resize(min(720, avail.width() - 40), min(900, avail.height() - 40))

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    preview = PagePreviewWidget(dialog)
    preview.set_footer_hint("← → change page · Ctrl+scroll zoom · Esc close")
    preview.set_loader(loader)
    preview.show_page(0)
    layout.addWidget(preview)

    def _cleanup() -> None:
        preview.set_loader(None)
        loader.close()

    dialog.finished.connect(lambda _code: _cleanup())

    # Esc closes via preview's closed signal when focused.
    preview.closed.connect(dialog.close)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    preview.setFocus(Qt.FocusReason.OtherFocusReason)
    return True
