# Licensing and redistribution

This note is project policy, not legal advice. Reconfirm with qualified counsel before a paid release.

## Summary

| Component | Free-wheel licence | Commercial alternative |
|---|---|---|
| PageDrop source (this repo) | AGPL-3.0-or-later (`LICENSE`) | — |
| PyQt6 | **GPLv3** (Riverbank) | Riverbank commercial |
| Qt (in free PyQt6 wheels) | **LGPL-3.0** (typical) | Qt commercial |
| PyMuPDF | **AGPL-3.0** (Artifex) | Artifex commercial |

PageDrop’s own source is licensed under **AGPL-3.0-or-later**. This is compatible with distributing a frozen app that embeds free (GPLv3) PyQt6 and free (AGPL) PyMuPDF, provided every distributed build follows the requirements below.

**Published binary builds** that ship free PyQt6 and PyMuPDF wheels are AGPL-covered Combined Works. Their corresponding source—including this repository at the exact release tag, `uv.lock`, `pagedrop.spec`, and installer scripts—must be available at no charge from the same release page, with a clear link beside the binary.

**Alternative:** purchase commercial PyQt6 + commercial PyMuPDF (and Qt if needed) and switch the build to those wheels when proprietary packaging needs terms incompatible with AGPL/GPL. Do not ship free wheels under that packaging.

## What redistributors must do

For every tagged binary package that includes free PyQt6 / PyMuPDF:

1. Release notes, About, and installer materials identify PageDrop as AGPL-3.0-or-later and link to the matching source release (or the commercial stack is in use).
2. `THIRD_PARTY_NOTICES.md` and `LICENSE` ship with the Windows installer next to `pagedrop.exe` (and in the onedir tree for local/frozen smoke).
3. Qt LGPL obligations below are addressed for that release (texts + source/offer; see replaceability note).

## PyInstaller onedir + installer layout

`pagedrop.spec` builds an **onedir** bundle: `dist/pagedrop/pagedrop` (Unix) or `dist/pagedrop/pagedrop.exe` (Windows), with Qt plugins and datas as loose files beside the exe. The Windows Inno Setup script installs that folder tree into Program Files and also copies `LICENSE` and `THIRD_PARTY_NOTICES.md` into the same install directory.

## Qt / LGPL — redistributor obligations

When shipping LGPL Qt from free PyQt6 wheels, each binary release should:

1. **Licence texts** — include LGPL-3.0 (and GPL-3.0 where required by PyQt6 / PyMuPDF) with the distribution; keep `THIRD_PARTY_NOTICES.md` accurate. The installer places notices beside the exe.
2. **Corresponding source or written offer** — provide or offer Qt (and any modified LGPL) corresponding source for at least three years, as LGPL requires.
3. **Replaceability** — the onedir install keeps Qt shared libraries as separate files under `{app}`, which is closer to LGPL-style library replacement than the old onefile layout. Still ship licence texts + corresponding-source/written-offer for the free-wheel Combined Work path.
4. **GPLv3 / AGPL** — Combined Work source (PageDrop + build recipe) must remain available under AGPL-3.0-or-later while free PyQt6 / PyMuPDF wheels are used.

### Suggested release note

> PageDrop is installed as a PyInstaller onedir folder. Licence texts and third-party notices are installed next to `pagedrop.exe` as `LICENSE` and `THIRD_PARTY_NOTICES.md`.
> Qt and other bundled libraries ship as files under the install directory.
> The corresponding source for this release is available from the matching PageDrop source release. See `THIRD_PARTY_NOTICES.md` for third-party license notices.

## Packaging gate

```bash
uv run python scripts/check_packaging.py
```

Asserts `THIRD_PARTY_NOTICES.md` exists, is referenced from `pagedrop.spec`, is installed by `windows.iss`, and states PyQt6 as GPLv3 (not LGPL).

See also [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) and [Building](building.md).
