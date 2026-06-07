from __future__ import annotations

from pathlib import Path


class PdfMergeModel:
    """Ordered list of whole PDF files to merge."""

    def __init__(self) -> None:
        self._paths: list[str] = []

    def add_files(self, paths: list[str]) -> None:
        for path in paths:
            self._paths.append(str(Path(path).resolve()))

    def remove_at(self, index: int) -> None:
        del self._paths[index]

    def remove_indices(self, indices: list[int]) -> None:
        if not indices:
            return
        remove = set(indices)
        self._paths = [path for i, path in enumerate(self._paths) if i not in remove]

    def move_up(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[0] == 0:
            return
        self._move_files(ordered, ordered[0] - 1)

    def move_down(self, indices: list[int]) -> None:
        if not indices:
            return
        ordered = sorted(set(indices))
        if ordered[-1] >= len(self._paths) - 1:
            return
        self._move_files(ordered, ordered[-1] + 2)

    def reorder(self, from_index: int, to_index: int) -> None:
        if from_index == to_index:
            return
        item = self._paths.pop(from_index)
        self._paths.insert(to_index, item)

    def file_count(self) -> int:
        return len(self._paths)

    def path_at(self, index: int) -> str:
        return self._paths[index]

    def display_name(self, index: int) -> str:
        return Path(self._paths[index]).name

    def all_paths(self) -> list[str]:
        return list(self._paths)

    def _move_files(self, indices: list[int], to_index: int) -> None:
        ordered = sorted(set(indices))
        moving = [self._paths[i] for i in ordered]
        remaining = [path for i, path in enumerate(self._paths) if i not in set(ordered)]

        adjusted = to_index
        for i in ordered:
            if i < to_index:
                adjusted -= 1
        adjusted = max(0, min(adjusted, len(remaining)))

        remaining[adjusted:adjusted] = moving
        self._paths = remaining
