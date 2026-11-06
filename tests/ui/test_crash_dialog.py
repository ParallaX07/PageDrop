from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt, QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from pagedrop.ui.crash_dialog import show_crash_dialog

LOG = Path("/home/someone/PageDrop/logs/pagedrop.log")


@pytest.fixture
def shown(monkeypatch, qapp):
    """Record each QMessageBox the dialog runs instead of blocking on it."""
    seen: list[dict] = []

    def record(self: QMessageBox) -> int:
        seen.append(
            {
                "icon": self.icon(),
                "title": self.windowTitle(),
                "format": self.textFormat(),
                "text": self.text(),
                "informative": self.informativeText(),
                "flags": self.textInteractionFlags(),
                "parent": self.parent(),
            }
        )
        return 0

    monkeypatch.setattr(QMessageBox, "exec", record)
    return seen


def test_dialog_names_the_log_file(shown):
    show_crash_dialog(LOG)
    (box,) = shown
    assert box["icon"] == QMessageBox.Icon.Critical
    assert box["title"] == "PageDrop"
    assert box["format"] == Qt.TextFormat.PlainText
    assert box["text"] == "PageDrop hit an unexpected problem."
    assert box["informative"] == (
        f"Details were saved to:\n{LOG}\n\n"
        "Save your work and restart PageDrop if anything looks wrong."
    )
    assert box["flags"] & Qt.TextInteractionFlag.TextSelectableByMouse
    assert box["parent"] is None


def test_dialog_says_when_nothing_was_saved(shown):
    show_crash_dialog(None)
    assert shown[0]["informative"] == (
        "PageDrop could not save the details to a log file.\n\n"
        "Save your work and restart PageDrop if anything looks wrong."
    )


def test_dialog_runs_at_once_when_no_event_loop_is_running(shown):
    show_crash_dialog(LOG)
    assert len(shown) == 1


def test_dialog_waits_for_control_when_called_inside_an_event_loop(shown, monkeypatch):
    loop = QEventLoop()
    during: list[int] = []

    def inside_loop() -> None:
        show_crash_dialog(LOG)
        during.append(len(shown))

    original = QMessageBox.exec

    def exec_then_quit(self: QMessageBox) -> int:
        original(self)
        loop.quit()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_then_quit)
    QTimer.singleShot(0, inside_loop)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()

    assert during == [0]
    assert len(shown) == 1


def test_no_application_means_no_dialog(shown, monkeypatch):
    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    show_crash_dialog(LOG)
    assert shown == []
