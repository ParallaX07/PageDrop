# Third-party notices

PageDrop bundles or depends on the following third-party software.

## PyQt6

- **Project:** [Riverbank Computing — PyQt](https://www.riverbankcomputing.com/software/pyqt/)
- **License:** GNU Lesser General Public License v3 (LGPL-3.0) (and commercial options from Riverbank)
- **Notes:** PageDrop dynamically links against PyQt6 / Qt libraries. If you redistribute binaries, comply with LGPL obligations (including offering corresponding source for the LGPL-covered libraries, or obtaining a commercial Qt/PyQt license).

## Qt (via PyQt6)

- **Project:** [Qt](https://www.qt.io/)
- **License:** LGPL-3.0 (community) / commercial Qt license
- **Notes:** Same redistribution obligations as PyQt6 when shipping the frozen Windows build.

## PyMuPDF (fitz)

- **Project:** [Artifex Software — PyMuPDF](https://pymupdf.readthedocs.io/)
- **License:** Dual — AGPL-3.0 by default, or a commercial license from Artifex
- **Notes:** The default PyPI package is AGPL. Distributing PageDrop binaries (including Microsoft Store packages) under a proprietary or non-AGPL license requires a commercial PyMuPDF license from Artifex, or releasing PageDrop under AGPL-compatible terms. Confirm coverage before Store submission.

## PyInstaller (build-time only)

- **Project:** [PyInstaller](https://pyinstaller.org/)
- **License:** GPLv2 with a special exception for frozen applications (bootloader exception)
- **Notes:** Used to produce the Windows onedir bundle; not a runtime dependency of the source tree beyond the frozen output.
