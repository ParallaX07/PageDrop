"""Tools hub — searchable category grid hosted as an editor tab."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, Qt, QObject, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.capabilities import (
    PI_HEIF,
    PILLOW,
    TESSDATA,
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
from pagedrop.ui.tool_page import StatusFooter
from pagedrop.utils.temp_manager import TempManager

if TYPE_CHECKING:
    pass

CATEGORIES: tuple[str, ...] = (
    "Organize",
    "Convert",
    "Modify",
    "Optimize",
    "Secure",
)

_GRID_COLUMNS = 3
_TILE_MIN_HEIGHT = 88
_TILE_MIN_HEIGHT_COMPACT = 64


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
    action: str | None = None  # "merge" | "create_pdf" | "organize" | "convert_to_pdf" | "export_from_pdf" | "office_to_pdf" | "optimize_secure" | "modify" | "ocr" | "extract_tables"


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
        "Side-by-side text and visual diff",
        "Organize",
        keywords=("diff", "heatmap", "side-by-side", "compare"),
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
        "convert_to_pdf",
        "Convert to PDF",
        "SVG, XPS, ebooks, text, HTML, and more → PDF",
        "Convert",
        keywords=("import", "svg", "epub", "markdown", "html", "cbz"),
        action="convert_to_pdf",
    ),
    ToolEntry(
        "export_from_pdf",
        "Export from PDF",
        "PNG, JPEG, WebP, SVG, text, JSON/XML, CBZ, tables",
        "Convert",
        keywords=("export", "png", "jpeg", "webp", "svg", "csv"),
        action="export_from_pdf",
    ),
    ToolEntry(
        "office_to_pdf",
        "Office to PDF",
        "Word, Excel, PowerPoint → PDF via Office or LibreOffice",
        "Convert",
        keywords=("word", "excel", "powerpoint", "docx", "xlsx", "pptx", "libreoffice"),
        action="office_to_pdf",
    ),
    ToolEntry(
        "ocr_pdf",
        "OCR to searchable PDF",
        "Add a text layer via tessdata (new file)",
        "Convert",
        keywords=("ocr", "tesseract", "searchable", "scan", "tessdata"),
        capability_id=TESSDATA,
        action="ocr",
    ),
    ToolEntry(
        "extract_tables",
        "Extract tables",
        "Export tables to CSV, JSON, or Excel",
        "Convert",
        keywords=("tables", "csv", "json", "xlsx", "excel", "spreadsheet"),
        action="extract_tables",
    ),
    ToolEntry(
        "crop",
        "Crop pages",
        "Crop by margins (CropBox or rebuild)",
        "Modify",
        keywords=("trim", "margins", "cropbox"),
        action="modify",
    ),
    ToolEntry(
        "watermark",
        "Watermark",
        "Text or image watermark on every page",
        "Modify",
        keywords=("stamp", "overlay", "confidential"),
        action="modify",
    ),
    ToolEntry(
        "header_footer",
        "Header & footer",
        "Add header and footer text with page tokens",
        "Modify",
        keywords=("header", "footer", "running"),
        action="modify",
    ),
    ToolEntry(
        "page_numbers",
        "Page numbers",
        "Stamp page numbers on every page",
        "Modify",
        keywords=("numbering", "folio"),
        action="modify",
    ),
    ToolEntry(
        "bates",
        "Bates numbers",
        "Sequential Bates stamps across one or more files",
        "Modify",
        keywords=("bates", "exhibit", "stamp"),
        action="modify",
    ),
    ToolEntry(
        "bookmarks",
        "Bookmarks & TOC",
        "Edit bookmarks and generate a TOC page",
        "Modify",
        keywords=("outline", "toc", "contents"),
        action="modify",
    ),
    ToolEntry(
        "annotations",
        "Remove / flatten annotations",
        "Strip annotations or bake form appearances",
        "Modify",
        keywords=("flatten", "bake", "markup", "forms"),
        action="modify",
    ),
    ToolEntry(
        "blank_pages",
        "Blank pages",
        "Detect and remove blank pages (with confirm)",
        "Modify",
        keywords=("empty", "detect", "remove"),
        action="modify",
    ),
    ToolEntry(
        "color_effects",
        "Color effects",
        "Greyscale, invert, or background tint",
        "Modify",
        keywords=("greyscale", "grayscale", "invert", "scanner"),
        action="modify",
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
        "import_heic",
        "HEIC to PDF",
        "Convert HEIC/HEIF images to PDF",
        "Convert",
        keywords=("heic", "heif", "apple", "photo"),
        capability_id=PI_HEIF,
        coming_soon=True,
    ),
    ToolEntry(
        "compress",
        "Compress PDF",
        "Reduce file size with a new copy",
        "Optimize",
        keywords=("shrink", "optimize"),
        action="optimize_secure",
    ),
    ToolEntry(
        "repair",
        "Repair PDF",
        "Rewrite a clean copy of a damaged PDF",
        "Optimize",
        keywords=("fix", "rewrite", "recover"),
        action="optimize_secure",
    ),
    ToolEntry(
        "encrypt",
        "Encrypt PDF",
        "Password-protect a new copy",
        "Secure",
        keywords=("password", "protect", "permissions"),
        action="optimize_secure",
    ),
    ToolEntry(
        "decrypt",
        "Decrypt PDF",
        "Write an unlocked copy (password required)",
        "Secure",
        keywords=("password", "unlock", "remove password"),
        action="optimize_secure",
    ),
    ToolEntry(
        "sanitize",
        "Sanitize PDF",
        "Strip metadata and optional annotations",
        "Secure",
        keywords=("scrub", "metadata", "privacy", "annotations"),
        action="optimize_secure",
    ),
)


def _matches_query(entry: ToolEntry, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        (entry.title, entry.description, entry.category, *entry.keywords)
    ).casefold()
    # Multi-token: every whitespace-separated term must appear in the haystack.
    return all(term in haystack for term in query.casefold().split())


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
        self._compact = False
        self._hovered = False
        self.setObjectName("ToolTile")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(_TILE_MIN_HEIGHT)
        self.setToolTip(entry.description)

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

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.setMinimumHeight(
            _TILE_MIN_HEIGHT_COMPACT if compact else _TILE_MIN_HEIGHT
        )
        margins = (10, 8, 10, 8) if compact else (14, 12, 14, 12)
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.setContentsMargins(*margins)
            layout.setSpacing(2 if compact else 4)
        self._refresh_chrome()

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
                hovered=self._hovered,
                blocked=blocked,
                coming_soon=self.entry.coming_soon and not blocked,
                compact=self._compact,
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

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._refresh_chrome()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._refresh_chrome()
        super().leaveEvent(event)

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


class ToolsWindow(QWidget):
    """Searchable Tools catalogue; job progress via BusyOverlay + status `…`."""

    WINDOW_TITLE = "Tools"
    PAGE_ID = "tools"

    def __init__(
        self,
        editor: QWidget | None = None,
        window_manager: object | None = None,
    ) -> None:
        super().__init__(None)
        self._editor = editor
        self._window_manager = window_manager  # kept for callers; unused for quit
        self.tool_page_id = self.PAGE_ID
        self._job_running = False
        self._cancel_token: CancelToken | None = None
        self._job_runner: SerializedJobRunner | None = None
        self._tiles: list[ToolTile] = []
        self._category_sections: dict[str, QWidget] = {}
        self._category_headings: dict[str, QToolButton] = {}
        self._category_grids: dict[str, QWidget] = {}
        self._collapsed_categories: set[str] = set()
        self._show_upcoming = False
        self._compact = False
        self._grid_columns = _GRID_COLUMNS
        self._status = StatusFooter(initial="Choose a tool")

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setObjectName("ToolsWindow")
        self.setMinimumSize(560, 420)

        self._nav_filter = _TileArrowNavFilter(self)
        self._build_ui()
        self.installEventFilter(self._nav_filter)
        self._apply_filter("")

    @property
    def tab_title(self) -> str:
        return self.WINDOW_TITLE

    def statusBar(self) -> StatusFooter:  # noqa: N802
        return self._status

    def set_editor(self, editor: QWidget | None) -> None:
        self._editor = editor

    @property
    def editor(self) -> QWidget | None:
        return self._editor

    def show_toast(self, message: str, *, kind: str = "info") -> None:
        self._toast.show_toast(message, kind=kind)

    def show_result(self, path: str | Path) -> None:
        self._result_bar.show_for(path)

    def job_runner(self) -> SerializedJobRunner:
        if self._job_runner is None:
            from pagedrop.ui.organize_tools import ensure_organize_runner

            self._job_runner = ensure_organize_runner(TempManager())
        return self._job_runner

    def request_close(self) -> bool:
        """Return False to abort closing this tab."""
        if not self._job_running:
            return True
        if not prompt_cancel_running_job(self, window_title=self.WINDOW_TITLE):
            return False
        self.cancel_active_job()
        self.end_job(status="Cancelled", toast="Job cancelled", toast_kind="info")
        return True

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(12)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search = QLineEdit()
        self._search.setObjectName("ToolsSearch")
        self._search.setPlaceholderText("Search tools…")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Search tools")
        self._search.textChanged.connect(self._apply_filter)
        self._search.returnPressed.connect(self._focus_first_visible_tile)
        search_row.addWidget(self._search, stretch=1)

        self._compact_btn = QToolButton()
        self._compact_btn.setObjectName("ToolsDensityToggle")
        self._compact_btn.setText("Compact")
        self._compact_btn.setCheckable(True)
        self._compact_btn.setToolTip("Toggle compact tile density")
        self._compact_btn.setAccessibleName("Compact density")
        self._compact_btn.toggled.connect(self._set_compact)
        search_row.addWidget(self._compact_btn)
        root.addLayout(search_row)

        self._match_label = QLabel()
        self._match_label.setObjectName("ToolsMatchCount")
        self._match_label.hide()
        root.addWidget(self._match_label)

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

            heading = QToolButton()
            heading.setObjectName("ToolsCategoryHeading")
            heading.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            heading.setArrowType(Qt.ArrowType.DownArrow)
            heading.setCheckable(True)
            heading.setChecked(True)
            heading.setAutoRaise(True)
            heading.setText(category)
            heading.setAccessibleName(f"{category} category")
            heading.toggled.connect(
                lambda checked, c=category: self._on_category_toggled(c, checked)
            )
            section_layout.addWidget(heading)

            grid_host = QWidget()
            grid_host.setObjectName("ToolsCategoryGrid")
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            section_layout.addWidget(grid_host)

            self._category_sections[category] = section
            self._category_headings[category] = heading
            self._category_grids[category] = grid_host
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

        self._upcoming_btn = QToolButton()
        self._upcoming_btn.setObjectName("ToolsUpcomingToggle")
        self._upcoming_btn.setCheckable(True)
        self._upcoming_btn.setAutoRaise(True)
        self._upcoming_btn.setToolTip("Show or hide tools that are not available yet")
        self._upcoming_btn.toggled.connect(self._on_upcoming_toggled)
        self._catalogue_layout.addWidget(self._upcoming_btn)

        self._catalogue_layout.addStretch(1)

        self._result_bar = ResultActionsBar()
        self._result_bar.preview_requested.connect(self._on_preview_result)
        self._result_bar.open_in_editor_requested.connect(self._on_open_result)
        self._result_bar.show_in_folder_requested.connect(self._on_show_folder)
        root.addWidget(self._result_bar)
        root.addWidget(self._status)

        self._busy_overlay = BusyOverlay(self)
        self._busy_overlay.set_cancellable(True)
        self._busy_overlay.cancelled.connect(self.cancel_active_job)
        self._toast = ToastOverlay(self)

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
        self._result_bar.clear()
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

    def _focus_first_visible_tile(self) -> None:
        tiles = self.visible_tiles()
        if tiles:
            tiles[0].setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _set_compact(self, compact: bool) -> None:
        self._compact = compact
        for tile in self._tiles:
            tile.set_compact(compact)

    def _on_category_toggled(self, category: str, expanded: bool) -> None:
        if expanded:
            self._collapsed_categories.discard(category)
        else:
            self._collapsed_categories.add(category)
        heading = self._category_headings[category]
        heading.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        grid_host = self._category_grids[category]
        # Only show grid when expanded and the section itself is visible.
        if self._category_sections[category].isVisible():
            grid_host.setVisible(expanded)

    def _on_upcoming_toggled(self, show: bool) -> None:
        self._show_upcoming = show
        self._apply_filter(self._search.text())

    def _upcoming_matching(self, query: str) -> int:
        return sum(
            1
            for entry in TOOL_CATALOGUE
            if entry.coming_soon and _matches_query(entry, query)
        )

    def _eligible_total(self, category: str) -> int:
        return sum(
            1
            for entry in TOOL_CATALOGUE
            if entry.category == category
            and (self._show_upcoming or not entry.coming_soon)
        )

    def _apply_filter(self, text: str) -> None:
        query = text.strip()
        any_visible = False
        match_count = 0

        for category in CATEGORIES:
            section = self._category_sections[category]
            heading = self._category_headings[category]
            grid_host = self._category_grids[category]
            grid = grid_host.layout()
            assert isinstance(grid, QGridLayout)

            while grid.count():
                grid.takeAt(0)

            visible_in_category: list[ToolTile] = []
            for tile in self._tiles:
                if tile.entry.category != category:
                    continue
                if tile.entry.coming_soon and not self._show_upcoming:
                    tile.hide()
                    continue
                if _matches_query(tile.entry, query):
                    visible_in_category.append(tile)
                else:
                    tile.hide()

            for index, tile in enumerate(visible_in_category):
                row, col = divmod(index, self._grid_columns)
                grid.addWidget(tile, row, col)
                tile.show()

            # Empty columns keep equal share so a lone tile doesn't full-bleed.
            for col in range(self._grid_columns):
                grid.setColumnStretch(col, 1)
            for col in range(self._grid_columns, 8):
                grid.setColumnStretch(col, 0)

            shown = len(visible_in_category)
            total = self._eligible_total(category)
            if query:
                heading.setText(f"{category} ({shown} of {total})")
            else:
                heading.setText(f"{category} ({total})")

            expanded = category not in self._collapsed_categories
            heading.blockSignals(True)
            heading.setChecked(expanded)
            heading.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
            heading.blockSignals(False)

            section_visible = shown > 0
            section.setVisible(section_visible)
            grid_host.setVisible(section_visible and expanded)
            any_visible = any_visible or section_visible
            match_count += shown

        self._empty_label.setVisible(not any_visible)

        if query:
            noun = "tool" if match_count == 1 else "tools"
            self._match_label.setText(f"{match_count} {noun} match")
            self._match_label.show()
        else:
            self._match_label.hide()

        upcoming_n = self._upcoming_matching(query)
        if self._show_upcoming:
            self._upcoming_btn.setText("Hide upcoming tools")
            self._upcoming_btn.setVisible(upcoming_n > 0 or self._show_upcoming)
        else:
            self._upcoming_btn.setText(f"Show upcoming tools ({upcoming_n})")
            self._upcoming_btn.setVisible(upcoming_n > 0)
        self._upcoming_btn.blockSignals(True)
        self._upcoming_btn.setChecked(self._show_upcoming)
        self._upcoming_btn.blockSignals(False)

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
            return
        if entry.action in {"convert_to_pdf", "export_from_pdf"}:
            from pagedrop.ui.native_convert_shell import open_conversion_shell

            open_conversion_shell(self, entry.id)
            return
        if entry.action == "office_to_pdf":
            from pagedrop.ui.office_convert_window import open_office_convert_shell

            open_office_convert_shell(self)
            return
        if entry.action == "optimize_secure":
            from pagedrop.ui.optimize_secure_shell import open_optimize_secure_shell

            open_optimize_secure_shell(self, entry.id)
            return
        if entry.action == "modify":
            from pagedrop.ui.modify_tools_shell import open_modify_shell

            open_modify_shell(self, entry.id)
            return
        if entry.action in {"ocr", "extract_tables"}:
            from pagedrop.ui.ocr_shell import open_ocr_shell

            open_ocr_shell(self, entry.id)
            return

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

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.request_close():
            event.ignore()
            return
        super().closeEvent(event)
