from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

DEFAULT_MAX_BYTES = 512 * 1024 * 1024  # 512 MiB


class TempManager:
    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="pagedrop_"))
        self._drag_counter = 0
        self._max_bytes = max_bytes
        atexit.register(self.cleanup)

    def get_dir(self) -> Path:
        return self._dir

    def create_drag_dir(self) -> Path:
        self._enforce_max_size()
        self._drag_counter += 1
        drag_dir = self._dir / f"drag_{self._drag_counter}"
        drag_dir.mkdir(parents=True, exist_ok=True)
        return drag_dir

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
        if self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)

    def _dir_size(self) -> int:
        if not self._dir.exists():
            return 0
        return sum(
            path.stat().st_size for path in self._dir.rglob("*") if path.is_file()
        )

    def _enforce_max_size(self) -> None:
        while self._dir_size() > self._max_bytes:
            drag_dirs = sorted(
                (d for d in self._dir.glob("drag_*") if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
            )
            if not drag_dirs:
                break
            shutil.rmtree(drag_dirs[0], ignore_errors=True)
