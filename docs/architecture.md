# Architecture

High-level map of how PageDrop is wired. For how to run and test, see [Development](development.md).

## Layers

```
main.py → WindowManager → MainWindow(s)
                ↓
         tab strip (PDF editor | Merge | Create PDF | Tools | tool shells)
                ↓
         grids / cards / preview / viewer
                ↓
         core/ (PdfEditModel, loaders, writers, jobs) — no Qt widgets
                ↓
         utils/ (temp lifecycle, helpers)
```

- **`WindowManager`** owns multi-window lifetime and cross-window page transfer
- **`ui/`** owns widgets, menus, shortcuts, toasts, and job chrome
- **`core/`** owns PDF open/edit/write/merge/extract and tool job handlers
- Optional backends (Office COM, LibreOffice, OCR data, codecs) live behind a soft **capability registry** so missing extras never break startup

## Edit model

`PdfEditModel` holds a logical page list decoupled from source PDF order. Each entry is a frozen `PageRef`:

| Field | Meaning |
|---|---|
| `source_path` | File the page bytes come from |
| `source_index` | 0-based page index in that file |
| `rotation` | Extra rotation in {0, 90, 180, 270} |

UI counts and labels use `logical_count()` after insert/delete/reorder — not the source loader’s page count. Writers and extractors follow the model; Save As / extract / merge always write **new** paths and never truncate the user’s original.

## Drag and drop

Outbound page drag uses `QDrag` with `file://` URLs so Explorer, Finder, and other file managers accept drops as real files. Internal transfers use app mime types (page indices, page refs, merge-file order) defined in `core/drag_mime.py`. Cross-window drop copies by default; Shift+drop moves.

Inbound drops (PDF onto the grid, images onto Create PDF, files onto tool shells) go through the same tab/grid hosts so behaviour matches the menu-driven paths.

## Jobs and capabilities

Batch Tools work through a **serialized job runner** (`SerializedJobRunner`): stage under temp, validate, promote to the user path, support cooperative cancel. Handlers take explicit input/output paths — not live `fitz.Document` handles from the UI.

Optional engines are probed via `core/capabilities.py`. Probes soft-fail; the UI can configure / recheck without crashing the app. Core thumbnail / edit / merge / Create PDF must remain usable when optional backends are absent.

External converters (Office COM helper, LibreOffice, Ghostscript) run in isolated subprocesses with timeouts. Cancel kills only owned process trees and cleans partial staging outputs.

## PyMuPDF concurrency

PyMuPDF is not safe for concurrent multithreaded use — even separate `Document` instances share MuPDF caches. PageDrop serializes in-process fitz work through a process-wide lock in `core/pdf_service.py` (`FITZ_LOCK`). Viewer thumbnails, previews, and fitz-backed job handlers take that lock (or call helpers that do). Workers open documents by path inside `run()`, close before returning, and never receive a live loader document from the UI thread.

UI render pools stay at max thread count 1 and still share the same lock across windows. Raising pool size does not make MuPDF safer.

## Result UX

Tool and conversion success surfaces status + toast by default. Opening a result in the editor or file manager is always an explicit Preview / Open / Show in folder choice (`result_actions`), never an automatic tab open.
