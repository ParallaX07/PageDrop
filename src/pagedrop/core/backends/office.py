"""Office → PDF orchestration: capability report, auto route, explicit retry.

Auto selects Microsoft Office COM when the installed app supports the format,
otherwise LibreOffice when detected. A COM **processing** failure never
silently falls back — callers must pass ``backend="libreoffice"`` (or use the
UI retry confirm) to try LibreOffice.

Outputs are staged under a temp dir, opened with PyMuPDF to validate, then
promoted to the user path.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import fitz

from pagedrop.core.backends import libreoffice, office_com
from pagedrop.core.capabilities import (
    LIBREOFFICE,
    OFFICE_COM,
    CapabilityStatus,
    configured_office_backend,
    configured_soffice_path,
    probe,
)
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError, JobError
from pagedrop.helpers.office_com_worker import (
    EXCEL_EXTENSIONS,
    POWERPOINT_EXTENSIONS,
    WORD_EXTENSIONS,
    office_app_for_path,
)
from pagedrop.utils.temp_manager import claim_backend_temp, release_backend_temp

OfficeBackend = Literal["auto", "com", "libreoffice"]
ResolvedBackend = Literal["com", "libreoffice"]

BACKEND_AUTO: OfficeBackend = "auto"
BACKEND_COM: OfficeBackend = "com"
BACKEND_LIBREOFFICE: OfficeBackend = "libreoffice"

BACKEND_LABELS: dict[str, str] = {
    "com": "Microsoft Office",
    "libreoffice": "LibreOffice",
    "auto": "Auto",
}

# LibreOffice-only extras beyond the COM sets (OpenDocument + common LO imports).
_LO_EXTRA_EXTENSIONS = frozenset(
    {
        ".odt",
        ".ods",
        ".odp",
        ".odg",
        ".sxw",
        ".sxc",
        ".sxi",
        ".wpd",
        ".wps",
    }
)

OFFICE_EXTENSIONS: frozenset[str] = (
    WORD_EXTENSIONS | EXCEL_EXTENSIONS | POWERPOINT_EXTENSIONS | _LO_EXTRA_EXTENSIONS
)


class OfficeConversionError(JobError):
    """Office → PDF failed after routing (or validation rejected the PDF)."""

    def __init__(self, message: str, code: str = "office_convert_error") -> None:
        self.code = code
        super().__init__(message)


class OfficeComFailedNeedsRetry(OfficeConversionError):
    """COM processing failed; LibreOffice is available for an **explicit** retry.

    Auto routing must not catch this and swap renderers — only the UI / caller
    after user confirmation (or ``backend="libreoffice"``) may retry.
    """

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, code="com_failed_retry_lo")
        self.cause = cause
        self.retry_with_libreoffice = True


@dataclass(frozen=True)
class OfficeCapabilityReport:
    """Present/absent snapshot for Office conversion backends."""

    com: CapabilityStatus
    libreoffice: CapabilityStatus
    preferred: OfficeBackend
    soffice_path: str | None

    @property
    def any_available(self) -> bool:
        return self.com.available or self.libreoffice.available

    def status_line(self) -> str:
        """Short status for the tool window (backend names, no jargon)."""
        parts: list[str] = []
        if self.com.available:
            apps = self.com.extras.get("apps") or []
            apps_s = ", ".join(apps) if apps else "ready"
            parts.append(f"Microsoft Office ({apps_s})")
        else:
            parts.append("Microsoft Office unavailable")
        if self.libreoffice.available:
            path = self.libreoffice.extras.get("path") or self.soffice_path or "found"
            parts.append(f"LibreOffice ({path})")
        else:
            parts.append("LibreOffice unavailable")
        return f"Preferred: {BACKEND_LABELS.get(self.preferred, self.preferred)}. " + "; ".join(
            parts
        )


@dataclass(frozen=True)
class OfficeConvertResult:
    """Successful conversion: user path + which engine wrote it."""

    path: Path
    backend: ResolvedBackend
    page_count: int

    @property
    def backend_label(self) -> str:
        return BACKEND_LABELS.get(self.backend, self.backend)


def is_office_path(path: str | Path) -> bool:
    """True when *path* has an Office / LibreOffice-convertible extension."""
    return Path(path).suffix.lower() in OFFICE_EXTENSIONS


def office_dialog_filter() -> str:
    """QFileDialog filter for Office → PDF inputs."""
    patterns = " ".join(f"*{ext}" for ext in sorted(OFFICE_EXTENSIONS))
    return (
        f"Office documents ({patterns});;"
        "Word (*.doc *.docx *.odt *.rtf);;"
        "Excel (*.xls *.xlsx *.ods *.csv);;"
        "PowerPoint (*.ppt *.pptx *.odp);;"
        "All files (*)"
    )


def capability_report(
    *,
    preferred: OfficeBackend | None = None,
    refresh: bool = False,
) -> OfficeCapabilityReport:
    """Probe COM + LibreOffice and return a structured report."""
    raw = preferred or configured_office_backend()
    pref: OfficeBackend = (
        raw if raw in ("auto", "com", "libreoffice") else "auto"  # type: ignore[assignment]
    )
    soffice = configured_soffice_path()
    if refresh:
        com = probe(OFFICE_COM, refresh=True)
        lo = probe(LIBREOFFICE, refresh=False)  # refresh already cleared cache
    else:
        com = probe(OFFICE_COM)
        lo = probe(LIBREOFFICE)
    return OfficeCapabilityReport(
        com=com,
        libreoffice=lo,
        preferred=pref,
        soffice_path=soffice,
    )


def com_supports_path(path: str | Path, *, apps: list[str] | None = None) -> bool:
    """True when COM can route *path* and the matching Office app ProgID exists."""
    try:
        kind = office_app_for_path(Path(path))
    except Exception:  # noqa: BLE001 — unsupported extension
        return False
    if apps is None:
        status = probe(OFFICE_COM)
        if not status.available:
            return False
        raw = status.extras.get("apps") or []
        apps = [str(a) for a in raw] if isinstance(raw, (list, tuple)) else []
    return kind in apps


def resolve_backend(
    path: str | Path,
    *,
    preference: OfficeBackend = "auto",
    report: OfficeCapabilityReport | None = None,
) -> ResolvedBackend:
    """Pick ``com`` or ``libreoffice`` for *path* without converting.

    Raises ``BackendUnavailableError`` when no usable backend exists.
    """
    snap = report or capability_report(preferred=preference)
    pref = preference if preference != "auto" else snap.preferred

    if pref == "com":
        if not snap.com.available:
            raise BackendUnavailableError(
                OFFICE_COM,
                snap.com.reason or "engine_missing",
                snap.com.detail,
            )
        if not com_supports_path(path, apps=list(snap.com.extras.get("apps") or [])):
            raise OfficeConversionError(
                f"Microsoft Office cannot convert {Path(path).suffix or 'this file'}",
                code="unsupported_format",
            )
        return "com"

    if pref == "libreoffice":
        if not snap.libreoffice.available:
            raise BackendUnavailableError(
                LIBREOFFICE,
                snap.libreoffice.reason or "engine_missing",
                snap.libreoffice.detail,
            )
        return "libreoffice"

    # auto: COM when format + app present → else LibreOffice
    apps = list(snap.com.extras.get("apps") or [])
    if snap.com.available and com_supports_path(path, apps=apps):
        return "com"
    if snap.libreoffice.available:
        return "libreoffice"
    if snap.com.available:
        # COM present but not for this format, and no LO.
        raise OfficeConversionError(
            f"No backend can convert {Path(path).name}: "
            "LibreOffice not found and Microsoft Office does not support this format",
            code="unsupported_format",
        )
    raise BackendUnavailableError(
        LIBREOFFICE,
        snap.libreoffice.reason or "engine_missing",
        snap.libreoffice.detail
        or "Neither Microsoft Office nor LibreOffice is available",
    )


def validate_pdf(path: str | Path) -> int:
    """Open *path* with fitz; return page count. Raises if not a usable PDF.

    Takes ``FITZ_LOCK`` briefly so Office / LibreOffice waits (outside the
    job-runner lock) never leave an unlocked fitz open here.
    """
    from pagedrop.core.pdf_service import FITZ_LOCK

    resolved = Path(path)
    if not resolved.is_file():
        raise OfficeConversionError(
            f"Staged PDF missing: {resolved}", code="empty_output"
        )
    with FITZ_LOCK:
        try:
            doc = fitz.open(resolved)
        except Exception as exc:  # noqa: BLE001 — corrupt / non-PDF
            raise OfficeConversionError(
                f"Output is not a valid PDF: {exc}", code="invalid_pdf"
            ) from exc
        try:
            count = int(doc.page_count)
            if count < 1:
                raise OfficeConversionError(
                    "Converted PDF has no pages", code="empty_pdf"
                )
            return count
        finally:
            doc.close()


def convert_office_to_pdf(
    input_path: str | Path,
    output_path: str | Path,
    *,
    backend: OfficeBackend = "auto",
    soffice_path: str | None = None,
    timeout_sec: float | None = None,
    cancel: CancelToken | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> OfficeConvertResult:
    """Convert one Office file to PDF: stage → convert → fitz validate → promote.

    When *backend* is ``auto`` (or resolves to COM) and COM **processing** fails
    while LibreOffice is available, raises :class:`OfficeComFailedNeedsRetry`
    instead of silently swapping. Pass ``backend="libreoffice"`` to retry.
    """
    src = Path(input_path).resolve()
    dst = Path(output_path).resolve()
    if not src.is_file():
        raise OfficeConversionError(f"Input not found: {src}", code="input_missing")
    if src == dst:
        raise OfficeConversionError(
            "Output path must not overwrite the source Office file",
            code="source_overwrite",
        )
    if not is_office_path(src):
        raise OfficeConversionError(
            f"Unsupported Office extension: {src.suffix or '(none)'}",
            code="unsupported_format",
        )

    report = capability_report(preferred=backend if backend != "auto" else None)
    if not report.any_available:
        raise BackendUnavailableError(
            LIBREOFFICE if not report.com.available else OFFICE_COM,
            "engine_missing",
            "Neither Microsoft Office nor LibreOffice is available",
        )

    resolved = resolve_backend(src, preference=backend, report=report)
    lo_path = soffice_path or report.soffice_path
    timeout = (
        float(timeout_sec)
        if timeout_sec is not None
        else float(office_com.DEFAULT_TIMEOUT_SEC)
    )

    stage_dir = claim_backend_temp(
        Path(tempfile.mkdtemp(prefix="pagedrop_office_stage_"))
    )
    staged = stage_dir / "staged.pdf"
    try:
        try:
            _run_backend(
                resolved,
                src,
                staged,
                soffice_path=lo_path,
                timeout_sec=timeout,
                cancel=cancel,
                on_progress=on_progress,
            )
        except Exception as exc:
            if (
                resolved == "com"
                and report.libreoffice.available
                and not isinstance(exc, (BackendUnavailableError,))
                and _is_processing_failure(exc)
            ):
                raise OfficeComFailedNeedsRetry(
                    f"Microsoft Office conversion failed: {exc}. "
                    "Retry with LibreOffice? Layouts may differ.",
                    cause=exc,
                ) from exc
            raise

        pages = validate_pdf(staged)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()
        try:
            staged.replace(dst)
        except OSError:
            shutil.copyfile(staged, dst)
            staged.unlink(missing_ok=True)
        return OfficeConvertResult(path=dst, backend=resolved, page_count=pages)
    finally:
        release_backend_temp(stage_dir)
        shutil.rmtree(stage_dir, ignore_errors=True)


def _is_processing_failure(exc: BaseException) -> bool:
    """True for converter failures (not cancel / missing-engine)."""
    from pagedrop.core.jobs.errors import JobCancelledError

    if isinstance(exc, (JobCancelledError, BackendUnavailableError)):
        return False
    return isinstance(
        exc,
        (office_com.OfficeComConversionError, libreoffice.LibreOfficeConversionError, OSError),
    )


def _run_backend(
    backend: ResolvedBackend,
    src: Path,
    staged: Path,
    *,
    soffice_path: str | None,
    timeout_sec: float,
    cancel: CancelToken | None,
    on_progress: Callable[[str], None] | None,
) -> None:
    if backend == "com":
        office_com.convert_via_com(
            src,
            staged,
            timeout_sec=timeout_sec,
            cancel=cancel,
            on_progress=on_progress,
        )
        return
    libreoffice.convert_via_libreoffice(
        src,
        staged,
        soffice_path=soffice_path,
        timeout_sec=timeout_sec,
        cancel=cancel,
        on_progress=on_progress,
    )


def _self_check() -> None:
    """Runnable check: report builds; validate rejects non-PDF; extensions set."""
    report = capability_report()
    assert report.com.id == OFFICE_COM
    assert report.libreoffice.id == LIBREOFFICE
    assert ".docx" in OFFICE_EXTENSIONS
    bad_dir = claim_backend_temp(
        Path(tempfile.mkdtemp(prefix="pagedrop_office_check_"))
    )
    bad = bad_dir / "x.bin"
    bad.write_bytes(b"not-a-pdf")
    try:
        try:
            validate_pdf(bad)
            raise AssertionError("validate_pdf should reject non-PDF")
        except OfficeConversionError as exc:
            assert exc.code == "invalid_pdf"
    finally:
        release_backend_temp(bad_dir)
        shutil.rmtree(bad_dir, ignore_errors=True)


if __name__ == "__main__":
    _self_check()
    print(capability_report().status_line())
