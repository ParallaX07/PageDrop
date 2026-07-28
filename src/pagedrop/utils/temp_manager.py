from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

# 512 MiB session quota for drag_* + job_* dirs; raise only with a
# measured complaint. Upgrade: running byte counter if rglob-on-enforce profiles hot.
DEFAULT_MAX_BYTES = 512 * 1024 * 1024  # 512 MiB

# Live session roots in this process — multi-window must not scrub each other.
_live_dirs: set[Path] = set()

# Backend mkdtemp prefixes under gettempdir(); not TempManager session roots.
_BACKEND_TEMP_PREFIXES = ("pagedrop_office_", "pagedrop_lo_")


class TempManager:
    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="pagedrop_"))
        # Shared so drag_* / job_* eviction order is creation order, not mtime ties.
        self._subdir_counter = 0
        self._max_bytes = max_bytes
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
        """Remove crashed-run ``pagedrop_*`` session dirs; never live or backend temps."""
        temp_root = Path(tempfile.gettempdir())
        try:
            entries = list(temp_root.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                if not entry.is_dir() or not entry.name.startswith("pagedrop_"):
                    continue
                if entry.name.startswith(_BACKEND_TEMP_PREFIXES):
                    continue
                if entry.resolve() in _live_dirs:
                    continue
                shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue
