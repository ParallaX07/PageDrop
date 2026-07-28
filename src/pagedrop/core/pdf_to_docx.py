"""PDF → DOCX via LibreOffice (Phase 32).

Layout is best-effort / lossy. Never overwrites the source PDF. LibreOffice is
detected via the capability registry and never bundled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from pagedrop.core.backends.libreoffice import (
    DEFAULT_TIMEOUT_SEC,
    LibreOfficeConversionError,
    convert_via_libreoffice,
)
from pagedrop.core.capabilities import LIBREOFFICE, find_soffice, probe
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.supported_formats import is_pdf_path


class PdfToDocxError(LibreOfficeConversionError):
    """PDF → DOCX conversion failed."""


def convert_pdf_to_docx(
    source_path: str | Path,
    output_path: str | Path,
    *,
    soffice_path: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    cancel: CancelToken | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Convert a PDF to a new DOCX path via headless LibreOffice.

    Raises:
        BackendUnavailableError: soffice not found
        PdfToDocxError: bad input / empty or invalid DOCX
        JobCancelledError: cancel token fired
    """
    source = Path(source_path)
    output = Path(output_path)
    if not is_pdf_path(source):
        raise PdfToDocxError(
            f"Expected a PDF input, got {source.suffix or '(no extension)'}",
            code="bad_input",
        )
    if not source.is_file():
        raise PdfToDocxError(f"Input not found: {source}", code="input_missing")
    reject_source_overwrite(output, source)

    binary = soffice_path or find_soffice()
    if not binary or not Path(binary).is_file():
        status = probe(LIBREOFFICE)
        raise BackendUnavailableError(
            LIBREOFFICE,
            status.reason or "engine_missing",
            status.detail or "LibreOffice (soffice) not found",
        )

    if on_progress is not None:
        on_progress("Converting PDF to Word with LibreOffice…")

    result = convert_via_libreoffice(
        source,
        output,
        convert_to="docx",
        # Without this, LO opens PDF as Draw and has no DOCX export filter.
        infilter="writer_pdf_import",
        soffice_path=binary,
        timeout_sec=timeout_sec,
        cancel=cancel,
        on_progress=on_progress,
    )
    _validate_docx(result)
    return result


def _validate_docx(path: Path) -> None:
    """DOCX is a ZIP package — require a non-empty PK header."""
    if not path.is_file() or path.stat().st_size < 4:
        raise PdfToDocxError(
            f"LibreOffice produced an empty DOCX: {path.name}",
            code="empty_output",
        )
    header = path.read_bytes()[:4]
    if header[:2] != b"PK":
        raise PdfToDocxError(
            f"LibreOffice output is not a DOCX package: {path.name}",
            code="invalid_docx",
        )
