"""Named QAction registry — one action feeds menu, toolbar, and shortcuts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import QWidget


class ActionRegistry:
    """``dict[str, QAction]`` with a small register helper.

    Call sites keep string keys (``actions[\"open\"]``) instead of scavenging
    ``findChildren(QAction)`` when a stable catalogue is needed.
    """

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._actions: dict[str, QAction] = {}

    def register(
        self,
        key: str,
        text: str,
        *,
        slot: Callable[..., Any] | None = None,
        shortcut: QKeySequence | QKeySequence.StandardKey | str | None = None,
        shortcuts: list[QKeySequence | QKeySequence.StandardKey | str]
        | None = None,
        checkable: bool = False,
        checked: bool = False,
        enabled: bool = True,
        icon: QIcon | None = None,
        tip: str | None = None,
        data: object = None,
        add_to_window: bool = False,
    ) -> QAction:
        if key in self._actions:
            raise KeyError(f"action already registered: {key!r}")

        action = QAction(text, self._parent)
        if icon is not None:
            action.setIcon(icon)
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
        action.setEnabled(enabled)
        if data is not None:
            action.setData(data)
        if tip is not None:
            action.setToolTip(tip)
            action.setStatusTip(tip)

        if shortcuts is not None:
            action.setShortcuts(
                [
                    s if isinstance(s, QKeySequence) else QKeySequence(s)
                    for s in shortcuts
                ]
            )
        elif shortcut is not None:
            action.setShortcut(
                shortcut
                if isinstance(shortcut, QKeySequence)
                else QKeySequence(shortcut)
            )

        # WindowShortcut: with multiple windows open, ApplicationShortcut
        # collides ("Ambiguous shortcut overload") and Qt fires neither.
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)

        if slot is not None:
            if checkable:
                action.toggled.connect(slot)
            else:
                action.triggered.connect(slot)

        if add_to_window:
            self._parent.addAction(action)

        self._actions[key] = action
        return action

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._actions

    def __getitem__(self, key: str) -> QAction:
        return self._actions[key]

    def get(self, key: str, default: QAction | None = None) -> QAction | None:
        return self._actions.get(key, default)

    def values(self) -> list[QAction]:
        return list(self._actions.values())

    def items(self) -> list[tuple[str, QAction]]:
        return list(self._actions.items())

    def __iter__(self) -> Iterator[str]:
        return iter(self._actions)

    def __len__(self) -> int:
        return len(self._actions)
