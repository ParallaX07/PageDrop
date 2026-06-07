# PageDrop — Complete Build Plan

A Python desktop app that renders PDF pages as thumbnails so you can drag single
or multiple pages directly into folders in your file manager. **Phases 1–9** (complete)
cover the read-only single-document workflow. **Phases 11–15** extend the app with
multi-tab editing, page reorder/delete, inbound PDF drop, and Save As. **Phase 17**
adds a separate Merge PDFs window for whole-file combine workflows. **Phase 18**
adds detachable tab windows and cross-window page drag (copy by default, Shift+drop to move).
**Phase 19** adds a separate Create PDF window for converting raster images into one
combined PDF or individual PDFs per image.

---

## Tech Stack Decisions

| Role | Library | Why |
|---|---|---|
| Project manager | `uv` | Fast, modern, replaces pip + venv |
| PDF rendering | `PyMuPDF` (fitz) | Best-in-class page → image rendering |
| PDF splitting | `pypdf` | Lightweight page extraction to new files |
| GUI + drag-drop | `PyQt6` | OS-level drag that file managers understand |
| Temp files | `tempfile` (stdlib) | No extra dep needed |
| Optional exe | `PyInstaller` | Single-file distribution |

> **Why PyQt6 for drag-drop?** It supports `QDrag` + `QMimeData` with file
> URLs — the exact protocol that Windows Explorer, Nautilus, Dolphin, Finder
> etc. all understand. No other pure-Python GUI library does this reliably.

---

## Project Structure (target)

```
pagedrop/
├── pyproject.toml
├── .python-version
├── README.md
└── src/
    └── pagedrop/
        ├── __init__.py
        ├── main.py               # entry point
        ├── ui/
        │   ├── __init__.py
        │   ├── main_window.py    # QMainWindow, toolbar, layout
        │   ├── window_manager.py # multi-window registry + factory       [Phase 18]
        │   ├── tab_manager.py    # QTabWidget wrapper + tab lifecycle   [Phase 11]
        │   ├── pdf_tab.py        # per-tab state container widget        [Phase 11]
        │   ├── merge_window.py   # modeless Merge PDFs window            [Phase 17]
        │   ├── convert_window.py # modeless Create PDF window            [Phase 19]
        │   ├── convert_file_grid.py  # image grid for Create PDF       [Phase 19]
        │   ├── convert_file_card.py  # single image card               [Phase 19]
        │   ├── thumbnail_grid.py # scrollable grid of pages
        │   ├── page_preview.py   # single-page preview + arrow navigation
        │   └── page_card.py      # individual page widget + drag logic
        ├── core/
        │   ├── __init__.py
        │   ├── pdf_loader.py     # open PDF, render pages via PyMuPDF
        │   ├── drag_mime.py      # internal + cross-window drag payloads [Phase 13/18]
        │   ├── pdf_editor.py     # PdfEditModel + PageRef dataclass      [Phase 12]
        │   ├── pdf_merge.py      # PdfMergeModel — ordered file list     [Phase 17]
        │   ├── pdf_writer.py     # write_pdf() + merge_pdf_files()       [Phase 15/17]
        │   ├── image_to_pdf.py   # images → single or individual PDFs    [Phase 19]
        │   ├── supported_formats.py  # image extension registry          [Phase 19]
        │   └── page_extractor.py # write selected pages to temp PDFs
        └── utils/
            ├── __init__.py
            └── temp_manager.py   # temp file lifecycle
```

---

## Phase 1 — Project Setup ✅

**Goal:** Runnable skeleton with uv, correct deps, proper src layout.

### Checklist

- [x] Install uv if needed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [x] `uv init pagedrop --lib` (creates src layout automatically)
- [x] Create `.python-version` with `3.11` (or `3.12`)
- [x] Edit `pyproject.toml` — add dependencies:
  ```toml
  [project]
  name = "pagedrop"
  version = "0.1.0"
  requires-python = ">=3.11"
  dependencies = [
      "PyQt6>=6.6.0",
      "PyMuPDF>=1.24.0",
      "pypdf>=4.2.0",
  ]

  [project.scripts]
  pagedrop = "pagedrop.main:main"

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"
  ```
- [x] `uv sync` — verify it resolves and installs without errors
- [x] Create the folder tree under `src/pagedrop/` with empty `__init__.py`
  files in each subfolder
- [x] Write minimal `main.py`:
  ```python
  import sys
  from PyQt6.QtWidgets import QApplication, QMainWindow

  def main():
      app = QApplication(sys.argv)
      win = QMainWindow()
      win.setWindowTitle("PageDrop")
      win.resize(900, 650)
      win.show()
      sys.exit(app.exec())

  if __name__ == "__main__":
      main()
  ```
- [x] Run: `uv run pagedrop`

### Checklist — Test Scripts & Smoke Tests

- [x] Add dev dependencies: `uv add --dev pytest pytest-qt`
- [x] Create test layout:
  ```
  tests/
  ├── conftest.py              # shared fixtures, Qt app session
  ├── smoke/
  │   └── test_phase1_boot.py  # one smoke module per phase (or grouped)
  └── fixtures/
      └── README.md            # how to add sample PDFs (gitignore large files)
  ```
- [x] Write `tests/smoke/test_phase1_boot.py`:
  - [x] `test_imports` — `import pagedrop`, `pagedrop.main`, `pagedrop.core`, `pagedrop.ui` with no errors
  - [x] `test_main_callable` — `pagedrop.main.main` exists and is callable
  - [x] `test_cli_entry_point` — subprocess: `uv run pagedrop` starts and exits cleanly when the window is closed (or use `pytest-qt` to close programmatically within a timeout)
- [x] Add a `Makefile` target or document in README: `uv run pytest tests/smoke/test_phase1_boot.py -v`
- [x] Confirm smoke tests run **without** activating a venv manually (`uv run pytest …`)

### ✅ Test Gate 1
- [x] **Window opens** with correct title, no import errors in terminal
- [x] **`uv run pagedrop`** works from the project root
- [x] **No venv activation needed** — uv handles it

---

## Phase 2 — PDF Loading & Page Rendering

**Goal:** Be able to open a PDF and render any page as a `QPixmap`.

### Checklist

- [x] Write `core/pdf_loader.py` with a `PdfLoader` class:
  ```python
  import fitz  # PyMuPDF

  class PdfLoader:
      def __init__(self, path: str):
          self.path = path
          self.doc = fitz.open(path)

      @property
      def page_count(self) -> int:
          return len(self.doc)

      def render_page(self, page_index: int, width_px: int = 160) -> bytes:
          """Render page to PNG bytes at target width."""
          page = self.doc[page_index]
          scale = width_px / page.rect.width
          mat = fitz.Matrix(scale, scale)
          pix = page.get_pixmap(matrix=mat, alpha=False)
          return pix.tobytes("png")

      def close(self):
          self.doc.close()
  ```
- [x] Write a quick sanity script (not part of the app, just a throwaway test):
  ```python
  # test_render.py — run with: uv run python test_render.py
  from pagedrop.core.pdf_loader import PdfLoader

  loader = PdfLoader("your_test.pdf")
  print(f"Pages: {loader.page_count}")
  png_bytes = loader.render_page(0, width_px=300)
  with open("page_0.png", "wb") as f:
      f.write(png_bytes)
  print("Saved page_0.png")
  ```
- [x] Handle password-protected PDFs: catch `fitz.EmptyFileError` and bad
  password, show `QMessageBox` error later when wired to UI
- [x] Handle invalid path / corrupt file with a clear exception message

### Checklist — Test Scripts & Smoke Tests

- [x] Add `tests/fixtures/generate_fixtures.py` — script that builds tiny PDFs with `pypdf` (1-page, 5-page, empty) so tests don't depend on checked-in binaries
- [x] Write `tests/core/test_pdf_loader.py`:
  - [x] `test_page_count` — open 5-page fixture, assert `page_count == 5`
  - [x] `test_render_page_returns_png` — first bytes are PNG magic (`\x89PNG`)
  - [x] `test_render_last_page` — render index `-1` equivalent without error
  - [x] `test_invalid_path_raises` — clear, catchable exception (not a bare traceback)
  - [x] `test_close_idempotent` — call `close()` twice without error
- [x] Write `tests/smoke/test_phase2_pdf_loader.py` — single entry that runs the core loader tests plus a quick render-to-disk sanity check into a temp dir (deleted in teardown)
- [x] Run: `uv run pytest tests/core/test_pdf_loader.py tests/smoke/test_phase2_pdf_loader.py -v`

### ✅ Test Gate 2
- [x] **Run the sanity script** — `page_0.png` opens and looks correct
- [x] **Try a multi-page PDF** — print page count, render page 0 and the last page
- [x] **Try an invalid path** — verify it raises a clean exception, not a cryptic crash
- [x] **Delete the sanity script** once satisfied (keep the repo clean)

---

## Phase 3 — Main Window & Layout

**Goal:** Persistent window with File menu, toolbar, and placeholder content area.

### Checklist

- [x] Write `ui/main_window.py` with `MainWindow(QMainWindow)`:
  - [x] **Menu bar**: `File → Open PDF`, `File → Close PDF`, `File → Exit`
  - [x] **Toolbar**: Open button (icon + text), separator, filename label
  - [x] **Status bar**: shows messages (page count, selection count, errors)
  - [x] **Central widget**: placeholder `QLabel("Open a PDF to begin")`
  - [x] **Window title**: `"PageDrop"` → updates to
    `"PageDrop — filename.pdf"` after opening
- [x] Wire `File → Open PDF` to `QFileDialog.getOpenFileName` filtering for
  `*.pdf`
- [x] Store the opened path in `self.current_pdf_path`
- [x] Update `main.py` to use `MainWindow` instead of bare `QMainWindow`
- [x] Add `closeEvent` to confirm if there are unsaved operations (skip for now,
  add a `pass`-body as a placeholder)

### Checklist — Test Scripts & Smoke Tests

- [x] Extend `tests/conftest.py` with a `qapp` fixture (`pytest-qt` provides this) and optional `main_window` fixture
- [x] Write `tests/ui/test_main_window.py`:
  - [x] `test_window_title_default` — title is `"PageDrop"` on launch
  - [x] `test_menu_actions_exist` — `File → Open PDF`, `Close PDF`, `Exit` actions are present
  - [x] `test_toolbar_open_button` — Open button exists and is enabled
  - [x] `test_open_pdf_updates_title` — mock or fixture PDF via `QFileDialog` monkeypatch → title becomes `"PageDrop — …"`
  - [x] `test_status_bar_shows_page_count` — after open, status bar contains `"Loaded"` and page count
  - [x] `test_exit_action_closes` — trigger Exit, verify window closes
- [x] Write `tests/smoke/test_phase3_main_window.py` — smoke script that constructs `MainWindow`, shows it hidden (`showMinimized` or off-screen), opens a fixture PDF programmatically, asserts title + status bar, then closes
- [x] Run headless-friendly: `uv run pytest tests/ui/test_main_window.py -v` (may need `QT_QPA_PLATFORM=offscreen` on CI/Linux)

### ✅ Test Gate 3
- [x] **Open → dialog appears**, filtered to PDF only
- [x] **Title bar updates** to reflect the filename after selection
- [x] **Status bar** shows "Loaded X pages" after selecting a file
- [x] **File → Exit** closes the app cleanly
- [x] **Cancel in dialog** leaves the app in its previous state (no crash)

---

## Phase 4 — Thumbnail Grid

**Goal:** Scrollable grid of page thumbnails rendered from the loaded PDF.

### Checklist

- [x] Write `ui/page_card.py` — `PageCard(QFrame)`:
  - [x] Contains a `QLabel` for the thumbnail image
  - [x] Contains a `QLabel` for the page number below the image
  - [x] Fixed card width (e.g. 170px), height auto from aspect ratio
  - [x] `set_thumbnail(pixmap: QPixmap)` method
  - [x] `set_selected(bool)` method — changes border style (e.g. 3px blue border
    when selected, 1px grey when not)
- [x] Write `ui/thumbnail_grid.py` — `ThumbnailGrid(QScrollArea)`:
  - [x] Inner widget uses `QGridLayout` (or `QFlowLayout` if you install one)
    with a fixed column count (e.g. auto-fit based on window width)
  - [x] `load_pdf(loader: PdfLoader)` clears old cards and creates new `PageCard`
    objects
  - [x] Render thumbnails in a **background thread** (`QThread` or
    `QRunnable`/`QThreadPool`) so the UI doesn't freeze
  - [x] Emit a signal per rendered page so cards populate progressively
  - [x] Show a `QProgressBar` in the status bar while rendering
- [x] Wire `MainWindow` to call `thumbnail_grid.load_pdf()` after dialog
- [x] Replace the placeholder central widget with the `ThumbnailGrid`

### Checklist — Threading Pattern
```python
class ThumbnailWorker(QRunnable):
    class Signals(QObject):
        page_ready = pyqtSignal(int, QPixmap)  # page_index, pixmap
        finished = pyqtSignal()

    def __init__(self, loader, total_pages):
        super().__init__()
        self.signals = self.Signals()
        self.loader = loader
        self.total_pages = total_pages

    def run(self):
        for i in range(self.total_pages):
            png = self.loader.render_page(i, width_px=160)
            pix = QPixmap()
            pix.loadFromData(png, "PNG")
            self.signals.page_ready.emit(i, pix)
        self.signals.finished.emit()
```
- [x] Connect `page_ready` signal → update the correct `PageCard` on the main thread
- [x] Connect `finished` signal → hide the progress bar

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/ui/test_page_card.py`:
  - [x] `test_set_thumbnail` — accepts a `QPixmap`, label shows it
  - [x] `test_set_selected_styles` — selected vs unselected change border/stylesheet
- [x] Write `tests/ui/test_thumbnail_grid.py`:
  - [x] `test_load_pdf_creates_cards` — 5-page fixture → 5 `PageCard` widgets
  - [x] `test_load_pdf_clears_previous` — load PDF A, then PDF B → card count matches B only
  - [x] `test_page_ready_populates_card` — mock worker or wait with `qtbot.waitSignal` until all pages ready
  - [x] `test_progress_bar_visible_during_load` — progress bar shown while worker runs, hidden on `finished`
- [x] Write `tests/smoke/test_phase4_thumbnail_grid.py`:
  - [x] Open 5-page fixture through `MainWindow`, wait for all thumbnails (timeout ≤ 30s)
  - [x] Assert card order labels read `1`, `2`, … `5`
  - [x] Optional stress hook: env var `PAGEDROP_STRESS_PAGES=50` loads a generated 50-page PDF and asserts UI stays responsive (manual/CI nightly)
- [x] Run: `uv run pytest tests/ui/test_page_card.py tests/ui/test_thumbnail_grid.py tests/smoke/test_phase4_thumbnail_grid.py -v`

### ✅ Test Gate 4
- [x] **5-page PDF** → all 5 thumbnails render, visible and correctly ordered
- [x] **50-page PDF** → thumbnails populate progressively, UI stays responsive
  (you can scroll while they load)
- [x] **100-page PDF** → no memory crash, reasonable load time
- [ ] **Resize window** → grid reflows correctly (or stays fixed width — either is
  fine, just make sure nothing clips)
- [x] **Open a second PDF** → old thumbnails are cleared, new ones appear

---

## Phase 5 — Page Selection

**Goal:** Click, Ctrl+click, Shift+click, Ctrl+A, Escape — all working with clear visual feedback.

### Checklist

- [x] Add a `SelectionManager` class (or manage in `ThumbnailGrid`):
  - [x] Stores `set[int]` of selected page indices
  - [x] `select_single(idx)` — clears others, selects one
  - [x] `toggle(idx)` — adds or removes from selection
  - [x] `select_range(start, end)` — selects a contiguous block
  - [x] `select_all()` / `clear()`
  - [x] Emits a `selection_changed` signal with the current selection set
- [x] Override `mousePressEvent` in `PageCard`:
  - [x] No modifier → `select_single`
  - [x] `Qt.KeyboardModifier.ControlModifier` → `toggle`
  - [x] `Qt.KeyboardModifier.ShiftModifier` → `select_range` from last clicked
- [x] Track `last_clicked_index` in the grid for shift-click anchor
- [x] Connect `selection_changed` → update every `PageCard.set_selected()`
- [x] Connect `selection_changed` → update status bar:
  `"3 pages selected"` / `"No selection"`
- [x] Add keyboard shortcuts in `MainWindow`:
  - [x] `Ctrl+A` → `selection_manager.select_all()`
  - [x] `Escape` → `selection_manager.clear()`

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/core/test_selection_manager.py` (pure logic, no Qt required if extracted):
  - [x] `test_select_single_clears_others`
  - [x] `test_toggle_adds_and_removes`
  - [x] `test_select_range_inclusive`
  - [x] `test_select_all_and_clear`
  - [x] `test_selection_changed_signal` — mock or spy emits correct set after each operation
- [x] Write `tests/ui/test_selection_interactions.py` with `pytest-qt`:
  - [x] Simulate click, Ctrl+click, Shift+click on cards; assert `set_selected(True/False)` state
  - [x] `Ctrl+A` shortcut → all cards selected
  - [x] `Escape` → none selected
  - [x] Status bar text matches selection count after each action
- [x] Write `tests/smoke/test_phase5_selection.py` — end-to-end on a 10-page fixture: run the full click / modifier / keyboard matrix from Test Gate 5 programmatically
- [x] Run: `uv run pytest tests/core/test_selection_manager.py tests/ui/test_selection_interactions.py tests/smoke/test_phase5_selection.py -v`

### ✅ Test Gate 5
- [x] **Click page 1** → only page 1 highlighted
- [x] **Click page 3** → only page 3 highlighted (page 1 deselected)
- [x] **Ctrl+click pages 1, 3, 5** → all three highlighted, nothing else
- [x] **Click page 2, Shift+click page 6** → pages 2–6 all highlighted
- [x] **Ctrl+A** → all pages highlighted
- [x] **Escape** → all deselected
- [x] **Status bar** updates correctly in every scenario above
- [x] **No visual glitch** — deselected cards go back to their normal grey border

---

## Phase 6 — Drag & Drop to File Manager

**Goal:** Dragging selected pages out of the app and dropping them into a file manager folder copies the page(s) as PDF files.

> This is the core feature. Take extra time here and test thoroughly.

### How it works
1. User starts dragging a `PageCard`
2. App checks: if the dragged card isn't selected, auto-select just it
3. App extracts selected pages to temp PDF files (one file per page)
4. App creates a `QDrag` with `QMimeData` containing `file://` URLs for the temp files
5. OS hands the drag off — file manager sees real file paths and copies them on drop

### Checklist — Page Extractor

- [x] Write `core/page_extractor.py`:
  ```python
  from pypdf import PdfReader, PdfWriter
  from pathlib import Path

  def extract_pages_to_files(
      source_pdf: str,
      page_indices: list[int],
      output_dir: Path,
      base_name: str,
  ) -> list[Path]:
      reader = PdfReader(source_pdf)
      out_paths = []
      for idx in sorted(page_indices):
          writer = PdfWriter()
          writer.add_page(reader.pages[idx])
          out_path = output_dir / f"{base_name}_page_{idx + 1:04d}.pdf"
          with open(out_path, "wb") as f:
              writer.write(f)
          out_paths.append(out_path)
      return out_paths
  ```
  - [x] Name files after the source PDF, e.g. `report_page_0003.pdf`
  - [x] Zero-pad page numbers so filenames sort correctly

### Checklist — Drag Logic in PageCard

- [x] Override `mousePressEvent` — record start position
- [x] Override `mouseMoveEvent` — check if drag threshold crossed
  (`QApplication.startDragDistance()`)
- [x] When threshold crossed:
  - [x] If this card is not in selection → auto-select just this card first
  - [x] Call `extract_pages_to_files()` via the extractor
  - [x] Build `QMimeData`:
    ```python
    mime = QMimeData()
    urls = [QUrl.fromLocalFile(str(p)) for p in temp_paths]
    mime.setUrls(urls)
    ```
  - [x] Create `QDrag(self)`, `drag.setMimeData(mime)`
  - [x] Optionally set a drag pixmap (composite of first thumbnail)
  - [x] `result = drag.exec(Qt.DropAction.CopyAction)`
  - [x] On completion, schedule temp file cleanup via `TempManager`
- [x] Signals needed: `PageCard` needs a reference to the `SelectionManager`
  and `PdfLoader` — pass them in via the grid

### Checklist — Drag Visual Feedback

- [x] Set drag cursor to show a stack-of-pages icon while dragging
- [x] Optionally show a small badge with the count of pages being dragged
  (e.g. overlay "×3" on the drag pixmap)

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/core/test_page_extractor.py`:
  - [x] `test_extract_single_page` — output PDF has exactly 1 page
  - [x] `test_extract_multiple_non_contiguous` — indices `[0, 3, 6]` → 3 files, correct page order in each
  - [x] `test_filename_zero_padding` — `report_page_0003.pdf` sorts before `report_page_0010.pdf`
  - [x] `test_extracted_content_matches_source` — compare page text or dimensions via `pypdf`/`fitz`
- [x] Write `tests/ui/test_drag_drop.py` (partial automation — OS drop target is hard to mock):
  - [x] `test_drag_without_selection_auto_selects` — starting drag on unselected card updates selection to that card only
  - [x] `test_mime_data_contains_file_urls` — after extract, `QMimeData.urls()` are local `file://` paths that exist on disk
  - [x] `test_drag_threshold_respected` — small mouse move does not start drag
- [x] Write `tests/smoke/test_phase6_drag_drop.py`:
  - [x] Script extracts pages to a temp output dir (simulates drop target without GUI drag)
  - [x] Verify dropped PDFs open in `pypdf` and contain expected page count
  - [x] Document manual steps for real Explorer/Finder drop (cannot fully automate cross-process DnD in CI)
- [x] Run: `uv run pytest tests/core/test_page_extractor.py tests/ui/test_drag_drop.py tests/smoke/test_phase6_drag_drop.py -v`

### ✅ Test Gate 6
- [x] **Drag 1 page** to a folder → open the dropped PDF, verify it contains exactly
  that page and looks correct
- [x] **Drag 3 non-contiguous pages** (e.g. 1, 4, 7) → verify 3 separate PDFs
  appear in the target folder, each with the right content
- [x] **Drag with no selection** (click-drag directly on an unselected card) →
  verify just that one page is extracted
- [x] **Cancel mid-drag** (release over no folder) → verify no PDF files are
  left in the target, temp files are cleaned up
- [x] **Drag to a read-only folder** → verify app shows an error, doesn't crash
- [x] **Drag the same pages twice** → both sets of files land in the target
  without name collisions (add timestamp or counter to filename if needed)
- [x] Open each dropped PDF in a real PDF viewer (Acrobat, browser, etc.)
  to confirm content is valid

---

## Phase 7 — Temp File Management

**Goal:** No orphan temp files left on disk after normal use or crashes.

### Checklist

- [x] Write `utils/temp_manager.py`:
  ```python
  import tempfile, atexit, shutil
  from pathlib import Path

  class TempManager:
      def __init__(self):
          self._dir = Path(tempfile.mkdtemp(prefix="pagedrop_"))
          atexit.register(self.cleanup)

      def get_dir(self) -> Path:
          return self._dir

      def cleanup(self):
          if self._dir.exists():
              shutil.rmtree(self._dir, ignore_errors=True)
  ```
- [x] Instantiate `TempManager` once at app startup, pass reference to
  `page_extractor`
- [x] After each drag completes (`drag.exec()` returns), clean up only the files
  from *that* drag (not all temp files — in case another drag is in progress)
- [x] On `MainWindow.closeEvent`, call `temp_manager.cleanup()` explicitly before
  the `atexit` handler fires
- [x] Consider a max temp dir size guard — if extracting hundreds of pages, disk
  usage can spike

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/utils/test_temp_manager.py`:
  - [x] `test_creates_prefixed_dir` — dir name starts with `pagedrop_`
  - [x] `test_cleanup_removes_dir` — after `cleanup()`, dir no longer exists
  - [x] `test_cleanup_idempotent` — second `cleanup()` does not raise
  - [x] `test_atexit_registered` — optional: verify handler registered (or integration test via subprocess)
- [x] Write `tests/smoke/test_phase7_temp_cleanup.py`:
  - [x] Perform 5 simulated extractions, assert per-drag files removed while manager still alive
  - [x] After `TempManager.cleanup()`, `listdir(tempfile.gettempdir())` has no orphaned files from that run
  - [x] Subprocess smoke: start app, kill with `SIGKILL`/`taskkill /F`, count `pagedrop_*` dirs before/after (document acceptable baseline)
- [x] Run: `uv run pytest tests/utils/test_temp_manager.py tests/smoke/test_phase7_temp_cleanup.py -v`

### ✅ Test Gate 7
- [x] **Do 5 drag operations** → check the temp dir, verify files are being
  cleaned up (not accumulating)
- [x] **Kill the app process** (task manager / `kill -9`) → relaunch and check
  that the old temp dir was cleaned or is harmless
- [x] **`os.listdir(tempfile.gettempdir())`** → count `pagedrop_*` dirs, make
  sure they don't pile up over multiple runs

---

## Phase 8 — Error Handling & Edge Cases

**Goal:** The app never crashes silently. Every failure shows a clear message.

### Checklist

- [x] **No PDF loaded** when drag starts → show status bar message
  `"Open a PDF first"`, cancel drag
- [x] **Corrupt PDF** on open → `QMessageBox.critical()` with filename and error
- [x] **Empty PDF** (0 pages) → show message, don't render grid
- [x] **Disk full** when extracting temp files → catch `OSError`, show dialog
- [x] **Very large pages** (e.g. engineering drawings at A0) → cap render DPI at
  150, or cap `width_px` to a safe value
- [x] **PDF with only 1 page** → selection + drag still works correctly
- [x] **Rapid re-opens** (open PDF while one is still loading) → cancel previous
  worker thread before starting new one
- [x] Wrap `QRunnable.run()` body in `try/except` — surface errors to main thread
  via a signal, never let thread crash silently

### Checklist — Test Scripts & Smoke Tests

- [x] Add fixtures: `corrupt.pdf` (text renamed to `.pdf`), `empty.pdf` (0 pages), `garbage.bin` with `.pdf` extension
- [x] Write `tests/core/test_pdf_loader_errors.py`:
  - [x] `test_corrupt_file_raises_clear_error`
  - [x] `test_empty_pdf_zero_pages`
- [x] Write `tests/ui/test_error_handling.py`:
  - [x] `test_open_corrupt_shows_message_box` — use `qtbot` + `QMessageBox` spy or mock
  - [x] `test_drag_without_pdf_shows_status_message`
  - [x] `test_disk_full_oserror` — mock `open()` or extractor to raise `OSError`, assert dialog not crash
  - [x] `test_rapid_reopen_cancels_worker` — open PDF A, immediately open PDF B, assert only B's cards remain
- [ ] Write `tests/smoke/test_phase8_edge_cases.py` — runs the error-path matrix; each case asserts app process still alive and window visible after failure
- [ ] Run: `uv run pytest tests/core/test_pdf_loader_errors.py tests/ui/test_error_handling.py tests/smoke/test_phase8_edge_cases.py -v`

### ✅ Test Gate 8
- [x] **Rename a PDF to `.pdf` but put garbage inside** → open it, see a clean
  error dialog
- [x] **Fill up a RAM disk / temp partition** (or mock the OSError) → verify
  graceful failure
- [x] **Open → cancel → open again → cancel** → app stays stable after multiple
  dialog cancellations

---

## Phase 9 — UX Polish

**Goal:** The app feels intentional and pleasant to use, not like a prototype.

### Checklist — Quality of Life Features

- [x] **Tooltip on hover** over each card: `"Page 3 · 210×297 mm · Click to select"`
- [x] **Right-click context menu** on a card or grid:
  - `Extract selected pages to folder…` → `QFileDialog.getExistingDirectory`
    fallback for users who don't want to drag
- [x] **Keyboard navigation**: arrow keys move focus between cards, Space toggles
  selection of focused card
- [x] **Zoom controls**: `+` / `-` or a slider to change thumbnail size (adjust
  `width_px` and re-render)
- [x] **Page count badge** in window title: `"PageDrop — report.pdf (12 pages)"`
- [x] **Persist last-opened directory** via `QSettings` so the file dialog
  remembers where you were
- [x] **Drag count badge**: when dragging multiple pages, overlay a small circle
  with the count on the drag pixmap
- [x] **Select All / Deselect All** buttons in toolbar (supplement keyboard shortcut)
- [x] **Minimum window size** so the grid never becomes unusably small

### Checklist — Styling

- [x] Give `PageCard` a subtle drop shadow or rounded corner so it looks like
  an actual card
- [x] Hover state: slightly lighten/darken the card on mouse-over (before click)
- [x] Selected state: 3px accent-colour border (Qt blue or your own colour)
- [x] Use a dark grey background for the grid area so white PDF thumbnails
  stand out

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/ui/test_ux_polish.py`:
  - [x] `test_card_tooltip` — hover (or `QToolTip.showText` trigger) shows page number and dimensions
  - [x] `test_context_menu_extract_action` — right-click → Extract triggers folder dialog mock and writes PDFs
  - [x] `test_arrow_keys_and_space` — focus moves between cards; Space toggles selection
  - [x] `test_zoom_changes_thumbnail_size` — `+`/`-` or slider updates card width
  - [x] `test_qsettings_remembers_directory` — two app sessions, second open dialog starts in same folder (use temp `QSettings` path in test)
  - [x] `test_minimum_window_size` — resize below minimum clamps correctly
- [x] Write `tests/smoke/test_phase9_ux.py` — visual/regression smoke checklist encoded as assertions where possible (title badge page count, toolbar buttons enabled/disabled states)
- [ ] Optional: screenshot diff test for card states (selected / hover / default) — skip in CI if flaky; run locally before release
- [x] Run: `uv run pytest tests/ui/test_ux_polish.py tests/smoke/test_phase9_ux.py -v`

### ✅ Test Gate 9
- [x] **Hover over a card** → tooltip appears after a short delay
- [x] **Right-click → Extract to folder** → PDF(s) land in the chosen folder
- [x] **Arrow keys** move between cards, Space selects
- [x] **Zoom in/out** → thumbnails resize, grid reflows
- [x] **Open app a second time** → file dialog opens in the last-used folder
- [x] **Visual check**: selected vs unselected vs hovered cards are all clearly
  distinguishable at a glance

---

## Phase 11 — Multi-Tab Shell

**Goal:** Browser-style tabs at the top of the app; each tab is an independent document
workspace. **Multiple PDFs can be open at the same time** — one PDF per tab. **Tabs can
be closed** individually at any time.

> **Design decisions (locked in):**
> - **Single file** in Open dialog → prompt: *Open in current tab* or *Open in new tab*
> - **Multiple files** selected in Open dialog → each PDF opens in its **own new tab**
>   (no current-tab prompt; batch open only creates new tabs)
> - Tab title shows `filename.pdf` or `filename.pdf*` when dirty
> - Closing the last tab → spawn a fresh blank tab (app stays open)
> - **Open in new window** and tab tear-off deferred to **Phase 18**

### Checklist — New Files

- [x] Write `ui/tab_manager.py` — `TabManager(QTabWidget)`:
  - [x] Add tab, close tab, switch active tab
  - [x] **Close button (`×`) on every tab** (`setTabsClosable(True)`)
  - [x] `close_tab(index)` — tear down tab widget, cancel render worker, release loaders
  - [x] `*` suffix on tab title when tab is dirty (stub `is_dirty=False` until Phase 15)
  - [x] Emit signals: `active_tab_changed`, `tab_closed`, `all_tabs_closed`
- [x] Write `ui/pdf_tab.py` — `PdfTab(QWidget)` per-tab container:
  - [x] Owns `ThumbnailGrid`, preview stack (`QStackedWidget`), zoom state
  - [x] Exposes `load_pdf(path)`, `close_loader()`, `is_dirty`, `tab_title`
  - [x] Per-tab render worker cancellation on close (reuse `_generation` pattern)

### Checklist — MainWindow Refactor

- [x] Replace single `_loader` / `_thumbnail_grid` with `TabManager` as central widget
- [x] **File → Open PDF** — `QFileDialog.getOpenFileNames` (multi-select enabled):
  - [x] **One file selected** → dialog: *Open in current tab* / *Open in new tab*
  - [x] **Multiple files selected** → open **each in its own new tab** (skip current-tab prompt)
  - [x] If current tab is blank and user picks *Open in current tab* (single file only),
    load into that tab instead of adding another
- [x] **File → Close Tab** — closes active tab; disable when only one blank tab remains
- [x] Rename **Close PDF** → **Close Tab** (same action as above)
- [x] **Close tab via `×`** on tab bar — same teardown as menu/keyboard close
- [x] Window title reflects active tab (filename + page count)
- [x] Route toolbar/menu actions (Select All, Preview, Zoom, Extract) to **active tab** only
- [x] Keyboard: `Ctrl+Tab` / `Ctrl+Shift+Tab` switch tabs; **`Ctrl+W` closes active tab**
- [x] Launch with one blank tab showing empty state `"Open a PDF to begin"`
- [x] **Closing the last tab** → spawn a new blank tab (do not quit the app)
- [x] Optional: **Ctrl+T** or **+** button to open a new blank tab without a PDF

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/ui/test_tab_manager.py`:
  - [x] `test_open_in_new_tab` — two tabs, independent paths
  - [x] `test_open_in_current_tab` — replaces blank tab content
  - [x] `test_multi_select_opens_each_in_new_tab` — pick 3 PDFs at once → 3 new tabs
  - [x] `test_close_tab_via_x_button` — tab removed, neighbours intact
  - [x] `test_close_tab_via_ctrl_w` — active tab closes
  - [x] `test_close_last_tab_spawns_blank_tab` — app stays open with empty tab
  - [x] `test_close_middle_tab` — other tabs unaffected
  - [x] `test_ctrl_tab_switches_active` — keyboard navigation
  - [x] `test_toolbar_routes_to_active_tab` — action on tab B does not affect tab A
- [x] Write `tests/smoke/test_phase11_tabs.py` — multi-select open 3 fixture PDFs,
  switch between tabs, close middle via `×`, verify no cross-contamination
- [x] Run: `uv run pytest tests/ui/test_tab_manager.py tests/smoke/test_phase11_tabs.py -v`

### ✅ Test Gate 11
- [x] **Multi-select 3 PDFs** in Open dialog → 3 tabs, each with correct thumbnails
- [x] **Single-file open** → current-tab vs new-tab prompt works
- [x] **Switch tabs** → selection, zoom, and scroll do not leak between tabs
- [x] **Close tab via `×`** → tab gone, others intact
- [x] **Close tab via `Ctrl+W`** → active tab closes
- [x] **Close last tab** → new blank tab appears, app keeps running
- [x] **Ctrl+Tab / Ctrl+Shift+Tab** switch tabs as expected

---

## Phase 12 — Editable Page Model (`PdfEditModel`)

**Goal:** Introduce a logical page list decoupled from source PDF order — foundation for
reorder, delete, insert, and save.

### Checklist — Core Model

- [x] Write `core/pdf_editor.py`:
  ```python
  @dataclass(frozen=True)
  class PageRef:
      source_path: str
      source_index: int  # 0-based in that file

  class PdfEditModel:
      def __init__(self, source_path: str, page_count: int): ...
      def logical_count(self) -> int: ...
      def page_at(self, logical_index: int) -> PageRef: ...
      def insert_pages(self, index: int, refs: list[PageRef]) -> None: ...
      def remove_pages(self, logical_indices: list[int]) -> None: ...
      def move_pages(self, indices: list[int], to_index: int) -> None: ...
      def move_up(self, indices: list[int]) -> None: ...
      def move_down(self, indices: list[int]) -> None: ...
      def is_dirty(self) -> bool: ...
      def mark_saved(self, save_path: str) -> None: ...
  ```
- [x] Each `PdfTab` owns a `PdfEditModel`; initial model = all pages from opened file in order
- [x] Track `original_path` separately from any future Save As path

### Checklist — Grid & Rendering Refactor

- [x] Refactor `ThumbnailGrid.load_pdf()` → `load_model(model, loader_cache)`:
  - [x] Cards reflect **logical** order; labels show `1…N` after edits
  - [x] `SelectionManager` indices are **logical** positions (re-document semantics)
- [x] Update `ThumbnailWorker` to render via `PageRef` (path + source_index), not single-path
- [x] Update `PagePreviewWidget` to resolve logical index → `PageRef` → render
- [x] Loader cache per tab: keyed by `source_path`, avoid duplicate `fitz.open()` handles

### Checklist — Outbound Drag Update

- [x] Update `page_extractor.py` (or add helper) to extract from `PageRef` list
- [x] Update `PageCard._start_drag()` to resolve selection through `PdfEditModel` so outbound
  drag exports the **edited logical order**, not raw source indices

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/core/test_pdf_editor.py`:
  - [x] `test_initial_model_matches_source_page_count`
  - [x] `test_insert_pages_at_index`
  - [x] `test_remove_pages`
  - [x] `test_move_pages_changes_order`
  - [x] `test_move_up_down`
  - [x] `test_is_dirty_after_edit`
  - [x] `test_mark_saved_clears_dirty`
- [x] Write `tests/smoke/test_phase12_edit_model.py` — open 5-page fixture, verify model,
  thumbnails, and preview stay in sync
- [x] Run: `uv run pytest tests/core/test_pdf_editor.py tests/smoke/test_phase12_edit_model.py -v`

### ✅ Test Gate 12
- [x] **Open 5-page PDF** → model count = 5, labels `1…5`
- [x] **Preview page 3** → shows correct source page after any model load
- [x] **Thumbnails** render from correct `PageRef` sources
- [x] **Outbound drag** still works and reflects logical selection

---

## Phase 13 — Reorder and Delete Pages

**Goal:** Reorganize and remove pages inside a tab. Reorder via internal drag-and-drop
**and** arrow-button fallback.

> **Design decision (locked in):** Both internal DnD and Move up/down toolbar buttons.

### Checklist — Delete Pages

- [x] Toolbar button: **Delete page(s)** (enabled when selection non-empty)
- [x] Context menu: **Delete selected pages**
- [x] `Delete` key shortcut
- [x] Call `PdfEditModel.remove_pages()`; refresh grid; mark tab dirty
- [x] Deleting all pages → empty grid message; tab stays open, marked dirty
- [x] No-op when nothing selected

### Checklist — Arrow Reorder

- [x] Toolbar: **Move up** / **Move down** (move selected block, preserve relative order)
- [x] Context menu entries mirroring toolbar
- [x] Shortcuts: `Ctrl+↑` / `Ctrl+↓`
- [x] After move: refresh grid, reselect moved pages at new logical positions
- [x] Disable at top/bottom boundary

### Checklist — Internal Drag-and-Drop Reorder

- [x] Distinguish **internal reorder drag** from **outbound file-manager drag**:
  - Internal mime: `application/x-pagedrop-page` with logical index payload
  - Outbound mime: existing `file://` URLs (unchanged protocol for Explorer/Finder)
- [x] Show **drop indicator line** between cards while dragging (insertion index from cursor)
- [x] Multi-page drag: move selected pages as a block to drop index
- [x] Call `PdfEditModel.move_pages()`; re-render affected thumbnails; mark dirty
- [x] Reset `last_clicked_index` after reorder (same rule as reload)

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/ui/test_page_reorder.py`:
  - [x] `test_delete_selected_pages`
  - [x] `test_delete_all_pages_shows_empty_state`
  - [x] `test_move_up_down_buttons`
  - [x] `test_labels_renumber_after_delete`
- [x] Write `tests/ui/test_internal_drag_reorder.py`:
  - [x] `test_drop_indicator_index`
  - [x] `test_multi_select_internal_move`
  - [x] `test_outbound_drag_still_uses_file_urls`
- [x] Update `tests/ui/test_drag_drop.py` for post-model outbound drag
- [x] Run: `uv run pytest tests/ui/test_page_reorder.py tests/ui/test_internal_drag_reorder.py -v`

### ✅ Test Gate 13
- [x] **Drag pages 3 and 5** to position 1 → order and labels correct
- [x] **Move selection down** with arrow buttons → order updates
- [x] **Delete page 2** → labels renumber, tab marked dirty
- [x] **Outbound drag** extracts pages in edited order
- [x] **Internal vs outbound drag** do not conflict

---

## Phase 14 — Inbound PDF Drop (Insert Pages)

**Goal:** Drag a PDF file from Explorer/Finder onto the thumbnail grid; all pages from the
dropped file insert at the exact drop position (between thumbnails).

> **Design decision (locked in):** Insert at exact drop point between cards, not append-only.

### Checklist — Drop Target

- [x] Enable `setAcceptDrops(True)` on `ThumbnailGrid` (or inner scroll container)
- [x] `dragEnterEvent`: accept `text/uri-list` with local `*.pdf` paths; reject non-PDF
- [x] `dragMoveEvent`: reuse Phase 13 **between-card insertion indicator**; compute drop index
- [x] `dropEvent`:
  - [x] Open dropped PDF via `PdfLoader` (corrupt/empty errors → existing dialogs)
  - [x] Create `PageRef` for **all pages** in dropped file
  - [x] `model.insert_pages(drop_index, refs)`; mark tab dirty
  - [x] Cache loader for dropped source path
  - [x] Queue thumbnail render for new pages
- [x] Status bar: `"Inserted N pages from other.pdf at position M"`

### Checklist — Edge Cases

- [x] Drop same file as tab's primary source → insert copies at position (duplicate refs OK)
- [x] Drop while thumbnails still loading → cancel-then-insert or queue (document choice)
- [x] Drop multiple files at once → insert in path-sorted order at same index
- [x] Reject drop on tab with no model (blank tab) or auto-init empty model first

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/ui/test_inbound_pdf_drop.py`:
  - [x] `test_drop_pdf_inserts_all_pages_at_index`
  - [x] `test_drop_rejects_non_pdf`
  - [x] `test_drop_marks_tab_dirty`
  - [x] `test_drop_multiple_files_sorted`
- [x] Write `tests/smoke/test_phase14_inbound_drop.py` — drag `B.pdf` (3 pages) between
  pages 2 and 3 of open doc; verify logical order and thumbnails
- [x] Run: `uv run pytest tests/ui/test_inbound_pdf_drop.py tests/smoke/test_phase14_inbound_drop.py -v`

### ✅ Test Gate 14
- [x] **Drag 3-page PDF** between pages 2 and 3 →  logical order correct
- [x] **Thumbnails** appear for inserted pages
- [x] **Tab marked dirty** after drop
- [x] **Non-PDF drop** rejected gracefully
- [x] **Drop indicator** shows correct insertion point while hovering

---

## Phase 15 — Save As (Never Overwrite Original)

**Goal:** Persist the edited logical document to a **new file only** — never silently
overwrite the original PDF.

> **Design decision (locked in):** Save As only. No Save-to-original. Validate output path
> ≠ `original_path`.

### Checklist — PDF Writer

- [x] Write `core/pdf_writer.py`:
  ```python
  def write_pdf(model: PdfEditModel, output_path: str) -> None:
      # pypdf: iterate model pages in order, add_page from each PageRef
  ```
- [x] Handle multi-source `PageRef` list (pages from dropped PDFs and primary file)
- [x] Reopen or cache `PdfReader` per unique `source_path` during write

### Checklist — Menu & Toolbar

- [x] **File → Save As…** (`Ctrl+Shift+S`) — always `QFileDialog.getSaveFileName`
- [x] Default filename: `{original_stem}_edited.pdf`
- [x] **No Save action** that writes to `original_path`
- [x] Reject if user picks the same path as `original_path` (dialog + do not write)
- [x] After success: `model.mark_saved(path)`; clear dirty; tab title loses `*`; status bar OK
- [x] Disable Save As when model is empty

### Checklist — Unsaved Changes Prompts

- [x] Implement `closeEvent` (replace `pass` TODO in `main_window.py`):
  - [x] Dirty tabs → *Save As* / *Discard* / *Cancel*
- [x] Same prompt when closing a dirty tab via `×` or `Ctrl+W`
- [x] *Save As* from prompt opens save dialog; *Cancel* aborts close

### Checklist — Test Scripts & Smoke Tests

- [ ] Write `tests/core/test_pdf_writer.py`:
  - [ ] `test_write_preserves_page_order`
  - [ ] `test_write_after_reorder_delete_insert`
  - [ ] `test_write_multi_source_refs`
- [ ] Write `tests/ui/test_save_as.py`:
  - [ ] `test_save_as_never_writes_original_path`
  - [ ] `test_dirty_flag_cleared_after_save`
  - [ ] `test_close_dirty_tab_shows_prompt`
- [ ] Write `tests/smoke/test_phase15_save_as.py` — full edit workflow → Save As → verify
  output with `pypdf`; original file byte-unchanged
- [ ] Run: `uv run pytest tests/core/test_pdf_writer.py tests/ui/test_save_as.py tests/smoke/test_phase15_save_as.py -v`

### ✅ Test Gate 15
- [x] **Reorder, delete, insert via drop** → Save As to new path
- [x] **Open saved file externally** → correct page count and order
- [x] **Original file unchanged** on disk
- [x] **Dirty `*`** appears after edits, clears after Save As
- [x] **Close dirty tab/app** → prompt with Save As / Discard / Cancel

> **Out of scope for Phases 11–15 (unless added later):** undo/redo, page rotation,
> password-prompt UI, Save-to-original / incremental Save. Same-window page reorder
> stays in Phase 13; **cross-window page drag** and **detachable tab windows** live in
> **Phase 18**. Whole-file PDF merge lives in **Phase 17** (separate window, not the tab editor).

---

## Phase 17 — Merge PDFs Window

**Goal:** A **separate modeless window** where users combine whole PDF files in order:
add, delete, and reorder **files** (not pages within files), preview any file on
double-click, then **Save As** the merged output. Stay in the merge window after save —
do **not** auto-open the result in the main editor tab.

> **Design decisions (locked in):**
> - File-order model only — do **not** reuse `PdfEditModel` for the list UI (page vs file reorder must stay distinct).
> - **Save As only** on merge — no “open in new tab” shortcut.
> - **Stack preview** (same pattern as `PdfTab`): list pane → full-document preview → Esc back to list.
> - **Allow duplicate paths** in the list (user may merge the same file twice intentionally).
> - Reuse `PagePreviewWidget.set_loader()` for preview — all pages navigable via ← → / ↑ ↓.

### Checklist — Core Model (`pdf_merge.py`)

- [x] Write `core/pdf_merge.py` with `PdfMergeModel`:
  - [x] Internal state: `list[str]` of absolute paths in merge order
  - [x] `add_files(paths)` — append; resolve to absolute paths
  - [x] `remove_at(index)` / `remove_indices(indices)`
  - [x] `move_up(indices)` / `move_down(indices)` — mirror `PdfEditModel` move semantics for whole files
  - [x] `reorder(from_index, to_index)` — for drag-drop sync from list widget
  - [x] Helpers: `file_count()`, `path_at(i)`, `display_name(i)` → `Path(path).name`
  - [x] `all_paths()` — ordered copy for writer

### Checklist — PDF Writer

- [x] Add to `core/pdf_writer.py`:
  ```python
  def merge_pdf_files(file_paths: list[str], output_path: str) -> None:
      # pypdf: for each path in order, append ALL pages; cache PdfReader per path
  ```
- [x] Reject empty `file_paths` with clear error
- [x] Reuse `PdfReader` cache-per-path pattern from `write_pdf()`
- [x] Propagate load/read errors using existing `PdfLoadError` style (corrupt, empty, missing)
- [x] Keep `write_pdf(model, …)` unchanged — tab Save As stays page-level

### Checklist — Merge Window UI (`merge_window.py`)

- [x] Write `ui/merge_window.py` — `MergeWindow(QMainWindow)`:
  - [x] Central `QStackedWidget`:
    - [x] Index 0: list pane (`MergeListPane` or inline layout)
    - [x] Index 1: reused `PagePreviewWidget`
  - [x] `QListWidget` rows:
    - [x] Primary text: **filename** (`Path(path).name`)
    - [x] Secondary text (optional): page count from `PdfLoader`
    - [x] Tooltip: full path
  - [x] Toolbar / actions: **Add PDFs…**, **Remove**, **Move Up**, **Move Down**, **Merge…**
  - [x] **Add PDFs…** — `QFileDialog.getOpenFileNames`; append to model; refresh list
  - [x] **Remove** — delete selected row(s) from model
  - [x] **Move Up / Down** — reorder selected file(s); disable at list bounds
  - [x] **Internal drag-drop** on list — `QListWidget.setDragDropMode(InternalMove)`; sync order back to `PdfMergeModel`
  - [x] **Drop target** on list — accept PDF `text/uri-list` drops (reuse path extraction from `ThumbnailGrid.pdf_paths_from_mime`)
  - [x] **Merge…** disabled when list empty
  - [x] **Merge…** — `QFileDialog.getSaveFileName`; default `{first_stem}_merged.pdf`; call `merge_pdf_files()`; status bar success message; **do not** open main tab
  - [x] Status bar: file count, preview page indicator when in preview stack

### Checklist — Stack Preview (double-click)

- [x] **Double-click** list row:
  - [x] Open `PdfLoader(path)` for that row
  - [x] `preview.set_loader(loader)` — builds single-source model with **all pages**
  - [x] `preview.show_page(0)` — start at page 1
  - [x] `stack.setCurrentWidget(preview)`
  - [x] Status: `"Preview — page N of M"` (connect `page_changed` while in preview)
- [x] **Back from preview:**
  - [x] Connect `PagePreviewWidget.closed` (Esc) → `stack.setCurrentWidget(list_pane)`
  - [x] Override or set footer hint to **"← → change page · Ctrl+scroll zoom · Esc back to list"** (not “back to grid”)
  - [x] Optional toolbar **Back to list** button while preview visible
- [x] Preview navigates **entire PDF** via arrow keys — no single-page-only preview

### Checklist — Main Window Entry

- [x] In `main_window.py`:
  - [x] **File → Merge PDFs…** — after Save As, before Exit
  - [x] Lazy-create one `MergeWindow` instance; show/raise on menu action (modeless)
  - [x] User can keep editing main-window tabs while merge window is open

### Checklist — Edge Cases & Polish

- [x] Close merge window with non-empty list → optional “Discard file list?” prompt
- [x] Add PDF that fails to load → dialog; do not add to list
- [x] Merge to path that already exists → normal overwrite confirm via save dialog (same as Save As)
- [x] Source PDFs on disk **unchanged** after merge (read-only inputs)

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/core/test_pdf_merge.py`:
  - [x] `test_add_remove_reorder_paths`
  - [x] `test_move_up_down_at_bounds`
  - [x] `test_display_name_returns_stem`
- [x] Extend `tests/core/test_pdf_writer.py`:
  - [x] `test_merge_pdf_files_preserves_file_order`
  - [x] `test_merge_pdf_files_rejects_empty_list`
  - [x] `test_merge_pdf_files_total_page_count`
- [x] Write `tests/ui/test_merge_window.py`:
  - [x] `test_add_files_populates_list_with_filenames`
  - [x] `test_remove_and_reorder_updates_model`
  - [x] `test_merge_disabled_when_empty`
  - [x] `test_double_click_enters_preview_stack`
  - [x] `test_escape_returns_to_list_from_preview`
- [x] Write `tests/smoke/test_phase17_merge.py` — add 3 fixture PDFs → reorder → Merge Save As →
  verify page order and counts with `pypdf`; source files byte-unchanged
- [x] Run: `uv run pytest tests/core/test_pdf_merge.py tests/core/test_pdf_writer.py tests/ui/test_merge_window.py tests/smoke/test_phase17_merge.py -v`

### ✅ Test Gate 17
- [ ] **File → Merge PDFs…** opens separate window (main window still usable)
- [ ] **Filenames visible** in list; tooltip shows full path
- [ ] **Add / Remove / Move Up / Down** and **drag reorder** change merge order
- [ ] **Double-click** → preview stack; **← →** navigates all pages of that file
- [ ] **Esc** (or Back) returns to file list
- [ ] **Merge…** writes correct combined PDF; **source files unchanged**
- [ ] **Drop PDFs** onto list adds them (consistent with Phase 14)

> **Out of scope for Phase 17:** page-level edit inside merge window, auto-open merged
> file in editor tab, merge-from-current-tab shortcut, password-prompt UI.

---

## Phase 18 — Detachable Windows & Cross-Window Page Drag

**Goal:** Let users work with **multiple editor windows** at once: tear a tab off into its
own window, open PDFs directly into a new window, and **drag pages between windows**
freely — copy by default, move with Shift+drop — so combining and reorganizing documents
across separate PDFs feels as natural as dragging within one tab.

> **Design decisions (locked in):**
> - **Tab tear-off** — drag a tab off the tab bar → that PDF moves into a **new top-level
>   window** (tab removed from source window)
> - **Open single PDF** — extend Phase 11 prompt to **three** targets: *Open in current tab*
>   / *Open in new tab* / **Open in new window**
> - **Open multiple PDFs** — default remains *each in new tab*; add batch choice *each in
>   new tab* vs *each in new window*
> - **Cross-window page drag** — **default = copy** (insert `PageRef`s at drop index; source
>   doc unchanged). **Shift+drop = move** (remove from source + insert in target; both
>   windows marked dirty)
> - **Same-window internal drag** — unchanged (Phase 13 reorder via logical indices; Shift
>   ignored for same-window drops)
> - **Window lifecycle** — multiple `MainWindow` instances under one `QApplication`;
>   `quitOnLastWindowClosed = False`; quit when the **last** editor window closes (merge
>   window counts toward keeping app alive if open)
> - **Blank tab tear-off** — new window with one blank tab (mirror Phase 11 blank-tab rules)

### Checklist — Multi-Window Shell

- [x] Add `ui/window_manager.py` — registry of open `MainWindow`s:
  - [x] `open_new_window(initial_tab: PdfTab | None = None) -> MainWindow`
  - [x] `window_for_widget(widget) -> MainWindow | None`
  - [x] Track window count; emit `last_window_closing` or call `QApplication.quit()` when appropriate
- [x] Update `main.py`:
  - [x] Create first window via `WindowManager`
  - [x] `QApplication.setQuitOnLastWindowClosed(False)`
  - [x] Quit when last editor window closes (document merge-window interaction)
- [x] Each `MainWindow` owns its own `TabManager` + `TempManager` (per-window temp cleanup on window close)
- [x] Window title / status bar remain **per active tab in that window** (reuse existing sync helpers)
- [x] **File → New Window** — spawns empty window with one blank tab
- [x] Optional shortcut: **Ctrl+Shift+N** for new window
- [x] Closing a window with multiple tabs — existing per-tab dirty prompts apply
- [x] Closing one window does not kill other open editor windows

### Checklist — Tab Tear-Off (Detach to Window)

- [x] Extend tab-bar drag beyond `QTabWidget.setMovable(True)` — distinguish **reorder within bar**
  vs **detach threshold** (pixel threshold + drag outside window geometry)
- [x] On detach:
  - [x] Remove tab from source `TabManager`
  - [x] Reparent `PdfTab` into new `MainWindow`'s `TabManager` via `WindowManager.open_new_window(tab)`
  - [x] Show and raise the new window
- [x] Source window after detach: if zero tabs → spawn blank tab (Phase 11 rule)
- [x] Detached tab keeps loader cache, `PdfEditModel`, dirty flag, zoom, scroll, preview stack state
- [x] Rebind render workers / grid signals to new parent window (no stale `MainWindow` references)
- [x] Optional visual: ghost tab / cursor hint while dragging tab for detach affordance
- [x] Context menu fallback: **Move to New Window** on tab right-click (accessibility / precision alternative to drag)

### Checklist — Open Target Prompt (extend Phase 11)

- [x] Extend `_ask_open_target()` — third button **Open in new window**
- [x] **Open in new window** → `WindowManager.open_new_window()` + load PDF into its first tab
- [x] Blank current tab + *current tab* choice — unchanged Phase 11 behavior
- [x] **Multi-select Open** — prompt or submenu: *each in new tab* (current default) vs *each in new window*
- [x] Phase 18 test gate covers new open targets — do **not** retroactively change Phase 11 checkboxes

### Checklist — Cross-Window Page Drag (`drag_mime.py` + grid drop routing)

- [x] Add `application/x-pagedrop-page-transfer` in `core/drag_mime.py`:
  - [x] Encode **list of `PageRef`** (`source_path`, `source_index`) — not logical indices
  - [x] Optional `transfer_mode: copy|move` in payload (or infer move from Shift on drop)
  - [x] Helpers: `encode_page_refs(refs) -> bytes`, `decode_page_refs(data) -> list[PageRef]`
- [x] Outbound drag from `PageCard` includes transfer payload whenever drag may leave the source grid
  (keep existing `file://` URLs for Explorer compatibility)
- [x] `ThumbnailGrid.dropEvent` routing:
  - [x] Same grid + `INTERNAL_PAGE_MIME` indices only → **reorder** (Phase 13, unchanged)
  - [x] Transfer payload from **different** top-level window → **insert** at drop index via `model.insert_pages()`
  - [x] **Default (no Shift):** copy — source model untouched; target dirty
  - [x] **Shift held on drop:** move — `remove_pages` on source for dragged logical indices, then insert in target; source dirty
- [x] Drop indicator (Phase 13) works when hovering over **another window's** grid
- [x] Target blank tab: auto-init model on first cross-window drop (align with Phase 14 blank-tab rule)
- [x] Status bar: `"Inserted N pages from other.pdf"` / `"Moved N pages to …"` with source filename
- [x] Reject transfer if source paths fail to load (corrupt/missing) — reuse Phase 14 error dialogs

### Checklist — Edge Cases & Polish

- [x] Drag pages from window A → drop on window A (same grid) — still internal reorder, not copy
- [x] Shift+drop on same window — Shift ignored; reorder only (no copy/move semantics)
- [x] Tear-off while tab in preview mode — preview state survives in new window
- [x] Tear-off dirty tab — dirty `*` travels with tab; unsaved prompt on close applies to correct window
- [x] Two windows, same PDF path open — allowed; cross-window copy may duplicate refs (Phase 14 precedent)
- [x] Merge window open + multiple editor windows — app stays alive until all closed
- [x] Explorer outbound drag still works from either window (unchanged `file://` protocol)

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/ui/test_window_manager.py`:
  - [x] `test_open_new_window_spawns_second_main_window`
  - [x] `test_last_window_close_quits_app_when_only_one`
  - [x] `test_two_windows_independent_tab_state`
- [x] Write `tests/ui/test_tab_detach.py`:
  - [x] `test_detach_tab_creates_new_window_with_same_pdf`
  - [x] `test_detach_last_tab_spawns_blank_in_source_window`
  - [x] `test_move_to_new_window_context_menu`
- [x] Write `tests/ui/test_open_in_new_window.py`:
  - [x] `test_single_file_open_new_window_prompt`
  - [x] `test_open_in_new_window_loads_pdf`
  - [x] `test_multi_select_open_each_in_new_window`
- [x] Write `tests/ui/test_cross_window_page_drag.py`:
  - [x] `test_copy_pages_from_window_a_to_b`
  - [x] `test_shift_drop_moves_pages_between_windows`
  - [x] `test_same_window_drop_still_reorders`
  - [x] `test_cross_window_drop_marks_target_dirty`
  - [x] `test_move_marks_source_dirty`
- [x] Write `tests/smoke/test_phase18_multi_window.py` — open two windows with fixture PDFs,
  copy pages A→B, Shift+move pages B→A, tear off tab, verify counts/order via `pypdf` after Save As
- [x] Run: `uv run pytest tests/ui/test_window_manager.py tests/ui/test_tab_detach.py tests/ui/test_open_in_new_window.py tests/ui/test_cross_window_page_drag.py tests/smoke/test_phase18_multi_window.py -v`

### ✅ Test Gate 18
- [x] **File → Open** single PDF → **Open in new window** opens a second window with that PDF
- [x] **File → New Window** (or **Ctrl+Shift+N**) spawns an empty editor window
- [x] **Drag tab off tab bar** → new window; source window retains other tabs / blank tab rule
- [x] **Move to New Window** context menu on tab works as tear-off alternative
- [x] **Two windows side by side** → drag pages from A to B inserts at drop indicator (copy)
- [x] **Shift+drop** between windows → pages removed from source and appear in target
- [x] **Explorer outbound drag** still works from either window
- [x] **Internal reorder within one window** unchanged
- [x] **Dirty tab** tear-off + close → Save As / Discard prompt on correct window
- [x] **Close all editor windows** → app exits cleanly

> **Out of scope for Phase 18:** cross-tab drag within the **same** window without detach
> (still reorder-only in one grid), syncing undo across windows, OS-level multi-instance
> (second app process), auto-tile window layout.

---

## Phase 19 — Create PDF (Images → PDF)

**Goal:** A **separate modeless window** where users add raster images in order, preview
any image on double-click, then export as **one combined PDF** or **one PDF per image**.
Stay in the Create PDF window after save — do **not** auto-open the result in the editor.

> **Design decisions (locked in):**
> - **Menubar entry:** top-level **Create PDF** beside **File** and **Merge PDFs** — not
>   inside the File menu (same pattern as `menubar.addAction("Merge PDFs")`).
> - **Inputs: raster images only** — PNG, JPEG, BMP, GIF, TIFF, WebP, etc. (PyMuPDF-openable).
>   Reject PDFs on add/drop with hint to use **Merge PDFs**.
> - **No LibreOffice**, no Office formats, no external converters — fully in-process PyMuPDF
>   (exe-safe; no new PyInstaller deps beyond existing `fitz`).
> - **Output mode:** **One PDF** (all images → one file, one page per image) or
>   **Separate PDFs** (each image → `{stem}.pdf` in a chosen folder).
> - File-order model — mirror Merge grid UX (add, remove, reorder, drop) but every row is
>   a single image thumbnail (do **not** reuse stacked PDF thumbnails or `PdfMergeModel`).
> - **Do not auto-open** converted PDF(s) in the editor tab (same as Phase 17 merge).
> - **Source images unchanged** on disk after convert.
> - **Allow duplicate paths** in the list (same as Phase 17).

> **Merge vs Create PDF:**
>
> | Window | Inputs | Output |
> |---|---|---|
> | Merge PDFs | PDF files | Always one combined PDF |
> | Create PDF | Image files | One combined PDF **or** one PDF per image |

### Checklist — Supported formats (`supported_formats.py`)

- [x] Write `core/supported_formats.py`:
  - [x] `SUPPORTED_IMAGE_EXTENSIONS` — PNG, JPG, JPEG, BMP, GIF, TIFF, TIF, WebP, …
  - [x] `is_supported_image(path) -> bool`
  - [x] `image_dialog_filter() -> str` for `QFileDialog` (“Images (*.png *.jpg …)”)
- [x] Reject non-image extensions on add/drop — dialog names the file and points to
  **Merge PDFs** for PDFs

### Checklist — Image-to-PDF writer (`image_to_pdf.py`)

- [x] Write `core/image_to_pdf.py` with `ConvertModel`:
  - [x] Internal state: `list[str]` of absolute image paths in order
  - [x] `add_files(paths)` — append; resolve to absolute paths; filter to supported images
  - [x] `remove_at(index)` / `remove_indices(indices)`
  - [x] `move_up(indices)` / `move_down(indices)` — mirror `PdfMergeModel` move semantics
  - [x] `reorder(from_index, to_index)` — for drag-drop sync from grid
  - [x] Helpers: `file_count()`, `path_at(i)`, `display_name(i)`, `all_paths()`
- [x] `images_to_single_pdf(paths, output_path) -> None`:
  - [x] One PyMuPDF page per image in list order
  - [x] Page size = image dimensions (preserve aspect ratio; no letter-size letterboxing in v1)
- [x] `images_to_individual_pdfs(paths, output_dir) -> list[str]`:
  - [x] Each image → `{stem}.pdf` one page
- [x] Reject empty path list with clear error
- [x] Corrupt/unreadable image → raise clear error (wrap `fitz` failures)
- [x] Filename collision in output dir → append `_2`, `_3`, …

### Checklist — Create PDF window UI (`convert_window.py`)

- [x] Write `ui/convert_window.py` — `ConvertWindow(QMainWindow)`:
  - [x] Window title: **Create PDF**
  - [x] Central `QStackedWidget`:
    - [x] Index 0: image grid (`ConvertFileGrid`)
    - [x] Index 1: full-size image preview (lightweight `QLabel` + scroll or reuse preview pane)
  - [x] `ConvertFileGrid` / `ConvertFileCard` — reuse merge grid layout patterns (zoom,
    selection, internal reorder drag) from `MergeFileGrid`:
    - [x] Each row: single-image thumbnail via `QPixmap` or PyMuPDF render
    - [x] Row label: filename; tooltip optional dimensions
  - [x] Toolbar: **Add Images…**, **Remove**, **Move Up**, **Move Down**
  - [x] **Output mode** control: **One PDF** / **Separate PDFs** (radio or segmented toggle;
    persist choice in session)
  - [x] Primary action label changes with mode: **Save PDF…** vs **Choose folder…**
  - [x] **Create** disabled when list empty or while worker running
  - [x] Background worker (`QThreadPool`) + busy overlay (mirror `MergeWindow._MergeWorker`)
  - [x] Status bar: image count, success/failure summary
  - [x] Drop target accepts image `text/uri-list` only (filter through `is_supported_image`)
  - [x] Close with non-empty list → optional “Discard file list?” prompt

### Checklist — Image preview (double-click)

- [x] **Double-click** grid row → full-size image in preview stack
- [x] **Esc** / Back returns to grid; footer hint: “Esc back to grid”
- [x] Optional toolbar **Back to grid** while preview visible

### Checklist — Main window entry

- [x] In `main_window.py` `_build_menu()` — add top-level **Create PDF** immediately after
  **Merge PDFs**:
  ```python
  create_pdf_action = menubar.addAction("Create PDF")
  create_pdf_action.triggered.connect(self._open_convert_window)
  ```
- [x] Menubar order: **File** | **Merge PDFs** | **Create PDF**
- [x] Lazy-create one `ConvertWindow`; show/raise on action (modeless)
- [x] `WindowManager` / app quit: convert window open keeps app alive (same rule as merge window)

### Checklist — Edge cases & polish

- [x] Drop/add PDF → reject: “Create PDF accepts images only. Use Merge PDFs for PDF files.”
- [x] One corrupt image in batch → fail-fast dialog before write (no partial output without confirmation)
- [x] Very large images → max dimension / memory guard before render
- [x] EXIF orientation (JPEG) — verify PyMuPDF/Qt auto-correct; apply rotation if not
- [x] **Separate PDFs** mode: confirm overwrite if `{stem}.pdf` exists in output folder
- [x] Transparent PNG → document chosen background (white or transparent) in v1

### Checklist — Test Scripts & Smoke Tests

- [x] Write `tests/core/test_supported_formats.py`:
  - [x] `test_supported_image_extensions`
  - [x] `test_rejects_pdf_extension`
- [x] Write `tests/core/test_image_to_pdf.py`:
  - [x] `test_images_to_single_pdf_page_order`
  - [x] `test_individual_pdfs_writes_one_file_per_image`
  - [x] `test_rejects_empty_list`
  - [x] `test_collision_suffix_on_duplicate_stem`
  - [x] `test_corrupt_image_raises`
- [x] Write `tests/ui/test_convert_window.py`:
  - [x] `test_add_images_populates_grid`
  - [x] `test_reject_pdf_on_add`
  - [x] `test_output_mode_toggle_updates_action_label`
  - [x] `test_convert_disabled_when_empty`
  - [x] `test_separate_mode_uses_folder_dialog`
  - [x] `test_menubar_create_pdf_beside_merge`
- [x] Write `tests/smoke/test_phase19_create_pdf.py` — fixture PNGs/JPEGs → combine +
  separate modes; verify page counts with `pypdf`
- [x] Run: `uv run pytest tests/core/test_supported_formats.py tests/core/test_image_to_pdf.py tests/ui/test_convert_window.py tests/smoke/test_phase19_create_pdf.py -v`

### ✅ Test Gate 19
- [ ] **Create PDF** (menubar, beside Merge PDFs) opens separate window
- [ ] **Add Images…** and **drop** PNG/JPEG — thumbnails appear in grid
- [ ] **Drop PDF** → rejected with helpful message pointing to Merge PDFs
- [ ] **One PDF** mode — N images → one PDF with N pages in list order
- [ ] **Separate PDFs** mode — N images → N `{stem}.pdf` files in chosen folder
- [ ] **Reorder** changes page order in combine mode
- [ ] **Source images unchanged** on disk
- [ ] **Double-click** → image preview; Esc back to grid
- [ ] **Built exe** (Phase 16): Create PDF combine + separate modes work on clean VM

> **Out of scope for Phase 19:** LibreOffice / Office document conversion, PDF files as
> Create PDF inputs (use Merge PDFs), auto-open result in editor tab, OCR, compression
> settings, custom page size / margins, converting **from** PDF to other formats.

---

## Phase 16 — Optional: Compile to Executable

**Goal:** A single `.exe` (Windows) or binary (Linux/macOS) that runs without Python.

### Checklist

- [x] Add `PyInstaller` as a dev dependency:
  ```toml
  [dependency-groups]
  dev = [..., "pyinstaller>=6.0"]
  ```
  Then: `uv sync --group dev`
- [x] Do a basic build first: `uv run pyinstaller --onefile --windowed src/pagedrop/main.py`
- [x] If that fails, create a `.spec` file and add hidden imports for PyMuPDF
  and PyQt6 plugins:
  ```python
  # pagedrop.spec
  hiddenimports=["fitz", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets"]
  ```
- [x] Add `--add-data` for any assets (icons, etc.) if you added them
- [ ] Test the built executable on a machine **without Python installed**
- [ ] Check that the exe opens PDFs correctly and drag-drop to file manager works
- [ ] Note: PyMuPDF bundles its own native libs — PyInstaller should pick them up
  automatically, but verify
- [ ] If exe size is too large, consider `--onedir` mode instead of `--onefile`
- [x] Add a `Makefile` or `build.sh` script so the build command is documented

### Checklist — Test Scripts & Smoke Tests

- [x] Write `scripts/smoke_exe.sh` / `scripts/smoke_exe.ps1`:
  - [x] Build exe via documented command
  - [x] Launch exe as subprocess with timeout
  - [x] Assert process starts (no immediate exit code ≠ 0)
  - [x] Optional: pass a fixture PDF path via env var if exe supports it, else document manual open step
- [x] Write `tests/smoke/test_phase16_executable.py` (skipped locally unless `PAGEDROP_EXE` env var set):
  - [x] `@pytest.mark.skipif(not os.environ.get("PAGEDROP_EXE"))`
  - [x] Launch built binary, verify it stays alive ≥ 5s
  - [ ] On Windows VM / clean machine checklist: same script run outside dev environment
- [x] Add CI or release note: run full smoke suite before tagging:
  ```bash
  uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
  PAGEDROP_EXE=./dist/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v
  ```

### ✅ Test Gate 16
- [ ] **Exe opens** without "DLL not found" or similar errors
- [ ] **Open a PDF** via the exe → thumbnails render
- [ ] **Drag a page to a folder** → works exactly like the dev version
- [ ] **Multi-tab, Save As, Merge PDFs, Create PDF, and multi-window drag** work in the built binary
- [ ] **Create PDF** — image combine + separate modes work in exe on a clean VM (no Python)
- [ ] **Test on a second machine** or VM that has never had Python installed

---

## Suggested Build Order

Work through phases in this order. **Don't move on until the test gate for each phase passes.**

Each phase also has a **Test Scripts & Smoke Tests** checklist — write those tests as you go so regressions are caught before the manual test gate.

```
Phase 1–9 (done) → 11 Tabs → 12 Model → 13 Reorder/Delete → 14 Inbound drop → 15 Save As → 17 Merge → 18 Multi-Window → 19 Create PDF → 16 Exe
     Setup…Polish      Multi-tab   PdfEditModel   Edit UI        Drop PDFs      Persist      Combine    Detach/Drag   Images→PDF  Binary
```

Phases 12–15 are sequential (each builds on `PdfEditModel`). Phase 11 should land before
Phase 13 UI work. Phase 17 is independent of `PdfEditModel` but should land after Phase 15
(writer patterns). Phase 18 builds on Phases 11–14 (tabs, model, internal drag, inbound
drop) and should land after Phase 17 and before Phase 19 (Create PDF). Phase 19 is
independent of `PdfEditModel` but should land after Phase 17 (writer/grid patterns) and
before Phase 16 (exe packaging). Phases 6–7 were
the hardest in the original build; Phase 13–14 (dual drag types + drop indicator) and
Phase 18 (cross-window mime + tab tear-off) will need similar care.

---

## Common Pitfalls to Avoid

| Pitfall | How to avoid |
|---|---|
| Rendering thumbnails on main thread | Always use `QRunnable`/`QThreadPool` |
| PyMuPDF doc object not thread-safe | Create a fresh `fitz.open()` inside the worker, not shared |
| Drag starting on every mouse move | Check `QApplication.startDragDistance()` before starting drag |
| Temp files piling up | Clean up per-drag, plus `atexit` handler as backstop |
| Shift+click breaks after re-load | Reset `last_clicked_index` to `None` when loading new PDF |
| File manager gets confused by non-`file://` URLs | Always use `QUrl.fromLocalFile()`, never manual string URLs |
| Worker still running when PDF is closed | Keep a reference to the worker, cancel/wait on PDF close |
| Internal reorder drag vs outbound file drag | Use separate mime types (`application/x-pagedrop-page` vs `file://` URLs); test both paths |
| Outbound drag uses stale source indices | Resolve selection through `PdfEditModel` / `PageRef`, not raw PDF indices |
| `pypdf` multi-source write | Cache or reopen `PdfReader` per unique `PageRef.source_path` in `write_pdf()` |
| PyMuPDF not thread-safe across paths | Worker opens doc by path per `PageRef`; loader cache on main thread only |
| Shift+click breaks after reorder | Reset `last_clicked_index` when logical order changes |
| Save As overwrites original | Reject output path == `original_path`; no silent Save action |
| Tab state leaks on switch | Route all toolbar/menu actions to active `PdfTab` only |
| Drop during thumbnail load | Cancel or queue insert until render generation settles |
| File merge vs page merge | Use `PdfMergeModel` + `merge_pdf_files()` for whole-file order; use `PdfEditModel` + `write_pdf()` for page-level tab edits — do not conflate |
| Merge preview stuck on one page | Use `PagePreviewWidget.set_loader()` so all pages are in the model; double-click calls `show_page(0)`; Esc returns to list stack |
| Merge list out of sync after drag | Sync `QListWidget` internal move back into `PdfMergeModel.reorder()` on `rowsMoved` or equivalent signal |
| Internal reorder indices used cross-window | Serialize `PageRef`s in `application/x-pagedrop-page-transfer`, not logical indices |
| Tab tear-off without rebinding workers/signals | Detach checklist: reparent `PdfTab`, rebind grid signals and render worker to new `MainWindow` |
| `quitOnLastWindowClosed` kills app while second window open | `setQuitOnLastWindowClosed(False)`; quit explicitly when last editor window closes |
| Cross-window drop treated as same-window reorder | Route by source vs target top-level window; transfer mime → `insert_pages`, internal mime → reorder |
| Merge vs Create PDF conflated | Merge = PDF-only, one output; Create PDF = images-only, dual output modes — separate models and windows |
| PDF dropped on Create PDF grid | Filter add/drop through `is_supported_image()`; reject PDFs with hint to use Merge PDFs |
| Huge PNG exhausts memory on convert | Max dimension guard before PyMuPDF embed; worker on thread pool, not main thread |
| JPEG appears rotated in output PDF | Verify EXIF orientation; rotate pixmap/page before embed if PyMuPDF does not auto-correct |

---

## Quick Reference — uv Commands

```bash
uv init pagedrop --lib   # initialise project
uv add PyQt6 PyMuPDF pypdf       # add runtime deps
uv add --dev pytest pytest-qt pyinstaller   # test + build deps
uv sync                          # install all deps
uv run pagedrop               # run the app
uv run python some_script.py     # run a one-off script
uv run pytest tests/ -v          # run all tests
uv run pytest tests/smoke/ -v    # smoke tests only
uv run pyinstaller pagedrop.spec  # build exe
```
