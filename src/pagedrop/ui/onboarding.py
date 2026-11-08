"""First-run tips overlay and keyboard shortcut reference."""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6 import sip
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pagedrop.ui.command_palette import action_label
from pagedrop.ui.settings import (
    has_seen_context_hint,
    set_has_seen_context_hint,
    set_has_seen_tips,
)

# A tiny orientation only; detailed shortcuts remain available in Help.
FIRST_RUN_TIPS: tuple[tuple[str, str], ...] = (
    ("Open", "Toolbar Open or File → Open PDF (Ctrl+O)."),
    ("Drop zone", "Drop a PDF onto an empty tab to open it."),
)

# Gestures that are not QActions; action shortcuts are read from the window.
GESTURE_GROUP: tuple[str, tuple[tuple[str, str], ...]] = (
    "Mouse and keyboard",
    (
        ("Move between pages", "Arrow keys"),
        ("Select a range of pages", "Shift+click"),
        ("Add or remove a page from the selection", "Ctrl+click"),
        ("Preview page", "Enter · double-click"),
        ("Clear selection or close preview", "Esc"),
        ("Thumbnail zoom", "Ctrl+scroll"),
        ("Copy pages to another window or the file manager", "Drag pages out"),
        ("Move instead of copy between windows", "Shift+drop"),
    ),
)

# Display order for action categories; unknown ones follow alphabetically.
_CATEGORY_ORDER = ("Document", "Pages", "View", "Tools")


def shortcut_groups(
    actions: Iterable[QAction],
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Group the actions that have shortcuts by command category, then add gestures."""
    by_category: dict[str, list[tuple[str, str]]] = {}
    for action in actions:
        label = action_label(action)
        keys = [
            seq.toString(QKeySequence.SequenceFormat.NativeText)
            for seq in action.shortcuts()
        ]
        if not label or not keys:
            continue
        category = str(action.property("commandCategory") or "Document")
        by_category.setdefault(category, []).append((label, ", ".join(keys)))
    ordered = sorted(
        by_category,
        key=lambda name: (
            _CATEGORY_ORDER.index(name) if name in _CATEGORY_ORDER else len(_CATEGORY_ORDER),
            name,
        ),
    )
    groups = [(name, by_category[name]) for name in ordered]
    groups.append((GESTURE_GROUP[0], list(GESTURE_GROUP[1])))
    return groups


class TipsOverlay(QWidget):
    """Dimmed first-run callout card; dismiss writes ``has_seen_tips``."""

    dismissed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TipsOverlay")
        # Without this the QSS dim background on a plain QWidget is not painted.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._prev_focus: QWidget | None = None
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(24, 24, 24, 24)

        card = QWidget()
        card.setObjectName("TipsOverlayCard")
        card.setMaximumWidth(420)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)

        title = QLabel("Quick tips")
        title.setObjectName("TipsOverlayTitle")
        card_layout.addWidget(title)

        intro = QLabel("A few places to start:")
        intro.setObjectName("TipsOverlayIntro")
        card_layout.addWidget(intro)

        for name, body in FIRST_RUN_TIPS:
            row = QLabel(f"<b>{name}</b>: {body}")
            row.setObjectName("TipsOverlayTip")
            row.setWordWrap(True)
            row.setTextFormat(Qt.TextFormat.RichText)
            card_layout.addWidget(row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._got_it = QPushButton("Got it")
        self._got_it.setObjectName("TipsOverlayDismiss")
        self._got_it.clicked.connect(self._dismiss)
        buttons.addWidget(self._got_it)
        card_layout.addLayout(buttons)

        layout.addWidget(card)

        if parent is not None:
            parent.installEventFilter(self)

    def show_tips(self) -> None:
        if not self.isVisible():
            self._prev_focus = QApplication.focusWidget()
        self._sync_geometry()
        self.show()
        self.raise_()
        self._got_it.setFocus(Qt.FocusReason.OtherFocusReason)

    def _dismiss(self) -> None:
        set_has_seen_tips(True)
        self.hide()
        prev, self._prev_focus = self._prev_focus, None
        if prev is not None and not sip.isdeleted(prev) and prev.isVisible():
            prev.setFocus(Qt.FocusReason.OtherFocusReason)
        self.dismissed.emit()

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: A002, N802
        # Got it is the only control; keep Tab from reaching widgets behind.
        return True

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_geometry()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._dismiss()
            return
        super().keyPressEvent(event)

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())


class ContextHint(QWidget):
    """Small non-modal, one-time cue anchored beside the relevant control."""

    def __init__(self, parent: QWidget, anchor: QWidget, key: str, text: str) -> None:
        super().__init__(parent)
        self.setObjectName("ContextHint")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._key = key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)
        label = QLabel(text)
        label.setObjectName("ContextHintText")
        label.setWordWrap(True)
        label.setMaximumWidth(300)
        layout.addWidget(label)
        dismiss = QPushButton("Got it")
        dismiss.setObjectName("ContextHintDismiss")
        dismiss.clicked.connect(self.dismiss)
        layout.addWidget(dismiss)
        self.setAccessibleName(text)
        self.adjustSize()
        self._place(anchor)

    def _place(self, anchor: QWidget) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        point = anchor.mapTo(parent, QPoint(anchor.width(), anchor.height()))
        x = min(max(8, point.x() - self.width()), max(8, parent.width() - self.width() - 8))
        y = min(max(8, point.y() + 8), max(8, parent.height() - self.height() - 8))
        self.move(x, y)

    def dismiss(self) -> None:
        set_has_seen_context_hint(self._key)
        self.deleteLater()


def show_context_hint(parent: QWidget, anchor: QWidget, key: str, text: str) -> ContextHint | None:
    """Show a cue at most once without taking focus or blocking interaction."""
    if has_seen_context_hint(key):
        return None
    # Mark on presentation so an ignored cue cannot nag on every later action.
    set_has_seen_context_hint(key)
    hint = ContextHint(parent, anchor, key, text)
    hint.show()
    hint.raise_()
    return hint


class KeyboardShortcutsDialog(QDialog):
    """Categorized shortcut reference (Help → Keyboard Shortcuts)."""

    def __init__(
        self, actions: Iterable[QAction], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("KeyboardShortcutsDialog")
        self.setWindowTitle("Keyboard shortcuts")
        self.setModal(True)
        # The list scrolls, so the dialog may shrink below its comfortable size.
        self.setMinimumSize(320, 240)
        self.resize(480, 520)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        scroll = QScrollArea()
        scroll.setObjectName("ShortcutsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(16)

        for category, entries in shortcut_groups(actions):
            heading = QLabel(category)
            heading.setObjectName("ShortcutCategory")
            body_layout.addWidget(heading)

            for action, keys in entries:
                row = QHBoxLayout()
                name_label = QLabel(action)
                name_label.setObjectName("ShortcutAction")
                name_label.setWordWrap(True)
                keys_label = QLabel(keys)
                keys_label.setObjectName("ShortcutKeys")
                keys_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                keys_label.setWordWrap(True)
                row.addWidget(name_label, 1)
                row.addWidget(keys_label, 1)
                body_layout.addLayout(row)

        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close.setDefault(True)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)
        root.addLayout(footer)
