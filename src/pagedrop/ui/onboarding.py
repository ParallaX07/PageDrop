"""First-run tips overlay and keyboard shortcut reference."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

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

# Grouped for Help → Keyboard Shortcuts. Ctrl+Tab is documented as MRU.
SHORTCUT_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "File",
        (
            ("Open PDF", "Ctrl+O"),
            ("Save as", "Ctrl+Shift+S"),
            ("New window", "Ctrl+Shift+N"),
        ),
    ),
    (
        "Pages",
        (
            ("Select all", "Ctrl+A"),
            ("Clear selection", "Esc"),
            ("Delete selected", "Delete"),
            ("Duplicate selected", "Ctrl+D"),
            ("Move selected up", "Ctrl+↑"),
            ("Move selected down", "Ctrl+↓"),
            ("Move to page", "Ctrl+Shift+M"),
            ("Undo", "Ctrl+Z"),
            ("Redo", "Ctrl+Shift+Z"),
        ),
    ),
    (
        "View",
        (
            ("Preview page", "Enter · double-click"),
            ("Go to page", "Ctrl+G"),
            ("Select pages", "Use Pages menu"),
            ("Reset zoom", "Ctrl+0"),
            ("Thumbnail zoom", "Ctrl+scroll"),
            ("Command palette", "Ctrl+Shift+P"),
            ("Tools", "Ctrl+Shift+O, not Ctrl+T (that opens a new tab)"),
            ("Keyboard shortcuts", "Ctrl+/"),
        ),
    ),
    (
        "Tabs",
        (
            (
                "Previous tab (MRU)",
                "Ctrl+Tab toggles the last two tabs, not sequential next",
            ),
            ("Cycle tabs backward", "Ctrl+Shift+Tab"),
            ("New tab", "Ctrl+T"),
            ("Close tab", "Ctrl+W"),
        ),
    ),
)


class TipsOverlay(QWidget):
    """Dimmed first-run callout card; dismiss writes ``has_seen_tips``."""

    dismissed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TipsOverlay")
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
        got_it = QPushButton("Got it")
        got_it.setObjectName("TipsOverlayDismiss")
        got_it.setDefault(True)
        got_it.clicked.connect(self._dismiss)
        buttons.addWidget(got_it)
        card_layout.addLayout(buttons)

        layout.addWidget(card)

        if parent is not None:
            parent.installEventFilter(self)

    def show_tips(self) -> None:
        self._sync_geometry()
        self.show()
        self.raise_()

    def _dismiss(self) -> None:
        set_has_seen_tips(True)
        self.hide()
        self.dismissed.emit()

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KeyboardShortcutsDialog")
        self.setWindowTitle("Keyboard shortcuts")
        self.setModal(True)
        self.setMinimumSize(480, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(16)

        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)

        for category, entries in SHORTCUT_GROUPS:
            heading = QLabel(category)
            heading.setObjectName("ShortcutCategory")
            body_layout.addWidget(heading)

            for action, keys in entries:
                row = QHBoxLayout()
                action_label = QLabel(action)
                action_label.setObjectName("ShortcutAction")
                action_label.setWordWrap(True)
                keys_label = QLabel(keys)
                keys_label.setObjectName("ShortcutKeys")
                keys_label.setFont(mono)
                keys_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                keys_label.setWordWrap(True)
                row.addWidget(action_label, 1)
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
