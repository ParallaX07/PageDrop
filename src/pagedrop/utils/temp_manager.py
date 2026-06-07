from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path


class TempManager:
    def __init__(self) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="pagedrop_"))
        self._drag_counter = 0
        atexit.register(self.cleanup)

    def get_dir(self) -> Path:
        return self._dir

    def create_drag_dir(self) -> Path:
        self._drag_counter += 1
        drag_dir = self._dir / f"drag_{self._drag_counter}"
        drag_dir.mkdir(parents=True, exist_ok=True)
        return drag_dir

    def cleanup_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path.exists():
                path.unlink()

    def cleanup(self) -> None:
        if self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)
