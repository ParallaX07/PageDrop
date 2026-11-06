"""Phase 7 smoke tests — temp file lifecycle and cleanup."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pagedrop.core.page_extractor import extract_pages_to_files
from pagedrop.utils.temp_manager import TempManager


def test_five_simulated_extractions_per_drag_cleanup(five_page_pdf):
    tm = TempManager()
    temp_dir = tm.get_dir()
    try:
        for _ in range(5):
            drag_dir = tm.create_drag_dir()
            paths = extract_pages_to_files(
                str(five_page_pdf),
                [0],
                drag_dir,
                five_page_pdf.stem,
            )
            assert all(path.exists() for path in paths)
            assert drag_dir.exists()

            tm.cleanup_paths(paths)

            assert not any(path.exists() for path in paths)
            assert not drag_dir.exists()
            assert temp_dir.exists()

        drag_subdirs = list(temp_dir.glob("drag_*"))
        assert drag_subdirs == []
    finally:
        tm.cleanup()


def test_cleanup_removes_run_orphans_from_system_temp():
    tm = TempManager()
    run_dir = tm.get_dir()
    run_name = run_dir.name
    assert run_dir.exists()

    tm.cleanup()

    temp_root = Path(tempfile.gettempdir())
    matching = [d for d in temp_root.iterdir() if d.name == run_name]
    assert matching == []


def test_subprocess_normal_exit_cleans_temp_dir():
    # Contract: this process's run dir is removed on normal close.
    # Do not assert a global pagedrop_* count — other tests (and prior runs)
    # leave orphans in the system temp dir until process atexit.
    code = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from pagedrop.ui.main_window import MainWindow

app = QApplication([])
window = MainWindow()
print(window._temp_manager.get_dir(), flush=True)
QTimer.singleShot(50, window.close)
QTimer.singleShot(100, app.quit)
app.exec()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    assert lines, f"expected temp dir on stdout, got {result.stdout!r}"
    created_dir = Path(lines[-1])
    assert created_dir.name.startswith("pagedrop_")
    assert not created_dir.exists()


def test_subprocess_force_kill_orphan_is_scrubbed_by_next_manager():
    """SIGKILL/taskkill skips atexit cleanup; the next TempManager scrubs the orphan.

    The killed process wrote ``.pagedrop_owner`` with its pid, so once it is dead
    the orphan is removed at once (no grace wait).
    """
    code = """
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from pagedrop.ui.main_window import MainWindow

app = QApplication([])
window = MainWindow()
print(window._temp_manager.get_dir(), flush=True)
sys.stdout.flush()
time.sleep(30)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    orphan_dir = None
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line
        orphan_dir = Path(line)
        assert orphan_dir.exists()

        proc.kill()
        proc.wait(timeout=10)
        # atexit never ran; a parallel worker may already have scrubbed the tree,
        # so only the post-scrub state is asserted.
        tm = TempManager()
        try:
            assert not orphan_dir.exists()
        finally:
            tm.cleanup()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if orphan_dir is not None:
            shutil.rmtree(orphan_dir, ignore_errors=True)
