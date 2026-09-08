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

## Windows updates

The Windows updater is deliberately separate from PDF work. `WindowManager`
creates exactly one `UpdateCoordinator` and one `UpdatePresenter` for the
application process. The coordinator owns network workers, scheduling, release
state, and local installer storage; windows only request presentation. This keeps
multiple PageDrop windows from starting competing checks or downloads.

```
idle → checking → available → downloading → ready → preparing → handing_off
                 │              │              │
                 └──────────────┴──────────────┴→ available / idle on a safe failure
```

The Qt-independent service in `utils/update_checker.py` fetches only the public
`ParallaX07/PageDrop` latest stable release's `latest.json` static asset, without
using GitHub's REST API. It validates schema version 1, the strict numeric version,
positive installer size, SHA-256, and string notes within a 1 MiB UTF-8 response.
Additive fields are ignored. Installer names and URLs are derived locally;
the digest comes from the manifest, avoiding a separate checksum request.
Trusted HTTPS redirects, exact size, and SHA-256 are verified before atomically
promoting downloaded bytes. HTTPS plus SHA-256
detects corrupt or mismatched release assets; it is not independent publisher
authentication if the release account is compromised.

On supported packaged Windows builds, automatic checking starts five seconds
after launch when due, then runs 24 hours after a successful check. Failures wait
at least one hour and retain any longer GitHub rate-limit deadline. Settings use
UTC values under `updates/`; malformed or implausibly future values cannot create
a request loop. Manual checks bypass the daily, reminder, and skip suppression
and ordinary failure backoff, but still honour a separately persisted
`server_retry_after_utc` deadline. Server throttling without a valid deadline
uses one minute; automatic failures retain their one-hour backoff in
`retry_after_utc`. The legacy retry value is automatic-only, so an old API
cooldown cannot block manual manifest checks. The first failed check schedules
a new automatic attempt even when there has never been a successful check.
Disabling automatic checks cancels only
scheduled checks, never a download already approved by the user.

`UpdateStorage` uses the Qt application-local `updates/` directory and gives each
process a locked session subdirectory. It revalidates a cached installer before
reuse, removes only recognised inactive updater files, and expires inactive
verified installers after seven days. It never uses PDF paths or the shared PDF
temporary-file lifecycle. Storage is created lazily for an approved download;
storage failures cannot prevent application startup. Failed cache verification
removes the owned invalid installer and offers another download.

The presenter reopens active checks, downloads, and offers. Shared typed-error
messages provide local retry times and recovery actions without exposing raw
exceptions. Background failures remain quiet and update Preferences; manual
failures offer the fixed releases page and a close button.

Installation remains explicit. The presenter may show a verified release, but
only starts a download after consent. Before handoff, `WindowManager` blocks new
interaction, requires active jobs to finish or be cancelled by the user, and
collects Save As/Discard/Cancel decisions for dirty tabs in every window. Discard
is deferred until the accepted installer launch, so cancellation or launch failure
leaves tabs intact and usable. The Windows helper revalidates the installer,
records a pending target version, invokes the normal elevated Inno Setup wizard,
and only then performs the one-shot prepared shutdown. A later launch clears the
pending version only after the running version reaches it.

Every packaged Windows process holds `Global\\PageDropInstallerMutex`, matching
Inno Setup's `AppMutex`. The mutex protects installation while allowing multiple
PageDrop instances; it does not close or terminate another process. On final
window close the coordinator cancels its owned network work and lets its worker
finish before the application quits.
