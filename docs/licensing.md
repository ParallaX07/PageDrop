# Licensing and redistribution

This note is project policy, not legal advice. Reconfirm with qualified counsel before a Store or paid release.

## Summary

| Component | Free-wheel licence | Commercial alternative |
|---|---|---|
| PageDrop source (this repo) | MIT (`LICENSE`) | — |
| PyQt6 | **GPLv3** (Riverbank) | Riverbank commercial |
| Qt (in free PyQt6 wheels) | **LGPL-3.0** (typical) | Qt commercial |
| PyMuPDF | **AGPL-3.0** (Artifex) | Artifex commercial |

MIT for PageDrop’s own code does **not** clear redistribution of a frozen app that embeds free (GPLv3) PyQt6 and free (AGPL) PyMuPDF. When those free wheels are included, the stricter **AGPL** obligations for the Combined Work apply.

**Open binary builds** that ship free PyQt6 and PyMuPDF wheels must be redistributed as an **AGPL-compatible Combined Work**: source available to recipients; installer / release notes point at this file and `THIRD_PARTY_NOTICES.md`.

**Alternative:** purchase commercial PyQt6 + commercial PyMuPDF (and Qt if needed) and switch the build to those wheels when Store or proprietary packaging needs terms incompatible with AGPL/GPL. Do not ship free wheels under that packaging.

## What redistributors must do

For every tagged binary or Store package that includes free PyQt6 / PyMuPDF:

1. Release notes / About / installer materials match this policy (or the commercial stack is in use).
2. `THIRD_PARTY_NOTICES.md` and `LICENSE` ship with the Windows installer next to `pagedrop.exe` (and in the onedir tree for local/frozen smoke).
3. Qt LGPL obligations below are addressed for that release (texts + source/offer; see replaceability note).

## PyInstaller onedir + installer layout

`pagedrop.spec` builds an **onedir** bundle: `dist/pagedrop/pagedrop` (Unix) or `dist/pagedrop/pagedrop.exe` (Windows), with Qt plugins and datas as loose files beside the exe. The Windows Inno Setup script installs that folder tree into Program Files and also copies `LICENSE` and `THIRD_PARTY_NOTICES.md` into the same install directory.

## Qt / LGPL — redistributor obligations

When shipping LGPL Qt from free PyQt6 wheels, each binary release should:

1. **Licence texts** — include LGPL-3.0 (and GPL-3.0 where required by PyQt6 / PyMuPDF) with the distribution; keep `THIRD_PARTY_NOTICES.md` accurate. The installer places notices beside the exe.
2. **Corresponding source or written offer** — provide or offer Qt (and any modified LGPL) corresponding source for at least three years, as LGPL requires.
3. **Replaceability** — the onedir install keeps Qt shared libraries as separate files under `{app}`, which is closer to LGPL-style library replacement than the old onefile layout. Still ship licence texts + corresponding-source/written-offer for the free-wheel Combined Work path.
4. **GPLv3 / AGPL** — Combined Work source (PageDrop + build recipe) must be available under terms compatible with GPLv3 and AGPL-3.0 while free PyQt6 / PyMuPDF wheels are used.

### Suggested release note

> PageDrop is installed as a PyInstaller onedir folder. Licence texts and third-party notices are installed next to `pagedrop.exe` as `LICENSE` and `THIRD_PARTY_NOTICES.md`.
> Qt and other bundled libraries ship as files under the install directory.
> Corresponding source offers for LGPL/GPL/AGPL components are described in `THIRD_PARTY_NOTICES.md` and in the PageDrop source repository for this version tag.

## Packaging gate

```bash
uv run python scripts/check_packaging.py
```

Asserts `THIRD_PARTY_NOTICES.md` exists, is referenced from `pagedrop.spec`, is installed by `windows.iss`, and states PyQt6 as GPLv3 (not LGPL).

See also [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) and [Building](building.md).
