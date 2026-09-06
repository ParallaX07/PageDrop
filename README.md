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

> Optional features: Office conversion needs Microsoft Office or LibreOffice installed separately. OCR may need language data (tessdata).

**Windows (GitHub Releases)**, no Python required:

1. Go to [Releases](https://github.com/ParallaX07/PageDrop/releases) and download the latest `PageDrop-*-Setup.exe` installer.
2. Run Setup.exe and follow the wizard. It installs to Program Files and adds a Start Menu shortcut.

> Windows may show a SmartScreen warning on unsigned builds. Choose **More info → Run anyway** if that happens.

macOS and Linux binaries aren't published yet. Run from source (below) or build your own with PyInstaller.

## Quick start

1. **Open a PDF**: File → Open PDF (`Ctrl+O`), or the toolbar Open button. Password-protected PDFs prompt for a password. Select multiple files to open each in its own tab.
2. **Select pages**: click one, Ctrl+click to toggle, Shift+click for a range, Ctrl+A for all. Jump with **Ctrl+G**, or select a range like `1-5` with **Ctrl+F**.
3. **Drag to a folder**: drag selected thumbnails into your file manager. Each page becomes its own PDF.
4. **Edit across PDFs**: reorder, delete, duplicate (`Ctrl+D`), or rotate. Drop another PDF onto the grid to insert pages. Drag between windows; hold Shift to move instead of copy. Undo with `Ctrl+Z`. Then File → Save As.
5. **Merge, Create PDF, or Tools**: Merge and Create PDF open as editor tabs. **Tools** (`Ctrl+Shift+O`) is the searchable hub for organize, convert, modify, optimize, and secure jobs.

The first launch shows short tips. Press **Ctrl+/** for shortcuts, or **Ctrl+Shift+P** for the command palette.

Full walkthrough: [docs/user-guide.md](docs/user-guide.md).

## Features

### Thumbnail grid and drag-out

- Open one or more PDFs as a scrollable thumbnail grid
- Drag pages to any file manager to extract them as individual PDFs
- Zoom with Ctrl+scroll; double-click or Enter for a full-page preview
- Right-click to extract to a folder, new tab, or new window; File → Export All Pages writes every page

### Multi-tab editor

- Browser-style tabs; reorder, delete, duplicate, rotate; undo/redo
- Drop PDFs onto the grid to open or insert; Save As never overwrites the original
- Dirty tabs show `*`; closing prompts Save As, Discard, or Cancel

### Multi-window workflows

- New windows, tear-off tabs, or File → New Window
- Drag pages between windows to copy; Shift+drop to move

### Merge PDFs and Create PDF

- **Merge PDFs** — combine whole files (add folder, reorder, preview); sources unchanged
- **Create PDF** — images → one PDF or separate PDFs; same Preview / Open / Show in folder result actions (no auto-open)

### Tools hub

Searchable catalogue (`Ctrl+Shift+O`) for organize, convert, modify, optimize, and secure jobs. Optional backends are capability-detected. Details: [docs/tools.md](docs/tools.md).

### Preferences and accessibility

Light theme, thumbnail quality, confirm-before-delete, reduce motion, and platform high-contrast where available.

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

Ctrl+Tab toggles the most recently used previous tab. Tools uses **Ctrl+Shift+O** so it does not steal **Ctrl+T** (New tab). Cross-window: drop copies; Shift+drop moves.

More detail: [docs/user-guide.md](docs/user-guide.md).

## Run from source

**Requirements:** Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ParallaX07/PageDrop.git
cd PageDrop
uv sync
uv run pagedrop
```

You don't need to activate a virtualenv manually. `uv` handles the environment for you.

Deeper setup, layout, and tests: [docs/development.md](docs/development.md).

## Documentation

| Doc | Contents |
|---|---|
| [docs/README.md](docs/README.md) | Docs index |
| [User guide](docs/user-guide.md) | Workflows, preferences, shortcuts |
| [Tools](docs/tools.md) | Tools hub catalogue and backends |
| [Development](docs/development.md) | Source layout, stack, tests, CI |
| [Building](docs/building.md) | PyInstaller, smoke checks, Windows installer |
| [Architecture](docs/architecture.md) | Layers, edit model, jobs, locking |
| [Licensing](docs/licensing.md) | Binary redistribution policy |

## Development and packaging

```bash
make test          # full suite via all_tests.py
make build-exe     # PyInstaller onedir → dist/pagedrop/pagedrop(.exe)
make smoke-exe     # build + Unix exe smoke
make test-release  # full pytest gate + executable smoke
```

Windows installer and packaging checklist: [docs/building.md](docs/building.md). Architecture overview: [docs/architecture.md](docs/architecture.md).

## License

PageDrop is licensed under the GNU Affero General Public License v3.0 or later — see [`LICENSE`](LICENSE). Source and build instructions for every published binary are available in the corresponding source release. See [docs/licensing.md](docs/licensing.md) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Status

**v0.5.1**: Patch over 0.5.0 — frozen builds re-enter redaction fresh-process verify via `--pagedrop-redact-verify` (same pattern as the Office COM worker) so Save with redaction no longer opens a second GUI or skips verification.

**v0.5.0**: Builds on 0.4.0 with ToolShell layout/help polish, stronger annotations (freetext styling, markup colors, redaction confirm), blank-page detection, multi-page print with credentials, FITZ_LOCK thread-safety across PDF ops, thumbnail/file-grid performance work, zoom control icons, and a Windows PyInstaller onedir bundle + installer path. macOS/Linux release binaries and Authenticode signing for the Inno installer are planned.
