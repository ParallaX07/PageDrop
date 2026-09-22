"""Ctrl+Shift+P command palette — fuzzy-find over existing QActions."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
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


def match_rank(query: str, text: str) -> int | None:
    """Rank an exact, prefix, substring, or subsequence command match."""
    q = query.casefold().strip()
    if not q:
        return 4
    t = text.casefold()
    if q == t:
        return 0
    if t.startswith(q):
        return 1
    if q in t:
        return 2
    i = 0
    for ch in t:
        if ch == q[i]:
            i += 1
            if i == len(q):
                return 3
    return None


def fuzzy_match(query: str, text: str) -> bool:
    """Backward-compatible boolean form of :func:`match_rank`."""
    return match_rank(query, text) is not None


def ranked_actions(actions: list[QAction], query: str) -> list[QAction]:
    """Return actions in deterministic label/synonym match order."""
    matches: list[tuple[int, str, QAction]] = []
    for action in actions:
        labels = [action_label(action), *(action.property("commandSynonyms") or [])]
        ranks = [rank for label in labels if (rank := match_rank(query, label)) is not None]
        if ranks:
            matches.append((min(ranks), action_label(action).casefold(), action))
    category_order = {"Document": 0, "Pages": 1, "View": 2, "Tools": 3}
    return [
        action
        for _rank, _label, action in sorted(
            matches,
            key=lambda match: (
                match[0],
                category_order.get(match[2].property("commandCategory"), 4),
                match[1],
            ),
        )
    ]


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
        self._actions = actions
        self._item_actions: list[QAction | None] = []
        self._return_focus = parent.focusWidget() if parent is not None else None

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
        self._item_actions = []
        query = text.strip()
        actions = ranked_actions(self._actions, query)
        if not query:
            actions = [action for action in actions if action.isEnabled()]
        else:
            actions = [
                action
                for action in actions
                if action.isEnabled() or action.property("unavailableReason")
            ]
        groups: dict[str, list[QAction]] = {}
        for action in actions:
            groups.setdefault(action.property("commandCategory") or "Document", []).append(action)
        for category, grouped_actions in groups.items():
            header = QListWidgetItem(category)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setData(
                Qt.ItemDataRole.AccessibleDescriptionRole, f"{category} commands"
            )
            self._list.addItem(header)
            self._item_actions.append(None)
            for action in grouped_actions:
                label = action_label(action)
                shortcut = action.shortcut().toString(
                    QKeySequence.SequenceFormat.NativeText
                )
                reason = (
                    action.property("unavailableReason") if not action.isEnabled() else ""
                )
                item = QListWidgetItem(f"{label}\t{shortcut}" if shortcut else label)
                item.setToolTip(reason or label)
                item.setData(
                    Qt.ItemDataRole.AccessibleDescriptionRole,
                    reason or f"{category} command",
                )
                if reason:
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(item)
                self._item_actions.append(action if action.isEnabled() else None)
        for row, action in enumerate(self._item_actions):
            if action is not None:
                self._list.setCurrentRow(row)
                return
        message = "No commands available" if not query else f"No commands match “{query}”"
        item = QListWidgetItem(message)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, message)
        self._list.addItem(item)
        self._item_actions.append(None)

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
        if row < 0 or row >= len(self._item_actions):
            return
        action = self._item_actions[row]
        if action is None:
            return
        self.accept()
        action.trigger()
        if self._return_focus is not None:
            QTimer.singleShot(0, self._return_focus.setFocus)
