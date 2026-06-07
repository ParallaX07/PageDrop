"""Shared pytest fixtures for PageDrop."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.fixtures.generate_fixtures import (
    ensure_fixtures,
    fixture_path,
)

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

# Headless Qt on CI/Linux; harmless on Windows when supported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PAGEDROP_TESTING"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "generated"

# Cap how long tests wait on thumbnail rendering (ms).
RENDER_TIMEOUT_MS = 15_000
RENDER_POOL_DRAIN_MS = 2000


def _install_nonblocking_qt() -> None:
    """Patch modal Qt APIs before any widgets exist.

    pytest-timeout cannot interrupt C++ event loops (drag.exec, dialog.exec).
    These stubs run at import time so they cannot be bypassed by fixture ordering.
    Individual tests may still monkeypatch over these for assertions.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QDrag
    from PyQt6.QtWidgets import QMenu, QMessageBox

    def _noop_drag_exec(self, *args, **kwargs):
        return Qt.DropAction.IgnoreAction

    def _noop_menu_exec(self, *args, **kwargs):
        return None

    QDrag.exec = _noop_drag_exec  # type: ignore[method-assign]
    QMenu.exec = _noop_menu_exec  # type: ignore[method-assign]

    _ok = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    QMessageBox.critical = _ok
    QMessageBox.warning = _ok
    QMessageBox.information = _ok
    QMessageBox.question = _ok


_install_nonblocking_qt()


def wait_for_pdf_loaded(qtbot: QtBot, window, *, timeout: int = RENDER_TIMEOUT_MS) -> None:
    """Wait until MainWindow finishes thumbnail rendering for the open PDF."""
    qtbot.waitUntil(
        lambda: (
            window._loader is not None
            and not window._progress_bar.isVisible()
            and "Loaded" in window.statusBar().currentMessage()
            and len(window._thumbnail_grid._cards) == window._loader.page_count
        ),
        timeout=timeout,
    )


def wait_for_grid_loaded(qtbot: QtBot, grid, *, timeout: int = RENDER_TIMEOUT_MS) -> None:
    """Wait until a standalone ThumbnailGrid finishes its initial render."""
    qtbot.waitUntil(
        lambda: (
            grid._loader is not None
            and grid._last_rendered_width_px == grid._thumbnail_width_px
            and grid._render_pool.activeThreadCount() == 0
        ),
        timeout=timeout,
    )


@pytest.fixture(autouse=True)
def _limit_qtbot_default_timeout(qtbot):
    qtbot._default_timeout = RENDER_TIMEOUT_MS
    yield


@pytest.fixture(autouse=True)
def _drain_render_workers_after_test():
    yield
    from PyQt6.QtWidgets import QApplication

    from pagedrop.ui.thumbnail_grid import ThumbnailGrid

    for widget in QApplication.allWidgets():
        if isinstance(widget, ThumbnailGrid):
            widget.cancel_rendering()
            widget._render_pool.waitForDone(RENDER_POOL_DRAIN_MS)


@pytest.fixture(scope="session")
def pdf_fixtures_dir() -> Path:
    """Session-scoped directory with generated PDF fixtures."""
    ensure_fixtures(FIXTURES_DIR)
    return FIXTURES_DIR


@pytest.fixture
def one_page_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "one_page")


@pytest.fixture
def five_page_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "five_page")


@pytest.fixture
def empty_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "empty")


@pytest.fixture
def corrupt_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "corrupt")


@pytest.fixture
def garbage_pdf(pdf_fixtures_dir: Path) -> Path:
    return fixture_path(pdf_fixtures_dir, "garbage")


@pytest.fixture
def main_window(qtbot):
    """Fresh MainWindow instance registered with qtbot."""
    from pagedrop.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window
