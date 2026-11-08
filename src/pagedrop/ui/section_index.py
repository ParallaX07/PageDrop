"""Sections pane: the document's top-level bookmarks as a list of jump targets."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QAbstractItemView, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.pdf_service import OutlineItem, outline_for_paths
from pagedrop.ui.editor_jobs import EditorJobWorker, release_editor_signals, start_editor_worker
from pagedrop.ui.list_row_delegate import MARKER_ROLE, VALUE_ROLE, ListRowDelegate
from pagedrop.ui.theme import SPACE_2, SPACE_4
from pagedrop.utils.diagnostics import log_failure

LOADING_TEXT = "Loading sections…"
EMPTY_TEXT = "No sections in this document"
FAILED_TEXT = "Sections could not be loaded"
_UNTITLED = "Untitled section"
_FIRST_LOGICAL_ROLE = Qt.ItemDataRole.UserRole + 3


@dataclass(frozen=True)
class SectionRow:
    title: str
    first_logical: int  # 0-based logical page index
    label: str  # "3" or "3–7": display page numbers, 1-based
    accessible_text: str


def build_section_rows(items: Sequence[OutlineItem], pages: Sequence[PageRef]) -> list[SectionRow]:
    """Top-level bookmarks mapped onto the current logical page order.

    A section covers its source pages from its own page up to the next
    top-level bookmark that starts later in the same source. When several
    bookmarks share a start page, the earlier ones cover that page only.
    """
    tops = [it for it in items if it.level == 1 and it.source_index >= 0]
    if not tops:
        return []

    # Per source: sorted distinct start pages, and the rows that start on each.
    starts: dict[str, list[int]] = {}
    owners: dict[tuple[str, int], list[int]] = {}
    for row_no, item in enumerate(tops):
        owners.setdefault((item.source_path, item.source_index), []).append(row_no)
    for source, start in owners:
        starts.setdefault(source, []).append(start)
    for values in starts.values():
        values.sort()

    first = [-1] * len(tops)
    last = [-1] * len(tops)
    count = [0] * len(tops)

    def add(row_no: int, logical: int) -> None:
        if count[row_no] == 0:
            first[row_no] = logical
        last[row_no] = logical
        count[row_no] += 1

    for logical, page in enumerate(pages):
        source_starts = starts.get(page.source_path)
        if not source_starts:
            continue
        pos = bisect_right(source_starts, page.source_index) - 1
        if pos < 0:
            continue
        group = owners[(page.source_path, source_starts[pos])]
        if page.source_index == source_starts[pos]:
            for row_no in group:
                add(row_no, logical)
        else:
            add(group[-1], logical)

    rows: list[SectionRow] = []
    for row_no, item in enumerate(tops):
        if count[row_no] == 0:
            continue
        title = item.title.strip() or _UNTITLED
        start = first[row_no] + 1
        end = last[row_no] + 1
        if count[row_no] > 1 and end - start + 1 == count[row_no]:
            label = f"{start}–{end}"
            spoken = f"pages {start} to {end}"
        else:
            label = str(start)
            spoken = f"page {start}"
        rows.append(SectionRow(title, first[row_no], label, f"{title}, {spoken}"))
    return rows


class SectionIndex(QWidget):
    """Read-only list of sections; activating one reports its first logical page."""

    section_activated = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SectionIndex")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName("Sections")
        self._generation = 0
        self._items: list[OutlineItem] | None = None
        self._pages: list[PageRef] | None = None
        self._failed = False
        self._loading = False
        self._shown: list[SectionRow] | None = None  # rows currently in the list
        self._index_colour: str | None = None

        title = QLabel("Sections")
        title.setObjectName("PanelTitle")
        title.setAccessibleName("Sections title")

        self._status = QLabel()
        self._status.setObjectName("PanelStatus")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._list = QListWidget()
        self._list.setObjectName("PanelList")
        self._list.setAccessibleName("Sections")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setItemDelegate(ListRowDelegate(self._list))
        self._list.itemActivated.connect(self._on_item_activated)
        self._list.itemClicked.connect(self._on_item_activated)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        layout.setSpacing(SPACE_2)
        layout.addWidget(title)
        layout.addWidget(self._status)
        layout.addWidget(self._list, stretch=1)
        self._render()

    # --- public API -------------------------------------------------------

    def load(self, paths: Sequence[Path | str], passwords: Mapping[str, str] | None = None) -> None:
        """Read the outline in the background; the latest call wins."""
        self._generation += 1
        generation = self._generation
        self._items = None
        self._failed = False
        self._loading = True
        self._render()

        path_list = [str(p) for p in paths]
        password_map = dict(passwords) if passwords else None

        def work(_progress) -> tuple[int, list[OutlineItem] | None, BaseException | None]:
            try:
                return generation, outline_for_paths(path_list, passwords=password_map), None
            except Exception as exc:
                return generation, None, exc

        worker = EditorJobWorker(work)
        signals = worker.signals
        signals.succeeded.connect(self._on_loaded)
        # Plain callables run on the GUI thread and survive this widget, so the
        # shared signal holder is always released.
        signals.succeeded.connect(lambda _result, s=signals: release_editor_signals(s))
        signals.failed.connect(lambda _message, s=signals: release_editor_signals(s))
        signals.cancelled.connect(lambda s=signals: release_editor_signals(s))
        start_editor_worker(worker)

    def refresh(self, pages: Iterable[PageRef]) -> None:
        """Remap the loaded outline onto *pages*; never touches a PDF."""
        self._pages = list(pages)
        self._render()

    def clear(self) -> None:
        self._generation += 1
        self._items = None
        self._pages = None
        self._failed = False
        self._loading = False
        self._render()

    def set_index_colour(self, name: str) -> None:
        self._index_colour = name
        for row in range(self._list.count()):
            self._list.item(row).setData(MARKER_ROLE, name)
        self._list.viewport().update()

    def status_text(self) -> str:
        """The quiet line shown in place of the list, or "" when rows are shown."""
        return self._status.text() if not self._status.isHidden() else ""

    def row_count(self) -> int:
        return self._list.count()

    # --- internals --------------------------------------------------------

    @pyqtSlot(object)
    def _on_loaded(self, result: object) -> None:
        generation, items, error = result  # type: ignore[misc]
        if generation != self._generation:
            return
        self._loading = False
        if error is not None:
            log_failure("Section outline load", error)
            self._failed = True
        else:
            self._items = items
        self._render()

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        logical = item.data(_FIRST_LOGICAL_ROLE)
        if isinstance(logical, int):
            self.section_activated.emit(logical)

    def _render(self) -> None:
        if self._failed:
            self._show_status(FAILED_TEXT)
            return
        if self._items is None:
            self._show_status(LOADING_TEXT if self._loading else "")
            return
        if self._pages is None:
            self._show_status(LOADING_TEXT)
            return
        rows = build_section_rows(self._items, self._pages)
        if not rows:
            self._show_status(EMPTY_TEXT)
            return
        if rows == self._shown:
            return  # an edit that left every section as it was
        current = self._list.currentItem()
        current_title = current.text() if current is not None else None
        scroll = self._list.verticalScrollBar().value()
        self._list.clear()
        self._status.setText("")
        self._status.setAccessibleName("")
        self._status.hide()
        self._list.show()
        for row in rows:
            item = QListWidgetItem(row.title)
            item.setData(VALUE_ROLE, row.label)
            item.setData(MARKER_ROLE, self._index_colour)
            item.setData(_FIRST_LOGICAL_ROLE, row.first_logical)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, row.accessible_text)
            item.setToolTip(row.title)
            self._list.addItem(item)
            if row.title == current_title and self._list.currentItem() is None:
                self._list.setCurrentItem(item)
        self._shown = rows
        self._list.verticalScrollBar().setValue(scroll)

    def _show_status(self, text: str) -> None:
        self._list.clear()
        self._shown = None
        self._status.setText(text)
        self._status.setAccessibleName(text)
        self._status.setVisible(bool(text))
        self._list.setVisible(not text)
