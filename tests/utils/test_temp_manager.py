"""Phase 7 unit tests — TempManager."""

from __future__ import annotations

import atexit
import subprocess
import sys
from pathlib import Path

from pagedrop.utils.temp_manager import TempManager


def test_creates_prefixed_dir():
    tm = TempManager()
    try:
        assert tm.get_dir().name.startswith("pagedrop_")
        assert tm.get_dir().is_dir()
    finally:
        tm.cleanup()


def test_cleanup_removes_dir():
    tm = TempManager()
    temp_dir = tm.get_dir()
    assert temp_dir.exists()
    tm.cleanup()
    assert not temp_dir.exists()


def test_cleanup_idempotent():
    tm = TempManager()
    tm.cleanup()
    tm.cleanup()


def test_create_drag_dir_and_cleanup_paths():
    tm = TempManager()
    try:
        drag_dir = tm.create_drag_dir()
        assert drag_dir.parent == tm.get_dir()
        assert drag_dir.name == "drag_1"

        file_a = drag_dir / "a.pdf"
        file_b = drag_dir / "b.pdf"
        file_a.write_bytes(b"pdf-a")
        file_b.write_bytes(b"pdf-b")

        tm.cleanup_paths([file_a, file_b])
        assert not file_a.exists()
        assert not file_b.exists()
        assert not drag_dir.exists()
    finally:
        tm.cleanup()


def test_atexit_registered(monkeypatch):
    registered: list[object] = []
    original_register = atexit.register

    def spy_register(func, *args, **kwargs):
        registered.append(func)
        return original_register(func, *args, **kwargs)

    monkeypatch.setattr(atexit, "register", spy_register)

    tm = TempManager()
    try:
        assert any(
            getattr(func, "__self__", None) is tm
            and getattr(func, "__name__", "") == "cleanup"
            for func in registered
        )
    finally:
        tm.cleanup()


def test_atexit_cleans_on_normal_exit():
    code = """
from pagedrop.utils.temp_manager import TempManager
tm = TempManager()
print(tm.get_dir())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    temp_dir = Path(result.stdout.strip())
    assert not temp_dir.exists()


def test_enforce_max_size_removes_oldest_drag_dirs():
    tm = TempManager(max_bytes=100)
    try:
        old_dir = tm.create_drag_dir()
        (old_dir / "old.pdf").write_bytes(b"x" * 80)

        new_dir = tm.create_drag_dir()
        (new_dir / "new.pdf").write_bytes(b"y" * 80)

        tm.create_drag_dir()
        assert not old_dir.exists()
        assert new_dir.exists()
    finally:
        tm.cleanup()
