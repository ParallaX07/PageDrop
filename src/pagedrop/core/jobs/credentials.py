"""In-memory PDF passwords for jobs — never persist or log secrets."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


class RuntimeCredentials:
    """One credential per resolved input path. Not picklable / not persistable."""

    __slots__ = ("_by_key",)

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}

    @staticmethod
    def path_key(path: str | Path) -> str:
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(Path(path))

    @staticmethod
    def lookup(passwords: Mapping[str, str] | None, path: str | Path) -> str | None:
        """Resolve *path* against a raw or path_key-keyed password map."""
        if not passwords:
            return None
        raw = str(path)
        found = passwords.get(raw)
        if found is not None:
            return found
        return passwords.get(RuntimeCredentials.path_key(raw))

    def get(self, path: str | Path) -> str | None:
        return self._by_key.get(self.path_key(path))

    def set(self, path: str | Path, password: str) -> None:
        self._by_key[self.path_key(path)] = password

    def discard(self, path: str | Path) -> None:
        self._by_key.pop(self.path_key(path), None)

    def clear(self) -> None:
        self._by_key.clear()

    def snapshot(self) -> dict[str, str]:
        """Copy of path_key → password for writers/extractors. Runtime-only."""
        return dict(self._by_key)

    def adopt(self, other: RuntimeCredentials, paths: list[str] | set[str]) -> None:
        """Copy credentials for *paths* from *other* (cross-tab / extract)."""
        for path in paths:
            password = other.get(path)
            if password is not None:
                self.set(path, password)

    def __len__(self) -> int:
        return len(self._by_key)

    def __repr__(self) -> str:
        # Never include password material.
        return f"RuntimeCredentials({len(self._by_key)} path(s))"

    def __str__(self) -> str:
        return repr(self)

    def __getstate__(self) -> object:
        raise TypeError(
            "RuntimeCredentials must not be pickled, logged, or persisted"
        )
