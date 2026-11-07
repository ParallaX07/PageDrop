# Development

## Run from source

**Requirements:** Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ParallaX07/PageDrop.git
cd PageDrop
uv sync
uv run pagedrop
```

You don't need to activate a virtualenv manually. `uv` handles the environment for you.

A plain `uv sync` installs the `dev` and `codecs` dependency groups. `codecs` adds openpyxl (PDF to Excel) and Pillow (image codecs). Without it the app still starts: capability probes report the missing package and the tool that needs it names it. On Windows, add `--group office` for pywin32 (Office COM support; Microsoft Office itself is a separate install).

## Project layout

```
src/pagedrop/
├── main.py              # entry → WindowManager
├── ui/                  # PyQt6 windows, tabs, grids, Merge/Create/Tools pages
├── core/                # PDF loading, editing model, merge/convert/tools writers
└── utils/               # temp file lifecycle and small helpers
tests/                   # unit, UI, and smoke tests (fixtures under tests/fixtures/)
```

- `ui/` — widgets only; signal wiring ends at windows and tabs
- `core/` — PDF logic with no Qt widgets
- `utils/` — temp files and shared helpers

## Tech stack

| Role | Library |
|---|---|
| GUI + drag-and-drop | PyQt6 (Fusion) |
| PDF read/write/split/render | PyMuPDF (`import fitz`) |
| Project manager | uv |
| Tests | pytest + pytest-qt |
| Package / build | hatchling, PyInstaller (`pagedrop.spec`) |

PageDrop uses PyQt6 because `QDrag` with `file://` URLs is what OS file managers expect when accepting dropped files.

## Tests

Full suite:

```bash
uv run pytest tests/ -v
```

Lint (also runs in CI):

```bash
uv run ruff check src tests
```

Smoke tests only:

```bash
uv run pytest tests/smoke/ -v
```

Or via Makefile:

```bash
make test        # all tests via all_tests.py
```

`QT_QPA_PLATFORM=offscreen` and `PAGEDROP_TESTING=1` are set in `conftest.py`. Test fixtures generate on the fly; see `tests/fixtures/README.md`.

For packaging and executable smoke checks, see [Building](building.md).

## CI

GitHub Actions runs on every `pull_request` and `push` to `master` via [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). The `test` job runs on Ubuntu and Windows with Python 3.11 and 3.12 (four combinations), each running:

```bash
uv sync --locked --group dev --group codecs
uv run ruff check src tests
uv run python scripts/check_packaging.py
uv build --wheel
uv run python all_tests.py
```

The `package-linux` job builds the Linux onedir bundle with `uv run pyinstaller --noconfirm pagedrop.spec`, then runs `scripts/check_packaging.py`, `bash scripts/smoke_exe.sh --skip-build`, and the executable smoke tests with `PAGEDROP_EXE=dist/pagedrop/pagedrop`. Those tests run the frozen binary through its helper re-entry flags (redaction verifier, lossy compressor, Office COM worker) and check each reply.

`all_tests.py` runs the suite sequentially, and CI does the same. `pytest-xdist` stays in the dev group, so `-n auto` opts into a parallel run locally, but CI does not use it.

CI installs the `codecs` group, so the openpyxl and Pillow tests always run. Office COM, LibreOffice and tessdata are unset on CI, and the `test` job has no frozen exe; those tests skip without `PAGEDROP_*` env vars.

To require the checks before merge: GitHub → **Settings → Branches** → branch protection for `master` → enable **Require status checks to pass**, and select each `test (<os>, py<version>)` check. That setting is manual; the workflow does not configure it.

## Product constraints

Keep these when changing behaviour:

- **Never overwrite the user's original PDF** on edit paths — Save As / extract / merge / convert write new paths only
- UI shows logical page counts after insert/delete (`edit_model.logical_count()`), not source `loader.page_count`
- No silent failures on user actions (shortcuts, drops, transfers) — status, toast, or dialog
- Drag-out to file managers must keep `file://` URL mime working
- PageDrop stays drag-and-drop-first; Tools is a secondary local catalogue
- Tool and conversion UIs open as editor tabs and do **not** auto-open results unless the user chooses Preview / Open / Show in folder
- Optional backends are capability-detected; core thumbnail / edit / merge / Create PDF must work when they are absent
- Optional imports must never break app startup
- Reuse existing helpers (`theme`, `base_file_grid`, `dialogs`, drag mime, temp manager) before adding parallel code
- Trace signal wiring end-to-end (grid → tab → window). Dead menu items and unconnected signals are bugs

Sentence-case toolbar/menu labels (`Move up`, not `Move Up`). Status: progress ends with `…`, idle does not. Respect accessibility hooks in `ui/accessibility.py` (contrast, reduce-motion).

## Native window-chrome verification

Automated tests exercise the custom title drag fallback and window-control wiring using
Qt's offscreen platform. They do not verify compositor-specific hit targets or native
window-manager behavior. Before release, manually verify title dragging plus minimize,
maximize/restore, and close on native Linux and Windows.

## Deeper reading

- [Architecture](architecture.md) — layers, edit model, jobs, locking
- [Building](building.md) — PyInstaller and release packaging
- [CI workflow](../.github/workflows/ci.yml) — GitHub Actions workflow
- [Licensing](licensing.md) — redistribution policy for binaries
