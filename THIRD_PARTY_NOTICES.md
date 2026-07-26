# Third-party notices

PageDrop bundles or depends on the following third-party software.
The repository `LICENSE` (MIT) covers PageDrop’s own source only — it does **not**
by itself authorize redistribution of a frozen binary that includes the free PyQt6
and PyMuPDF wheels. See `docs/licensing-decision.md` for the distribution decision.

## PyQt6

- **Project:** [Riverbank Computing — PyQt](https://www.riverbankcomputing.com/software/pyqt/)
- **License:** GNU General Public License v3 (GPLv3), or a [commercial license from Riverbank](https://www.riverbankcomputing.com/commercial/pyqt)
- **Notes:** PyQt6 is **not** LGPL. Free PyPI wheels are GPLv3. Distributing PageDrop
  binaries that include those wheels requires GPLv3-compatible terms for the Combined
  Work (or a Riverbank commercial license). Your PyQt6 license must also be compatible
  with the Qt license you ship.

## Qt (via PyQt6 wheels)

- **Project:** [Qt](https://www.qt.io/)
- **License:** LGPL-3.0 (community, as typically shipped in free PyQt6 wheels) / commercial Qt license
- **Notes:** Qt shared libraries in the PyInstaller **onedir** layout remain separate
  files under `_internal/` (not statically linked into `pagedrop` / `pagedrop.exe`).
  That makes replacement and relinking *practical*, but **onedir alone is not LGPL
  compliance**. Redistributors must still ship or offer corresponding Qt source (or
  written offer), include LGPL licence texts, and allow the user to replace the Qt
  libraries. See `docs/licensing-decision.md` § Qt / LGPL.

## PyMuPDF (fitz)

- **Project:** [Artifex Software — PyMuPDF](https://pymupdf.readthedocs.io/)
- **License:** Dual — AGPL-3.0 by default, or a commercial license from Artifex
- **Notes:** The default PyPI package is AGPL. Distributing PageDrop binaries
  (including Microsoft Store packages) under a proprietary or non-AGPL license
  requires a commercial PyMuPDF license from Artifex, or releasing the Combined Work
  under AGPL-compatible terms. Confirm coverage before Store submission or the next
  tagged binary.

## PyInstaller (build-time only)

- **Project:** [PyInstaller](https://pyinstaller.org/)
- **License:** GPLv2 with a special exception for frozen applications (bootloader exception)
- **Notes:** Used to produce the onedir bundle; not a runtime dependency of the source
  tree beyond the frozen output.
