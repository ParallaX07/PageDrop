"""Process-owned local storage for verified update installers."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths

from pagedrop.utils.update_checker import ReleaseInfo, UpdateStorageError

_INSTALLER_RE = re.compile(r"^PageDrop-(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-Setup\.exe$")
_EXPIRY = timedelta(days=7)


class UpdateStorage:
    """Own one updater-cache session without touching files outside it."""

    def __init__(self, root: Path | None = None) -> None:
        base = root or (
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
            / "updates"
        )
        self.root = base.absolute()
        if self.root.is_symlink():
            raise UpdateStorageError("Update storage directory must not be a link")
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.root / uuid.uuid4().hex
        self.session_dir.mkdir()
        self._lock = QLockFile(str(self.session_dir / ".active.lock"))
        self._lock.setStaleLockTime(0)
        if not self._lock.tryLock(0):
            raise UpdateStorageError("Could not reserve update storage")
        self.cleanup()

    def destination(self, release: ReleaseInfo) -> Path:
        return self.session_dir / release.installer_name

    def reusable_installer(self, release: ReleaseInfo) -> Path | None:
        candidate = self.destination(release)
        if not self._owned_file(candidate):
            return None
        if candidate.stat().st_size != release.installer_size:
            candidate.unlink()
            return None
        with candidate.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest == release.expected_sha256:
            return candidate
        candidate.unlink()
        return None

    def cleanup(self, *, now: datetime | None = None) -> None:
        """Remove only inactive, expired installers and inactive partial files."""
        cutoff = (now or datetime.now(UTC)).timestamp() - _EXPIRY.total_seconds()
        for session in self.root.iterdir():
            if session == self.session_dir or session.is_symlink() or not session.is_dir():
                continue
            lock = QLockFile(str(session / ".active.lock"))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                continue
            try:
                for child in session.iterdir():
                    if child.is_symlink() or not child.is_file():
                        continue
                    if child.name.endswith(".part") and _INSTALLER_RE.fullmatch(child.name[:-5]):
                        child.unlink(missing_ok=True)
                    elif _INSTALLER_RE.fullmatch(child.name) and child.stat().st_mtime < cutoff:
                        child.unlink(missing_ok=True)
            finally:
                lock.unlock()

    def close(self) -> None:
        self._lock.unlock()

    def _owned_file(self, path: Path) -> bool:
        return path.parent == self.session_dir and not path.is_symlink() and path.is_file()
