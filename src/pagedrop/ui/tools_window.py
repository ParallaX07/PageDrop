"""Modeless Tools hub — searchable category grid over local utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, Qt, QObject, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.capabilities import (
    PILLOW,
    AbsenceReason,
    CapabilityStatus,
    probe,
)
from pagedrop.core.jobs import CancelToken, SerializedJobRunner
from pagedrop.ui.busy_overlay import BusyOverlay, ToastOverlay
from pagedrop.ui.dialogs import prompt_cancel_running_job, prompt_missing_capability
from pagedrop.ui.organize_tools import launch_organize_tool
from pagedrop.ui.result_actions import (
    ResultActionsBar,
    open_in_editor,
    preview_pdf,
    show_in_folder,
)
from pagedrop.ui.theme import tool_tile_stylesheet
from pagedrop.utils.temp_manager import TempManager

if TYPE_CHECKING:
    from pagedrop.ui.window_manager import WindowManager

CATEGORIES: tuple[str, ...] = (
    "Organize",
    "Convert",
    "Optimize",
    "Secure",
    "View",
)

_GRID_COLUMNS = 3


@dataclass(frozen=True)
class ToolEntry:
    """Catalogue entry for one Tools hub tile."""

    id: str
    title: str
    description: str
    category: str
    keywords: tuple[str, ...] = ()
    capability_id: str | None = None
    coming_soon: bool = False
    action: str | None = None  # "merge" | "create_pdf"


# Shell catalogue: wired actions + placeholders later phases fill in.
TOOL_CATALOGUE: tuple[ToolEntry, ...] = (
    ToolEntry(
        "merge",
        "Merge PDFs",
        "Combine PDFs into one file",
        "Organize",
        keywords=("combine", "join"),
        action="merge",
    ),
    ToolEntry(
        "split",
        "Split / extract",
        "Split by ranges into new files",
        "Organize",
        keywords=("extract", "ranges", "split"),
        action="organize",
    ),
    ToolEntry(
        "alternate",
        "Alternate pages",
        "Mix pages from two PDFs",
        "Organize",
        keywords=("interleave", "mix"),
        action="organize",
    ),
    ToolEntry(
        "reverse",
        "Reverse pages",
        "Reverse order; optional blank page",
        "Organize",
        keywords=("flip", "blank"),
        action="organize",
    ),
    ToolEntry(
        "n_up",
        "N-up",
        "Pack pages onto a grid",
        "Organize",
        keywords=("impose", "grid", "2-up", "4-up"),
        action="organize",
    ),
    ToolEntry(
        "booklet",
        "Booklet",
        "Simple 2-up booklet imposition",
        "Organize",
        keywords=("impose", "print"),
        action="organize",
    ),
    ToolEntry(
        "posterize",
        "Posterize",
        "Split each page into tiles",
        "Organize",
        keywords=("tiles", "poster"),
        action="organize",
    ),
    ToolEntry(
        "divide",
        "Divide pages",
        "Split each page horizontally or vertically",
        "Organize",
        keywords=("halve", "cut"),
        action="organize",
    ),
    ToolEntry(
        "combine",
        "Combine to long page",
        "Stack all pages into one long page",
        "Organize",
        keywords=("scroll", "strip"),
        action="organize",
    ),
    ToolEntry(
        "normalize",
        "Normalize page size",
        "Fit or fill pages to a target size",
        "Organize",
        keywords=("resize", "paper", "a4", "letter"),
        action="organize",
    ),
    ToolEntry(
        "attachments",
        "Attachments",
        "List, add, extract, or remove embedded files",
        "Organize",
        keywords=("embed", "embfile"),
        action="organize",
    ),
    ToolEntry(
        "metadata",
        "Metadata",
        "View, edit, or strip document info",
        "Organize",
        keywords=("info", "xmp", "strip"),
        action="organize",
    ),
    ToolEntry(
        "page_labels",
        "Page labels",
        "Set PDF page label style",
        "Organize",
        keywords=("roman", "numbering"),
        action="organize",
    ),
    ToolEntry(
        "zip",
        "ZIP PDFs",
        "Pack PDFs into a ZIP archive",
        "Organize",
        keywords=("archive", "compress"),
        action="organize",
    ),
    ToolEntry(
        "compare",
        "Compare PDFs",
        "Visual sample diff with a heatmap PDF",
        "Organize",
        keywords=("diff", "heatmap"),
        action="organize",
    ),
    ToolEntry(
        "create_pdf",
        "Create PDF",
        "Build a PDF from images",
        "Convert",
        keywords=("images", "photos"),
        action="create_pdf",
    ),
    ToolEntry(
        "export_tiff",
        "Export TIFF",
        "Export pages as TIFF images",
        "Convert",
        keywords=("image", "tiff"),
        capability_id=PILLOW,
        coming_soon=True,
    ),
    ToolEntry(
        "compress",
        "Compress PDF",
        "Reduce file size with a new copy",
        "Optimize",
        keywords=("shrink", "optimize"),
        coming_soon=True,
    ),
    ToolEntry(
        "encrypt",
        "Encrypt PDF",
        "Password-protect a new copy",
        "Secure",
        keywords=("password", "protect"),
        coming_soon=True,
    ),
    ToolEntry(
        "viewer",
        "PDF viewer",
        "Read and navigate pages",
        "View",
        keywords=("read", "preview"),
        coming_soon=True,
    ),
)


def _matches_query(entry: ToolEntry, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        (entry.title, entry.description, entry.category, *entry.keywords)
    ).casefold()
    return query.casefold() in haystack


def _absence_subtitle(status: CapabilityStatus) -> str:
    reason = status.reason or AbsenceReason.ENGINE_MISSING
    labels = {
        AbsenceReason.ENGINE_MISSING: "Engine missing",
        AbsenceReason.DATA_MISSING: "Data missing",
        AbsenceReason.CODEC_MISSING: "Codec missing",
        AbsenceReason.LICENCE_BLOCKED: "Licence blocked",
    }
    return labels.get(reason, "Unavailable")


class ToolTile(QFrame):
    """Focusable catalogue card; Enter/Space activates."""

    activated = pyqtSignal(str)

    def __init__(self, entry: ToolEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("ToolTile")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(88)

        self._capability: CapabilityStatus | None = None
        if entry.capability_id is not None:
            self._capability = probe(entry.capability_id)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self._title = QLabel(entry.title)
        self._title.setObjectName("ToolTileTitle")
        layout.addWidget(self._title)

        self._subtitle = QLabel(self._subtitle_text())
        self._subtitle.setObjectName("ToolTileSubtitle")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._refresh_chrome()

    def _subtitle_text(self) -> str:
        if self._capability is not None and not self._capability.available:
            return f"{_absence_subtitle(self._capability)} — {self.entry.description}"
        if self.entry.coming_soon and self.entry.action is None:
            return f"Coming soon — {self.entry.description}"
        return self.entry.description

    def is_blocked(self) -> bool:
        return self._capability is not None and not self._capability.available

    def refresh_capability(self) -> None:
        if self.entry.capability_id is None:
            return
        self._capability = probe(self.entry.capability_id, refresh=False)
        self._subtitle.setText(self._subtitle_text())
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        blocked = self.is_blocked()
        self.setProperty("blocked", blocked)
        self.setProperty("comingSoon", self.entry.coming_soon and not blocked)
        self.setStyleSheet(
            tool_tile_stylesheet(
                focused=self.hasFocus(),
                blocked=blocked,
                coming_soon=self.entry.coming_soon and not blocked,
            )
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.entry.id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.entry.id)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._refresh_chrome()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._refresh_chrome()


class _TileArrowNavFilter(QObject):
    """Arrow keys move focus between visible tool tiles."""

    def __init__(self, window: ToolsWindow) -> None:
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or not isinstance(event, QKeyEvent):
            return False
        key = event.key()
        if key not in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            return False
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            return False
        tiles = self._window.visible_tiles()
        if not tiles:
            return False
        focus = self._window.focusWidget()
        if not isinstance(focus, ToolTile) or focus not in tiles:
            return False
        index = tiles.index(focus)
        cols = max(1, self._window.grid_columns())
        if key == Qt.Key.Key_Left:
            index = max(0, index - 1)
        elif key == Qt.Key.Key_Right:
            index = min(len(tiles) - 1, index + 1)
        elif key == Qt.Key.Key_Up:
            index = max(0, index - cols)
        else:
            index = min(len(tiles) - 1, index + cols)
        tiles[index].setFocus(Qt.FocusReason.TabFocusReason)
        return True


class ToolsWindow(QMainWindow):
    """Searchable Tools catalogue; job progress via BusyOverlay + status `…`."""

    WINDOW_TITLE = "Tools"

    def __init__(
        self,
        editor: QWidget | None = None,
        window_manager: WindowManager | None = None,
    ) -> None:
        # Top-level (no QObject parent) so closing the last editor keeps Tools alive.
        super().__init__(None)
        self._editor = editor
        self._window_manager = window_manager
        self._job_running = False
        self._cancel_token: CancelToken | None = None
        self._job_runner: SerializedJobRunner | None = None
        self._tiles: list[ToolTile] = []
        self._category_sections: dict[str, QWidget] = {}
        self._grid_columns = _GRID_COLUMNS

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setObjectName("ToolsWindow")
        self.setMinimumSize(560, 420)
        self.resize(720, 560)

        self._nav_filter = _TileArrowNavFilter(self)
        self._build_ui()
        self.installEventFilter(self._nav_filter)
        self._apply_filter("")
        self.statusBar().showMessage("Choose a tool")

    def set_editor(self, editor: QWidget | None) -> None:
        self._editor = editor

    def job_runner(self) -> SerializedJobRunner:
        if self._job_runner is None:
            from pagedrop.ui.organize_tools import ensure_organize_runner

            self._job_runner = ensure_organize_runner(TempManager())
        return self._job_runner

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("ToolsCentral")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(12)

        self._search = QLineEdit()
        self._search.setObjectName("ToolsSearch")
        self._search.setPlaceholderText("Search tools…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        root.addWidget(self._search)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("ToolsScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self._scroll, stretch=1)

        self._catalogue = QWidget()
        self._catalogue.setObjectName("ToolsCatalogue")
        self._catalogue_layout = QVBoxLayout(self._catalogue)
        self._catalogue_layout.setContentsMargins(0, 0, 8, 0)
        self._catalogue_layout.setSpacing(16)
        self._scroll.setWidget(self._catalogue)

        for category in CATEGORIES:
            section = QWidget()
            section.setObjectName("ToolsCategorySection")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(8)

            heading = QLabel(category)
            heading.setObjectName("ToolsCategoryHeading")
            section_layout.addWidget(heading)

            grid_host = QWidget()
            grid_host.setObjectName("ToolsCategoryGrid")
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            section_layout.addWidget(grid_host)

            self._category_sections[category] = section
            self._catalogue_layout.addWidget(section)

            for entry in TOOL_CATALOGUE:
                if entry.category != category:
                    continue
                tile = ToolTile(entry)
                tile.activated.connect(self._on_tile_activated)
                tile.installEventFilter(self._nav_filter)
                self._tiles.append(tile)

        self._empty_label = QLabel("No tools match your search.")
        self._empty_label.setObjectName("ToolsEmptyState")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.hide()
        self._catalogue_layout.addWidget(self._empty_label)
        self._catalogue_layout.addStretch(1)

        self._result_bar = ResultActionsBar()
        self._result_bar.preview_requested.connect(self._on_preview_result)
        self._result_bar.open_in_editor_requested.connect(self._on_open_result)
        self._result_bar.show_in_folder_requested.connect(self._on_show_folder)
        root.addWidget(self._result_bar)

        self._busy_overlay = BusyOverlay(central)
        self._toast = ToastOverlay(central)

    def grid_columns(self) -> int:
        return self._grid_columns

    def visible_tiles(self) -> list[ToolTile]:
        return [t for t in self._tiles if t.isVisible()]

    def is_job_running(self) -> bool:
        return self._job_running

    def begin_job(self, message: str = "Working…") -> CancelToken:
        """Show BusyOverlay + progress status (must end with `…`)."""
        if not message.endswith("…"):
            message = f"{message.rstrip('.')}…"
        self._job_running = True
        self._cancel_token = CancelToken()
        self._result_bar.clear()
        self._busy_overlay.show_message(message)
        self.statusBar().showMessage(message)
        self._search.setEnabled(False)
        return self._cancel_token

    def set_job_progress(self, _fraction: float, message: str) -> None:
        if not self._job_running:
            return
        if message and not message.endswith("…") and message != "Done":
            message = f"{message.rstrip('.')}…"
        if message == "Done":
            return
        self._busy_overlay.show_message(message or "Working…")
        self.statusBar().showMessage(message or "Working…")

    def end_job(
        self,
        *,
        status: str | None = None,
        toast: str | None = None,
        toast_kind: str = "info",
        result_path: str | None = None,
        error: str | None = None,
    ) -> None:
        self._job_running = False
        self._cancel_token = None
        self._busy_overlay.hide_overlay()
        self._search.setEnabled(True)
        if error:
            self.statusBar().showMessage("Job failed")
            self._toast.show_toast(toast or "Job failed", kind="error")
            QMessageBox.critical(self, self.WINDOW_TITLE, error)
            return
        if status:
            self.statusBar().showMessage(status)
        if toast:
            self._toast.show_toast(toast, kind=toast_kind)
        if result_path:
            self._result_bar.show_for(result_path)

    def cancel_active_job(self) -> None:
        if self._cancel_token is not None:
            self._cancel_token.cancel()

    def _apply_filter(self, text: str) -> None:
        query = text.strip()
        any_visible = False
        for category in CATEGORIES:
            section = self._category_sections[category]
            grid_host = section.findChild(QWidget, "ToolsCategoryGrid")
            assert grid_host is not None
            grid = grid_host.layout()
            assert isinstance(grid, QGridLayout)

            while grid.count():
                grid.takeAt(0)

            visible_in_category: list[ToolTile] = []
            for tile in self._tiles:
                if tile.entry.category != category:
                    continue
                if _matches_query(tile.entry, query):
                    visible_in_category.append(tile)
                else:
                    tile.hide()

            for index, tile in enumerate(visible_in_category):
                row, col = divmod(index, self._grid_columns)
                grid.addWidget(tile, row, col)
                tile.show()

            section.setVisible(bool(visible_in_category))
            any_visible = any_visible or bool(visible_in_category)

        self._empty_label.setVisible(not any_visible)

    def _on_tile_activated(self, tool_id: str) -> None:
        entry = next((e for e in TOOL_CATALOGUE if e.id == tool_id), None)
        if entry is None:
            return
        tile = next((t for t in self._tiles if t.entry.id == tool_id), None)

        if entry.capability_id is not None:
            status = probe(entry.capability_id)
            if not status.available:
                result = prompt_missing_capability(
                    self, status, tool_title=entry.title
                )
                if tile is not None:
                    tile.refresh_capability()
                if result == "recheck":
                    status = probe(entry.capability_id)
                    if not status.available:
                        return
                else:
                    return

        if entry.coming_soon or entry.action is None:
            self.statusBar().showMessage(f"{entry.title} is coming soon")
            self._toast.show_toast(f"{entry.title} is coming soon", kind="info")
            return

        editor = self._editor
        if entry.action == "organize":
            launch_organize_tool(self, entry.id)
            return
        if entry.action == "merge":
            open_fn = getattr(editor, "_open_merge_window", None)
            if callable(open_fn):
                open_fn()
            return
        if entry.action == "create_pdf":
            open_fn = getattr(editor, "_open_convert_window", None)
            if callable(open_fn):
                open_fn()

    def _on_preview_result(self, path: str) -> None:
        preview_pdf(path, parent=self)

    def _on_open_result(self, path: str) -> None:
        editor = self._editor
        if editor is None:
            self._toast.show_toast("No editor window available", kind="error")
            return
        try:
            open_in_editor(path, editor)
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.WINDOW_TITLE,
                f"Could not open in editor:\n{exc}",
            )
            return
        self._toast.show_toast(f"Opened {Path(path).name}", kind="success")

    def _on_show_folder(self, path: str) -> None:
        if not show_in_folder(path):
            QMessageBox.warning(
                self,
                self.WINDOW_TITLE,
                "Could not open the folder for this file.",
            )
            return
        self._toast.show_toast("Opened folder", kind="info")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        width = max(1, self._scroll.viewport().width())
        cols = max(1, min(4, width // 200))
        if cols != self._grid_columns:
            self._grid_columns = cols
            self._apply_filter(self._search.text())
        parent = self._busy_overlay.parentWidget()
        if parent is not None:
            self._busy_overlay.setGeometry(parent.rect())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._job_running:
            if not prompt_cancel_running_job(self, window_title=self.WINDOW_TITLE):
                event.ignore()
                return
            self.cancel_active_job()
            self.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
        super().closeEvent(event)
        # quitOnLastWindowClosed is False — deferred quit after last editor.
        if event.isAccepted() and self._window_manager is not None:
            self._window_manager.notify_utility_closed(self)
