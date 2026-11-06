# Licensing and redistribution

This note is project policy, not legal advice.

## Summary

PageDrop is free software under **AGPL-3.0-or-later**. Anyone may use, study, modify, fork, self-host and redistribute it at no cost. There are no paid tiers and no separate licences.

| Component | Licence |
|---|---|
| PageDrop source (this repo) | AGPL-3.0-or-later (`LICENSE`) |
| PyQt6 | **GPLv3** (Riverbank free wheels) |
| Qt (in free PyQt6 wheels) | **LGPL-3.0** (typical) |
| PyMuPDF | **AGPL-3.0** (Artifex) |
| openpyxl, et-xmlfile, Pillow, pywin32 | Bundled codecs and Office COM support; see [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) |

A permissive licence is not possible: the free PyQt6 (GPLv3) and PyMuPDF (AGPL) wheels make every PageDrop build an AGPL-covered combined work. The only obligations fall on people who distribute PageDrop, or host a modified build: they must pass the same freedom on, with source.

**Published binary builds** ship those free wheels, so the corresponding source (this repository at the exact release tag, `uv.lock`, `pagedrop.spec`, and installer scripts) must be available at no charge from the same release page, with a clear link beside the binary. Every build also carries a written offer for corresponding source (see `THIRD_PARTY_NOTICES.md`).

## What redistributors must do

For every tagged binary package:

1. Pass on the same licence: keep PageDrop under AGPL-3.0-or-later and provide the corresponding source for the build.
2. Release notes, About, and installer materials identify PageDrop as AGPL-3.0-or-later and link to the matching source release.
3. `THIRD_PARTY_NOTICES.md`, `LICENSE`, and the `licenses/` folder (GPL-3.0 and LGPL-3.0 texts) ship inside the Windows installation and Linux AppImage (and in the onedir tree for local/frozen smoke). Third-party licence files travel in the bundled `*.dist-info` folders.
4. Qt LGPL obligations below are addressed for that release (texts + source/offer; see replaceability note).

## PyInstaller onedir + installer layout

`pagedrop.spec` builds an **onedir** bundle: `dist/pagedrop/pagedrop` (Unix) or `dist/pagedrop/pagedrop.exe` (Windows), with Qt plugins and datas as loose files beside the exe. The Windows Inno Setup script installs that folder tree into Program Files and also copies `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `licenses/` into the same install directory. The Linux AppImage build puts the same files under `usr/share/licenses/pagedrop/` inside its AppDir before creating the image.

## Qt / LGPL — redistributor obligations

When shipping LGPL Qt from free PyQt6 wheels, each binary release should:

1. **Licence texts** — include LGPL-3.0 and GPL-3.0 (the `licenses/` folder) with the distribution; keep `THIRD_PARTY_NOTICES.md` accurate. The installer places notices beside the exe.
2. **Corresponding source or written offer** — provide or offer Qt (and any modified LGPL) corresponding source for at least three years, as LGPL requires. `THIRD_PARTY_NOTICES.md` carries that written offer.
3. **Replaceability** — the onedir install keeps Qt shared libraries as separate files under `{app}`, which is closer to LGPL-style library replacement than the old onefile layout. Still ship licence texts + corresponding-source/written-offer for the combined work.
4. **GPLv3 / AGPL** — Combined Work source (PageDrop + build recipe) must remain available under AGPL-3.0-or-later as long as the PyQt6 / PyMuPDF wheels are used.

### Suggested release note

> PageDrop is distributed as a PyInstaller onedir folder inside its installer or AppImage. Licence texts and third-party notices are included in each distribution.
> Qt and other bundled libraries ship as files under the install directory.
> The corresponding source for this release is available from the matching PageDrop source release. See `THIRD_PARTY_NOTICES.md` for third-party license notices.

## Packaging gate

```bash
uv run python scripts/check_packaging.py
```

Asserts that `LICENSE`, `licenses/GPL-3.0.txt`, `licenses/LGPL-3.0.txt` and `THIRD_PARTY_NOTICES.md` exist and are shipped by `pagedrop.spec`, `windows.iss` and the AppImage script; that the notices state PyQt6 as GPLv3 (not LGPL), cover each bundled codec and carry the written offer; that `docs/licensing.md`, `README.md`, About and the release-notes template state AGPL-3.0-or-later and the matching tag link; and that any built `dist/pagedrop/` contains the licence files and the codecs' `dist-info` licences.

See also [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) and [Building](building.md).
