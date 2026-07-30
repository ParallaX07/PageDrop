# Building and packaging

PageDrop ships as a PyInstaller **onefile** executable (`pagedrop.spec`). Windows releases are distributed only via the Inno Setup installer — not as a portable zip.

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

Output:

- Linux/macOS: `dist/pagedrop`
- Windows: `dist/pagedrop.exe`

You can launch that binary for local smoke testing. Published Windows builds go through the installer below.

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
PAGEDROP_EXE=./dist/pagedrop uv run pytest tests/smoke/ -v -k executable

# Windows PowerShell
$env:PAGEDROP_EXE = ".\dist\pagedrop.exe"
uv run pytest tests/smoke/ -v -k executable
```

## Release test gate

Full pytest suite plus executable smoke (set `PAGEDROP_EXE` if the binary is not at the default path):

```bash
make test-release
```

Default executable path for the Makefile is `./dist/pagedrop`. Override with `PAGEDROP_EXE=…`.

Before tagging a release, also verify manually on a machine without Python: install Setup.exe, open a PDF, drag a page into the file manager, and confirm the extracted files appear.

## Windows installer (GitHub Releases)

Version comes from `pyproject.toml`. Generate icons once (or after logo changes), then build the Inno Setup installer ([Inno Setup 6+](https://jrsoftware.org/isinfo.php), with `iscc` on PATH or `$env:ISCC`):

```powershell
uv run --with pillow python scripts/generate_icons.py   # or: make generate-icons
.\scripts\build_windows_installer.ps1                   # or: make build-installer
# reuse existing dist: .\scripts\build_windows_installer.ps1 -SkipBuild
uv run python scripts/check_packaging.py
```

Output lands at `installer/Output/PageDrop-<version>-Setup.exe` (gitignored — do not commit binaries). The installer places `pagedrop.exe`, `LICENSE`, and `THIRD_PARTY_NOTICES.md` under Program Files.

Publish to GitHub Releases (replace `X.Y.Z` with the `pyproject.toml` version):

```powershell
gh release create "vX.Y.Z" `
  "installer/Output/PageDrop-X.Y.Z-Setup.exe" `
  --repo ParallaX07/PageDrop `
  --title "vX.Y.Z" `
  --notes "Windows Setup.exe for PageDrop X.Y.Z."
```

## Packaging checklist

Before a tagged binary or Store package:

1. Run `make test-release` (or equivalent full suite + executable smoke)
2. Run `uv run python scripts/check_packaging.py` — asserts notices exist, are referenced from `pagedrop.spec` and `windows.iss`, and state PyQt6 as GPLv3
3. Confirm release notes / About / installer materials match the redistribution policy in [Licensing](licensing.md)
4. Confirm Qt LGPL obligations (licence texts + source/offer) for that release

See [Licensing](licensing.md) and [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) for Combined Work and Qt details.
