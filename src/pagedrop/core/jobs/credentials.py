"""In-memory PDF passwords for jobs — never persist or log secrets."""

from __future__ import annotations

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

    def get(self, path: str | Path) -> str | None:
        return self._by_key.get(self.path_key(path))

    def set(self, path: str | Path, password: str) -> None:
        self._by_key[self.path_key(path)] = password

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
