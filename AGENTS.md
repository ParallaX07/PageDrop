# PageDrop

Desktop PDF app: thumbnail grid, multi-tab editing, drag pages to the file manager,
merge, and image→PDF. Keep it local, trustworthy, keyboard-friendly, and accessible.

## Stack and commands

- Python 3.11+, managed with `uv`; do not invent a virtualenv workflow.
- GUI: PyQt6 with Fusion; OS drag-out uses `QDrag` and `file://` URLs.
- PDF: PyMuPDF, imported as `fitz`. Tests: pytest and pytest-qt.
- Run `uv sync`, `uv run pagedrop`, `uv run pytest tests/ -v`, or `make test`.

## Structure

- `src/pagedrop/main.py`: entry point and `WindowManager`.
- `src/pagedrop/ui/`: windows, tabs, grids, theme, dialogs; no PDF ownership logic.
- `src/pagedrop/core/`: load/edit/write/merge/extract; no Qt imports.
- `src/pagedrop/utils/`: helpers and temporary-file management.
- `tests/`: unit, UI, and smoke tests; fixtures under `tests/fixtures/`.

## Always

- Use the smallest working diff. Read and trace existing flows; reuse helpers, types,
  fixtures, and patterns before adding code or dependencies.
- Never overwrite a user’s original PDF. Edit, extract, merge, convert, encrypt, and
  sanitize operations write new paths and reject an output equal to the source.
- Never silently fail a user action; use existing status, toast, or dialog patterns.
- Display logical page counts from `edit_model.logical_count()`, never raw
  `loader.page_count` after edits.
- Preserve `file://` drag mime data. Cross-window drops copy by default; Shift+drop moves,
  and transfer failures must be visible beyond status alone.
- Keep optional imports/backends capability-detected so startup and core features work
  without them. Use typed user-facing errors, not bare `Exception`.
- Respect accessibility hooks for contrast, keyboard traversal, and reduced motion.
- Use sentence-case labels; progress status ends with `…`, idle/success status does not.
- Follow `redesign.md`; stay on Fusion and `theme.py`, with no third-party Qt widget kits.

## Core PDF and jobs

- Reuse typed load errors such as `PdfPasswordRequiredError` and `PdfCorruptError`.
  Support password authenticate/retry and never persist passwords or certificate secrets.
- Edit order belongs to the edit model; writers and extractors must follow it.
- Close/release `fitz` documents and avoid duplicate opens when a loader/cache owns one.
- PyMuPDF is not safe for concurrent multithreaded use. Serialize PDF work or use
  multiprocessing with per-process opens; never pass cached documents into workers.
- Jobs use explicit input/output paths, temp staging, validation, cooperative cancellation,
  cleanup, and owned-process timeouts. Redaction requires fresh-process verification
  after a non-incremental garbage-collecting save; visual cover alone is insufficient.

## UI and interaction

- Widgets call `core/`; do not open `fitz` documents from widgets when a loader/editor owns them.
- Wire every toolbar, menu, context-menu, shortcut, and event-filter action. Guard
  application shortcuts when preview/viewer mode is active.
- Use `theme.py`, `BaseFileGrid`, `BusyOverlay`, and `dialogs.py` instead of one-off styling.
- Custom window chrome must keep drag, minimize, maximize/restore, and close usable on both Windows and Linux; prefer Qt system APIs with a tested fallback where a window manager declines them.
- Tools are editor tabs and use the shared job/progress/cancel/error flow. Outputs do not
  auto-open; offer explicit Preview, Open, or Show in folder actions.
- Name the Office backend (COM vs LibreOffice); never silently switch after failure.
- Prefer `QKeySequence.StandardKey`; animate only toast/busy states, honor reduced motion,
  and do not animate navigation or grid keyboard movement.
- Password-protected PDFs prompt and retry through existing dialogs.

## Tests

- Use existing `qtbot` and PDF fixtures; prefer focused behavioural regressions over snapshots.
- Wait on signals rather than fixed sleeps. Every write/convert/redact test proves the
  source hash is unchanged and output is a different path.
- Job tests cover mid-run cancellation and temp/process cleanup. Generate PDF fixtures with
  `fitz`; do not add `pypdf` without an explicit decision.
- Mark optional-backend tests with existing markers and test mocked capability contracts in CI.

## Release reminder

Before binary or Store release, resolve combined PyQt6 (GPLv3/commercial) and PyMuPDF
(AGPL/commercial) redistribution requirements; MIT `LICENSE` alone is not enough.

## Git commits

- Use Conventional Commits format: `type(scope): imperative summary`.
- Keep the subject concise, lowercase, and without a trailing period.
- Never commit anything yourself or even ask for permission to commit, except inside a
  workflow that explicitly owns commits (Claude Code's `/phase`).
- Always suggest a commit message after a checklist is completed.