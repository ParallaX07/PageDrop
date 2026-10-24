@AGENTS.md

# Claude Code

`AGENTS.md` above is the shared source of truth for every coding agent. Put project rules there; keep this file for Claude Code–only notes.

## Workflow

- `/phase <N | feature description>` runs a phase from a plan doc (built from `plan-template.md`) or a free-form feature end to end on a `feat/<topic>` branch:
  - `explorer` (Haiku) searches and maps the code
  - `implementer` (Sonnet) writes code and tests per checklist block
  - the orchestrating session (Opus) plans, reviews, and commits each block
  - `reviewer` (Opus) does a fresh-context review of the branch before the final report
- Inside `/phase`, only the orchestrating session commits; sub-agents never commit and nothing is pushed. Outside `/phase`, the `AGENTS.md` commit rules apply.
- Never put "phase" or a phase number in branch names or commit messages, and never mention plan files, `AGENTS.md`/`CLAUDE.md`, agents, skills, Claude, or Codex in commits, code, tests, or `docs/`. Plan docs are the only place phase numbers live.

## Tools

- Use Context7 for current PyQt6, PyMuPDF, pytest-qt, and uv docs rather than guessing APIs.
- The `ponytail` skill backs the "smallest working diff" rule. Skills are managed with `npx skills` and pinned in `skills-lock.json`; install new ones with `-a claude-code -a codex` so both agents get them.
- Tests run headless (`QT_QPA_PLATFORM=offscreen` via `tests/conftest.py`) and in parallel through xdist; CI runs the parallel suite (`uv run python all_tests.py`) on Python 3.11 and 3.12, plus `uv run ruff check src tests` and `uv build --wheel`.
