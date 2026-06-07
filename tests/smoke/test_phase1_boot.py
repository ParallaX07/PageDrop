"""Phase 1 smoke tests — project boot and entry point."""

from __future__ import annotations

import subprocess
import sys

import pytest


def test_imports():
    import pagedrop  # noqa: F401
    import pagedrop.core  # noqa: F401
    import pagedrop.main  # noqa: F401
    import pagedrop.ui  # noqa: F401


def test_main_callable():
    from pagedrop.main import main

    assert callable(main)


def test_cli_entry_point():
    """Entry point starts Qt and exits cleanly when the window is closed."""
    code = """
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from pagedrop.main import main
from pagedrop.ui.main_window import MainWindow

_original_show = MainWindow.show

def _auto_close_show(self):
    _original_show(self)
    QTimer.singleShot(100, self.close)
    QTimer.singleShot(200, QApplication.instance().quit)

MainWindow.show = _auto_close_show
sys.exit(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"CLI entry point failed (code {result.returncode})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
