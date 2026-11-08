# Third-party notices

PageDrop bundles or depends on the following third-party software.
The repository `LICENSE` (AGPL-3.0-or-later) covers PageDrop’s own source. Every
published binary includes the free PyQt6 and PyMuPDF wheels, so it has matching
corresponding source available from its release page; see the written offer at the
end of this file. The full GPL-3.0 and LGPL-3.0 texts ship with this file. See `docs/licensing.md` for the distribution policy.

## PyQt6

- **Project:** [Riverbank Computing — PyQt](https://www.riverbankcomputing.com/software/pyqt/)
- **License:** GNU General Public License v3 (GPLv3)
- **Notes:** PageDrop uses the free PyPI wheels, which are GPLv3. PyQt6 is **not**
  LGPL. Binaries that include those wheels are distributed as a combined work under
  GPLv3-compatible terms, here AGPL-3.0-or-later. Riverbank also sells other licences
  for PyQt; PageDrop does not use them.

## Qt (via PyQt6 wheels)

- **Project:** [Qt](https://www.qt.io/)
- **License:** LGPL-3.0 (open-source edition, as typically shipped in free PyQt6 wheels)
- **Notes:** PageDrop’s published Windows build is a PyInstaller **onedir** bundle
  installed by Setup.exe. Qt shared libraries ship as separate files under the
  install directory beside `pagedrop.exe`. The installer places `LICENSE`,
  `THIRD_PARTY_NOTICES.md` and the `licenses/` folder (GPL-3.0 and LGPL-3.0 texts)
  next to `pagedrop.exe`; the Linux AppImage carries them under
  `usr/share/licenses/pagedrop/`. Corresponding Qt source is covered by the written
  offer below. See `docs/licensing.md`.

## PyMuPDF (fitz)

- **Project:** [Artifex Software — PyMuPDF](https://pymupdf.readthedocs.io/)
- **License:** AGPL-3.0 (the PyPI package PageDrop uses)
- **Notes:** PageDrop uses the free AGPL PyPI wheels and is distributed under
  AGPL-3.0-or-later with matching corresponding source for each release. Artifex
  also sells other licences for PyMuPDF and MuPDF; PageDrop does not use them.

## PyInstaller (build-time only)

- **Project:** [PyInstaller](https://pyinstaller.org/)
- **License:** GPLv2 with a special exception for frozen applications (bootloader exception)
- **Notes:** Used to produce the onedir bundle; not a runtime dependency of the
  source tree beyond the frozen output.

## pywin32 (Windows binary)

- **Project:** [pywin32](https://github.com/mhammond/pywin32)
- **License:** PSF-style; see the [project licence](https://github.com/mhammond/pywin32/blob/main/win32/License.txt)
- **Notes:** Bundled in the Windows binary (the `office` dependency group installs it
  only when `sys_platform == 'win32'`; Linux and macOS builds do not include it). Used
  solely for Microsoft Office → PDF through a dedicated helper process. Its licence
  file ships in the bundled `pywin32` package metadata.

## openpyxl

- **Project:** [openpyxl](https://openpyxl.readthedocs.io/)
- **License:** MIT
- **Notes:** Bundled for spreadsheet conversion. Its licence file ships in the
  bundled `openpyxl` package metadata. The notice follows:

```
This software is under the MIT Licence
======================================

Copyright (c) 2010 openpyxl

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## et-xmlfile

- **Project:** [et_xmlfile](https://foss.heptapod.net/openpyxl/et_xmlfile)
- **License:** MIT (a dependency of openpyxl)
- **Notes:** Bundled with openpyxl. It also includes code from the Python standard
  library under the Python Software Foundation licence; both licence files ship in
  the bundled `et_xmlfile` package metadata. The notice follows:

```
This software is under the MIT Licence
======================================

Copyright (c) 2010 openpyxl

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Pillow

- **Project:** [Pillow](https://python-pillow.org/)
- **License:** MIT-CMU
- **Notes:** Bundled for image import and conversion. The full `LICENSE` file, which
  also covers the libraries bundled in Pillow’s wheel, ships in the bundled Pillow
  package metadata. The Pillow notice follows:

```
The Python Imaging Library (PIL) is

    Copyright © 1997-2011 by Secret Labs AB
    Copyright © 1995-2011 by Fredrik Lundh and contributors

Pillow is the friendly PIL fork. It is

    Copyright © 2010 by Jeffrey 'Alex' Clark and contributors

Like PIL, Pillow is licensed under the open source MIT-CMU License:

By obtaining, using, and/or copying this software and/or its associated
documentation, you agree that you have read, understood, and will comply
with the following terms and conditions:

Permission to use, copy, modify and distribute this software and its
documentation for any purpose and without fee is hereby granted,
provided that the above copyright notice appears in all copies, and that
both that copyright notice and this permission notice appear in supporting
documentation, and that the name of Secret Labs AB or the author not be
used in advertising or publicity pertaining to distribution of the software
without specific, written prior permission.

SECRET LABS AB AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS
SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS.
IN NO EVENT SHALL SECRET LABS AB OR THE AUTHOR BE LIABLE FOR ANY SPECIAL,
INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE
OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```

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

## Public Sans (bundled font)

- **Project:** [Public Sans](https://github.com/uswds/public-sans)
- **License:** SIL Open Font License 1.1
- **Copyright:** Copyright 2015 The Public Sans Project Authors
  (https://github.com/uswds/public-sans)
- **Notes:** PageDrop bundles the Regular, Medium, SemiBold and Bold static
  fonts, unmodified, under `src/pagedrop/assets/fonts/` as the interface
  typeface. The licence text also ships beside them as `OFL.txt`. The full text
  follows:

```
Copyright 2015 The Public Sans Project Authors (https://github.com/uswds/public-sans)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
https://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded, 
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

## Written offer for corresponding source

For at least three years from the date a PageDrop binary was received, and for as
long as that release is offered, anyone holding it may obtain the complete
corresponding source of the GPL, LGPL and AGPL components in it (PageDrop, PyQt6,
Qt, PyMuPDF and MuPDF) at no charge beyond the reasonable cost of the transfer.
Request it through [github.com/ParallaX07/PageDrop/issues](https://github.com/ParallaX07/PageDrop/issues),
naming the release version. PageDrop’s own source for each release is at its matching
tag, `https://github.com/ParallaX07/PageDrop/tree/v<version>`. Each release page also
links the source of those components.
