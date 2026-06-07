# PageDrop — Complete Build Plan

A Python desktop app that renders PDF pages as thumbnails so you can drag single
or multiple pages directly into folders in your file manager. **Phases 1–9** (complete)
cover the read-only single-document workflow. **Phases 11–15** extend the app with
multi-tab editing, page reorder/delete, inbound PDF drop, and Save As.

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
        │   ├── tab_manager.py    # QTabWidget wrapper + tab lifecycle   [Phase 11]
        │   ├── pdf_tab.py        # per-tab state container widget        [Phase 11]
        │   ├── thumbnail_grid.py # scrollable grid of pages
        │   └── page_card.py      # individual page widget + drag logic
        ├── core/
        │   ├── __init__.py
        │   ├── pdf_loader.py     # open PDF, render pages via PyMuPDF
        │   ├── pdf_editor.py     # PdfEditModel + PageRef dataclass      [Phase 12]
        │   ├── pdf_writer.py     # write_pdf() — merge from multiple src [Phase 15]
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

- [ ] Write `core/pdf_editor.py`:
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
- [ ] Each `PdfTab` owns a `PdfEditModel`; initial model = all pages from opened file in order
- [ ] Track `original_path` separately from any future Save As path

### Checklist — Grid & Rendering Refactor

- [ ] Refactor `ThumbnailGrid.load_pdf()` → `load_model(model, loader_cache)`:
  - [ ] Cards reflect **logical** order; labels show `1…N` after edits
  - [ ] `SelectionManager` indices are **logical** positions (re-document semantics)
- [ ] Update `ThumbnailWorker` to render via `PageRef` (path + source_index), not single-path
- [ ] Update `PagePreviewWidget` to resolve logical index → `PageRef` → render
- [ ] Loader cache per tab: keyed by `source_path`, avoid duplicate `fitz.open()` handles

### Checklist — Outbound Drag Update

- [ ] Update `page_extractor.py` (or add helper) to extract from `PageRef` list
- [ ] Update `PageCard._start_drag()` to resolve selection through `PdfEditModel` so outbound
  drag exports the **edited logical order**, not raw source indices

### Checklist — Test Scripts & Smoke Tests

- [ ] Write `tests/core/test_pdf_editor.py`:
  - [ ] `test_initial_model_matches_source_page_count`
  - [ ] `test_insert_pages_at_index`
  - [ ] `test_remove_pages`
  - [ ] `test_move_pages_changes_order`
  - [ ] `test_move_up_down`
  - [ ] `test_is_dirty_after_edit`
  - [ ] `test_mark_saved_clears_dirty`
- [ ] Write `tests/smoke/test_phase12_edit_model.py` — open 5-page fixture, verify model,
  thumbnails, and preview stay in sync
- [ ] Run: `uv run pytest tests/core/test_pdf_editor.py tests/smoke/test_phase12_edit_model.py -v`

### ✅ Test Gate 12
- [ ] **Open 5-page PDF** → model count = 5, labels `1…5`
- [ ] **Preview page 3** → shows correct source page after any model load
- [ ] **Thumbnails** render from correct `PageRef` sources
- [ ] **Outbound drag** still works and reflects logical selection

---

## Phase 13 — Reorder and Delete Pages

**Goal:** Reorganize and remove pages inside a tab. Reorder via internal drag-and-drop
**and** arrow-button fallback.

> **Design decision (locked in):** Both internal DnD and Move up/down toolbar buttons.

### Checklist — Delete Pages

- [ ] Toolbar button: **Delete page(s)** (enabled when selection non-empty)
- [ ] Context menu: **Delete selected pages**
- [ ] `Delete` key shortcut
- [ ] Call `PdfEditModel.remove_pages()`; refresh grid; mark tab dirty
- [ ] Deleting all pages → empty grid message; tab stays open, marked dirty
- [ ] No-op when nothing selected

### Checklist — Arrow Reorder

- [ ] Toolbar: **Move up** / **Move down** (move selected block, preserve relative order)
- [ ] Context menu entries mirroring toolbar
- [ ] Shortcuts: `Ctrl+↑` / `Ctrl+↓`
- [ ] After move: refresh grid, reselect moved pages at new logical positions
- [ ] Disable at top/bottom boundary

### Checklist — Internal Drag-and-Drop Reorder

- [ ] Distinguish **internal reorder drag** from **outbound file-manager drag**:
  - Internal mime: `application/x-pagedrop-page` with logical index payload
  - Outbound mime: existing `file://` URLs (unchanged protocol for Explorer/Finder)
- [ ] Show **drop indicator line** between cards while dragging (insertion index from cursor)
- [ ] Multi-page drag: move selected pages as a block to drop index
- [ ] Call `PdfEditModel.move_pages()`; re-render affected thumbnails; mark dirty
- [ ] Reset `last_clicked_index` after reorder (same rule as reload)

### Checklist — Test Scripts & Smoke Tests

- [ ] Write `tests/ui/test_page_reorder.py`:
  - [ ] `test_delete_selected_pages`
  - [ ] `test_delete_all_pages_shows_empty_state`
  - [ ] `test_move_up_down_buttons`
  - [ ] `test_labels_renumber_after_delete`
- [ ] Write `tests/ui/test_internal_drag_reorder.py`:
  - [ ] `test_drop_indicator_index`
  - [ ] `test_multi_select_internal_move`
  - [ ] `test_outbound_drag_still_uses_file_urls`
- [ ] Update `tests/ui/test_drag_drop.py` for post-model outbound drag
- [ ] Run: `uv run pytest tests/ui/test_page_reorder.py tests/ui/test_internal_drag_reorder.py -v`

### ✅ Test Gate 13
- [ ] **Drag pages 3 and 5** to position 1 → order and labels correct
- [ ] **Move selection down** with arrow buttons → order updates
- [ ] **Delete page 2** → labels renumber, tab marked dirty
- [ ] **Outbound drag** extracts pages in edited order
- [ ] **Internal vs outbound drag** do not conflict

---

## Phase 14 — Inbound PDF Drop (Insert Pages)

**Goal:** Drag a PDF file from Explorer/Finder onto the thumbnail grid; all pages from the
dropped file insert at the exact drop position (between thumbnails).

> **Design decision (locked in):** Insert at exact drop point between cards, not append-only.

### Checklist — Drop Target

- [ ] Enable `setAcceptDrops(True)` on `ThumbnailGrid` (or inner scroll container)
- [ ] `dragEnterEvent`: accept `text/uri-list` with local `*.pdf` paths; reject non-PDF
- [ ] `dragMoveEvent`: reuse Phase 13 **between-card insertion indicator**; compute drop index
- [ ] `dropEvent`:
  - [ ] Open dropped PDF via `PdfLoader` (corrupt/empty errors → existing dialogs)
  - [ ] Create `PageRef` for **all pages** in dropped file
  - [ ] `model.insert_pages(drop_index, refs)`; mark tab dirty
  - [ ] Cache loader for dropped source path
  - [ ] Queue thumbnail render for new pages
- [ ] Status bar: `"Inserted N pages from other.pdf at position M"`

### Checklist — Edge Cases

- [ ] Drop same file as tab's primary source → insert copies at position (duplicate refs OK)
- [ ] Drop while thumbnails still loading → cancel-then-insert or queue (document choice)
- [ ] Drop multiple files at once → insert in path-sorted order at same index
- [ ] Reject drop on tab with no model (blank tab) or auto-init empty model first

### Checklist — Test Scripts & Smoke Tests

- [ ] Write `tests/ui/test_inbound_pdf_drop.py`:
  - [ ] `test_drop_pdf_inserts_all_pages_at_index`
  - [ ] `test_drop_rejects_non_pdf`
  - [ ] `test_drop_marks_tab_dirty`
  - [ ] `test_drop_multiple_files_sorted`
- [ ] Write `tests/smoke/test_phase14_inbound_drop.py` — drag `B.pdf` (3 pages) between
  pages 2 and 3 of open doc; verify logical order and thumbnails
- [ ] Run: `uv run pytest tests/ui/test_inbound_pdf_drop.py tests/smoke/test_phase14_inbound_drop.py -v`

### ✅ Test Gate 14
- [ ] **Drag 3-page PDF** between pages 2 and 3 →  logical order correct
- [ ] **Thumbnails** appear for inserted pages
- [ ] **Tab marked dirty** after drop
- [ ] **Non-PDF drop** rejected gracefully
- [ ] **Drop indicator** shows correct insertion point while hovering

---

## Phase 15 — Save As (Never Overwrite Original)

**Goal:** Persist the edited logical document to a **new file only** — never silently
overwrite the original PDF.

> **Design decision (locked in):** Save As only. No Save-to-original. Validate output path
> ≠ `original_path`.

### Checklist — PDF Writer

- [ ] Write `core/pdf_writer.py`:
  ```python
  def write_pdf(model: PdfEditModel, output_path: str) -> None:
      # pypdf: iterate model pages in order, add_page from each PageRef
  ```
- [ ] Handle multi-source `PageRef` list (pages from dropped PDFs and primary file)
- [ ] Reopen or cache `PdfReader` per unique `source_path` during write

### Checklist — Menu & Toolbar

- [ ] **File → Save As…** (`Ctrl+Shift+S`) — always `QFileDialog.getSaveFileName`
- [ ] Default filename: `{original_stem}_edited.pdf`
- [ ] **No Save action** that writes to `original_path`
- [ ] Reject if user picks the same path as `original_path` (dialog + do not write)
- [ ] After success: `model.mark_saved(path)`; clear dirty; tab title loses `*`; status bar OK
- [ ] Disable Save As when model is empty

### Checklist — Unsaved Changes Prompts

- [ ] Implement `closeEvent` (replace `pass` TODO in `main_window.py`):
  - [ ] Dirty tabs → *Save As* / *Discard* / *Cancel*
- [ ] Same prompt when closing a dirty tab via `×` or `Ctrl+W`
- [ ] *Save As* from prompt opens save dialog; *Cancel* aborts close

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
- [ ] **Reorder, delete, insert via drop** → Save As to new path
- [ ] **Open saved file externally** → correct page count and order
- [ ] **Original file unchanged** on disk
- [ ] **Dirty `*`** appears after edits, clears after Save As
- [ ] **Close dirty tab/app** → prompt with Save As / Discard / Cancel

> **Out of scope for Phases 11–15 (unless added later):** undo/redo, page rotation,
> cross-tab page drag, password-prompt UI, Save-to-original / incremental Save.

---

## Phase 16 — Optional: Compile to Executable

**Goal:** A single `.exe` (Windows) or binary (Linux/macOS) that runs without Python.

### Checklist

- [ ] Add `PyInstaller` as a dev dependency:
  ```toml
  [project.optional-dependencies]
  dev = ["pyinstaller>=6.0"]
  ```
  Then: `uv sync --extra dev`
- [ ] Do a basic build first: `uv run pyinstaller --onefile --windowed src/pagedrop/main.py`
- [ ] If that fails, create a `.spec` file and add hidden imports for PyMuPDF
  and PyQt6 plugins:
  ```python
  # pagedrop.spec
  hiddenimports=["fitz", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets"]
  ```
- [ ] Add `--add-data` for any assets (icons, etc.) if you added them
- [ ] Test the built executable on a machine **without Python installed**
- [ ] Check that the exe opens PDFs correctly and drag-drop to file manager works
- [ ] Note: PyMuPDF bundles its own native libs — PyInstaller should pick them up
  automatically, but verify
- [ ] If exe size is too large, consider `--onedir` mode instead of `--onefile`
- [ ] Add a `Makefile` or `build.sh` script so the build command is documented

### Checklist — Test Scripts & Smoke Tests

- [ ] Write `scripts/smoke_exe.sh` / `scripts/smoke_exe.ps1`:
  - [ ] Build exe via documented command
  - [ ] Launch exe as subprocess with timeout
  - [ ] Assert process starts (no immediate exit code ≠ 0)
  - [ ] Optional: pass a fixture PDF path via env var if exe supports it, else document manual open step
- [ ] Write `tests/smoke/test_phase16_executable.py` (skipped locally unless `PAGEDROP_EXE` env var set):
  - [ ] `@pytest.mark.skipif(not os.environ.get("PAGEDROP_EXE"))`
  - [ ] Launch built binary, verify it stays alive ≥ 5s
  - [ ] On Windows VM / clean machine checklist: same script run outside dev environment
- [ ] Add CI or release note: run full smoke suite before tagging:
  ```bash
  uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
  PAGEDROP_EXE=./dist/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v
  ```

### ✅ Test Gate 16
- [ ] **Exe opens** without "DLL not found" or similar errors
- [ ] **Open a PDF** via the exe → thumbnails render
- [ ] **Drag a page to a folder** → works exactly like the dev version
- [ ] **Multi-tab and Save As** work in the built binary
- [ ] **Test on a second machine** or VM that has never had Python installed

---

## Suggested Build Order

Work through phases in this order. **Don't move on until the test gate for each phase passes.**

Each phase also has a **Test Scripts & Smoke Tests** checklist — write those tests as you go so regressions are caught before the manual test gate.

```
Phase 1–9 (done) → 11 Tabs → 12 Model → 13 Reorder/Delete → 14 Inbound drop → 15 Save As → 16 Exe
     Setup…Polish      Multi-tab   PdfEditModel   Edit UI        Drop PDFs      Persist      Binary
```

Phases 12–15 are sequential (each builds on `PdfEditModel`). Phase 11 should land before
Phase 13 UI work. Phases 6–7 were the hardest in the original build; Phase 13–14 (dual drag
types + drop indicator) will need similar care.

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
