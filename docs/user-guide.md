# User guide

PageDrop is built around a thumbnail grid and drag-and-drop. You open PDFs in tabs, select pages, edit them, and drag pages out to your file manager — without overwriting the original file.

## Open and select

1. **Open a PDF**: File → Open PDF (`Ctrl+O`), or the toolbar Open button. Password-protected PDFs prompt for a password. Select multiple files to open each in its own tab. File → Open Recent reopens recent paths.
2. **Select pages**: click one, Ctrl+click to toggle, Shift+click for a range, Ctrl+A for all. Jump to a page with **Ctrl+G**, or select a page or range like `1-5` with **Ctrl+F**.
3. **Zoom and preview**: Ctrl+scroll zooms thumbnails; Ctrl+0 resets. Double-click or press Enter for a full-page preview; arrow keys plus Space handle keyboard navigation. Escape returns to the grid from preview.

The first launch shows short tips. Press **Ctrl+/** for the full shortcut list, or **Ctrl+Shift+P** for the command palette.

## Drag pages out

Drag selected thumbnails into Explorer, Finder, Nautilus, Dolphin, or any file manager. Each page becomes its own PDF (for example `report_page_0003.pdf`).

Right-click to extract selected pages to a folder, a new tab, or a new window. File → Export All Pages writes every page as its own PDF.

## Edit pages

- Reorder by dragging thumbnails or using Move up / Move down / Move to… (`Ctrl+Shift+M`)
- Delete, duplicate (`Ctrl+D`), and rotate from the toolbar, context menu, or shortcuts
- Undo / redo with `Ctrl+Z` / `Ctrl+Shift+Z`; deleting many pages at once can prompt for confirmation
- Drop a PDF onto the grid (including a blank tab) to open or insert its pages at the cursor
- **File → Save As** writes edits to a new file. The original stays untouched
- Dirty tabs show a `*` in the title; closing one prompts Save As, Discard, or Cancel

## Multi-window

- Open PDFs in new windows, tear tabs off the tab bar, or use File → New Window (`Ctrl+Shift+N`)
- Drag pages between windows to **copy** by default; hold **Shift** while dropping to **move** them (a short Undo toast appears after a move)
- Each window has its own tab strip, so Merge, Create PDF, and Tools can stay open beside editor tabs

## Merge PDFs

Open via the menu bar **Merge PDFs** or the Tools hub tile. It is an editor tab for combining whole PDF files:

- Add, remove, and reorder files (drag-and-drop supported)
- Add folder recursively adds PDFs from a directory
- Double-click or press Enter on a file to preview all its pages
- Merge writes one combined PDF and leaves source files unchanged
- Success offers Preview / Open in editor / Show in folder — results do **not** auto-open

## Create PDF

Open via the menu bar **Create PDF** or the Tools hub tile. Turn images into PDFs:

- Supports PNG, JPEG, BMP, GIF, TIFF, WebP, and other raster formats PyMuPDF can open
- Add images via dialog or drag-and-drop (PDFs are rejected here; use Merge PDFs for those)
- Export as one combined PDF (one page per image) or as separate PDFs (one file per image)
- Reorder images before exporting; double-click or Enter for a full-size preview with Ctrl+scroll zoom
- Same result actions as Merge — no auto-open into a PDF tab

## Tools hub

**Tools** (`Ctrl+Shift+O`) is a searchable catalogue of organize, convert, modify, optimize, and secure jobs. Tool pages open as sibling tabs in the same strip. After a job finishes, use Preview / Open / Show in folder explicitly — PageDrop does not auto-open results into PDF tabs.

See [Tools](tools.md) for the full catalogue and optional backends.

## Preferences and accessibility

- View → Toggle Light Theme, and View → Thumbnail quality (Low / Medium / High); the app remembers your last thumbnail zoom
- Preferences cover confirm-before-delete, confirm dirty tab close, remember window geometry, and **Reduce motion** (platform reduce-motion is still honored when available)
- High-contrast preferences are respected where the platform exposes them
- Window size and position are restored on launch; toasts confirm saves, extracts, and similar actions

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

For cross-window page drags: dropping copies pages; Shift+drop moves them.
