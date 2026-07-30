"""Tools hub — searchable category grid hosted as an editor tab."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QSize, Qt, QObject, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pagedrop.core.capabilities import (
    LIBREOFFICE,
    OPENPYXL,
    TESSDATA,
    AbsenceReason,
    CapabilityStatus,
    probe,
)
from pagedrop.ui import icons
from pagedrop.ui.busy_overlay import ToastOverlay
from pagedrop.ui.dialogs import prompt_missing_capability
from pagedrop.ui.keyboard_nav import enable_toolbar_keyboard_navigation
from pagedrop.ui.organize_tools import launch_organize_tool
from pagedrop.ui.settings import light_theme
from pagedrop.ui.theme import TEXT_MUTED, TEXT_MUTED_LIGHT
from pagedrop.ui.tool_page import StatusFooter

_EMPTY_GLYPH_PX = 32

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
    icon: str | None = None  # Phosphor stem under assets/icons/
    # R19: detailed shell help popup; None → shell falls back to description.
    help_text: str | None = None


# Shell catalogue: wired actions + placeholders later phases fill in.
TOOL_CATALOGUE: tuple[ToolEntry, ...] = (
    ToolEntry(
        "merge",
        "Merge PDFs",
        "Combine PDFs into one file",
        "Organize",
        keywords=("combine", "join"),
        action="merge",
        icon="stack",
    ),
    ToolEntry(
        "split",
        "Split / extract",
        "Split by ranges into new files",
        "Organize",
        keywords=("extract", "ranges", "split"),
        action="organize",
        icon="scissors",
        help_text=(
            "Break one PDF into several new files by page ranges (for example "
            "1-3, 5, 8-10). Each range becomes its own PDF. Useful when you need "
            "chapters, attachments, or a subset of pages without editing the "
            "original. The source file is never overwritten."
        ),
    ),
    ToolEntry(
        "alternate",
        "Alternate pages",
        "Mix pages from two PDFs",
        "Organize",
        keywords=("interleave", "mix"),
        action="organize",
        icon="arrows-left-right",
        help_text=(
            "Interleave pages from two PDFs into one new file — page 1 from A, "
            "page 1 from B, page 2 from A, and so on. Handy for duplex scans "
            "that came out as separate front/back files, or for merging two "
            "related sequences. Output is a new PDF."
        ),
    ),
    ToolEntry(
        "reverse",
        "Reverse pages",
        "Reverse order; optional blank page",
        "Organize",
        keywords=("flip", "blank"),
        action="organize",
        icon="arrow-counter-clockwise",
        help_text=(
            "Flip the page order of a PDF (last page becomes first). Optionally "
            "add a blank page when reversing odd-length documents for duplex "
            "printing. Writes a new file; the original is unchanged."
        ),
    ),
    ToolEntry(
        "n_up",
        "N-up",
        "Pack pages onto a grid",
        "Organize",
        keywords=("impose", "grid", "2-up", "4-up"),
        action="organize",
        icon="grid-four",
        help_text=(
            "N-up means putting several original pages onto each sheet of the "
            "new PDF — for example 2-up (two pages side by side) or 4-up "
            "(a 2×2 grid). Choose rows and columns; PageDrop scales pages to "
            "fit the cells. Use it to save paper when printing handouts, or to "
            "make a compact overview. Output is a new PDF."
        ),
    ),
    ToolEntry(
        "booklet",
        "Booklet",
        "Simple 2-up booklet imposition",
        "Organize",
        keywords=("impose", "print"),
        action="organize",
        icon="book-open",
        help_text=(
            "Rearranges pages so that when you print double-sided and fold the "
            "stack in half, you get a simple booklet (like a folded pamphlet). "
            "Each sheet holds two pages (2-up), ordered for saddle-style "
            "folding. Print duplex, fold, and staple in the middle. Best for "
            "short documents; output is a new PDF ready to print."
        ),
    ),
    ToolEntry(
        "posterize",
        "Posterize",
        "Split each page into tiles",
        "Organize",
        keywords=("tiles", "poster"),
        action="organize",
        icon="bounding-box",
        help_text=(
            "Slice each page into a grid of tiles (rows × columns). Each tile "
            "becomes its own page in the new PDF so you can print a large page "
            "across several sheets and tape them into a poster. Pick how many "
            "rows and columns you need. The source file is not changed."
        ),
    ),
    ToolEntry(
        "divide",
        "Divide pages",
        "Split each page horizontally or vertically",
        "Organize",
        keywords=("halve", "cut"),
        action="organize",
        icon="columns",
        help_text=(
            "Cut every page in half — horizontally or vertically — so each "
            "half becomes its own page in a new PDF. Useful for scanned "
            "spreads, booklets that were scanned as one page, or two-up "
            "sheets you want to separate again."
        ),
    ),
    ToolEntry(
        "combine",
        "Combine to long page",
        "Stack all pages into one long page",
        "Organize",
        keywords=("scroll", "strip"),
        action="organize",
        icon="arrows-in-line-vertical",
        help_text=(
            "Stack every page of the PDF into one continuous tall (or wide) "
            "page — like a long screenshot strip. Handy for sharing a full "
            "document as a single scrollable page. Creates a new file."
        ),
    ),
    ToolEntry(
        "normalize",
        "Normalize page size",
        "Fit or fill pages to a target size",
        "Organize",
        keywords=("resize", "paper", "a4", "letter"),
        action="organize",
        icon="arrows-out",
        help_text=(
            "Make every page the same paper size (Letter, A4, and similar). "
            "Choose fit (scale to fit inside, may letterbox) or fill (cover "
            "the page, may crop). Useful before merging mixed-size scans or "
            "sending to a printer that expects one size. Writes a new PDF."
        ),
    ),
    ToolEntry(
        "attachments",
        "Attachments",
        "List, add, extract, or remove embedded files",
        "Organize",
        keywords=("embed", "embfile"),
        action="organize",
        icon="paperclip",
        help_text=(
            "PDFs can carry embedded files (attachments) inside them. List "
            "what is already embedded, add new files, extract copies to disk, "
            "or remove attachments. Changes are written to a new PDF so the "
            "original stays intact."
        ),
    ),
    ToolEntry(
        "metadata",
        "Metadata",
        "View, edit, or strip document info",
        "Organize",
        keywords=("info", "xmp", "strip"),
        action="organize",
        icon="info",
        help_text=(
            "Edit document properties such as title, author, subject, and "
            "keywords, or strip metadata for privacy. Load values from the "
            "current file, change them, and save a new PDF. The source file "
            "is never overwritten."
        ),
    ),
    ToolEntry(
        "page_labels",
        "Page labels",
        "Set PDF page label style",
        "Organize",
        keywords=("roman", "numbering"),
        action="organize",
        icon="list-numbers",
        help_text=(
            "Page labels are how a PDF names pages in the viewer (i, ii, iii "
            "for a preface, then 1, 2, 3 for the body). Set styles and ranges "
            "so the sidebar and print dialogs show the labels you want. This "
            "does not stamp numbers onto the page art — use Page numbers for "
            "that. Output is a new PDF."
        ),
    ),
    ToolEntry(
        "zip",
        "ZIP PDFs",
        "Pack PDFs into a ZIP archive",
        "Organize",
        keywords=("archive", "compress"),
        action="organize",
        icon="file-zip",
        help_text=(
            "Put one or more PDFs into a ZIP archive for sharing or backup. "
            "The PDFs themselves are not recompressed as PDF; they are packed "
            "as files inside the zip. Originals are left alone."
        ),
    ),
    ToolEntry(
        "compare",
        "Compare PDFs",
        "Side-by-side text and visual diff",
        "Organize",
        keywords=("diff", "heatmap", "side-by-side", "compare"),
        action="organize",
        icon="git-diff",
    ),
    ToolEntry(
        "create_pdf",
        "Create PDF",
        "Build a PDF from images",
        "Convert",
        keywords=("images", "photos"),
        action="create_pdf",
        icon="images",
    ),
    ToolEntry(
        "convert_to_pdf",
        "Convert to PDF",
        "SVG, XPS, ebooks, text, HTML, CSV, Excel, and more → PDF",
        "Convert",
        keywords=(
            "import",
            "svg",
            "epub",
            "markdown",
            "html",
            "cbz",
            "csv",
            "xlsx",
            "excel",
        ),
        action="convert_to_pdf",
        icon="file-arrow-down",
        help_text=(
            "Turn supported non-PDF files into a new PDF — SVG, XPS, ebooks, "
            "Markdown, HTML, text, CBZ, CSV, Excel, and similar. Drop one or "
            "more files and run. Layout fidelity depends on the format. The "
            "originals are left alone."
        ),
    ),
    ToolEntry(
        "export_from_pdf",
        "Export from PDF",
        "PNG, JPEG, WebP, SVG, text, JSON/XML, CBZ, tables",
        "Convert",
        keywords=("export", "png", "jpeg", "webp", "svg", "csv"),
        action="export_from_pdf",
        icon="export",
        help_text=(
            "Export pages or content out of a PDF into other formats — images "
            "(PNG, JPEG, WebP), SVG, plain text, structured JSON/XML, CBZ, or "
            "tables. Choose the format and options, then save new files. The "
            "PDF itself is not modified."
        ),
    ),
    ToolEntry(
        "office_to_pdf",
        "Office to PDF",
        "Word, Excel, PowerPoint → PDF via Office or LibreOffice",
        "Convert",
        keywords=(
            "word",
            "excel",
            "powerpoint",
            "docx",
            "xlsx",
            "csv",
            "pptx",
            "libreoffice",
        ),
        action="office_to_pdf",
        icon="file-doc",
        help_text=(
            "Convert Word, Excel, or PowerPoint documents to PDF using "
            "Microsoft Office (Windows) or LibreOffice when available. The "
            "status line names which engine ran. Output is a new PDF; the "
            "Office file is unchanged."
        ),
    ),
    ToolEntry(
        "pdf_to_word",
        "PDF to Word",
        "Convert PDF to DOCX via LibreOffice (layout may differ)",
        "Convert",
        keywords=("word", "docx", "libreoffice", "export"),
        capability_id=LIBREOFFICE,
        action="pdf_to_word",
        icon="file-doc",
        help_text=(
            "Convert a PDF to an editable Word (.docx) file via LibreOffice. "
            "Complex layouts, columns, and graphics may not match the PDF "
            "exactly — treat the result as a starting point for editing. "
            "Needs LibreOffice installed. Writes a new DOCX; the PDF is "
            "unchanged."
        ),
    ),
    ToolEntry(
        "ocr_pdf",
        "OCR to searchable PDF",
        "Add a text layer via tessdata (new file)",
        "Convert",
        keywords=("ocr", "tesseract", "searchable", "scan", "tessdata"),
        capability_id=TESSDATA,
        action="ocr",
        icon="scan",
        help_text=(
            "Optical character recognition (OCR) reads text from scanned or "
            "image-only pages and adds a searchable text layer to a new PDF. "
            "Needs tessdata language packs configured in settings. Pick "
            "languages that match the document. The original file is never "
            "overwritten."
        ),
    ),
    ToolEntry(
        "extract_tables",
        "Extract tables",
        "Export tables to CSV, JSON, or Excel",
        "Convert",
        keywords=("tables", "csv", "json", "xlsx", "excel", "spreadsheet"),
        action="extract_tables",
        icon="table",
        help_text=(
            "Find tables in a PDF and export them to CSV, JSON, or Excel. "
            "Best on clear, grid-like tables; complex or scanned layouts may "
            "need cleanup afterward. Creates new data files; the PDF stays "
            "as-is."
        ),
    ),
    ToolEntry(
        "pdf_to_csv",
        "PDF to CSV",
        "Extract tables from a PDF to CSV",
        "Convert",
        keywords=("tables", "csv", "spreadsheet", "export"),
        action="pdf_to_csv",
        icon="table",
        help_text=(
            "Extract tables from a PDF into CSV files you can open in a "
            "spreadsheet. Works best with neat, text-based tables. Output is "
            "new CSV files; the PDF is not modified."
        ),
    ),
    ToolEntry(
        "pdf_to_excel",
        "PDF to Excel",
        "Extract tables from a PDF to Excel (XLSX)",
        "Convert",
        keywords=("tables", "xlsx", "excel", "spreadsheet", "export"),
        capability_id=OPENPYXL,
        action="pdf_to_excel",
        icon="table",
        help_text=(
            "Extract tables from a PDF into an Excel workbook (.xlsx). Needs "
            "the optional openpyxl capability. Best on clear text tables. "
            "Writes a new spreadsheet; the PDF is unchanged."
        ),
    ),
    ToolEntry(
        "crop",
        "Crop pages",
        "Crop by margins (CropBox or rebuild)",
        "Modify",
        keywords=("trim", "margins", "cropbox"),
        action="modify",
        icon="crop",
        help_text=(
            "Trim margins from every page (or a page range). You can adjust "
            "the CropBox (viewer crop) or rebuild pages to permanently remove "
            "trimmed content. Use it to clean scanned borders or focus on the "
            "content area. Saves a new PDF."
        ),
    ),
    ToolEntry(
        "watermark",
        "Watermark",
        "Text or image watermark on every page",
        "Modify",
        keywords=("stamp", "overlay", "confidential"),
        action="modify",
        icon="drop",
        help_text=(
            "Stamp text or an image onto chosen pages. Drag the overlay in the "
            "preview to place it, or use the snap grid. Size is a percent of the "
            "page diagonal; opacity and angle apply live. Flatten burns the "
            "watermark into page content (harder to remove later). Output is "
            "always a new PDF — the source file is never overwritten."
        ),
    ),
    ToolEntry(
        "header_footer",
        "Header & footer",
        "Add header and footer text with page tokens",
        "Modify",
        keywords=("header", "footer", "running"),
        action="modify",
        icon="text-t",
        help_text=(
            "Add running header and/or footer text on each page. You can use "
            "tokens for page numbers and similar fields. Position left, "
            "center, or right. Writes a new PDF with the stamps applied."
        ),
    ),
    ToolEntry(
        "page_numbers",
        "Page numbers",
        "Stamp page numbers on every page",
        "Modify",
        keywords=("numbering", "folio"),
        action="modify",
        icon="hash",
        help_text=(
            "Draw page numbers onto the page (visible on the printed page), "
            "with format and position options. Different from Page labels, "
            "which only change how the viewer names pages in the sidebar. "
            "Output is a new PDF."
        ),
    ),
    ToolEntry(
        "bates",
        "Bates numbers",
        "Sequential Bates stamps across one or more files",
        "Modify",
        keywords=("bates", "exhibit", "stamp"),
        action="modify",
        icon="hash",
        help_text=(
            "Bates numbering stamps a unique sequential ID on each page "
            "(often used in legal discovery), optionally with a prefix and "
            "across multiple PDFs in one run. Numbers continue in order "
            "through the batch. Each stamped file is saved as a new PDF."
        ),
    ),
    ToolEntry(
        "bookmarks",
        "Bookmarks & TOC",
        "Edit bookmarks and generate a TOC page",
        "Modify",
        keywords=("outline", "toc", "contents"),
        action="modify",
        icon="bookmarks",
        help_text=(
            "Edit the PDF outline (bookmarks that appear in the sidebar) and "
            "optionally generate a table-of-contents page from them. Helps "
            "readers jump to sections in long documents. Saves a new PDF."
        ),
    ),
    ToolEntry(
        "annotations",
        "Remove / flatten annotations",
        "Strip annotations or bake form appearances",
        "Modify",
        keywords=("flatten", "bake", "markup", "forms"),
        action="modify",
        icon="note-pencil",
        help_text=(
            "Remove markup annotations, or flatten them (and form appearances) "
            "so they become ordinary page content that cannot be edited as "
            "comments. Use flatten before sharing a final copy; use remove to "
            "strip review marks. Always writes a new file."
        ),
    ),
    ToolEntry(
        "blank_pages",
        "Blank pages",
        "Detect and remove blank pages (with confirm)",
        "Modify",
        keywords=("empty", "detect", "remove"),
        action="modify",
        icon="file-dashed",
        help_text=(
            "Detect mostly blank pages (common after scanning) and remove them "
            "after you confirm. Review the detection before running so "
            "lightly marked pages are not dropped by mistake. Output is a new "
            "PDF."
        ),
    ),
    ToolEntry(
        "color_effects",
        "Color effects",
        "Greyscale, invert, or background tint",
        "Modify",
        keywords=("greyscale", "grayscale", "invert", "scanner"),
        action="modify",
        icon="palette",
        help_text=(
            "Apply whole-page color effects: greyscale, invert, or a "
            "background tint. Some effects rasterize pages (turn them into "
            "images), which can increase file size and reduce text "
            "selectability — the tool warns when that applies. Saves a new "
            "PDF."
        ),
    ),
    ToolEntry(
        "compress",
        "Compress PDF",
        "Reduce file size with a new copy",
        "Optimize",
        keywords=("shrink", "optimize"),
        action="optimize_secure",
        icon="file-zip",
        help_text=(
            "Create a smaller copy of the PDF by recompressing images and "
            "cleaning structure where possible. Quality vs size is a tradeoff; "
            "try it when emailing or uploading large scans. The original file "
            "is left unchanged."
        ),
    ),
    ToolEntry(
        "repair",
        "Repair PDF",
        "Rewrite a clean copy of a damaged PDF",
        "Optimize",
        keywords=("fix", "rewrite", "recover"),
        action="optimize_secure",
        icon="wrench",
        help_text=(
            "Rewrite the PDF into a clean new file. Can help when a document "
            "opens with errors, has odd structure, or fails in other tools. "
            "Not a guarantee for severely corrupt files. Source is never "
            "overwritten."
        ),
    ),
    ToolEntry(
        "encrypt",
        "Encrypt PDF",
        "Password-protect a new copy",
        "Secure",
        keywords=("password", "protect", "permissions"),
        action="optimize_secure",
        icon="lock",
        help_text=(
            "Password-protect a new copy of the PDF and optionally restrict "
            "printing, copying, or editing. You choose open and/or permissions "
            "passwords. Keep passwords somewhere safe — PageDrop cannot recover "
            "them. The unlocked original is not changed."
        ),
    ),
    ToolEntry(
        "decrypt",
        "Decrypt PDF",
        "Write an unlocked copy (password required)",
        "Secure",
        keywords=("password", "unlock", "remove password"),
        action="optimize_secure",
        icon="lock-open",
        help_text=(
            "Remove password protection by writing an unlocked copy. You must "
            "know the current password. Use this when you own the file and "
            "need an unprotected version for editing or archiving."
        ),
    ),
    ToolEntry(
        "sanitize",
        "Sanitize PDF",
        "Strip metadata and optional annotations",
        "Secure",
        keywords=("scrub", "metadata", "privacy", "annotations"),
        action="optimize_secure",
        icon="broom",
        help_text=(
            "Scrub privacy-sensitive extras before sharing: strip document "
            "metadata and optionally remove annotations. Produces a cleaner "
            "copy for distribution. Does not replace redaction for sensitive "
            "content on the page — use redaction in the viewer for that."
        ),
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
        self.setObjectName("ToolTile")
        self.setProperty("pressed", False)
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

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._icon_label: QLabel | None = None
        if entry.icon:
            self._icon_label = QLabel()
            self._icon_label.setObjectName("ToolTileIcon")
            self._icon_label.setFixedSize(20, 20)
            title_row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignTop)
        self._title = QLabel(entry.title)
        self._title.setObjectName("ToolTileTitle")
        title_row.addWidget(self._title, 1)
        layout.addLayout(title_row)

        self._subtitle = QLabel(self._subtitle_text())
        self._subtitle.setObjectName("ToolTileSubtitle")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._refresh_chrome()
        self.refresh_icon()

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
        if self._icon_label is not None:
            size = 16 if compact else 20
            self._icon_label.setFixedSize(size, size)
        self._refresh_chrome()
        self.refresh_icon()

    def refresh_capability(self) -> None:
        if self.entry.capability_id is None:
            return
        self._capability = probe(self.entry.capability_id, refresh=False)
        self._subtitle.setText(self._subtitle_text())
        self._refresh_chrome()

    def refresh_icon(self) -> None:
        if self._icon_label is None or not self.entry.icon:
            return
        size = 16 if self._compact else 20
        pix = icons.icon(self.entry.icon).pixmap(QSize(size, size))
        self._icon_label.setPixmap(pix)

    def _refresh_chrome(self) -> None:
        """Sync rare state properties; hover/focus come from shared app QSS."""
        blocked = self.is_blocked()
        self.setProperty("blocked", blocked)
        self.setProperty("comingSoon", self.entry.coming_soon and not blocked)
        self.setProperty("compact", self._compact)
        self.setAccessibleName(self.entry.title)
        self.setAccessibleDescription(self._subtitle_text())
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def _set_pressed(self, pressed: bool) -> None:
        if bool(self.property("pressed")) == pressed:
            return
        self.setProperty("pressed", pressed)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self.is_blocked():
            self._set_pressed(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        was_pressed = bool(self.property("pressed"))
        self._set_pressed(False)
        if event.button() == Qt.MouseButton.LeftButton and was_pressed:
            self.activated.emit(self.entry.id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_pressed(False)
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.entry.id)
            event.accept()
            return
        super().keyPressEvent(event)


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
    """Searchable Tools catalogue. Jobs run on tool shells, not here.

    Toast stays for coming-soon / info; BusyOverlay + ResultActionsBar live on
    ``ToolShellWindow`` (O7 / O15).
    """

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
        self._tiles: list[ToolTile] = []
        self._category_sections: dict[str, QWidget] = {}
        self._category_headings: dict[str, QToolButton] = {}
        self._category_grids: dict[str, QWidget] = {}
        self._collapsed_categories: set[str] = set()
        self._show_upcoming = False
        self._compact = False
        self._grid_columns = _GRID_COLUMNS
        self._status = StatusFooter()
        self._toast = ToastOverlay(self)

        self.setWindowTitle(self.WINDOW_TITLE)
        self.setObjectName("ToolsWindow")
        self.setMinimumSize(560, 420)

        self._nav_filter = _TileArrowNavFilter(self)
        self._build_ui()
        self.installEventFilter(self._nav_filter)
        self._apply_filter("")

        refresh_cb = self._refresh_tile_icons
        icons.register_refresh(refresh_cb)
        self.destroyed.connect(lambda *_: icons.unregister_refresh(refresh_cb))

    def _refresh_tile_icons(self) -> None:
        """Re-tint catalogue glyph pixmaps after a light/dark swap."""
        for tile in self._tiles:
            tile.refresh_icon()
        self._refresh_empty_glyph()

    def _refresh_empty_glyph(self) -> None:
        tint = TEXT_MUTED_LIGHT if light_theme() else TEXT_MUTED
        pix = icons.icon("wrench", color=tint).pixmap(
            QSize(_EMPTY_GLYPH_PX, _EMPTY_GLYPH_PX)
        )
        self._empty_glyph.setPixmap(pix)

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

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 8)
        root.setSpacing(12)

        toolbar = QToolBar("Tools", self)
        toolbar.setObjectName("ToolsToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self._toolbar = toolbar

        self._search = QLineEdit()
        self._search.setObjectName("ToolsSearch")
        self._search.setPlaceholderText("Search tools…")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Search tools")
        self._search.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._search.textChanged.connect(self._apply_filter)
        self._search.returnPressed.connect(self._focus_first_visible_tile)
        toolbar.addWidget(self._search)

        self._compact_btn = QToolButton()
        self._compact_btn.setObjectName("ToolsDensityToggle")
        self._compact_btn.setText("Compact")
        self._compact_btn.setCheckable(True)
        self._compact_btn.setToolTip("Toggle compact tile density")
        self._compact_btn.setAccessibleName("Compact density")
        self._compact_btn.toggled.connect(self._set_compact)
        toolbar.addWidget(self._compact_btn)

        enable_toolbar_keyboard_navigation(toolbar)
        root.addWidget(toolbar)

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

        self._empty_state = QWidget()
        self._empty_state.setObjectName("ToolsEmptyPanel")
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setContentsMargins(0, 24, 0, 24)
        empty_layout.setSpacing(8)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_glyph = QLabel()
        self._empty_glyph.setObjectName("ToolsEmptyGlyph")
        self._empty_glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_glyph.setAccessibleName("Tools")
        self._refresh_empty_glyph()
        self._empty_label = QLabel("No tools match your search.")
        self._empty_label.setObjectName("ToolsEmptyState")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_glyph)
        empty_layout.addWidget(self._empty_label)
        self._empty_state.hide()
        self._catalogue_layout.addWidget(self._empty_state)

        self._upcoming_btn = QToolButton()
        self._upcoming_btn.setObjectName("ToolsUpcomingToggle")
        self._upcoming_btn.setCheckable(True)
        self._upcoming_btn.setAutoRaise(True)
        self._upcoming_btn.setToolTip("Show or hide tools that are not available yet")
        self._upcoming_btn.toggled.connect(self._on_upcoming_toggled)
        self._catalogue_layout.addWidget(self._upcoming_btn)

        self._catalogue_layout.addStretch(1)

        root.addWidget(self._status)

    def grid_columns(self) -> int:
        return self._grid_columns

    def visible_tiles(self) -> list[ToolTile]:
        return [t for t in self._tiles if t.isVisible()]

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

        self._empty_state.setVisible(not any_visible)

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
        if entry.action == "pdf_to_word":
            from pagedrop.ui.pdf_to_word_shell import open_pdf_to_word_shell

            open_pdf_to_word_shell(self)
            return
        if entry.action == "optimize_secure":
            from pagedrop.ui.optimize_secure_shell import open_optimize_secure_shell

            open_optimize_secure_shell(self, entry.id)
            return
        if entry.action == "modify":
            from pagedrop.ui.modify_tools_shell import open_modify_shell

            open_modify_shell(self, entry.id)
            return
        if entry.action in {"ocr", "extract_tables", "pdf_to_csv", "pdf_to_excel"}:
            from pagedrop.ui.ocr_shell import open_ocr_shell

            open_ocr_shell(self, entry.id)
            return

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        width = max(1, self._scroll.viewport().width())
        cols = max(1, min(4, width // 200))
        if cols != self._grid_columns:
            self._grid_columns = cols
            self._apply_filter(self._search.text())
