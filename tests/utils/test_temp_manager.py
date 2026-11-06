"""Phase 7 / O4 / O13 unit tests — TempManager."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from pagedrop.utils.temp_manager import (
    TempManager,
    _ORPHAN_NO_OWNER_GRACE_SEC,
    _pid_alive,
)


def _age_past_orphan_grace(path: Path) -> None:
    """Make *path* look older than the no-owner scrub grace window."""
    past = time.time() - (_ORPHAN_NO_OWNER_GRACE_SEC + 5.0)
    os.utime(path, (past, past))


def test_pid_alive_self_and_bogus():
    """Liveness check must not use os.kill(pid, 0) on Windows (CTRL_C_EVENT)."""
    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(-1) is False
    assert _pid_alive(0) is False
    # Unlikely to be a live PID; must return False without raising / signaling.
    assert _pid_alive(2_147_000_000) is False


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
        tm.unpin_dir(old_job)  # finished job: evictable

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
        tm.unpin_dir(old_job)  # finished job: evictable

        drag = tm.create_drag_dir()
        (drag / "drag.pdf").write_bytes(b"y" * 80)

        tm.create_drag_dir()
        assert not old_job.exists()
        assert drag.exists()
    finally:
        tm.cleanup()


def test_init_scrubs_orphan_pagedrop_dirs():
    """Dirs with no owner file (pre-pid leftovers) are scrubbed once past grace."""
    orphan = Path(tempfile.mkdtemp(prefix="pagedrop_"))
    marker = orphan / "leftover.bin"
    marker.write_bytes(b"orphan")
    _age_past_orphan_grace(orphan)
    assert orphan.exists()

    tm = TempManager()
    try:
        assert not orphan.exists()
        assert tm.get_dir().exists()
        assert (tm.get_dir() / ".pagedrop_owner").is_file()
    finally:
        tm.cleanup()


def test_init_preserves_young_no_owner_dirs():
    """Fresh mkdtemp (mid-claim window) must survive a parallel TempManager scrub."""
    young = Path(tempfile.mkdtemp(prefix="pagedrop_office_stage_"))
    (young / "staged.pdf").write_bytes(b"%PDF")
    try:
        tm = TempManager()
        try:
            assert young.exists()
            assert (young / "staged.pdf").is_file()
        finally:
            tm.cleanup()
    finally:
        shutil.rmtree(young, ignore_errors=True)


def test_init_scrubs_dead_owner_pid():
    """Dirs whose owner pid is dead are scrubbed even with an owner file."""
    # Capture a pid from a process that has already exited.
    result = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    dead_pid = int(result.stdout.strip())

    orphan = Path(tempfile.mkdtemp(prefix="pagedrop_"))
    (orphan / ".pagedrop_owner").write_text(str(dead_pid), encoding="ascii")
    (orphan / "leftover.bin").write_bytes(b"orphan")

    tm = TempManager()
    try:
        assert not orphan.exists()
    finally:
        tm.cleanup()


def test_init_preserves_foreign_live_owner():
    """Dirs owned by a still-running process (other workers / instances) survive."""
    import os

    foreign = Path(tempfile.mkdtemp(prefix="pagedrop_"))
    (foreign / ".pagedrop_owner").write_text(str(os.getpid()), encoding="ascii")
    (foreign / "keep.bin").write_bytes(b"live")
    try:
        tm = TempManager()
        try:
            assert foreign.exists()
            assert (foreign / "keep.bin").exists()
        finally:
            tm.cleanup()
    finally:
        shutil.rmtree(foreign, ignore_errors=True)


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


def test_init_scrubs_orphan_backend_temp_prefixes():
    """Crash leftovers under pagedrop_office_* / pagedrop_lo_* are scrubbed on init."""
    office = Path(tempfile.mkdtemp(prefix="pagedrop_office_stage_"))
    lo = Path(tempfile.mkdtemp(prefix="pagedrop_lo_profile_"))
    (office / "leftover.bin").write_bytes(b"orphan")
    (lo / "leftover.bin").write_bytes(b"orphan")
    _age_past_orphan_grace(office)
    _age_past_orphan_grace(lo)
    assert office.exists() and lo.exists()

    tm = TempManager()
    try:
        assert not office.exists()
        assert not lo.exists()
    finally:
        tm.cleanup()


def test_init_preserves_claimed_backend_temps():
    """Live LO/Office trees claimed via claim_backend_temp survive scrub."""
    from pagedrop.utils.temp_manager import claim_backend_temp, release_backend_temp

    office = claim_backend_temp(Path(tempfile.mkdtemp(prefix="pagedrop_office_stage_")))
    lo = claim_backend_temp(Path(tempfile.mkdtemp(prefix="pagedrop_lo_profile_")))
    try:
        assert (office / ".pagedrop_owner").is_file()
        assert (lo / ".pagedrop_owner").is_file()
        tm = TempManager()
        try:
            assert office.exists()
            assert lo.exists()
        finally:
            tm.cleanup()
    finally:
        release_backend_temp(office)
        release_backend_temp(lo)
        for path in (office, lo):
            shutil.rmtree(path, ignore_errors=True)


def _run_with_timeout(fn, timeout: float = 5.0) -> bool:
    """Run *fn* in a daemon thread; True if it returned within *timeout*."""
    worker = threading.Thread(target=fn, daemon=True)
    worker.start()
    worker.join(timeout)
    return not worker.is_alive()


def test_enforce_max_size_returns_when_candidate_cannot_be_removed(monkeypatch):
    tm = TempManager(max_bytes=100)
    try:
        for _ in range(2):
            stuck = tm.create_drag_dir()
            (stuck / "big.pdf").write_bytes(b"x" * 80)

        with monkeypatch.context() as patch:
            patch.setattr(shutil, "rmtree", lambda *args, **kwargs: None)
            assert _run_with_timeout(tm._enforce_max_size)
            assert _run_with_timeout(tm.create_drag_dir)
    finally:
        tm.cleanup()


def test_pinned_job_dir_survives_eviction_until_unpinned():
    tm = TempManager(max_bytes=100)
    try:
        live = tm.create_job_dir()
        (live / "output.pdf").write_bytes(b"x" * 200)

        newest = tm.create_job_dir()
        assert newest.exists()  # a dir is never evicted by its own creation
        assert live.exists()

        tm.unpin_dir(live)
        tm.create_drag_dir()
        assert not live.exists()
        assert newest.exists()
    finally:
        tm.cleanup()


def test_remove_dir_is_best_effort_and_unpins():
    tm = TempManager()
    try:
        job = tm.create_job_dir()
        (job / "partial.pdf").write_bytes(b"x")
        tm.remove_dir(job)
        assert not job.exists()
        tm.remove_dir(job)  # already gone: no error
    finally:
        tm.cleanup()


def test_cleanup_paths_tolerates_missing_files_and_unlink_errors(monkeypatch):
    tm = TempManager()
    try:
        drag_dir = tm.create_drag_dir()
        missing = drag_dir / "missing.pdf"
        tm.cleanup_paths([missing])
        assert not drag_dir.exists()

        drag_dir = tm.create_drag_dir()
        stuck = drag_dir / "stuck.pdf"
        stuck.write_bytes(b"x")

        def deny(self, *args, **kwargs):
            raise PermissionError("in use")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", deny)
            tm.cleanup_paths([stuck])
        assert stuck.exists()
    finally:
        tm.cleanup()


def test_concurrent_creates_get_distinct_dirs():
    tm = TempManager()
    created: list[Path] = []

    def make_many() -> None:
        for _ in range(25):
            created.append(tm.create_drag_dir())
            created.append(tm.create_job_dir())

    try:
        threads = [threading.Thread(target=make_many) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        assert len(created) == 200
        assert len(set(created)) == 200
    finally:
        tm.cleanup()


def test_dir_size_ignores_a_file_that_vanishes_mid_walk(monkeypatch):
    tm = TempManager(max_bytes=100)
    try:
        job = tm.create_job_dir()
        (job / "gone.bin").write_bytes(b"x" * 50)
        (job / "kept.bin").write_bytes(b"x" * 30)
        real_stat = Path.stat
        real_is_file = Path.is_file

        def flaky_stat(self, *args, **kwargs):
            if self.name == "gone.bin":
                raise FileNotFoundError(self.name)
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky_stat)
        monkeypatch.setattr(
            Path, "is_file", lambda self: self.name == "gone.bin" or real_is_file(self)
        )
        assert tm._dir_size() >= 30
        tm.create_drag_dir()  # runs the quota check; must not raise
    finally:
        monkeypatch.undo()
        tm.cleanup()
