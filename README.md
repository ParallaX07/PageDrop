<p align="center">
  <img src="src/pagedrop/assets/logo.png" alt="PageDrop logo — documents dropping into a folder" width="128">
</p>

# PageDrop

A free, open-source PDF desktop app for people who actually organize documents: pulling pages from one PDF into another, reordering, merging, and dragging pages straight into your file manager.

Adobe costs too much. Cracked tools carry risk you don't want. Most free PDF apps work, but they feel clunky. PageDrop gives you a clean thumbnail grid, browser-style tabs, and drag-and-drop built around real multi-PDF editing, not just viewing a single file.

## See it in action

### Drag pages to your file manager

Select thumbnails and drop them into Explorer, Finder, or any file manager. Each page becomes its own PDF.

![Drag PDF pages into Explorer](demos/hero_clip.gif)

### Multi-tab editing

Reorder pages, insert another PDF, delete pages, and use **Save As** without touching the original.

![Multi-tab PDF editing in PageDrop](demos/multi-tab-editing.gif)

### Cross-window page transfer

Copy pages between windows. Hold **Shift** while dropping to move them from one document to another instead.

![Copy and move pages between PageDrop windows](demos/cross-window-page-transfer.gif)

### Drop a PDF onto the grid

Drag a PDF from your file manager onto the thumbnail grid, and its pages insert at the cursor position.

![Insert pages by dropping a PDF onto the grid](demos/drop-pdf-onto-grid.gif)

## Download

**Microsoft Store**: install from the [Microsoft Store listing](https://apps.microsoft.com/detail/9PBS1QFP36C0).

**Windows (GitHub Releases)**, no Python required:

1. Go to [Releases](https://github.com/ParallaX07/PageDrop/releases) and download the latest `PageDrop-*-Setup.exe` installer, or the `PageDrop-v*-windows-x64.zip` portable version.
2. Run Setup.exe and follow the wizard. It installs to Program Files and adds a Start Menu shortcut.
3. Or extract the zip, keep `pagedrop.exe` next to its `_internal\` folder, and double-click `pagedrop.exe`.

> Windows may show a SmartScreen warning on unsigned builds. Choose **More info → Run anyway** if that happens.

macOS and Linux binaries aren't published yet. Run from source (below) or build your own with PyInstaller.

## Quick start

1. **Open a PDF**: File → Open PDF (`Ctrl+O`), or the toolbar Open button. Password-protected PDFs prompt for a password. Select multiple files to open each in its own tab. File → Open Recent reopens recent paths.
2. **Select pages**: click one, Ctrl+click to toggle, Shift+click for a range, Ctrl+A for all. Jump to a page with **Ctrl+G**, or select a page or range like `1-5` with **Ctrl+F**.
3. **Drag to a folder**: drag selected thumbnails into Explorer, Finder, or any file manager. Each page becomes its own PDF, like `report_page_0003.pdf`.
4. **Edit across PDFs**: reorder, delete, duplicate (`Ctrl+D`), or rotate pages. Drop another PDF onto the grid to insert its pages. Drag pages between windows, and hold Shift while dropping to move instead of copy. Undo with `Ctrl+Z`. Then File → Save As.
5. **Merge, Create PDF, or Tools**: Merge PDFs and Create PDF open as editor tabs (same strip as your PDFs). **Tools** (`Ctrl+Shift+O`) is the searchable hub for organize, convert, modify, optimize, and secure jobs.

The first launch shows short tips. Press **Ctrl+/** for the full shortcut list, or **Ctrl+Shift+P** for the command palette.

## Features

### Thumbnail grid and drag-out

- Open one or more PDFs and view every page as a scrollable thumbnail grid
- Drag pages to Explorer, Finder, Nautilus, Dolphin, or any file manager to extract selected pages as individual PDFs
- Select pages with click, Ctrl+click, Shift+click, or Ctrl+A
- Zoom thumbnails with Ctrl+scroll, reset with Ctrl+0, and double-click or press Enter for a full-page preview; arrow keys plus Space handle keyboard navigation
- Right-click to extract selected pages to a folder, a new tab, or a new window
- File → Export All Pages writes every page as its own PDF

### Multi-tab editor

- Browser-style tabs keep multiple PDFs open at once, each in its own workspace
- Reorder pages by dragging them or using Move up / Move down / Move to… (Ctrl+Shift+M)
- Delete, duplicate, and rotate pages from the toolbar, context menu, or shortcuts
- Undo and redo page edits with `Ctrl+Z` / `Ctrl+Shift+Z`; deleting many pages at once can prompt for confirmation (Edit menu)
- Drop PDFs onto the grid, including a blank tab, to open or insert pages at the cursor
- Save As writes your edits to a new file. The original stays untouched
- Dirty tabs show a `*` in the title, and closing one prompts Save As, Discard, or Cancel
- Window size and position are restored on launch, and toasts confirm saves, extracts, and similar actions

### Multi-window workflows

- Open PDFs in new windows, tear tabs off the tab bar, or use File → New Window
- Drag pages between windows to copy by default, or hold Shift while dropping to move pages from one document to another (a short Undo toast appears after a move)
- Each window has its own tab strip, so Merge, Create PDF, and Tools can stay open beside editor tabs

### Merge PDFs

An editor tab (menu bar **Merge PDFs**, or the Tools hub tile) for combining whole PDF files:

- Add, remove, and reorder files, with drag-and-drop supported
- Add folder recursively adds PDFs from a directory
- Double-click or press Enter on a file to preview all its pages
- Merge writes one combined PDF and leaves source files unchanged; success offers Preview / Open in editor / Show in folder without auto-opening the result

### Create PDF

An editor tab (menu bar **Create PDF**, or the Tools hub tile) for turning images into PDFs:

- Supports PNG, JPEG, BMP, GIF, TIFF, WebP, and other raster formats PyMuPDF can open
- Add images via dialog or drag-and-drop (PDFs get rejected here; use Merge PDFs for those)
- Export as one combined PDF with one page per image, or as separate PDFs with one file per image
- Reorder images before exporting, and double-click or press Enter for a full-size preview with Ctrl+scroll zoom
- Same result actions as Merge — no auto-open into a PDF tab

### Tools hub

A searchable catalogue tab (**Tools**, `Ctrl+Shift+O`) for batch and multi-step jobs. Tiles open modeless tool pages in the same tab strip (drop zone → options → Run → cancelable progress → toast + Preview / Open / Show in folder).

- **Organize** — split/extract, alternate, reverse, N-up, booklet, posterize, divide, combine, normalize size, attachments, metadata, page labels, ZIP, compare
- **Convert** — Create PDF, Convert to PDF, Export from PDF, Office to PDF, PDF to Word, OCR, extract tables / PDF to CSV / Excel (optional backends show clearly when missing)
- **Modify** — crop, watermark, header & footer, page numbers, Bates, bookmarks/TOC, annotations, blank pages, color effects
- **Optimize / Secure** — compress, repair, encrypt, decrypt, sanitize
- Coming-soon tiles stay hidden until you enable **Show upcoming**; optional engines (Office COM, LibreOffice, tessdata, openpyxl) are capability-detected so core editing still works without them

### Preferences and accessibility

- View → Toggle Light Theme, and View → Thumbnail quality (Low / Medium / High); the app remembers your last thumbnail zoom
- Preferences cover confirm-before-delete, confirm dirty tab close, remember window geometry, and **Reduce motion** (platform reduce-motion is still honored when available)
- High-contrast preferences are respected where the platform exposes them
- Keyboard-first use across the main, Merge, Create, and Tools/shell toolbars and grids; Help → Keyboard Shortcuts (`Ctrl+/`) covers everything

## Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Open PDF | Ctrl+O |
| Save As | Ctrl+Shift+S |
| New window | Ctrl+Shift+N |
| New tab | Ctrl+T |
| Close tab | Ctrl+W |
| Previous tab (MRU) / cycle backward | Ctrl+Tab / Ctrl+Shift+Tab |
| Select all pages | Ctrl+A |
| Clear selection | Escape |
| Delete selected pages | Delete |
| Duplicate selected pages | Ctrl+D |
| Move pages up / down | Ctrl+↑ / Ctrl+↓ |
| Move to page | Ctrl+Shift+M |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z |
| Go to page | Ctrl+G |
| Select page / range | Ctrl+F |
| Reset zoom / fit width (preview) | Ctrl+0 |
| Thumbnail zoom | Ctrl+scroll |
| Preview focused page | Enter |
| Command palette | Ctrl+Shift+P |
| Tools | Ctrl+Shift+O |
| Keyboard shortcuts | Ctrl+/ |
| Back to grid / list (in preview) | Escape |

Ctrl+Tab toggles the most recently used previous tab rather than moving sequentially. Ctrl+Shift+Tab cycles backward through all tabs. Tools uses **Ctrl+Shift+O** so it does not steal **Ctrl+T** (New tab).

For cross-window page drags: dropping copies pages, and Shift+drop moves them.

## Run from source

Use this for development or on platforms without a published binary.

**Requirements:** Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ParallaX07/PageDrop.git
cd PageDrop
uv sync
uv run pagedrop
```

You don't need to activate a virtualenv manually. `uv` handles the environment for you.

## Development

### Project layout

```
src/pagedrop/
├── main.py              # entry point
├── ui/                  # PyQt6 windows, tabs, grids, Merge/Create/Tools pages
├── core/                # PDF loading, editing model, merge/convert/tools writers
└── utils/               # temp file lifecycle
tests/                   # unit, UI, and smoke tests
```

### Tech stack

| Role | Library |
|---|---|
| GUI + drag-and-drop | PyQt6 |
| PDF read/write/split/render | PyMuPDF (fitz) |
| Project manager | uv |

PageDrop uses PyQt6 for drag-and-drop because it supports `QDrag` with `file://` URLs, the protocol file managers expect when accepting dropped files.

### Tests

Run the full suite:

```bash
uv run pytest tests/ -v
```

Run smoke tests only:

```bash
uv run pytest tests/smoke/ -v
```

Or use the Makefile:

```bash
make test        # all tests via all_tests.py
make test-phase4 # cumulative gate through a specific phase
```

Test fixtures generate on the fly. See `tests/fixtures/README.md` for details.

### Building an executable

Install dev dependencies (this includes PyInstaller), then build:

```bash
uv sync --group dev
uv run pyinstaller --noconfirm pagedrop.spec
```

The onedir bundle lands in `dist/pagedrop/`. Launch it with `dist/pagedrop/pagedrop` on Linux/macOS or `dist/pagedrop/pagedrop.exe` on Windows.

Smoke-test the build (it builds first unless you pass `--skip-build` / `-SkipBuild`):

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

### Windows installer (GitHub Releases)

Version comes from `pyproject.toml`. Generate icons once, or after logo changes, then build the Inno Setup installer ([Inno Setup 6+](https://jrsoftware.org/isinfo.php), with `iscc` on PATH or `$env:ISCC`):

```powershell
uv run --with pillow python scripts/generate_icons.py   # or: make generate-icons
.\scripts\build_windows_installer.ps1                   # or: make build-installer
# reuse existing dist: .\scripts\build_windows_installer.ps1 -SkipBuild
uv run python scripts/check_packaging.py
```

Output lands at `installer/Output/PageDrop-<version>-Setup.exe` (gitignored: don't commit binaries).

Publish to GitHub Releases (replace `X.Y.Z` with the `pyproject.toml` version):

```powershell
gh release create "vX.Y.Z" `
  "installer/Output/PageDrop-X.Y.Z-Setup.exe" `
  --repo ParallaX07/PageDrop `
  --title "vX.Y.Z" `
  --notes "Windows Setup.exe for PageDrop X.Y.Z."
```

You can also attach a portable zip of `dist/pagedrop/` as `PageDrop-vX.Y.Z-windows-x64.zip` on the same release.

Before tagging a release, run the full suite plus the executable smoke test:

```bash
uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
PAGEDROP_EXE=./dist/pagedrop/pagedrop uv run pytest tests/smoke/test_phase16_executable.py -v
```

On Windows PowerShell, set `$env:PAGEDROP_EXE = ".\dist\pagedrop\pagedrop.exe"` instead.

Verify manually on a machine without Python: open a PDF, drag a page into the file manager, and confirm the extracted files appear.

## Status

**v0.3.0**: Windows Setup.exe and a portable zip are up on [Releases](https://github.com/ParallaX07/PageDrop/releases). This build adds password-protected PDFs, page rotate/duplicate, undo/redo, export-all pages, a command palette, onboarding tips, recent files, window geometry persistence, toast notifications, a light theme, and accessibility/reduce-motion preferences on top of the 0.2.0 core workflows. macOS/Linux release binaries and Authenticode signing for the Inno installer are planned.