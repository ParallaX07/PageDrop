<p align="center">
  <img src="src/pagedrop/assets/logo.png" alt="PageDrop logo — documents dropping into a folder" width="128">
</p>

# PageDrop

A free, open-source PDF desktop app built for people who actually organize documents — pulling pages from one PDF into another, reordering, merging, and dragging pages straight into your file manager.

Adobe is expensive. Cracked tools aren’t worth the risk. Most free PDF apps get the job done but feel clunky. PageDrop is the opposite: a clean thumbnail grid, browser-style tabs, and drag-and-drop workflows designed around real multi-PDF editing — not just viewing a single file.

## Download

**Windows (recommended for most users)** — no Python or install required:

1. Go to [**Releases**](https://github.com/ParallaX07/PageDrop/releases) and download `pagedrop.exe` (or the latest `PageDrop-v*-windows-x64.exe` asset).
2. Double-click to run.

> Windows may show a SmartScreen warning because the build is unsigned. Choose **More info → Run anyway** if prompted. First launch can take a few seconds while the app unpacks.

macOS and Linux binaries are not published yet — run from source (below) or build your own with PyInstaller.

## Quick start

1. **Open a PDF** — File → Open PDF, or the toolbar Open button. Select multiple files to open each in its own tab.
2. **Select pages** — click one; Ctrl+click to toggle; Shift+click for a range; Ctrl+A for all.
3. **Drag to a folder** — drag selected thumbnails into Explorer, Finder, or any file manager. Each page becomes its own PDF (e.g. `report_page_0003.pdf`).
4. **Edit across PDFs** — reorder or delete pages, drop another PDF onto the grid to insert pages, drag pages between windows (Shift+drop to move), then **File → Save As**.
5. **Merge or convert** — **Merge PDFs** combines whole files; **Create PDF** turns images into PDFs.

## Features

### Thumbnail grid and drag-out

- Open one or more PDFs and view every page as a scrollable thumbnail grid
- **Drag pages to Explorer, Finder, Nautilus, Dolphin, etc.** — selected pages are extracted as individual PDF files
- Select pages with click, Ctrl+click, Shift+click, or Ctrl+A
- Zoom thumbnails, double-click for full-page preview, and use arrow keys + Space for keyboard navigation
- Right-click **Extract selected pages to folder…** if you prefer a save dialog over drag-and-drop

### Multi-tab editor

- Browser-style tabs — multiple PDFs open at once, each in its own workspace
- **Reorder** pages via internal drag-and-drop or Move Up / Move Down
- **Delete** unwanted pages
- **Drop PDFs onto the grid** to insert all pages from another file at the cursor position
- **Save As** writes your edited document to a new file — the original is never overwritten
- Dirty tabs show a `*` in the tab title; closing prompts Save As / Discard / Cancel

### Multi-window workflows

- Open PDFs in new windows, tear tabs off the tab bar, or use **File → New Window**
- **Drag pages between windows** — default is copy; hold **Shift** while dropping to move pages from one document to another
- Merge PDFs and Create PDF windows can stay open alongside editor windows

### Merge PDFs

A separate window (**Merge PDFs** in the menu bar) for combining whole PDF files:

- Add, remove, and reorder files (drag-and-drop supported)
- Double-click a file to preview all its pages
- **Merge…** saves one combined PDF; source files are left unchanged

### Create PDF

A separate window (**Create PDF** in the menu bar) for turning images into PDFs:

- Supported formats: PNG, JPEG, BMP, GIF, TIFF, WebP, and other raster images PyMuPDF can open
- Add images via dialog or drag-and-drop (PDFs are rejected — use Merge PDFs for those)
- Export as **one combined PDF** (one page per image) or **separate PDFs** (one file per image)
- Reorder images before exporting; double-click for full-size preview

## Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Open PDF | *(menu / toolbar)* |
| Save As | Ctrl+Shift+S |
| New window | Ctrl+Shift+N |
| New tab | Ctrl+T |
| Close tab | Ctrl+W |
| Next / previous tab | Ctrl+Tab / Ctrl+Shift+Tab |
| Select all pages | Ctrl+A |
| Clear selection | Escape |
| Delete selected pages | Delete |
| Move pages up / down | Ctrl+↑ / Ctrl+↓ |
| Back to grid / list | Escape *(in preview)* |

Cross-window page drag: drop to **copy**; **Shift+drop** to **move**.

## Run from source

For development or platforms without a published binary.

**Requirements:** Python **3.11+** and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ParallaX07/PageDrop.git
cd PageDrop
uv sync
uv run pagedrop
```

No manual virtualenv activation is needed — `uv` handles the environment.

## Development

### Project layout

```
src/pagedrop/
├── main.py              # entry point
├── ui/                  # PyQt6 windows, tabs, grids, merge/convert windows
├── core/                # PDF loading, editing model, merge/convert writers
└── utils/               # temp file lifecycle
tests/                   # unit, UI, and smoke tests
```

### Tech stack

| Role | Library |
|---|---|
| GUI + drag-and-drop | PyQt6 |
| PDF rendering | PyMuPDF (fitz) |
| PDF read/write/split | pypdf |
| Project manager | uv |

PyQt6 is used for drag-and-drop because it supports `QDrag` with `file://` URLs — the protocol file managers expect when accepting dropped files.

### Tests

Run the full suite:

```bash
uv run pytest tests/ -v
```

Smoke tests only:

```bash
uv run pytest tests/smoke/ -v
```

Or use the Makefile:

```bash
make test        # all tests via all_tests.py
make test-phase4 # cumulative gate through a specific phase
```

Test fixtures are generated on the fly — see `tests/fixtures/README.md` for details.

### Building an executable

Install dev dependencies (includes PyInstaller), then build:

```bash
uv sync --group dev
uv run pyinstaller --noconfirm pagedrop.spec
```

The binary is written to `dist/pagedrop` (Linux/macOS) or `dist/pagedrop.exe` (Windows).

Smoke-test the build (builds first unless `--skip-build` / `-SkipBuild`):

```bash
# Linux/macOS
./scripts/smoke_exe.sh

# Windows
.\scripts\smoke_exe.ps1
```

Or via Makefile:

```bash
make build-exe
make smoke-exe          # Unix smoke script
make test-release       # full pytest gate + exe smoke (set PAGEDROP_EXE if needed)
```

Before tagging a release, run the full suite plus the executable smoke test:

```bash
uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
PAGEDROP_EXE=./dist/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v
```

On Windows PowerShell, set `$env:PAGEDROP_EXE = ".\dist\pagedrop.exe"` instead of `PAGEDROP_EXE=...`.

Verify manually on a machine **without Python**: open a PDF, drag a page into the file manager, and confirm extracted files appear.

## Status

**v0.1.0** — Windows standalone executable available on [Releases](https://github.com/ParallaX07/PageDrop/releases). Core workflows are implemented: thumbnail drag-out, multi-tab editing, Save As, merge, multi-window page transfer, and image-to-PDF conversion. macOS/Linux release binaries and code signing are planned.

For the detailed implementation checklist and design decisions, see [`checklist.md`](checklist.md).
