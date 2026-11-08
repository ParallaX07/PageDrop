"""Assert packaging helpers stay consistent with pyproject.toml.

  uv run python scripts/check_packaging.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from read_version import read_version  # noqa: E402

NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
SPEC = ROOT / "pagedrop.spec"
LICENSE = ROOT / "LICENSE"
APP_ID = "{{A7C3E91F-2B4D-4F8A-9E1C-6D5B0A8F3C21}}"
APP_MUTEX = r"Global\PageDropInstallerMutex"


def _assert_notices_content(text: str) -> None:
    """PyQt6 is GPLv3 — not LGPL. Qt remains LGPL; PyMuPDF is AGPL (Artifex)."""
    lower = text.lower()
    assert "pyqt6" in lower, "notices must mention PyQt6"
    assert "gplv3" in lower or "gpl v3" in lower or "gpl-3" in lower, (
        "notices must state PyQt6 as GPLv3"
    )
    # Guard the old mistake: PyQt **License:** line claiming LGPL.
    assert "## PyQt6" in text, "notices must have a PyQt6 section"
    pyqt_section = text.split("## PyQt6", 1)[1].split("\n## ", 1)[0]
    license_lines = [
        ln for ln in pyqt_section.splitlines() if ln.strip().lower().startswith("- **license:**")
    ]
    assert license_lines, "PyQt6 section must include a License line"
    assert "lgpl" not in license_lines[0].lower(), (
        "PyQt6 License line must not claim LGPL (Qt may; PyQt must not)"
    )
    assert "gpl" in license_lines[0].lower(), "PyQt6 License line must state GPL"
    assert "agpl" in lower, "notices must mention PyMuPDF AGPL"
    assert "artifex" in lower, "notices must name Artifex as the PyMuPDF licensor"


LICENSE_TEXTS = {
    "GPL-3.0.txt": "GNU GENERAL PUBLIC LICENSE",
    "LGPL-3.0.txt": "GNU LESSER GENERAL PUBLIC LICENSE",
}
NOTICE_SECTIONS = ("## pywin32", "## openpyxl", "## et-xmlfile", "## Pillow", "## Written offer")
LICENCE_GATE = re.compile(r"commercial|\bMIT\b", re.IGNORECASE)


def _assert_license_texts() -> None:
    """Verbatim GPL/LGPL texts exist and every packaging path ships them."""
    for name, title in LICENSE_TEXTS.items():
        path = ROOT / "licenses" / name
        assert path.is_file() and path.stat().st_size > 0, f"missing non-empty {path}"
        head = path.read_text(encoding="utf-8")[:200]
        assert title in head, f"{path} must be the {title.title()} text"
    shippers = {
        "pagedrop.spec": ('ROOT / "licenses"',),
        "installer/windows.iss": ("licenses\\*", "{app}\\licenses"),
        "scripts/build_linux_appimage.sh": tuple(f"licenses/{name}" for name in LICENSE_TEXTS),
    }
    for rel, needles in shippers.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for needle in needles:
            assert needle in text, f"{rel} must ship the licenses/ texts ({needle})"


def _assert_notices_sections(text: str) -> None:
    """Every bundled codec has a notice, and the written offer is present."""
    for heading in NOTICE_SECTIONS:
        assert heading in text, f"notices must have a '{heading}' section"
    offer = text.split("## Written offer", 1)[1]
    assert "github.com/ParallaX07/PageDrop/issues" in offer, (
        "written offer must say how to request corresponding source"
    )


def _assert_license_wording() -> None:
    """Docs, README and the release-notes template state the free licence."""
    for rel in ("docs/licensing.md", "README.md", "release-notes/TEMPLATE.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "AGPL-3.0-or-later" in text, f"{rel} must state AGPL-3.0-or-later"
    template = (ROOT / "release-notes" / "TEMPLATE.md").read_text(encoding="utf-8")
    assert "tree/v{{version}}" in template, "release-notes/TEMPLATE.md must link the source tag"
    about = (ROOT / "src" / "pagedrop" / "ui" / "main_window.py").read_text(encoding="utf-8")
    about = about.split("def _show_about", 1)[1].split("\n    def ", 1)[0]
    for needle in ("AGPL-3.0-or-later", "/tree/v", "/blob/v", "NO WARRANTY"):
        assert needle in about, f"About dialog must contain {needle}"
    for link in (
        "pypi.org/project/PyQt6",
        "download.qt.io/official_releases/qt",
        "pypi.org/project/PyMuPDF",
        "mupdf.com/releases",
    ):
        assert link in template, f"release-notes/TEMPLATE.md must link source: {link}"
    notes = ROOT / "release-notes" / f"v{read_version()}.md"
    if notes.is_file():
        marker = "PageDrop is free software under AGPL-3.0-or-later."
        assert marker in template, "release-notes/TEMPLATE.md must keep the licence paragraph"
        paragraph = template[template.index(marker):].strip()
        assert paragraph in notes.read_text(encoding="utf-8"), (
            f"{notes.relative_to(ROOT).as_posix()} must end with the TEMPLATE.md licence paragraph"
        )


def _assert_no_paid_licence_wording() -> None:
    """README and docs describe free software only (same gate as the release check)."""
    files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for path in files:
        match = LICENCE_GATE.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{path.relative_to(ROOT).as_posix()} must not contain {match.group(0)!r}"


def _assert_dist_licences(data_root: Path, *, windows: bool) -> None:
    """A built bundle carries the project, GPL/LGPL and bundled-codec licence files."""
    fix = "rebuild with current pagedrop.spec"
    files = [data_root / "LICENSE", *(data_root / "licenses" / name for name in LICENSE_TEXTS)]
    for path in files:
        assert path.is_file() and path.stat().st_size > 0, (
            f"onedir bundle must include non-empty {path} ({fix})"
        )
    for name in ("openpyxl", "et_xmlfile", "pillow") + (("pywin32",) if windows else ()):
        infos = [
            d for d in data_root.iterdir()
            if d.is_dir() and d.name.lower().startswith(f"{name}-") and d.name.endswith(".dist-info")
        ]
        assert infos, f"onedir bundle must include the {name} dist-info ({fix})"
        assert any(
            f.is_file() and f.stat().st_size > 0 and f.name.lower().startswith("licen")
            for info in infos
            for f in info.rglob("*")
        ), f"{name} dist-info must include its non-empty licence file ({fix})"


def _assert_notices_in_spec(spec_text: str) -> None:
    assert "THIRD_PARTY_NOTICES.md" in spec_text, (
        "pagedrop.spec must bundle THIRD_PARTY_NOTICES.md in datas"
    )


def _assert_icons_in_spec(spec_text: str) -> None:
    assert "assets/icons" in spec_text or 'ASSETS / "icons"' in spec_text, (
        "pagedrop.spec must bundle Phosphor SVG icons under pagedrop/assets/icons"
    )
    assert "PyQt6.QtSvg" in spec_text, (
        "pagedrop.spec must collect PyQt6.QtSvg for SVG toolbar icons"
    )
    assert 'ASSETS / "logo.svg"' in spec_text, "pagedrop.spec must bundle logo.svg"


def _assert_onedir_spec(spec_text: str) -> None:
    assert "exclude_binaries=True" in spec_text, (
        "pagedrop.spec must use a thin EXE (exclude_binaries=True) for onedir"
    )
    assert "COLLECT(" in spec_text, "pagedrop.spec must COLLECT into dist/pagedrop/"
    assert "PyQt6.QtPrintSupport" in spec_text, (
        "pagedrop.spec must collect PyQt6.QtPrintSupport for frozen print"
    )


def _onedir_data_root(bundle: Path) -> Path:
    """PyInstaller 6+ puts COLLECT datas under `_internal/`; older layouts use the bundle root."""
    internal = bundle / "_internal"
    return internal if internal.is_dir() else bundle


def _assert_onedir_dist_if_present() -> None:
    """When dist/pagedrop/ exists with an exe, require its release contents."""
    bundle = ROOT / "dist" / "pagedrop"
    if not bundle.is_dir():
        return
    exe_candidates = [bundle / "pagedrop.exe", bundle / "pagedrop"]
    exe = next((p for p in exe_candidates if p.is_file()), None)
    if exe is None:
        return
    data_root = _onedir_data_root(bundle)
    notices = data_root / "THIRD_PARTY_NOTICES.md"
    assert notices.is_file() and notices.stat().st_size > 0, (
        f"onedir bundle must include non-empty {notices} "
        f"(rebuild with current pagedrop.spec)"
    )
    icons = data_root / "pagedrop" / "assets" / "icons"
    assert icons.is_dir() and any(icons.iterdir()), (
        f"onedir bundle must include Phosphor icons under {icons}"
    )
    logo = data_root / "pagedrop" / "assets" / "logo.svg"
    assert logo.is_file() and logo.stat().st_size > 0, (
        f"onedir bundle must include non-empty {logo}"
    )
    metadata = list(data_root.glob("pagedrop-*.dist-info/METADATA"))
    assert len(metadata) == 1, "onedir bundle must include exactly one PageDrop METADATA file"
    metadata_text = metadata[0].read_text(encoding="utf-8")
    assert "Name: pagedrop\n" in metadata_text, "frozen metadata must name pagedrop"
    assert f"Version: {read_version()}\n" in metadata_text, (
        "frozen metadata version must match scripts/read_version.py"
    )
    _assert_dist_licences(data_root, windows=exe.name == "pagedrop.exe")
    _assert_frozen_backends(bundle, exe, data_root)


def _frozen_modules(exe: Path) -> set[str]:
    """Module names in the frozen executable's embedded PYZ archive."""
    from PyInstaller.archive.readers import CArchiveReader

    return set(CArchiveReader(str(exe)).open_embedded_archive("PYZ.pyz").toc)


def _assert_frozen_backends(bundle: Path, exe: Path, data_root: Path) -> None:
    """The release bundle must carry every backend the docs advertise."""
    fix = "sync with `--group codecs` (and `--group office` on Windows) and rebuild"
    modules = _frozen_modules(exe)
    required = ["openpyxl", "PIL.Image"]
    is_windows = (bundle / "pagedrop.exe").is_file()
    if is_windows:
        required.append("win32com.client")
    missing = [name for name in required if name not in modules]
    assert not missing, f"frozen bundle is missing {', '.join(missing)}: {fix}"
    if is_windows:
        for pattern in ("pywintypes*.dll", "pythoncom*.dll"):
            assert any(data_root.rglob(pattern)), (
                f"Windows bundle is missing {pattern} under {data_root}: {fix}"
            )


def _assert_installer_if_present(version: str) -> None:
    """Validate a locally built installer/checksum pair without requiring a build."""
    output = ROOT / "installer" / "Output"
    installer = output / f"PageDrop-{version}-Setup.exe"
    checksum = output / f"{installer.name}.sha256"
    if not installer.exists() and not checksum.exists():
        return
    assert installer.is_file() and installer.stat().st_size > 0, (
        f"missing non-empty installer: {installer}"
    )
    assert checksum.is_file(), f"missing checksum: {checksum}"
    expected = f"{sha256(installer.read_bytes()).hexdigest()}  {installer.name}\n"
    assert checksum.read_text(encoding="ascii") == expected, (
        "checksum must contain the final installer SHA-256 and exact filename"
    )


def _assert_backends_declared(spec_text: str) -> None:
    """Spec, dependency groups and sync commands must all carry the backends."""
    for name in ("openpyxl", "PIL.Image", "PIL.WebPImagePlugin"):
        assert f'"{name}"' in spec_text, f"pagedrop.spec must list hidden import {name}"
    for name in ("win32com.client", "pythoncom", "pywintypes"):
        assert f'"{name}"' in spec_text, f"pagedrop.spec must list hidden import {name}"

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    codecs = " ".join(pyproject.get("dependency-groups", {}).get("codecs", [])).lower()
    for pkg in ("openpyxl", "pillow"):
        assert pkg in codecs, f"pyproject.toml codecs group must include {pkg}"
    defaults = pyproject.get("tool", {}).get("uv", {}).get("default-groups", [])
    assert "codecs" in defaults, "pyproject.toml [tool.uv] default-groups must include codecs"

    workflows = ROOT / ".github" / "workflows"
    release = (workflows / "release.yml").read_text(encoding="utf-8")
    windows_job = release.split("build-windows:", 1)[1].split("build-linux:", 1)[0]
    linux_job = release.split("build-linux:", 1)[1]
    ps1 = (ROOT / "scripts" / "build_windows_installer.ps1").read_text(encoding="utf-8")
    for label, text in (
        ("ci.yml", (workflows / "ci.yml").read_text(encoding="utf-8")),
        ("release.yml build-windows", windows_job),
        ("release.yml build-linux", linux_job),
        ("build_windows_installer.ps1", ps1),
    ):
        assert "--group codecs" in text, f"{label} must sync --group codecs"
    for label, text in (("release.yml build-windows", windows_job), ("build_windows_installer.ps1", ps1)):
        assert "--group office" in text, f"{label} must sync --group office"


def _assert_linux_release_script() -> None:
    script = ROOT / "scripts" / "build_linux_appimage.sh"
    text = script.read_text(encoding="utf-8")
    assert "THIRD_PARTY_NOTICES.md" in text and "LICENSE" in text, (
        "Linux AppImage must include licence texts and third-party notices"
    )
    assert "gh-releases-zsync|ParallaX07|PageDrop|latest|PageDrop-*-x86_64.AppImage.zsync" in text, (
        "Linux AppImage must embed the GitHub zsync update information"
    )
    assert "X-AppImage-Version=${VERSION}" in text and "<<DESKTOP" in text, (
        "Linux AppImage desktop file must carry the app version for AppImage managers"
    )


def _assert_ci_package_job() -> None:
    """CI must build the Linux bundle and probe its frozen helper entry points."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "\n  package-linux:" in ci, "ci.yml must define a package-linux job"
    job = ci.split("\n  package-linux:", 1)[1]
    for needle in ("pyinstaller", "check_packaging.py", "smoke_exe.sh", "PAGEDROP_EXE"):
        assert needle in job, f"ci.yml package-linux job must run {needle}"
    probes = (ROOT / "tests" / "smoke" / "test_phase16_executable.py").read_text(encoding="utf-8")
    for needle in ("REDACT_VERIFY_FLAG", "COMPRESS_WORKER_FLAG", "--pagedrop-office-com-worker"):
        assert needle in probes, f"the frozen smoke tests must probe {needle}"


def main() -> None:
    ver = read_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", ver), f"unexpected semver: {ver!r}"

    ico = ROOT / "src" / "pagedrop" / "assets" / "app-icon.ico"
    assert ico.is_file() and ico.stat().st_size > 0, f"missing {ico}"

    iss = ROOT / "installer" / "windows.iss"
    iss_text = iss.read_text(encoding="utf-8")
    assert "pagedrop.exe" in iss_text
    assert "CurrentVersion\\Run" not in iss_text  # no autostart
    assert "AppVersion" in iss_text
    assert f"AppId={APP_ID}" in iss_text, "windows.iss AppId must stay fixed"
    assert f"AppMutex={APP_MUTEX}" in iss_text, "windows.iss must use the updater mutex"
    assert "CloseApplications=no" in iss_text and "RestartApplications=no" in iss_text, (
        "windows.iss must not close or restart PageDrop automatically"
    )
    assert "OutputBaseFilename=PageDrop-{#AppVersion}-Setup" in iss_text, (
        "windows.iss must use the exact release installer name"
    )
    assert "recursesubdirs" in iss_text.lower(), (
        "windows.iss must install the onedir tree (recursesubdirs)"
    )
    assert "dist\\pagedrop" in iss_text or "dist/pagedrop" in iss_text, (
        "windows.iss must source from dist/pagedrop/ onedir output"
    )

    assert NOTICES.is_file() and NOTICES.stat().st_size > 0, f"missing {NOTICES}"
    license_text = LICENSE.read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text, (
        "PageDrop source must be licensed under AGPL-3.0-or-later"
    )
    notices_text = NOTICES.read_text(encoding="utf-8")
    _assert_notices_content(notices_text)
    _assert_notices_sections(notices_text)
    _assert_license_texts()
    _assert_license_wording()
    _assert_no_paid_licence_wording()

    assert SPEC.is_file(), f"missing {SPEC}"
    spec_text = SPEC.read_text(encoding="utf-8")
    _assert_notices_in_spec(spec_text)
    _assert_icons_in_spec(spec_text)
    _assert_onedir_spec(spec_text)
    _assert_backends_declared(spec_text)
    _assert_onedir_dist_if_present()
    _assert_installer_if_present(ver)
    _assert_linux_release_script()
    _assert_ci_package_job()

    assert "THIRD_PARTY_NOTICES.md" in iss_text, (
        "windows.iss must install THIRD_PARTY_NOTICES.md beside the exe"
    )

    print(f"ok packaging checks (version {ver})")


if __name__ == "__main__":
    main()
