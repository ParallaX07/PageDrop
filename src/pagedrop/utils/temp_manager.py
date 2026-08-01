from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# ponytail: 512 MiB session quota for drag_* + job_* dirs; raise only with a
# measured complaint. Upgrade: running byte counter if rglob-on-enforce profiles hot.
DEFAULT_MAX_BYTES = 512 * 1024 * 1024  # 512 MiB

_OWNER_FILE = ".pagedrop_owner"

# mkdtemp → owner-file window is open to parallel TempManager scrubs (xdist).
# Skip no-owner trees younger than this; dead-owner trees scrub immediately.
_ORPHAN_NO_OWNER_GRACE_SEC = 60.0

# Live session roots in this process — multi-window must not scrub each other.
_live_dirs: set[Path] = set()

# Backend mkdtemp trees (LO/Office) claimed while a conversion holds them.
_live_backend_dirs: set[Path] = set()

# Windows: OpenProcess access right for existence check (no terminate / no signal).
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5


def _write_owner_pid(path: Path) -> None:
    """Record the owning process so other PageDrop processes skip this tree."""
    try:
        (path / _OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """True if *pid* still refers to a running process.

    On Windows, ``os.kill(pid, 0)`` is *not* a liveness probe: signal ``0`` is
    ``CTRL_C_EVENT``, so it calls ``GenerateConsoleCtrlEvent`` and can SIGINT
    every process attached to the same console (pytest controller + xdist workers).
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # Access denied ⇒ process exists but we cannot open it.
        return ctypes.GetLastError() == _ERROR_ACCESS_DENIED
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _owner_process_alive(path: Path) -> bool:
    """True if ``.pagedrop_owner`` names a still-running process."""
    owner_file = path / _OWNER_FILE
    try:
        raw = owner_file.read_text(encoding="ascii").strip()
        pid = int(raw)
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def claim_backend_temp(path: Path) -> Path:
    """Mark a backend mkdtemp tree live so orphan scrub will not delete it."""
    resolved = path.resolve()
    _write_owner_pid(resolved)
    _live_backend_dirs.add(resolved)
    return path


def release_backend_temp(path: Path) -> None:
    """Drop the live claim after the backend finishes (success or fail)."""
    _live_backend_dirs.discard(path.resolve())


class TempManager:
    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="pagedrop_"))
        # Shared so drag_* / job_* eviction order is creation order, not mtime ties.
        self._subdir_counter = 0
        self._max_bytes = max_bytes
        _write_owner_pid(self._dir)
        _live_dirs.add(self._dir.resolve())
        self._scrub_orphan_pagedrop_dirs()
        atexit.register(self.cleanup)

    def get_dir(self) -> Path:
        return self._dir

    def create_drag_dir(self) -> Path:
        self._enforce_max_size()
        self._subdir_counter += 1
        drag_dir = self._dir / f"drag_{self._subdir_counter}"
        drag_dir.mkdir(parents=True, exist_ok=True)
        return drag_dir

    def create_job_dir(self) -> Path:
        """Directory for a Tools job's staged output (promote or cleanup)."""
        self._enforce_max_size()
        self._subdir_counter += 1
        job_dir = self._dir / f"job_{self._subdir_counter}"
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def cleanup_paths(self, paths: list[Path]) -> None:
        drag_dirs: set[Path] = set()
        for path in paths:
            if path.exists():
                path.unlink()
            drag_dirs.add(path.parent)
        for drag_dir in drag_dirs:
            if drag_dir.exists() and drag_dir.is_dir() and not any(drag_dir.iterdir()):
                drag_dir.rmdir()

    def cleanup(self) -> None:
        resolved = self._dir.resolve() if self._dir.exists() else self._dir
        _live_dirs.discard(resolved)
        if self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)

    def _dir_size(self) -> int:
        # full rglob on each create — fine under 512 MiB / few dirs;
        # callers can write outside TempManager, so a running counter needs write
        # hooks (upgrade if enforce shows up in profiles).
        if not self._dir.exists():
            return 0
        return sum(
            path.stat().st_size for path in self._dir.rglob("*") if path.is_file()
        )

    @staticmethod
    def _evict_dir_sort_key(path: Path) -> tuple[int, str]:
        name = path.name
        for prefix in ("drag_", "job_"):
            if name.startswith(prefix):
                suffix = name.removeprefix(prefix)
                break
        else:
            suffix = name
        try:
            counter = int(suffix)
        except ValueError:
            counter = -1  # non-numeric junk first
        return (counter, name)

    def _enforce_max_size(self) -> None:
        # ponytail: one concurrent create_* per manager under the usual
        # SerializedJobRunner / one-active-job path. Eviction deletes the oldest
        # drag_*/job_* with no pin — a second create while an older dir is still
        # in use could remove it. Pin/unpin only if that race is measured.
        while self._dir_size() > self._max_bytes:
            candidates = sorted(
                (
                    d
                    for d in self._dir.iterdir()
                    if d.is_dir()
                    and (d.name.startswith("drag_") or d.name.startswith("job_"))
                ),
                key=self._evict_dir_sort_key,
            )
            if not candidates:
                break
            shutil.rmtree(candidates[0], ignore_errors=True)

    @staticmethod
    def _scrub_orphan_pagedrop_dirs() -> None:
        """Remove crashed-run ``pagedrop_*`` session and backend dirs; never live ones.

        Skips trees owned by a still-running process (other PageDrop instances /
        pytest-xdist workers) via ``.pagedrop_owner``. Fresh dirs with no owner
        yet (mid ``mkdtemp`` → claim) are left alone until past the grace window.
        """
        temp_root = Path(tempfile.gettempdir())
        try:
            entries = list(temp_root.iterdir())
        except OSError:
            return
        now = time.time()
        for entry in entries:
            try:
                if not entry.is_dir() or not entry.name.startswith("pagedrop_"):
                    continue
                resolved = entry.resolve()
                if resolved in _live_dirs or resolved in _live_backend_dirs:
                    continue
                owner_file = entry / _OWNER_FILE
                if owner_file.exists():
                    if _owner_process_alive(resolved):
                        continue
                else:
                    # No owner: could be mid-claim on another worker — don't race it.
                    age = now - entry.stat().st_mtime
                    if age < _ORPHAN_NO_OWNER_GRACE_SEC:
                        continue
                shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue
