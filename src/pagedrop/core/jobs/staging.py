"""Stage job outputs under TempManager; promote on success; cleanup otherwise."""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
from pathlib import Path

from pagedrop.core.jobs.errors import OutputExistsError
from pagedrop.utils.temp_manager import TempManager


class JobStaging:
    """Owns one job's temp directory for staged writes."""

    def __init__(self, temp_manager: TempManager) -> None:
        self._temp_manager = temp_manager
        self._job_dir = temp_manager.create_job_dir()
        self._staged: list[Path] = []
        self._published: dict[Path, tuple[int, int]] = {}

    @property
    def job_dir(self) -> Path:
        return self._job_dir

    def stage_file(self, name: str = "output.pdf") -> Path:
        """Return a path inside the job dir for the handler to write."""
        path = self._job_dir / name
        self._staged.append(path)
        return path

    def promote(self, staged: Path, destination: Path) -> Path:
        """Atomically replace *destination* with a validated staged file."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(staged, destination)
        except OSError as exc:
            # /tmp is often a different filesystem from ~/Downloads.
            if exc.errno != errno.EXDEV:
                raise
            fd, copy_path = tempfile.mkstemp(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".stage",
            )
            os.close(fd)
            copy_path = Path(copy_path)
            try:
                shutil.copyfile(staged, copy_path)
                os.replace(copy_path, destination)
            except Exception:
                copy_path.unlink(missing_ok=True)
                raise
            staged.unlink()
        if staged in self._staged:
            self._staged.remove(staged)
        return destination

    def promote_no_clobber(self, staged: Path, destination: Path) -> Path:
        """Publish *staged* only when *destination* did not already exist."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError as exc:
            raise OutputExistsError(str(destination)) from exc
        identity = _file_identity_from_fd(fd)
        try:
            with os.fdopen(fd, "wb") as output, staged.open("rb") as source:
                shutil.copyfileobj(source, output)
        except Exception:
            _unlink_if_owned(destination, identity)
            raise
        staged.unlink()
        if staged in self._staged:
            self._staged.remove(staged)
        self._published[destination] = identity
        return destination

    def remove_published(self, destination: Path) -> None:
        """Remove a no-clobber output only if this staging instance still owns it."""
        identity = self._published.pop(destination, None)
        if identity is not None:
            _unlink_if_owned(destination, identity)

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


def _file_identity_from_fd(fd: int) -> tuple[int, int]:
    stat = os.fstat(fd)
    return stat.st_dev, stat.st_ino


def _unlink_if_owned(path: Path, identity: tuple[int, int]) -> None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return
    if (stat.st_dev, stat.st_ino) == identity:
        path.unlink()
