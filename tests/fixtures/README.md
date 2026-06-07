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
