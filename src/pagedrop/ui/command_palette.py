"""Ctrl+Shift+P command palette — fuzzy-find over existing QActions."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


def action_label(action: QAction) -> str:
    """Display text for a QAction (ampersands stripped)."""
    return action.text().replace("&", "").strip()


def fuzzy_match(query: str, text: str) -> bool:
    """True when *query* is a substring or character subsequence of *text*."""
    q = query.casefold().strip()
    if not q:
        return True
    t = text.casefold()
    if q in t:
        return True
    i = 0
    for ch in t:
        if ch == q[i]:
            i += 1
            if i == len(q):
                return True
    return False


def collect_actions(root: QWidget) -> list[QAction]:
    """Gather labeled actions from a registry, or fall back to menu/toolbar scan."""
    registry = getattr(root, "_actions", None)
    if registry is not None and hasattr(registry, "values"):
        result = [a for a in registry.values() if action_label(a)]
        result.sort(key=lambda a: action_label(a).casefold())
        return result

    seen: set[int] = set()
    result: list[QAction] = []

    def _add(action: QAction | None) -> None:
        if action is None or action.isSeparator():
            return
        if action.menu() is not None:
            for child in action.menu().actions():
                _add(child)
            return
        label = action_label(action)
        if not label:
            return
        key = id(action)
        if key in seen:
            return
        seen.add(key)
        result.append(action)

    menubar = getattr(root, "menuBar", None)
    if callable(menubar):
        for action in menubar().actions():
            _add(action)

    for action in root.findChildren(QAction):
        _add(action)

    result.sort(key=lambda a: action_label(a).casefold())
    return result


class CommandPalette(QDialog):
    """Modal fuzzy finder that triggers the chosen QAction."""

    def __init__(self, actions: list[QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self.setWindowTitle("Command palette")
        self.setModal(True)
        self.setMinimumSize(420, 360)
        self._actions = [a for a in actions if a.isEnabled()]
        self._filtered: list[QAction] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…")
        self._input.setClearButtonEnabled(True)
        layout.addWidget(self._input)

        self._list = QListWidget()
        self._list.setObjectName("CommandPaletteList")
        self._list.setUniformItemSizes(True)
        layout.addWidget(self._list, 1)

        hint = QLabel("↑↓ select · Enter run · Esc close")
        hint.setObjectName("CommandPaletteHint")
        layout.addWidget(hint)

        self._input.textChanged.connect(self._refilter)
        self._input.returnPressed.connect(self._activate_current)
        self._list.itemActivated.connect(lambda _item: self._activate_current())
        self._refilter("")

    def _refilter(self, text: str) -> None:
        self._list.clear()
        self._filtered = [
            action
            for action in self._actions
            if fuzzy_match(text, action_label(action))
        ]
        for action in self._filtered:
            label = action_label(action)
            shortcut = action.shortcut().toString(
                QKeySequence.SequenceFormat.NativeText
            )
            item = QListWidgetItem(
                f"{label}    {shortcut}" if shortcut else label
            )
            item.setToolTip(label)
            self._list.addItem(item)
        if self._filtered:
            self._list.setCurrentRow(0)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._list.count():
            row = self._list.currentRow()
            if key == Qt.Key.Key_Down:
                row = min(row + 1, self._list.count() - 1)
            else:
                row = max(row - 1, 0)
            self._list.setCurrentRow(row)
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def _activate_current(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._filtered):
            return
        action = self._filtered[row]
        self.accept()
        action.trigger()
