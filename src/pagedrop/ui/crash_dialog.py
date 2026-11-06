"""Last-resort crash notice. Imports only PyQt6 so it works when the app modules failed."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox


def _show_now(log_path: Path | None) -> None:
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("PageDrop")
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText("PageDrop hit an unexpected problem.")
    where = (
        f"Details were saved to:\n{log_path}"
        if log_path is not None
        else "PageDrop could not save the details to a log file."
    )
    box.setInformativeText(
        f"{where}\n\nSave your work and restart PageDrop if anything looks wrong."
    )
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.exec()


def _show_deferred(log_path: Path | None) -> None:
    try:
        _show_now(log_path)
    except Exception:
        logging.getLogger("pagedrop").error("Could not show the crash dialog", exc_info=True)


def show_crash_dialog(log_path: Path | None) -> None:
    """Tell the user PageDrop hit a problem; the exception text is never shown."""
    if not isinstance(QApplication.instance(), QApplication):
        return
    if QThread.currentThread().loopLevel() > 0:
        # A nested exec inside a paint or slot call is unsafe; run once control returns.
        QTimer.singleShot(0, lambda: _show_deferred(log_path))
    else:
        _show_now(log_path)
