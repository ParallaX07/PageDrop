# PageDrop — Complete Build Plan

A Python desktop app that renders PDF pages as thumbnails so you can drag single
or multiple pages directly into folders in your file manager.

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
        │   ├── thumbnail_grid.py # scrollable grid of pages
        │   └── page_card.py      # individual page widget + drag logic
        ├── core/
        │   ├── __init__.py
        │   ├── pdf_loader.py     # open PDF, render pages via PyMuPDF
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

### ✅ Test Gate 1
- [x] **Window opens** with correct title, no import errors in terminal
- [x] **`uv run pagedrop`** works from the project root
- [x] **No venv activation needed** — uv handles it

---

## Phase 2 — PDF Loading & Page Rendering

**Goal:** Be able to open a PDF and render any page as a `QPixmap`.

### Checklist

- [ ] Write `core/pdf_loader.py` with a `PdfLoader` class:
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
- [ ] Write a quick sanity script (not part of the app, just a throwaway test):
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
- [ ] Handle password-protected PDFs: catch `fitz.EmptyFileError` and bad
  password, show `QMessageBox` error later when wired to UI
- [ ] Handle invalid path / corrupt file with a clear exception message

### ✅ Test Gate 2
- [ ] **Run the sanity script** — `page_0.png` opens and looks correct
- [ ] **Try a multi-page PDF** — print page count, render page 0 and the last page
- [ ] **Try an invalid path** — verify it raises a clean exception, not a cryptic crash
- [ ] **Delete the sanity script** once satisfied (keep the repo clean)

---

## Phase 3 — Main Window & Layout

**Goal:** Persistent window with File menu, toolbar, and placeholder content area.

### Checklist

- [ ] Write `ui/main_window.py` with `MainWindow(QMainWindow)`:
  - [ ] **Menu bar**: `File → Open PDF`, `File → Close PDF`, `File → Exit`
  - [ ] **Toolbar**: Open button (icon + text), separator, filename label
  - [ ] **Status bar**: shows messages (page count, selection count, errors)
  - [ ] **Central widget**: placeholder `QLabel("Open a PDF to begin")`
  - [ ] **Window title**: `"PageDrop"` → updates to
    `"PageDrop — filename.pdf"` after opening
- [ ] Wire `File → Open PDF` to `QFileDialog.getOpenFileName` filtering for
  `*.pdf`
- [ ] Store the opened path in `self.current_pdf_path`
- [ ] Update `main.py` to use `MainWindow` instead of bare `QMainWindow`
- [ ] Add `closeEvent` to confirm if there are unsaved operations (skip for now,
  add a `pass`-body as a placeholder)

### ✅ Test Gate 3
- [ ] **Open → dialog appears**, filtered to PDF only
- [ ] **Title bar updates** to reflect the filename after selection
- [ ] **Status bar** shows "Loaded X pages" after selecting a file
- [ ] **File → Exit** closes the app cleanly
- [ ] **Cancel in dialog** leaves the app in its previous state (no crash)

---

## Phase 4 — Thumbnail Grid

**Goal:** Scrollable grid of page thumbnails rendered from the loaded PDF.

### Checklist

- [ ] Write `ui/page_card.py` — `PageCard(QFrame)`:
  - [ ] Contains a `QLabel` for the thumbnail image
  - [ ] Contains a `QLabel` for the page number below the image
  - [ ] Fixed card width (e.g. 170px), height auto from aspect ratio
  - [ ] `set_thumbnail(pixmap: QPixmap)` method
  - [ ] `set_selected(bool)` method — changes border style (e.g. 3px blue border
    when selected, 1px grey when not)
- [ ] Write `ui/thumbnail_grid.py` — `ThumbnailGrid(QScrollArea)`:
  - [ ] Inner widget uses `QGridLayout` (or `QFlowLayout` if you install one)
    with a fixed column count (e.g. auto-fit based on window width)
  - [ ] `load_pdf(loader: PdfLoader)` clears old cards and creates new `PageCard`
    objects
  - [ ] Render thumbnails in a **background thread** (`QThread` or
    `QRunnable`/`QThreadPool`) so the UI doesn't freeze
  - [ ] Emit a signal per rendered page so cards populate progressively
  - [ ] Show a `QProgressBar` in the status bar while rendering
- [ ] Wire `MainWindow` to call `thumbnail_grid.load_pdf()` after dialog
- [ ] Replace the placeholder central widget with the `ThumbnailGrid`

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
- [ ] Connect `page_ready` signal → update the correct `PageCard` on the main thread
- [ ] Connect `finished` signal → hide the progress bar

### ✅ Test Gate 4
- [ ] **5-page PDF** → all 5 thumbnails render, visible and correctly ordered
- [ ] **50-page PDF** → thumbnails populate progressively, UI stays responsive
  (you can scroll while they load)
- [ ] **100-page PDF** → no memory crash, reasonable load time
- [ ] **Resize window** → grid reflows correctly (or stays fixed width — either is
  fine, just make sure nothing clips)
- [ ] **Open a second PDF** → old thumbnails are cleared, new ones appear

---

## Phase 5 — Page Selection

**Goal:** Click, Ctrl+click, Shift+click, Ctrl+A, Escape — all working with clear visual feedback.

### Checklist

- [ ] Add a `SelectionManager` class (or manage in `ThumbnailGrid`):
  - [ ] Stores `set[int]` of selected page indices
  - [ ] `select_single(idx)` — clears others, selects one
  - [ ] `toggle(idx)` — adds or removes from selection
  - [ ] `select_range(start, end)` — selects a contiguous block
  - [ ] `select_all()` / `clear()`
  - [ ] Emits a `selection_changed` signal with the current selection set
- [ ] Override `mousePressEvent` in `PageCard`:
  - [ ] No modifier → `select_single`
  - [ ] `Qt.KeyboardModifier.ControlModifier` → `toggle`
  - [ ] `Qt.KeyboardModifier.ShiftModifier` → `select_range` from last clicked
- [ ] Track `last_clicked_index` in the grid for shift-click anchor
- [ ] Connect `selection_changed` → update every `PageCard.set_selected()`
- [ ] Connect `selection_changed` → update status bar:
  `"3 pages selected"` / `"No selection"`
- [ ] Add keyboard shortcuts in `MainWindow`:
  - [ ] `Ctrl+A` → `selection_manager.select_all()`
  - [ ] `Escape` → `selection_manager.clear()`

### ✅ Test Gate 5
- [ ] **Click page 1** → only page 1 highlighted
- [ ] **Click page 3** → only page 3 highlighted (page 1 deselected)
- [ ] **Ctrl+click pages 1, 3, 5** → all three highlighted, nothing else
- [ ] **Click page 2, Shift+click page 6** → pages 2–6 all highlighted
- [ ] **Ctrl+A** → all pages highlighted
- [ ] **Escape** → all deselected
- [ ] **Status bar** updates correctly in every scenario above
- [ ] **No visual glitch** — deselected cards go back to their normal grey border

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

- [ ] Write `core/page_extractor.py`:
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
  - [ ] Name files after the source PDF, e.g. `report_page_0003.pdf`
  - [ ] Zero-pad page numbers so filenames sort correctly

### Checklist — Drag Logic in PageCard

- [ ] Override `mousePressEvent` — record start position
- [ ] Override `mouseMoveEvent` — check if drag threshold crossed
  (`QApplication.startDragDistance()`)
- [ ] When threshold crossed:
  - [ ] If this card is not in selection → auto-select just this card first
  - [ ] Call `extract_pages_to_files()` via the extractor
  - [ ] Build `QMimeData`:
    ```python
    mime = QMimeData()
    urls = [QUrl.fromLocalFile(str(p)) for p in temp_paths]
    mime.setUrls(urls)
    ```
  - [ ] Create `QDrag(self)`, `drag.setMimeData(mime)`
  - [ ] Optionally set a drag pixmap (composite of first thumbnail)
  - [ ] `result = drag.exec(Qt.DropAction.CopyAction)`
  - [ ] On completion, schedule temp file cleanup via `TempManager`
- [ ] Signals needed: `PageCard` needs a reference to the `SelectionManager`
  and `PdfLoader` — pass them in via the grid

### Checklist — Drag Visual Feedback

- [ ] Set drag cursor to show a stack-of-pages icon while dragging
- [ ] Optionally show a small badge with the count of pages being dragged
  (e.g. overlay "×3" on the drag pixmap)

### ✅ Test Gate 6
- [ ] **Drag 1 page** to a folder → open the dropped PDF, verify it contains exactly
  that page and looks correct
- [ ] **Drag 3 non-contiguous pages** (e.g. 1, 4, 7) → verify 3 separate PDFs
  appear in the target folder, each with the right content
- [ ] **Drag with no selection** (click-drag directly on an unselected card) →
  verify just that one page is extracted
- [ ] **Cancel mid-drag** (release over no folder) → verify no PDF files are
  left in the target, temp files are cleaned up
- [ ] **Drag to a read-only folder** → verify app shows an error, doesn't crash
- [ ] **Drag the same pages twice** → both sets of files land in the target
  without name collisions (add timestamp or counter to filename if needed)
- [ ] Open each dropped PDF in a real PDF viewer (Acrobat, browser, etc.)
  to confirm content is valid

---

## Phase 7 — Temp File Management

**Goal:** No orphan temp files left on disk after normal use or crashes.

### Checklist

- [ ] Write `utils/temp_manager.py`:
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
- [ ] Instantiate `TempManager` once at app startup, pass reference to
  `page_extractor`
- [ ] After each drag completes (`drag.exec()` returns), clean up only the files
  from *that* drag (not all temp files — in case another drag is in progress)
- [ ] On `MainWindow.closeEvent`, call `temp_manager.cleanup()` explicitly before
  the `atexit` handler fires
- [ ] Consider a max temp dir size guard — if extracting hundreds of pages, disk
  usage can spike

### ✅ Test Gate 7
- [ ] **Do 5 drag operations** → check the temp dir, verify files are being
  cleaned up (not accumulating)
- [ ] **Kill the app process** (task manager / `kill -9`) → relaunch and check
  that the old temp dir was cleaned or is harmless
- [ ] **`os.listdir(tempfile.gettempdir())`** → count `pagedrop_*` dirs, make
  sure they don't pile up over multiple runs

---

## Phase 8 — Error Handling & Edge Cases

**Goal:** The app never crashes silently. Every failure shows a clear message.

### Checklist

- [ ] **No PDF loaded** when drag starts → show status bar message
  `"Open a PDF first"`, cancel drag
- [ ] **Corrupt PDF** on open → `QMessageBox.critical()` with filename and error
- [ ] **Empty PDF** (0 pages) → show message, don't render grid
- [ ] **Disk full** when extracting temp files → catch `OSError`, show dialog
- [ ] **Very large pages** (e.g. engineering drawings at A0) → cap render DPI at
  150, or cap `width_px` to a safe value
- [ ] **PDF with only 1 page** → selection + drag still works correctly
- [ ] **Rapid re-opens** (open PDF while one is still loading) → cancel previous
  worker thread before starting new one
- [ ] Wrap `QRunnable.run()` body in `try/except` — surface errors to main thread
  via a signal, never let thread crash silently

### ✅ Test Gate 8
- [ ] **Rename a PDF to `.pdf` but put garbage inside** → open it, see a clean
  error dialog
- [ ] **Fill up a RAM disk / temp partition** (or mock the OSError) → verify
  graceful failure
- [ ] **Open → cancel → open again → cancel** → app stays stable after multiple
  dialog cancellations

---

## Phase 9 — UX Polish

**Goal:** The app feels intentional and pleasant to use, not like a prototype.

### Checklist — Quality of Life Features

- [ ] **Tooltip on hover** over each card: `"Page 3 · 210×297 mm · Click to select"`
- [ ] **Right-click context menu** on a card or grid:
  - `Extract selected pages to folder…` → `QFileDialog.getExistingDirectory`
    fallback for users who don't want to drag
- [ ] **Keyboard navigation**: arrow keys move focus between cards, Space toggles
  selection of focused card
- [ ] **Zoom controls**: `+` / `-` or a slider to change thumbnail size (adjust
  `width_px` and re-render)
- [ ] **Page count badge** in window title: `"PageDrop — report.pdf (12 pages)"`
- [ ] **Persist last-opened directory** via `QSettings` so the file dialog
  remembers where you were
- [ ] **Drag count badge**: when dragging multiple pages, overlay a small circle
  with the count on the drag pixmap
- [ ] **Select All / Deselect All** buttons in toolbar (supplement keyboard shortcut)
- [ ] **Minimum window size** so the grid never becomes unusably small

### Checklist — Styling

- [ ] Give `PageCard` a subtle drop shadow or rounded corner so it looks like
  an actual card
- [ ] Hover state: slightly lighten/darken the card on mouse-over (before click)
- [ ] Selected state: 3px accent-colour border (Qt blue or your own colour)
- [ ] Use a dark grey background for the grid area so white PDF thumbnails
  stand out

### ✅ Test Gate 9
- [ ] **Hover over a card** → tooltip appears after a short delay
- [ ] **Right-click → Extract to folder** → PDF(s) land in the chosen folder
- [ ] **Arrow keys** move between cards, Space selects
- [ ] **Zoom in/out** → thumbnails resize, grid reflows
- [ ] **Open app a second time** → file dialog opens in the last-used folder
- [ ] **Visual check**: selected vs unselected vs hovered cards are all clearly
  distinguishable at a glance

---

## Phase 10 — Optional: Compile to Executable

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

### ✅ Test Gate 10
- [ ] **Exe opens** without "DLL not found" or similar errors
- [ ] **Open a PDF** via the exe → thumbnails render
- [ ] **Drag a page to a folder** → works exactly like the dev version
- [ ] **Test on a second machine** or VM that has never had Python installed

---

## Suggested Build Order

Work through phases in this order. **Don't move on until the test gate for each phase passes.**

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 → Phase 8 → Phase 9 → Phase 10
Setup     PDF load  Window    Grid      Select    Drag/Drop  Temp mgmt  Errors    Polish    Exe
```

Phases 6 and 7 are the hardest — budget the most time there. The rest is fairly linear.

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

---

## Quick Reference — uv Commands

```bash
uv init pagedrop --lib   # initialise project
uv add PyQt6 PyMuPDF pypdf       # add runtime deps
uv add --dev pyinstaller         # add dev-only dep
uv sync                          # install all deps
uv run pagedrop               # run the app
uv run python some_script.py     # run a one-off script
uv run pyinstaller pagedrop.spec  # build exe
```
