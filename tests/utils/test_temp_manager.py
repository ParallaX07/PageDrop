"""Phase 7 / O4 unit tests — TempManager."""

from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import tempfile
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


def test_enforce_max_size_tolerates_non_numeric_drag_dirs():
    tm = TempManager(max_bytes=50)
    try:
        bad_dir = tm.get_dir() / "drag_foo"
        bad_dir.mkdir()
        (bad_dir / "stray.pdf").write_bytes(b"x" * 60)

        drag_dir = tm.create_drag_dir()
        assert drag_dir.exists()
        assert not bad_dir.exists()
    finally:
        tm.cleanup()


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


def test_enforce_max_size_evicts_oldest_job_dirs():
    tm = TempManager(max_bytes=100)
    try:
        old_job = tm.create_job_dir()
        (old_job / "old.pdf").write_bytes(b"x" * 80)

        new_job = tm.create_job_dir()
        (new_job / "new.pdf").write_bytes(b"y" * 80)

        tm.create_job_dir()
        assert not old_job.exists()
        assert new_job.exists()
    finally:
        tm.cleanup()


def test_enforce_max_size_evicts_oldest_across_drag_and_job():
    tm = TempManager(max_bytes=100)
    try:
        old_job = tm.create_job_dir()
        (old_job / "old.pdf").write_bytes(b"x" * 80)

        drag = tm.create_drag_dir()
        (drag / "drag.pdf").write_bytes(b"y" * 80)

        tm.create_drag_dir()
        assert not old_job.exists()
        assert drag.exists()
    finally:
        tm.cleanup()


def test_init_scrubs_orphan_pagedrop_dirs():
    orphan = Path(tempfile.mkdtemp(prefix="pagedrop_"))
    marker = orphan / "leftover.bin"
    marker.write_bytes(b"orphan")
    assert orphan.exists()

    tm = TempManager()
    try:
        assert not orphan.exists()
        assert tm.get_dir().exists()
    finally:
        tm.cleanup()


def test_init_preserves_live_sibling_temp_manager():
    first = TempManager()
    try:
        second = TempManager()
        try:
            assert first.get_dir().exists()
            assert second.get_dir().exists()
            assert first.get_dir() != second.get_dir()
        finally:
            second.cleanup()
        assert first.get_dir().exists()
    finally:
        first.cleanup()


def test_init_preserves_backend_temp_prefixes():
    office = Path(tempfile.mkdtemp(prefix="pagedrop_office_stage_"))
    lo = Path(tempfile.mkdtemp(prefix="pagedrop_lo_profile_"))
    try:
        tm = TempManager()
        try:
            assert office.exists()
            assert lo.exists()
        finally:
            tm.cleanup()
    finally:
        for path in (office, lo):
            shutil.rmtree(path, ignore_errors=True)