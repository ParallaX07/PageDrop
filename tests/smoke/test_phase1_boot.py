"""Phase 1 smoke tests — project boot and entry point."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def test_imports():
    import pagedrop  # noqa: F401
    import pagedrop.core  # noqa: F401
    import pagedrop.main  # noqa: F401
    import pagedrop.ui  # noqa: F401


def test_main_window_defers_tool_window_imports():
    """O9: Merge/Create/Tools must not load until first open."""
    code = """
import sys
from pagedrop.ui.main_window import MainWindow

assert MainWindow is not None
for name in (
    "pagedrop.ui.merge_window",
    "pagedrop.ui.convert_window",
    "pagedrop.ui.tools_window",
):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"deferred-import check failed (code {result.returncode})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


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
    assert "Starting PageDrop version=" in result.stderr


def test_compress_worker_flag_dispatches_without_creating_a_qapplication(monkeypatch):
    """The compress child runs headless: flag stripped, no Qt application built."""
    from PyQt6 import QtWidgets

    from pagedrop import main as main_module
    from pagedrop.core import optimize_secure
    from pagedrop.utils import diagnostics

    flag = optimize_secure.COMPRESS_WORKER_FLAG
    received: list[list[str]] = []

    class Forbidden:
        instance = staticmethod(QtWidgets.QApplication.instance)  # pytest-qt calls it

        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("QApplication must not be created for the compress worker")

    monkeypatch.setattr(diagnostics, "configure_terminal_logging", lambda: None)
    monkeypatch.setattr(diagnostics, "log_startup", lambda **_kw: None)
    monkeypatch.setattr(QtWidgets, "QApplication", Forbidden)
    monkeypatch.setattr(
        optimize_secure, "main", lambda argv: received.append(list(argv)) or 7
    )
    monkeypatch.setattr(sys, "argv", ["pagedrop", flag, "--compress-json"])

    assert main_module.main() == 7
    assert received == [["--compress-json"]]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux library path")
def test_main_restores_the_library_path_before_dispatching_worker_flags(monkeypatch):
    """Frozen Linux: the worker flag sees the original path, not the bundled one."""
    from pagedrop import main as main_module
    from pagedrop.core import optimize_secure
    from pagedrop.utils import diagnostics

    seen: list[str | None] = []
    monkeypatch.setattr(diagnostics, "configure_terminal_logging", lambda: None)
    monkeypatch.setattr(diagnostics, "log_startup", lambda **_kw: None)
    monkeypatch.setattr(
        optimize_secure, "main", lambda _argv: seen.append(os.environ.get("LD_LIBRARY_PATH")) or 0
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys, "argv", ["pagedrop", optimize_secure.COMPRESS_WORKER_FLAG, "--compress-json"]
    )
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/_internal:/usr/lib/x")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/x")

    assert main_module.main() == 0
    assert seen == ["/usr/lib/x"]


@pytest.mark.parametrize(
    "flag",
    ["--pagedrop-redact-verify", "--pagedrop-compress-worker"],
)
def test_module_run_exits_with_the_helper_status(flag):
    """A helper started as ``python -m pagedrop.main`` reports failure to its parent."""
    result = subprocess.run(
        [sys.executable, "-m", "pagedrop.main", flag],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 1, result.stderr
    assert "Usage:" in result.stderr


def test_command_line_paths_drop_options_and_blanks():
    from pagedrop.main import command_line_paths

    args = [
        "--pagedrop-office-com-worker",
        "a.pdf",
        "",
        "--pagedrop-redact-verify",
        "-platform",
        "/tmp/b.pdf",
        "--pagedrop-compress-worker",
    ]
    assert command_line_paths(args) == ["a.pdf", "/tmp/b.pdf"]
    assert command_line_paths([]) == []
