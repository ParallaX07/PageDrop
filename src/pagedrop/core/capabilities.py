"""Optional backend capability registry.

Probes report present/absent for Tools / convert backends without requiring those
packages at install time. Soft-fail every optional import and external lookup —
calling ``probe`` / ``probe_all`` must never raise ``ImportError`` (or other
import-time crashes) from optional deps.

Absence reasons match the shared configure UX:

- ``engine_missing`` — converter / processing engine (Office COM, LibreOffice,
  Ghostscript, veraPDF, pyHanko, OpenCV)
- ``data_missing`` — language or model data (tessdata)
- ``codec_missing`` — format codec pack (Pillow, openpyxl, pi-heif)
- ``licence_blocked`` — present but redistribution / use blocked by policy
  (reserved; probes do not invent a block without an explicit gate)
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

# Stable capability ids (Tools / jobs / tests).
OFFICE_COM = "office_com"
LIBREOFFICE = "libreoffice"
TESSDATA = "tessdata"
PILLOW = "pillow"
OPENPYXL = "openpyxl"
PI_HEIF = "pi_heif"
PYHANKO = "pyhanko"
OPENCV = "opencv"
GHOSTSCRIPT = "ghostscript"
VERAPDF = "verapdf"

CAPABILITY_IDS: tuple[str, ...] = (
    OFFICE_COM,
    LIBREOFFICE,
    TESSDATA,
    PILLOW,
    OPENPYXL,
    PI_HEIF,
    PYHANKO,
    OPENCV,
    GHOSTSCRIPT,
    VERAPDF,
)


class AbsenceReason(str, Enum):
    """Why a capability is unavailable (Tools configure / download / recheck UX)."""

    ENGINE_MISSING = "engine_missing"
    DATA_MISSING = "data_missing"
    CODEC_MISSING = "codec_missing"
    LICENCE_BLOCKED = "licence_blocked"


@dataclass(frozen=True)
class CapabilityStatus:
    """Structured present/absent report for one optional backend."""

    id: str
    available: bool
    reason: AbsenceReason | None = None
    detail: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.available and self.reason is not None:
            raise ValueError(f"{self.id}: available capability must not set reason")
        if not self.available and self.reason is None:
            raise ValueError(f"{self.id}: absent capability requires a typed reason")


_cache: dict[str, CapabilityStatus] | None = None


def clear_cache() -> None:
    """Drop cached probe results (tests / Settings Recheck)."""
    global _cache
    _cache = None


def soft_import(module_name: str) -> tuple[Any | None, BaseException | None]:
    """Import *module_name*; return ``(module, None)`` or ``(None, error)``.

    Catches ``BaseException`` so a broken optional wheel cannot break the registry
    (ImportError, OSError from missing shared libs, even SystemExit from bad
    package ``__init__``). Re-raises KeyboardInterrupt / SystemExit from *this*
    process only when they are not produced by the import — SystemExit from the
    imported module is swallowed as absence.
    """
    try:
        return importlib.import_module(module_name), None
    except Exception as exc:
        return None, exc
    except SystemExit as exc:  # noqa: BLE001 — optional package misbehaved
        return None, exc


def probe(capability_id: str, *, refresh: bool = False) -> CapabilityStatus:
    """Return status for one capability; soft-fails all optional lookups."""
    if capability_id not in CAPABILITY_IDS:
        raise KeyError(f"unknown capability id: {capability_id!r}")
    if refresh:
        clear_cache()
    return probe_all(refresh=False)[capability_id]


def probe_all(*, refresh: bool = False) -> dict[str, CapabilityStatus]:
    """Probe every registered capability. Safe to call at startup."""
    global _cache
    if refresh or _cache is None:
        _cache = {cid: _PROBES[cid]() for cid in CAPABILITY_IDS}
    return dict(_cache)


# --- individual probes -------------------------------------------------------


def _absent(cid: str, reason: AbsenceReason, detail: str, **extras: Any) -> CapabilityStatus:
    return CapabilityStatus(
        id=cid, available=False, reason=reason, detail=detail, extras=extras
    )


def _present(cid: str, detail: str = "", **extras: Any) -> CapabilityStatus:
    return CapabilityStatus(id=cid, available=True, detail=detail, extras=extras)


def _probe_python_module(
    cid: str,
    module_name: str,
    reason: AbsenceReason,
    label: str,
) -> CapabilityStatus:
    _mod, err = soft_import(module_name)
    if err is not None:
        return _absent(cid, reason, f"{label} not available ({type(err).__name__})")
    return _present(cid, f"{label} importable")


def _probe_office_com() -> CapabilityStatus:
    if platform.system() != "Windows":
        return _absent(
            OFFICE_COM,
            AbsenceReason.ENGINE_MISSING,
            "Microsoft Office COM is only available on Windows",
        )
    _mod, err = soft_import("win32com.client")
    if err is not None:
        return _absent(
            OFFICE_COM,
            AbsenceReason.ENGINE_MISSING,
            f"pywin32 not available ({type(err).__name__})",
        )
    apps = _windows_office_progids()
    if not apps:
        return _absent(
            OFFICE_COM,
            AbsenceReason.ENGINE_MISSING,
            "pywin32 present but no Office COM ProgIDs registered",
            apps=[],
        )
    return _present(OFFICE_COM, "Office COM ProgIDs found", apps=apps)


def _windows_office_progids() -> list[str]:
    """ProgIDs present under HKCR — no Dispatch (does not launch Office)."""
    try:
        import winreg
    except ImportError:
        return []
    found: list[str] = []
    for progid, short in (
        ("Word.Application", "word"),
        ("Excel.Application", "excel"),
        ("PowerPoint.Application", "powerpoint"),
    ):
        try:
            key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid)
            winreg.CloseKey(key)
            found.append(short)
        except OSError:
            continue
    return found


# User-configured soffice path (Settings / tests). Checked before PATH.
_configured_soffice_path: str | None = None

# Preferred Office → PDF backend: ``auto`` | ``com`` | ``libreoffice``.
_configured_office_backend: str = "auto"
_OFFICE_BACKEND_VALUES = frozenset({"auto", "com", "libreoffice"})


def set_configured_soffice_path(path: str | None) -> None:
    """Set or clear the user-configured LibreOffice ``soffice`` path.

    Call from Settings when the user picks a custom binary. Does not probe;
    callers should ``clear_cache()`` after changing.
    """
    global _configured_soffice_path
    raw = (path or "").strip()
    _configured_soffice_path = raw or None


def configured_soffice_path() -> str | None:
    """Return the path last set via :func:`set_configured_soffice_path`."""
    return _configured_soffice_path


def set_configured_office_backend(backend: str | None) -> None:
    """Set preferred Office → PDF backend (``auto`` / ``com`` / ``libreoffice``)."""
    global _configured_office_backend
    raw = (backend or "auto").strip().lower()
    _configured_office_backend = raw if raw in _OFFICE_BACKEND_VALUES else "auto"


def configured_office_backend() -> str:
    """Return the preferred backend last set via :func:`set_configured_office_backend`."""
    return _configured_office_backend


def _probe_libreoffice() -> CapabilityStatus:
    path = find_soffice()
    if path is None:
        return _absent(
            LIBREOFFICE,
            AbsenceReason.ENGINE_MISSING,
            "LibreOffice (soffice) not found (configured path, PATH, registry, or install dirs)",
        )
    return _present(LIBREOFFICE, "LibreOffice found", path=path)


def find_soffice(configured_path: str | None = None) -> str | None:
    """Locate ``soffice`` / LibreOffice binary.

    Order: *configured_path* argument → module-configured path → env
    (``PAGEDROP_LO_PATH``, ``LIBREOFFICE_PATH``) → ``PATH`` → Windows registry
    → common install directories.
    """
    for candidate in _soffice_candidates(configured_path):
        if candidate is not None and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def _soffice_candidates(configured_path: str | None) -> list[str | None]:
    ordered: list[str | None] = []
    for raw in (configured_path, _configured_soffice_path):
        if raw and raw.strip():
            ordered.append(raw.strip())
    for env_key in ("PAGEDROP_LO_PATH", "LIBREOFFICE_PATH"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            ordered.append(raw)
    for name in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            ordered.append(found)
    registry = _windows_registry_soffice()
    if registry:
        ordered.append(registry)
    home = Path.home()
    for path in (
        Path("/usr/bin/soffice"),
        Path("/usr/lib/libreoffice/program/soffice"),
        Path("/usr/local/bin/soffice"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        home / "Applications" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice",
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ):
        ordered.append(str(path))
    return ordered


def _windows_registry_soffice() -> str | None:
    """Resolve soffice.exe from LibreOffice / App Paths registry keys (Windows)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    def _file_if_exists(raw: str) -> str | None:
        path = Path(raw)
        if path.is_file():
            return str(path)
        # UNO InstallPath is typically the ``program`` directory.
        for name in ("soffice.exe", "soffice"):
            candidate = path / name
            if candidate.is_file():
                return str(candidate)
            candidate = path / "program" / name
            if candidate.is_file():
                return str(candidate)
        return None

    roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    subkeys = (
        r"SOFTWARE\LibreOffice\UNO\InstallPath",
        r"SOFTWARE\WOW6432Node\LibreOffice\UNO\InstallPath",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe",
    )
    for root in roots:
        for sub in subkeys:
            try:
                with winreg.OpenKey(root, sub) as key:
                    value, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                found = _file_if_exists(value.strip())
                if found:
                    return found
    return None


# Back-compat for callers / tests that used the private name.
_find_soffice = find_soffice


def _probe_tessdata() -> CapabilityStatus:
    directory, langs = _find_tessdata()
    if directory is None or not langs:
        return _absent(
            TESSDATA,
            AbsenceReason.DATA_MISSING,
            "No tessdata languages found (set TESSDATA_PREFIX or PAGEDROP_TESSDATA)",
            languages=[],
            path=None,
        )
    return _present(
        TESSDATA,
        f"{len(langs)} tessdata language(s)",
        languages=langs,
        path=str(directory),
    )


def _find_tessdata() -> tuple[Path | None, list[str]]:
    candidates: list[Path] = []
    for env_key in ("PAGEDROP_TESSDATA", "TESSDATA_PREFIX"):
        raw = os.environ.get(env_key, "").strip()
        if not raw:
            continue
        base = Path(raw)
        candidates.append(base)
        # TESSDATA_PREFIX may be the parent of the tessdata folder.
        if base.name != "tessdata":
            candidates.append(base / "tessdata")
    candidates.extend(
        [
            Path("/usr/share/tessdata"),
            Path("/usr/share/tesseract-ocr/5/tessdata"),
            Path("/usr/share/tesseract-ocr/4.00/tessdata"),
            Path("/usr/local/share/tessdata"),
            Path("/opt/homebrew/share/tessdata"),
            Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
        ]
    )
    seen: set[Path] = set()
    for directory in candidates:
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        langs = sorted(
            p.stem
            for p in resolved.glob("*.traineddata")
            if p.is_file() and p.stem and p.stem != "osd"
        )
        if langs:
            return resolved, langs
    return None, []


def _probe_ghostscript() -> CapabilityStatus:
    path = _which_first("gs", "gswin64c", "gswin32c", "gs.exe")
    if path is None:
        return _absent(
            GHOSTSCRIPT,
            AbsenceReason.ENGINE_MISSING,
            "Ghostscript not found on PATH",
        )
    return _present(GHOSTSCRIPT, "Ghostscript found", path=path)


def _probe_verapdf() -> CapabilityStatus:
    path = _which_first("verapdf", "verapdf.bat")
    if path is None:
        return _absent(
            VERAPDF,
            AbsenceReason.ENGINE_MISSING,
            "veraPDF not found on PATH",
        )
    return _present(VERAPDF, "veraPDF found", path=path)


def _which_first(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


_PROBES: dict[str, Callable[[], CapabilityStatus]] = {
    OFFICE_COM: _probe_office_com,
    LIBREOFFICE: _probe_libreoffice,
    TESSDATA: _probe_tessdata,
    PILLOW: lambda: _probe_python_module(
        PILLOW, "PIL", AbsenceReason.CODEC_MISSING, "Pillow"
    ),
    OPENPYXL: lambda: _probe_python_module(
        OPENPYXL, "openpyxl", AbsenceReason.CODEC_MISSING, "openpyxl"
    ),
    PI_HEIF: lambda: _probe_python_module(
        PI_HEIF, "pi_heif", AbsenceReason.CODEC_MISSING, "pi-heif"
    ),
    PYHANKO: lambda: _probe_python_module(
        PYHANKO, "pyhanko", AbsenceReason.ENGINE_MISSING, "pyHanko"
    ),
    OPENCV: lambda: _probe_python_module(
        OPENCV, "cv2", AbsenceReason.ENGINE_MISSING, "OpenCV"
    ),
    GHOSTSCRIPT: _probe_ghostscript,
    VERAPDF: _probe_verapdf,
}


def _self_check() -> None:
    """Runnable check: registry enumerates without raising."""
    clear_cache()
    statuses = probe_all(refresh=True)
    assert set(statuses) == set(CAPABILITY_IDS)
    for status in statuses.values():
        assert status.available or status.reason in AbsenceReason
    # Typed reasons are the UX contract — keep names stable.
    assert {r.value for r in AbsenceReason} == {
        "engine_missing",
        "data_missing",
        "codec_missing",
        "licence_blocked",
    }


if __name__ == "__main__":
    _self_check()
    for cid, status in probe_all().items():
        flag = "ok" if status.available else status.reason.value  # type: ignore[union-attr]
        print(f"{cid}: {flag} — {status.detail}")
    sys.exit(0)
