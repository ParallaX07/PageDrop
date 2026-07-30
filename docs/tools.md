# Tools hub

The Tools hub (`Ctrl+Shift+O`, or the Tools menu) is a searchable catalogue tab for batch and multi-step jobs. It is secondary to the drag-and-drop editor: tiles open modeless tool pages in the same tab strip as your PDFs.

## How a tool runs

Typical flow: drop zone → options → Run → cancelable progress → toast, then **Preview / Open / Show in folder**.

PageDrop does **not** auto-open job results into PDF editor tabs. You choose Preview, Open, or Show in folder when you want them.

Coming-soon tiles stay hidden until you enable **Show upcoming** in the hub.

## Catalogue

### Organize

Split/extract, alternate, reverse, N-up, booklet, posterize, divide, combine, normalize size, attachments, metadata, page labels, ZIP, compare.

### Convert

Create PDF, Convert to PDF, Export from PDF, Office to PDF, PDF to Word, OCR, extract tables / PDF to CSV / Excel.

Optional backends (Office COM, LibreOffice, tessdata, openpyxl, and related codecs) show clearly when missing. Core thumbnail editing, Merge, and Create PDF still work without them.

### Modify

Crop, watermark, header & footer, page numbers, Bates, bookmarks/TOC, annotations, blank pages, color effects.

### Optimize / Secure

Compress, repair, encrypt, decrypt, sanitize.

## Optional backends

Capabilities are probed at runtime through a soft registry. Missing engines never break app startup. When a tool needs something that is not installed (for example Office COM on Windows, LibreOffice, or tessdata), the UI names what is missing and offers configure / recheck paths.

PageDrop never installs third-party apps. For LibreOffice it opens the official download page or copies a winget command for you to run yourself. OCR language packs (tessdata) download only after an explicit confirm.

Office conversions name the engine in status. If a COM run fails, fallback to another engine requires an explicit retry — PageDrop does not silently swap backends.

## Cancel and cleanup

Cancel stops the owned job and, for helper processes (Office / LibreOffice), kills only the owned process trees. Partial outputs under temp staging are removed; promoted results stay where you saved them.
