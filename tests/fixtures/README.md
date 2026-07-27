# Test PDF fixtures

Tests generate small PDFs at runtime via `generate_fixtures.py` so the repo
does not need checked-in binary files.

## Generated files

After the first test run (or `uv run python tests/fixtures/generate_fixtures.py`):

```
tests/fixtures/generated/
├── one_page.pdf
├── five_page.pdf
└── empty.pdf
```

The `generated/` directory is gitignored. Delete it anytime; tests will recreate
the files.

## Adding your own sample PDFs

1. Place optional PDFs in `tests/fixtures/samples/` (create the folder if needed).
2. Keep files small (a few pages, under ~500 KB).
3. Do **not** commit large or confidential documents — add patterns to
   `.gitignore` if needed, e.g. `tests/fixtures/samples/*.pdf`.

Use generated fixtures in tests via the `one_page_pdf`, `five_page_pdf`, and
`empty_pdf` fixtures in `tests/conftest.py`.

## Optional backend markers

Registered in `pyproject.toml` (`[tool.pytest.ini_options].markers`) with
`--strict-markers`. Normal CI runs mocked present/absent capability contracts
only — do **not** require Office / LibreOffice / tessdata on every machine.

| Marker | Env / condition | What it exercises |
|--------|-----------------|-------------------|
| `office_com` | `PAGEDROP_OFFICE_COM=1` | Real Microsoft Office COM → PDF (`tests/smoke/test_phase26_office.py`) |
| `libreoffice` | `PAGEDROP_LO_PATH=/path/to/soffice` | Real headless LibreOffice → PDF (same smoke module) |
| `tessdata` | tessdata languages available (`PAGEDROP_TESSDATA` / install) | Real OCR language packs |

Examples:

```bash
# CI / default — mocked Office convert unit + UI only
uv run pytest tests/core/test_office_convert.py tests/ui/test_office_convert_ui.py -v

# Gated LibreOffice smoke (when soffice is installed)
PAGEDROP_LO_PATH=/usr/bin/soffice uv run pytest -m libreoffice tests/smoke/test_phase26_office.py -v

# Gated Office COM smoke (Windows + Microsoft Office)
PAGEDROP_OFFICE_COM=1 uv run pytest -m office_com tests/smoke/test_phase26_office.py -v
```

Smoke tests skip unless the matching env var is set, even if the binary happens
to be on `PATH`.
