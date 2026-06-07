# PageDrop

A desktop PDF utility for Windows, macOS, and Linux. Open a PDF, browse pages as thumbnails, and drag individual pages straight into your file manager — each drop becomes a separate PDF file. Edit documents in tabs, merge whole files, or convert images to PDF, all without leaving the app.

## Features

### Thumbnail grid and drag-out

- Open one or more PDFs and view every page as a scrollable thumbnail grid
- **Drag pages to Explorer, Finder, Nautilus, Dolphin, etc.** — selected pages are extracted as individual PDF files (e.g. `report_page_0003.pdf`)
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

## Requirements

- Python **3.11+** (project targets 3.12)
- [uv](https://docs.astral.sh/uv/) for dependency management and running the app

## Installation

```bash
git clone <repository-url>
cd PageDrop
uv sync
```

## Run

```bash
uv run pagedrop
```

No manual virtualenv activation is needed — `uv` handles the environment.

## Quick start

1. **Open a PDF** — File → Open PDF, or the toolbar Open button. With multiple files selected, each opens in its own tab.
2. **Select pages** — click to select one; Ctrl+click to toggle; Shift+click for a range.
3. **Drag to a folder** — drag selected thumbnails into any file manager window. Each page becomes its own PDF file.
4. **Edit** — reorder or delete pages, drop other PDFs onto the grid to insert pages, then File → Save As to persist changes.
5. **Merge or convert** — use **Merge PDFs** or **Create PDF** from the menu bar for whole-file combine or image-to-PDF workflows.

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

### Building an executable (optional)

PyInstaller packaging is planned (Phase 16 in the build checklist) but not yet set up. See `checklist.md` for the full build plan and phase history.

## Status

PageDrop is under active development. Phases 1–9 (core viewer and drag-out), 11–15 (multi-tab editing and Save As), 17 (merge), 18 (multi-window), and 19 (Create PDF) are implemented. Standalone executable distribution is not yet available.

For the detailed implementation checklist and design decisions, see [`checklist.md`](checklist.md).
