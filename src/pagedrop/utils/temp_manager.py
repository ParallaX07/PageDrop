from __future__ import annotations

import atexit
import os
import shutil
import stat
import sys
import tempfile
import threading
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
_STILL_ACTIVE = 259  # GetExitCodeProcess value while the process runs


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
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            # An exited process stays openable while any handle to it lives,
            # so a successful open alone does not mean it is running.
            code = wintypes.DWORD()
            try:
                ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            finally:
                kernel32.CloseHandle(handle)
            return bool(ok) and code.value == _STILL_ACTIVE
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


def process_is_alive(pid: int) -> bool:
    """Cross-platform process liveness probe without signalling Windows consoles."""
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
        # Guards the counter, dir creation, pins and eviction: the GUI drag path
        # and the job runner worker share one manager.
        self._lock = threading.Lock()
        self._pinned: set[Path] = set()
        _write_owner_pid(self._dir)
        _live_dirs.add(self._dir.resolve())
        self._scrub_orphan_pagedrop_dirs()
        atexit.register(self.cleanup)

    def get_dir(self) -> Path:
        return self._dir

    def create_drag_dir(self) -> Path:
        with self._lock:
            self._enforce_max_size()
            self._subdir_counter += 1
            drag_dir = self._dir / f"drag_{self._subdir_counter}"
            drag_dir.mkdir(parents=True, exist_ok=True)
            return drag_dir

    def create_job_dir(self) -> Path:
        """Directory for a Tools job's staged output (promote or cleanup).

        The dir is pinned (never evicted) until :meth:`unpin_dir`.
        """
        with self._lock:
            self._enforce_max_size()
            self._subdir_counter += 1
            job_dir = self._dir / f"job_{self._subdir_counter}"
            job_dir.mkdir(parents=True, exist_ok=True)
            self._pinned.add(job_dir)
            return job_dir

    def unpin_dir(self, path: Path) -> None:
        """Make a pinned job dir evictable again (its job has finished)."""
        with self._lock:
            self._pinned.discard(path)

    def remove_dir(self, path: Path) -> None:
        """Best-effort removal of *path* (a drag/job dir); never raises."""
        with self._lock:
            self._pinned.discard(path)
        shutil.rmtree(path, ignore_errors=True)

    def cleanup_paths(self, paths: list[Path]) -> None:
        drag_dirs: set[Path] = set()
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            drag_dirs.add(path.parent)
        for drag_dir in drag_dirs:
            try:
                if drag_dir.is_dir() and not any(drag_dir.iterdir()):
                    drag_dir.rmdir()
            except OSError:
                pass

    def cleanup(self) -> None:
        resolved = self._dir.resolve() if self._dir.exists() else self._dir
        _live_dirs.discard(resolved)
        if self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)

    def _dir_size(self) -> int:
        # Full rglob on each create: cheap while session dirs stay small. Callers
        # (job handlers, drag extraction) write outside the lock and can remove
        # files mid-walk, so a vanished entry just counts as zero. A running
        # counter would need write hooks (upgrade if enforce shows up in profiles).
        if not self._dir.exists():
            return 0
        total = 0
        for path in self._dir.rglob("*"):
            try:
                info = path.stat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
        return total

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
        """Evict oldest unpinned drag_*/job_* dirs until under quota (caller holds the lock).

        One pass: a dir that cannot be removed is skipped, never retried.
        """
        if self._dir_size() <= self._max_bytes:
            return
        candidates = sorted(
            (
                d
                for d in self._dir.iterdir()
                if d.is_dir()
                and d not in self._pinned
                and (d.name.startswith("drag_") or d.name.startswith("job_"))
            ),
            key=self._evict_dir_sort_key,
        )
        for candidate in candidates:
            shutil.rmtree(candidate, ignore_errors=True)
            if self._dir_size() <= self._max_bytes:
                return

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
