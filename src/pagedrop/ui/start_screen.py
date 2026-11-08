"""Start screen: what a tab with no document shows."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pagedrop.assets import logo_pixmap
from pagedrop.ui.list_row_delegate import VALUE_ROLE, ListRowDelegate
from pagedrop.ui.settings import recent_file_entries
from pagedrop.ui.theme import SPACE_2, SPACE_3, SPACE_6, SPACE_7

COLUMN_MAX_WIDTH = 440
LOGO_SIZE = 64
MISSING_TEXT = "Missing"
NO_RECENT_TEXT = "No recent files"
PATH_ROLE = Qt.ItemDataRole.UserRole


class StartScreen(QWidget):
    """Open actions and recent files, filling the tab.

    Drag and drop is forwarded to the tab's thumbnail grid, so PDFs and page
    transfers take the one path they take everywhere else.
    """

    recent_file_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StartScreen")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setAccessibleName("Open a PDF")
        self.setAccessibleDescription(
            "Arrange pages, extract selections, or combine documents"
        )
        # The tab's floor must not depend on how many recent files there are.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._drop_target: QWidget | None = None
        self._actions: tuple[QAction, QAction, QAction] | None = None

        self._logo = QLabel()
        self._logo.setObjectName("GridEmptyLogo")
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo.setAccessibleName("PageDrop logo")

        self._title = QLabel("Open a PDF")
        self._title.setObjectName("GridEmptyState")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._drop_hint = QLabel("or drop a file here")
        self._drop_hint.setObjectName("GridEmptyKbd")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._open_button = QPushButton("Open PDF")
        self._open_button.setObjectName("EmptyStateOpenButton")
        self._merge_button = QPushButton("Merge PDFs")
        self._tools_button = QPushButton("All tools")
        for button in (self._merge_button, self._tools_button):
            button.setObjectName("ToolbarSecondary")
        self._buttons = (self._open_button, self._merge_button, self._tools_button)
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE_3)
        buttons.setContentsMargins(0, SPACE_3, 0, 0)
        buttons.addStretch(1)
        for index, button in enumerate(self._buttons):
            button.setAccessibleName(button.text())
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.clicked.connect(lambda _checked=False, i=index: self._trigger(i))
            buttons.addWidget(button)
        buttons.addStretch(1)

        self._recent_title = QLabel("Recent files")
        self._recent_title.setObjectName("StartScreenSection")
        self._recent_title.setAccessibleName("Recent files heading")

        self._recent = QListWidget()
        self._recent.setObjectName("PanelList")
        self._recent.setAccessibleName("Recent files")
        self._recent.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._recent.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._recent.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._recent.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._recent.setItemDelegate(ListRowDelegate(self._recent, elide_value=True))
        self._recent.itemClicked.connect(self._on_recent_item)
        self._recent.installEventFilter(self)

        self._no_recent = QLabel(NO_RECENT_TEXT)
        self._no_recent.setObjectName("PanelStatus")
        self._no_recent.setAlignment(Qt.AlignmentFlag.AlignCenter)

        column = QWidget()
        column.setObjectName("StartScreenColumn")
        column.setMaximumWidth(COLUMN_MAX_WIDTH)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(SPACE_2)
        column_layout.addWidget(self._logo)
        column_layout.addWidget(self._title)
        column_layout.addWidget(self._drop_hint)
        column_layout.addLayout(buttons)
        column_layout.addSpacing(SPACE_6)
        column_layout.addWidget(self._recent_title)
        column_layout.addWidget(self._recent)
        column_layout.addWidget(self._no_recent)

        # Stretch on both sides centres the column; the scroll area takes over
        # when the tab is too short for it.
        content = QWidget()
        content.setObjectName("StartScreenContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(SPACE_6, SPACE_7, SPACE_6, SPACE_7)
        content_layout.addStretch(1)
        content_layout.addWidget(column, 0, Qt.AlignmentFlag.AlignHCenter)
        content_layout.addStretch(2)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("StartScreenScroll")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)

        QWidget.setTabOrder(self._open_button, self._merge_button)
        QWidget.setTabOrder(self._merge_button, self._tools_button)
        QWidget.setTabOrder(self._tools_button, self._recent)
        self.refresh_recent()

    # --- public API -------------------------------------------------------

    def bind_actions(
        self, open_action: QAction, merge_action: QAction, tools_action: QAction
    ) -> None:
        """Make the three buttons a projection of the window's own actions."""
        if self._actions is not None:
            for action in self._actions:
                try:
                    action.changed.disconnect(self._sync_actions)
                except (TypeError, RuntimeError):
                    # The old action may belong to a window that is already gone.
                    pass
        self._actions = (open_action, merge_action, tools_action)
        for action in self._actions:
            action.changed.connect(self._sync_actions)
        self._sync_actions()

    def set_drop_target(self, target: QWidget | None) -> None:
        """Widget whose drag and drop handlers receive this screen's events."""
        self._drop_target = target

    @property
    def open_button(self) -> QPushButton:
        return self._open_button

    @property
    def merge_button(self) -> QPushButton:
        return self._merge_button

    @property
    def tools_button(self) -> QPushButton:
        return self._tools_button

    @property
    def recent_list(self) -> QListWidget:
        return self._recent

    def refresh_recent(self) -> None:
        """Rebuild the list from the stored recents, marking files that went missing."""
        self._recent.clear()
        entries = recent_file_entries()
        for path, exists in entries:
            file = Path(path)
            item = QListWidgetItem(file.name)
            item.setData(PATH_ROLE, path)
            item.setData(VALUE_ROLE, str(file.parent) if exists else MISSING_TEXT)
            item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"{file.name}, {file.parent}" if exists else f"{file.name}, missing",
            )
            item.setToolTip(path)
            self._recent.addItem(item)
        has_recent = bool(entries)
        self._recent_title.setVisible(has_recent)
        self._recent.setVisible(has_recent)
        self._no_recent.setVisible(not has_recent)
        self._fit_recent_height()

    def _fit_recent_height(self) -> None:
        # The page scrolls as a whole; the list never needs a bar of its own.
        count = self._recent.count()
        if count:
            self._recent.ensurePolished()
            row = self._recent.sizeHintForRow(0)
            self._recent.setFixedHeight(
                row * count + 2 * self._recent.frameWidth()
            )

    # --- drag and drop ----------------------------------------------------

    def _set_drop_active(self, active: bool) -> None:
        if bool(self.property("dropActive")) == active:
            return
        self.setProperty("dropActive", active)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def _forward(self, handler: str, event) -> bool:
        target = self._drop_target
        if target is None:
            event.ignore()
            return False
        getattr(target, handler)(event)
        return event.isAccepted()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._set_drop_active(self._forward("dragEnterEvent", event))

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._set_drop_active(self._forward("dragMoveEvent", event))

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drop_active(False)
        self._forward("dragLeaveEvent", event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drop_active(False)
        self._forward("dropEvent", event)

    # --- internals --------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        pixmap = logo_pixmap(logical_size=LOGO_SIZE, device_pixel_ratio=self.devicePixelRatioF())
        if pixmap.isNull():
            self._logo.clear()
        else:
            self._logo.setPixmap(pixmap)
        # A file may have gone since the list was built.
        self.refresh_recent()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._recent and event.type() == QEvent.Type.StyleChange:
            # Item padding comes from the style sheet, which can change after the first fit.
            self._fit_recent_height()
        if (
            watched is self._recent
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            item = self._recent.currentItem()
            if item is not None:
                self._on_recent_item(item)
                return True
        return super().eventFilter(watched, event)

    def _on_recent_item(self, item: QListWidgetItem) -> None:
        path = item.data(PATH_ROLE)
        if isinstance(path, str) and path:
            self.recent_file_requested.emit(path)

    def _trigger(self, index: int) -> None:
        if self._actions is not None:
            self._actions[index].trigger()

    def _sync_actions(self) -> None:
        if self._actions is None:
            return
        for button, action in zip(self._buttons, self._actions, strict=True):
            name = action.text().replace("&", "")
            button.setText(name)
            button.setAccessibleName(name)
            button.setEnabled(action.isEnabled())
            button.setToolTip(action.toolTip() or name)
