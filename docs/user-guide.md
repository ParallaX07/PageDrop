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
- **File → Save As** writes edits to a new file in the background. The original stays untouched; you can cancel while it is saving. Later saves continue from that saved copy, preserving prior page edits, annotations, forms, and verified redactions
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
- Success prioritizes the output summary and offers Preview / Open in editor / Show in folder — results do **not** auto-open

## Create PDF

Open via the menu bar **Create PDF** or the Tools hub tile. Turn images into PDFs:

- Supports PNG, JPEG, BMP, GIF, TIFF, WebP, and other raster formats PyMuPDF can open
- Add images via dialog or drag-and-drop (PDFs are rejected here; use Merge PDFs for those)
- Export as one combined PDF (one page per image) or as separate PDFs (one file per image)
- Reorder images before exporting; double-click or Enter for a full-size preview with Ctrl+scroll zoom
- Same result actions as Merge — no auto-open into a PDF tab

## Tools hub

**Tools** (`Ctrl+Shift+O`) is a searchable catalogue of organize, convert, modify, optimize, and secure jobs. Tool pages open as sibling tabs in the same strip. Once you choose an input, its large drop area becomes a concise filename summary with **Change file**. After a job finishes, use Preview / Open / Show in folder explicitly — PageDrop does not auto-open results into PDF tabs.

See [Tools](tools.md) for the full catalogue and optional backends.

## Preferences and accessibility

- View → Toggle Light Theme, and View → Thumbnail quality (Low / Medium / High); the app remembers your last thumbnail zoom
- Preferences cover confirm-before-delete, confirm dirty tab close, remember window geometry, **Automatically check for updates**, and **Reduce motion** (platform reduce-motion is still honored when available)
- High-contrast preferences are respected where the platform exposes them
- Window size and position are restored on launch; toasts confirm saves, extracts, and similar actions

## Windows updates

Updates are available only in the packaged Windows version. PageDrop checks for a
new stable release five seconds after opening when a check is due, then at most
once a day after a successful check. Turn off **Automatically check for updates**
in Preferences to stop background checks. Preferences also show the last
successful check and any current background error; background failures do not
interrupt your work.

Use Help → **Check for updates…** at any time for visible feedback. It can show
that PageDrop is current, that published update information is unavailable, a
temporary rate limit, or a connection/problem message. A manual check can reveal
an update you skipped or deferred and immediately retry ordinary failures.
Server throttling shows the exact retry date and time in your local timezone.
Manual errors include **Open releases page** and **Close**.
An active download or a verified update is reopened without starting another
check. Unsupported builds offer
the PageDrop releases page instead of checking.

When an update is available, review its plain-text release notes and choose one:

- **Download update** downloads the installer only after your approval. Progress
  includes Cancel; cancellation removes the partial download.
- **Remind me tomorrow** hides this offer for 24 hours.
- **Skip this version** hides only that exact version. A later version is still
  offered.

After the download is verified, choose **Install and close PageDrop** or **Later**.
Later keeps the verified download available without fetching it again. Before an
install, PageDrop asks you to finish or cancel active tasks and resolves unsaved
tabs in every window with Save As, Discard, or Cancel. Save As always writes a
new file; PageDrop never overwrites the original PDF. Cancelling a save or the
installer launch leaves all windows and unsaved work usable.

Download and installation failures explain what went wrong and offer recovery
actions. Check available space and folder permissions for storage errors.
A failed verification removes the invalid file before another download.
Refusing UAC keeps the verified update ready to try again. **Try again** reopens
the appropriate download or installation choice; **Open releases page** provides
a manual fallback.

Choosing install opens the normal elevated Windows installer (UAC). Refusing UAC,
cancelling the wizard, or a failed launch does not close PageDrop. Windows may
show an unsigned or unknown-publisher warning if the installer is not code signed;
read that prompt and do not proceed unless you trust the release. Other open
PageDrop processes block installation through the installer and are never closed
automatically.

The updater validates the expected installer size and SHA-256 checksum over HTTPS
before it offers installation. This detects corruption and mismatched assets, but
does not independently prove publisher identity if the release account itself is
compromised. Existing builds without the updater need one manual installation of
the first updater-capable release; for an older build without the installer mutex,
close every old PageDrop process manually before upgrading.

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
