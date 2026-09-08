# Building and packaging

PageDrop ships as a PyInstaller **onedir** bundle (`pagedrop.spec` → `COLLECT` →
`dist/pagedrop/`). Windows releases are distributed only via the Inno Setup
installer — not as a portable zip. Onefile is no longer the primary Windows
artifact.

## Build the executable

Install dev dependencies (includes PyInstaller), then build:

```bash
uv sync --group dev
make build-exe
```

Equivalent:

```bash
uv run pyinstaller --noconfirm pagedrop.spec
```

Output (onedir folder):

- Linux/macOS: `dist/pagedrop/pagedrop`
- Windows: `dist/pagedrop/pagedrop.exe`

Qt plugins, icons, `LICENSE`, and `THIRD_PARTY_NOTICES.md` live beside the exe
inside that folder. You can launch the binary for local smoke testing. Published
Windows builds go through the installer below.

## Smoke the build

Unix (builds first unless you skip build in the script):

```bash
make smoke-exe
# or: ./scripts/smoke_exe.sh
```

Windows:

```powershell
.\scripts\smoke_exe.ps1
# reuse existing dist: .\scripts\smoke_exe.ps1 -SkipBuild
```

Executable smoke tests live under `tests/smoke/`. Point them at a built binary with `PAGEDROP_EXE`:

```bash
# Linux/macOS
PAGEDROP_EXE=./dist/pagedrop/pagedrop uv run pytest tests/smoke/ -v -k executable

# Windows PowerShell
$env:PAGEDROP_EXE = ".\dist\pagedrop\pagedrop.exe"
uv run pytest tests/smoke/ -v -k executable
```

## Release test gate

Full pytest suite plus executable smoke (set `PAGEDROP_EXE` if the binary is not at the default path):

```bash
make test-release
```

Default executable path for the Makefile is `./dist/pagedrop/pagedrop`. Override with `PAGEDROP_EXE=…`.

Before tagging a release, also verify manually on a machine without Python: install Setup.exe, open a PDF, drag a page into the file manager, and confirm the extracted files appear. On a frozen onedir build, also confirm toolbar icons, Print dialog, and Show in folder.

## Windows installer (GitHub Releases)

Windows releases are published only from the `vMAJOR.MINOR.PATCH` tag that
exactly matches the version in `pyproject.toml`. The release workflow builds and
tests one onedir installer, produces its checksum from the final bytes, then
passes that tested pair to its publication job. Do not create a release manually
or rebuild an artifact between testing and publication.

For a local Windows packaging check, generate icons once (or after logo changes),
then build the Inno Setup installer ([Inno Setup 6+](https://jrsoftware.org/isinfo.php),
with `iscc` on PATH or `$env:ISCC`):

```powershell
uv run --with pillow python scripts/generate_icons.py   # or: make generate-icons
.\scripts\build_windows_installer.ps1                   # or: make build-installer
# reuse existing dist: .\scripts\build_windows_installer.ps1 -SkipBuild
uv run python scripts/check_packaging.py
```

Output lands at `installer/Output/PageDrop-<version>-Setup.exe` (gitignored — do not commit binaries). The installer copies the whole `dist/pagedrop/` onedir tree plus `LICENSE` and `THIRD_PARTY_NOTICES.md` under Program Files.

The workflow creates the required checksum beside it:

```text
<64 lowercase SHA-256 hex characters>  PageDrop-X.Y.Z-Setup.exe
```

On a matching tag push, `.github/workflows/release-windows.yml` runs the full
test suite, packaging validation, and the newly built executable smoke test on
Windows x64 before publication. It then creates or resumes an unpublished draft,
generates `latest.json` from the tested installer and draft release notes, verifies
the downloaded installer, checksum, and manifest bytes, and publishes all three. A
published release is never changed. If an unpublished draft is interrupted, rerun
the same tag workflow: it replaces only incomplete or mismatched draft assets and
re-verifies all three assets before publishing. It will not move “latest” backwards.

The UTF-8 manifest contains `schema_version: 1`, numeric `version` as a
`MAJOR.MINOR.PATCH` string, positive integer `installer_size`, lowercase
`installer_sha256`, and plain-text `notes`. Generation is deterministic and
limited to 1 MiB. Notes changed during publication cause publication to fail;
rerun the draft workflow to regenerate and verify the manifest.

The first manifest-capable release must include this asset. Older API-based
updaters can still discover its installer/checksum pair. Newly built clients use
`https://github.com/ParallaX07/PageDrop/releases/latest/download/latest.json`;
until that release is published, a missing manifest is reported as unavailable
update information, with an explicit link to the releases page. No API fallback
or client credentials are used.

Do not use `-SkipBuild` for a release. Never upload a checksum made from anything
other than the final installer bytes. The production updater and workflow are
pinned to `ParallaX07/PageDrop`.

### First updater-capable release

Existing PageDrop builds without the in-app updater must be upgraded by manually
installing the first updater-capable release. Builds from before the installer
mutex also need every old PageDrop process closed manually before upgrading; they
cannot advertise the mutex to the installer.

## Packaging checklist

Before a tagged binary package:

1. Run `make test-release` (or equivalent full suite + executable smoke)
2. Run `uv run python scripts/check_packaging.py` — asserts onedir spec/Inno layout, notices, icons, `QtPrintSupport`, installer identity, and updater mutex contract
3. Confirm release notes / About / installer materials match the redistribution policy in [Licensing](licensing.md)
4. Confirm Qt LGPL obligations (licence texts + source/offer) for that release

Passing source tests or this checklist is not release clearance. Follow the
binary-release requirements in [Licensing](licensing.md) for every published
installer.

See [Licensing](licensing.md) and [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) for Combined Work and Qt details.
