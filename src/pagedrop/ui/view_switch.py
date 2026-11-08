"""Two-segment command-bar switch between the page grid and the pages view."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QWidget

from pagedrop.ui import icons
from pagedrop.ui.theme import ICON_SIZE, current_theme


class ViewSwitch(QWidget):
    """Icon-only grid / pages segments that drive one toggle action.

    The window owns the mode: it calls ``set_viewer_mode`` when the view
    changes. Clicking the segment you are not in triggers *action* (the same
    action the menu, palette and Esc use); clicking the current one does
    nothing. The switch is enabled whenever the action is.
    """

    def __init__(self, action: QAction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToolbarViewSwitch")
        self.setAccessibleName("View")
        self._action = action
        self._viewer_mode = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._grid_button = self._segment("grid-four", "Grid view", "first")
        self._pages_button = self._segment("book-open", "Pages view", "last")
        self._grid_button.clicked.connect(lambda: self._on_clicked(False))
        self._pages_button.clicked.connect(lambda: self._on_clicked(True))
        layout.addWidget(self._grid_button)
        layout.addWidget(self._pages_button)

        action.changed.connect(self._sync_enabled)
        self._sync_enabled()
        self.set_viewer_mode(False)
        icons.register_refresh(self._refresh_icons)

    def _segment(self, icon_name: str, label: str, position: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("ToolbarViewSegment")
        button.setProperty("segment", position)
        button.setProperty("iconName", icon_name)
        button.setCheckable(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._group.addButton(button)
        return button

    @property
    def segments(self) -> tuple[QToolButton, QToolButton]:
        """Grid and pages buttons, left to right."""
        return (self._grid_button, self._pages_button)

    def set_viewer_mode(self, viewer: bool) -> None:
        self._viewer_mode = viewer
        (self._pages_button if viewer else self._grid_button).setChecked(True)
        self._refresh_icons()

    def _on_clicked(self, to_viewer: bool) -> None:
        if to_viewer != self._viewer_mode:
            self._action.trigger()
        # The window decides whether the view changed; show what it decided.
        self.set_viewer_mode(self._viewer_mode)

    def _sync_enabled(self) -> None:
        self.setEnabled(self._action.isEnabled())

    def _refresh_icons(self) -> None:
        on_ink = current_theme().on_ink
        for button in self.segments:
            name = str(button.property("iconName"))
            button.setIcon(
                icons.icon(name, color=on_ink) if button.isChecked() else icons.icon(name)
            )
