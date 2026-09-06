# Third-party notices

PageDrop bundles or depends on the following third-party software.
The repository `LICENSE` (AGPL-3.0-or-later) covers PageDrop’s own source. Every
published binary that includes the free PyQt6 and PyMuPDF wheels must have matching
corresponding source available from its release page. See `docs/licensing.md` for
the distribution policy.

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
- **Notes:** PageDrop’s published Windows build is a PyInstaller **onedir** bundle
  installed by Setup.exe. Qt shared libraries ship as separate files under the
  install directory beside `pagedrop.exe`. Redistributors must still ship or offer
  corresponding Qt source (or a written offer) and include LGPL licence texts. The
  installer places `LICENSE` and `THIRD_PARTY_NOTICES.md` next to `pagedrop.exe`.
  See `docs/licensing.md`.

## PyMuPDF (fitz)

- **Project:** [Artifex Software — PyMuPDF](https://pymupdf.readthedocs.io/)
- **License:** Dual — AGPL-3.0 by default, or a commercial license from Artifex
- **Notes:** The default PyPI package is AGPL. Distributing PageDrop binaries under
  a proprietary or non-AGPL license requires a commercial PyMuPDF license from
  Artifex. Free-wheel builds are distributed under AGPL-3.0-or-later with matching
  corresponding source for each release.

## PyInstaller (build-time only)

- **Project:** [PyInstaller](https://pyinstaller.org/)
- **License:** GPLv2 with a special exception for frozen applications (bootloader exception)
- **Notes:** Used to produce the onedir bundle; not a runtime dependency of the
  source tree beyond the frozen output.

## pywin32 (optional, Windows Office COM pack only)

- **Project:** [pywin32](https://github.com/mhammond/pywin32)
- **License:** PSF-style (see project licence)
- **Notes:** Not part of the base install. Extra `office` / dependency group installs
  `pywin32` only when `sys_platform == 'win32'`. Linux and macOS wheels must not require
  it. Used solely for Microsoft Office → PDF via a dedicated helper process.

## Phosphor Icons (vendored SVG subset)

- **Project:** [Phosphor Icons](https://phosphoricons.com/) /
  [phosphor-icons/core](https://github.com/phosphor-icons/core)
- **License:** MIT
- **Copyright:** Copyright (c) 2023 Phosphor Icons
- **Notes:** PageDrop vendors a small regular-weight SVG subset under
  `src/pagedrop/assets/icons/` for toolbar chrome and Tools hub tiles
  (loaded/tinted by `pagedrop.ui.icons`). Not a PyPI icon package. The MIT
  license text follows:

```
MIT License

Copyright (c) 2023 Phosphor Icons

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
