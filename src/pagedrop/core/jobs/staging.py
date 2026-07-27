"""Stage job outputs under TempManager; promote on success; cleanup otherwise."""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

from pagedrop.utils.temp_manager import TempManager


class JobStaging:
    """Owns one job's temp directory for staged writes."""

    def __init__(self, temp_manager: TempManager) -> None:
        self._temp_manager = temp_manager
        self._job_dir = temp_manager.create_job_dir()
        self._staged: list[Path] = []

    @property
    def job_dir(self) -> Path:
        return self._job_dir

    def stage_file(self, name: str = "output.pdf") -> Path:
        """Return a path inside the job dir for the handler to write."""
        path = self._job_dir / name
        self._staged.append(path)
        return path

    def promote(self, staged: Path, destination: Path) -> Path:
        """Move a validated staged file to the user destination."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(staged, destination)
        except OSError as exc:
            # /tmp is often a different filesystem from ~/Downloads.
            if exc.errno != errno.EXDEV:
                raise
            shutil.copyfile(staged, destination)
            staged.unlink()
        if staged in self._staged:
            self._staged.remove(staged)
        return destination

    def cleanup(self) -> None:
        """Remove staged files and the job directory (cancel / fail)."""
        self._temp_manager.cleanup_paths(list(self._staged))
        self._staged.clear()
        if self._job_dir.exists():
            for child in self._job_dir.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
            try:
                self._job_dir.rmdir()
            except OSError:
                pass
