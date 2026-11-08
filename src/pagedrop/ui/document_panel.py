"""Document panel: facts about the open document."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtWidgets import QAbstractItemView, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from pagedrop.ui.list_row_delegate import VALUE_ROLE, ListRowDelegate
from pagedrop.ui.theme import SPACE_2, SPACE_4

EMPTY_TEXT = "No document open"
NOT_SAVED_TEXT = "Not saved yet"
UNAVAILABLE_TEXT = "Unavailable"
_LABELS = ("Pages", "Size", "Location", "Selection")


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class DocumentPanel(QWidget):
    """Pages, size, location and selection for the active document."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DocumentPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName("Document")
        self._values = dict.fromkeys(_LABELS, "")

        title = QLabel("Document")
        title.setObjectName("PanelTitle")
        title.setAccessibleName("Document title")

        self._status = QLabel(EMPTY_TEXT)
        self._status.setObjectName("PanelStatus")
        self._status.setAccessibleName(EMPTY_TEXT)
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._list = QListWidget()
        self._list.setObjectName("PanelList")
        self._list.setAccessibleName("Document")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocusProxy(self._list)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setItemDelegate(ListRowDelegate(self._list, elide_value=True))
        self._rows: dict[str, QListWidgetItem] = {}
        for label in _LABELS:
            item = QListWidgetItem(label)
            self._list.addItem(item)
            self._rows[label] = item

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        layout.setSpacing(SPACE_2)
        layout.addWidget(title)
        layout.addWidget(self._status)
        layout.addWidget(self._list, stretch=1)
        self.clear()

    # --- public API -------------------------------------------------------

    def set_document(self, pages: int, file_path: Path | str | None) -> None:
        """Show a document; *pages* is the caller's logical page count."""
        self._status.hide()
        self._list.show()
        self.set_page_count(pages)
        if file_path is None:
            self._set("Size", NOT_SAVED_TEXT)
            self._set("Location", NOT_SAVED_TEXT)
        else:
            path = Path(file_path)
            try:
                size = os.stat(path).st_size
            except OSError:
                self._set("Size", UNAVAILABLE_TEXT)
            else:
                self._set(
                    "Size",
                    QLocale().formattedDataSize(size, 1, QLocale.DataSizeFormat.DataSizeTraditionalFormat),
                )
            self._set("Location", str(path.parent), tooltip=str(path))
        self.set_selection(0, pages)

    def set_page_count(self, count: int) -> None:
        self._set("Pages", str(count))

    def set_selection(self, selected: int, total: int) -> None:
        if selected <= 0:
            self._set("Selection", "None")
        else:
            self._set("Selection", f"{selected} of {_plural(total, 'page')}")

    def clear(self) -> None:
        for label in _LABELS:
            self._set(label, "")
        self._list.hide()
        self._status.setText(EMPTY_TEXT)
        self._status.show()

    def facts(self) -> dict[str, str]:
        """Current value of each row, keyed by its label."""
        return dict(self._values)

    def status_text(self) -> str:
        return self._status.text() if not self._status.isHidden() else ""

    # --- internals --------------------------------------------------------

    def _set(self, label: str, value: str, *, tooltip: str = "") -> None:
        self._values[label] = value
        item = self._rows[label]
        item.setData(VALUE_ROLE, value)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{label}: {value}")
        item.setToolTip(tooltip or value)
