"""Security-grade PDF redaction (Phase 30).

Mark regions → apply redaction annotations → full non-incremental
garbage-collecting rewrite to a **new** path → verify in a **fresh process**.
Visual black boxes alone never pass. Failed verification deletes the staged
output so no promoted redacted copy remains.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import fitz

from pagedrop.core.jobs.errors import JobError
from pagedrop.core.jobs.paths import reject_source_overwrite
from pagedrop.core.pdf_loader import open_pdf
from pagedrop.core.pdf_service import FITZ_LOCK
from pagedrop.core.pdf_tools import STANDARD_METADATA_KEYS

if TYPE_CHECKING:
    from pagedrop.core.markup import MarkupEntry
    from pagedrop.core.pdf_editor import PdfEditModel

# Thorough defaults: remove overlapping text; blank image pixels; remove
# touched vector art. Cosmetic cover is never enough.
_IMAGES = fitz.PDF_REDACT_IMAGE_PIXELS
_GRAPHICS = fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
_TEXT = fitz.PDF_REDACT_TEXT_REMOVE

# Frozen: fresh-process verifier re-enters the exe before Qt starts (main.py).
REDACT_VERIFY_FLAG = "--pagedrop-redact-verify"


class RedactionError(JobError):
    """Raised when redaction cannot be applied or prepared."""


class RedactionVerifyError(JobError):
    """Raised when post-redaction verification fails (output must not be kept)."""

    def __init__(self, message: str, *, failures: Sequence[str] = ()) -> None:
        self.failures = tuple(failures)
        super().__init__(message)


@dataclass(frozen=True)
class RedactionRegion:
    """One redaction rectangle in unrotated PDF page space (origin top-left)."""

    page_index: int
    rect: tuple[float, float, float, float]
    fill: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Extra strings that must be absent after apply (beyond text under the rect).
    expected_absent: tuple[str, ...] = ()


@dataclass(frozen=True)
class RedactionScope:
    """Optional document scrubbing applied with the redaction rewrite."""

    strip_metadata: bool = True
    strip_xmp: bool = True
    remove_attachments: bool = False


@dataclass
class RedactionVerifyReport:
    """Structured verify result (empty ``failures`` means pass)."""

    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _normalize_secret(text: str) -> str:
    return " ".join(text.split()).strip()


def _secret_byte_forms(secret: str) -> list[bytes]:
    """Byte patterns that may appear in a PDF file for *secret*."""
    forms: list[bytes] = []
    for enc in ("utf-8", "latin-1"):
        try:
            forms.append(secret.encode(enc))
        except UnicodeEncodeError:
            continue
    try:
        # MuPDF often writes ASCII text as hex strings inside content streams.
        forms.append(secret.encode("ascii").hex().encode("ascii"))
    except UnicodeEncodeError:
        pass
    # Deduplicate while preserving order.
    seen: set[bytes] = set()
    out: list[bytes] = []
    for form in forms:
        if form and form not in seen:
            seen.add(form)
            out.append(form)
    return out


def _file_contains_any(
    path: Path,
    needles: Sequence[bytes],
    *,
    chunk_size: int = 1024 * 1024,
) -> bytes | None:
    """Return the first needle found in *path*, scanning in overlapping chunks.

    Avoids loading the whole PDF into RAM (verify used to ``read_bytes()`` the
    entire output). Overlap is ``max(len(needle)) - 1`` so matches that straddle
    chunk boundaries are still found.
    """
    active = [n for n in needles if n]
    if not active:
        return None
    overlap = max(len(n) for n in active) - 1
    prev = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            data = prev + chunk if prev else chunk
            for needle in active:
                if needle in data:
                    return needle
            prev = data[-overlap:] if overlap > 0 else b""
    return None


def _secrets_under_regions(
    doc: fitz.Document, regions: Sequence[RedactionRegion]
) -> list[str]:
    """Collect non-empty text under each region plus caller-supplied secrets."""
    secrets: list[str] = []
    seen: set[str] = set()
    for region in regions:
        if region.page_index < 0 or region.page_index >= doc.page_count:
            raise RedactionError(
                f"Page index {region.page_index} out of range ({doc.page_count} pages)"
            )
        page = doc[region.page_index]
        box = fitz.Rect(*region.rect)
        captured = _normalize_secret(page.get_textbox(box) or "")
        candidates = [captured, *region.expected_absent]
        for raw in candidates:
            secret = _normalize_secret(raw)
            if len(secret) < 2:
                continue
            if secret in seen:
                continue
            seen.add(secret)
            secrets.append(secret)
    return secrets


def _apply_regions(doc: fitz.Document, regions: Sequence[RedactionRegion]) -> None:
    if not regions:
        raise RedactionError("No redaction regions to apply")
    by_page: dict[int, list[RedactionRegion]] = {}
    for region in regions:
        if region.page_index < 0 or region.page_index >= doc.page_count:
            raise RedactionError(
                f"Page index {region.page_index} out of range ({doc.page_count} pages)"
            )
        by_page.setdefault(region.page_index, []).append(region)

    for page_index, page_regions in by_page.items():
        page = doc[page_index]
        for region in page_regions:
            page.add_redact_annot(
                fitz.Rect(*region.rect),
                fill=region.fill,
                cross_out=False,
            )
        page.apply_redactions(images=_IMAGES, graphics=_GRAPHICS, text=_TEXT)


def _apply_scope(doc: fitz.Document, scope: RedactionScope) -> None:
    if scope.strip_metadata:
        meta = dict(doc.metadata or {})
        for key in STANDARD_METADATA_KEYS:
            if key in meta:
                meta[key] = ""
        doc.set_metadata(meta)
    if scope.strip_xmp:
        doc.del_xml_metadata()
    if scope.remove_attachments:
        for name in list(doc.embfile_names() or []):
            doc.embfile_del(name)


def _gc_save(doc: fitz.Document, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # garbage=4 + clean + non-incremental: drop unreachable objects / prior revs.
    doc.save(
        str(output_path),
        garbage=4,
        deflate=True,
        clean=True,
        incremental=False,
    )


def _page_has_redact_annot(page: fitz.Page) -> bool:
    for annot in page.annots() or []:
        if annot.type and annot.type[0] == fitz.PDF_ANNOT_REDACT:
            return True
    return False


def inspect_redaction_result(
    path: str | Path,
    *,
    absent_text: Sequence[str] = (),
    password: str | None = None,
    expect_no_redact_annots: bool = True,
    expect_empty_metadata: bool = False,
    expect_no_attachments: bool = False,
    forbidden_image_xrefs: Sequence[int] = (),
) -> RedactionVerifyReport:
    """In-process inspection used by the fresh-process verifier."""
    report = RedactionVerifyReport()
    doc = open_pdf(str(path), password=password)
    try:
        secrets = [_normalize_secret(s) for s in absent_text if _normalize_secret(s)]
        path_obj = Path(path)

        for secret in secrets:
            # Text extraction / search.
            for page in doc:
                extracted = _normalize_secret(page.get_text("text") or "")
                if secret in extracted:
                    report.failures.append(f"text extract still contains {secret!r}")
                    break
                try:
                    hits = page.search_for(secret)
                except Exception as exc:
                    # Fail closed: search errors are not "no hits".
                    report.failures.append(
                        f"search_for failed for {secret!r}: {type(exc).__name__}"
                    )
                    break
                if hits:
                    report.failures.append(f"search_for still hits {secret!r}")
                    break

            # Raw file / content-stream presence (catches incremental leftovers
            # and hex-encoded TJ operators). Chunked scan — reopen+search alone
            # misses stream encodings; full read_bytes() would hold the whole
            # output in RAM.
            leaked = _file_contains_any(path_obj, _secret_byte_forms(secret))
            if leaked is not None:
                report.failures.append(
                    f"raw file bytes still contain {secret!r} ({leaked!r})"
                )

        if expect_no_redact_annots:
            for i, page in enumerate(doc):
                if _page_has_redact_annot(page):
                    report.failures.append(f"unresolved redaction annot on page {i}")

        if expect_empty_metadata:
            meta = doc.metadata or {}
            leftover = [
                k
                for k in STANDARD_METADATA_KEYS
                if (meta.get(k) or "").strip()
                and k not in ("format",)  # MuPDF may keep format label
            ]
            # Producer/creator often rewritten by save — only flag user fields.
            user_keys = ("title", "author", "subject", "keywords")
            leftover = [k for k in leftover if k in user_keys]
            if leftover:
                report.failures.append(f"metadata still set: {', '.join(leftover)}")

        if expect_no_attachments and list(doc.embfile_names() or []):
            report.failures.append("attachments still present")

        if forbidden_image_xrefs:
            remaining: set[int] = set()
            for page in doc:
                for img in page.get_images(full=True):
                    remaining.add(int(img[0]))
            leaked = sorted(set(forbidden_image_xrefs) & remaining)
            if leaked:
                report.failures.append(f"forbidden image xrefs still present: {leaked}")

        # Drawings that still sit inside redacted areas are checked by callers
        # that pass absent_text / image xrefs; keep this inspector focused.
    finally:
        doc.close()
    return report


def verify_argv() -> list[str]:
    """Argv that starts the redaction verifier in a fresh interpreter / frozen exe."""
    if getattr(sys, "frozen", False):
        return [sys.executable, REDACT_VERIFY_FLAG, "--verify-json"]
    return [sys.executable, "-m", "pagedrop.core.redact", "--verify-json"]


def verify_redacted_pdf_fresh_process(
    path: str | Path,
    *,
    absent_text: Sequence[str] = (),
    password: str | None = None,
    expect_no_redact_annots: bool = True,
    expect_empty_metadata: bool = False,
    expect_no_attachments: bool = False,
    forbidden_image_xrefs: Sequence[int] = (),
    timeout: float = 60.0,
) -> RedactionVerifyReport:
    """Re-open *path* in a fresh interpreter and run ``inspect_redaction_result``."""
    payload = {
        "path": str(Path(path).resolve()),
        "absent_text": list(absent_text),
        "password": password,
        "expect_no_redact_annots": expect_no_redact_annots,
        "expect_empty_metadata": expect_empty_metadata,
        "expect_no_attachments": expect_no_attachments,
        "forbidden_image_xrefs": list(forbidden_image_xrefs),
    }
    try:
        proc = subprocess.run(
            verify_argv(),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RedactionVerifyReport(
            failures=[f"fresh-process verifier timed out after {timeout:.0f}s"]
        )
    if proc.returncode not in (0, 2):
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return RedactionVerifyReport(
            failures=[f"fresh-process verifier crashed: {detail}"]
        )
    raw = (proc.stdout or "").strip()
    if not raw:
        return RedactionVerifyReport(
            failures=["fresh-process verifier returned empty stdout"]
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return RedactionVerifyReport(
            failures=[f"fresh-process verifier returned non-JSON: {proc.stdout!r}"]
        )
    if not isinstance(data, dict) or "failures" not in data:
        return RedactionVerifyReport(
            failures=[
                f"fresh-process verifier missing failures key: {proc.stdout!r}"
            ]
        )
    failures = data["failures"]
    if not isinstance(failures, list):
        return RedactionVerifyReport(
            failures=[
                f"fresh-process verifier failures not a list: {proc.stdout!r}"
            ]
        )
    return RedactionVerifyReport(failures=list(failures))


def _delete_quiet(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def redact_pdf(
    source_pdf: str | Path,
    output_path: str | Path,
    regions: Sequence[RedactionRegion],
    *,
    scope: RedactionScope | None = None,
    password: str | None = None,
    extra_absent: Sequence[str] = (),
    verify: bool = True,
    forbidden_image_xrefs: Sequence[int] = (),
) -> Path:
    """Apply *regions*, GC-rewrite to *output_path*, optionally verify.

    In-process open/apply/GC-save/close holds ``FITZ_LOCK``. Fresh-process
    verification runs outside the lock. On verification failure the output
    file is deleted and ``RedactionVerifyError`` is raised — no promoted
    redacted copy remains. The source file is never modified.
    """
    source = Path(source_pdf)
    output = Path(output_path)
    reject_source_overwrite(output, source)
    if not regions:
        raise RedactionError("No redaction regions to apply")

    effective_scope = scope or RedactionScope()
    secrets: list[str] = []
    # In-process MuPDF only — fresh-process verify stays outside the lock.
    with FITZ_LOCK:
        doc = open_pdf(str(source), password=password)
        try:
            secrets = _secrets_under_regions(doc, regions)
            for raw in extra_absent:
                secret = _normalize_secret(raw)
                if secret and secret not in secrets:
                    secrets.append(secret)
            _apply_regions(doc, regions)
            _apply_scope(doc, effective_scope)
            _gc_save(doc, output)
        except Exception:
            _delete_quiet(output)
            raise
        finally:
            doc.close()

    if not verify:
        return output

    report = verify_redacted_pdf_fresh_process(
        output,
        absent_text=secrets,
        password=password,
        expect_no_redact_annots=True,
        expect_empty_metadata=effective_scope.strip_metadata,
        expect_no_attachments=effective_scope.remove_attachments,
        forbidden_image_xrefs=forbidden_image_xrefs,
    )
    if not report.ok:
        _delete_quiet(output)
        raise RedactionVerifyError(
            "Redaction verification failed; no redacted copy was produced. "
            + "; ".join(report.failures),
            failures=report.failures,
        )
    return output


def redact_document(
    doc: fitz.Document,
    output_path: str | Path,
    regions: Sequence[RedactionRegion],
    *,
    scope: RedactionScope | None = None,
    extra_absent: Sequence[str] = (),
    verify: bool = True,
    forbidden_image_xrefs: Sequence[int] = (),
    password: str | None = None,
) -> Path:
    """Apply redaction to an already-open assembled document, then GC-save.

    Caller owns *doc* (not closed here). Used when Save As has already built a
    logical page list in memory. Verification still uses a fresh process.
    """
    output = Path(output_path)
    if not regions:
        raise RedactionError("No redaction regions to apply")
    effective_scope = scope or RedactionScope()
    secrets = _secrets_under_regions(doc, regions)
    for raw in extra_absent:
        secret = _normalize_secret(raw)
        if secret and secret not in secrets:
            secrets.append(secret)
    try:
        _apply_regions(doc, regions)
        _apply_scope(doc, effective_scope)
        _gc_save(doc, output)
    except Exception:
        _delete_quiet(output)
        raise

    if not verify:
        return output

    report = verify_redacted_pdf_fresh_process(
        output,
        absent_text=secrets,
        password=password,
        expect_no_redact_annots=True,
        expect_empty_metadata=effective_scope.strip_metadata,
        expect_no_attachments=effective_scope.remove_attachments,
        forbidden_image_xrefs=forbidden_image_xrefs,
    )
    if not report.ok:
        _delete_quiet(output)
        raise RedactionVerifyError(
            "Redaction verification failed; no redacted copy was produced. "
            + "; ".join(report.failures),
            failures=report.failures,
        )
    return output


def redact_edit_model(
    model: PdfEditModel,
    output_path: str | Path,
    regions: Sequence[RedactionRegion],
    *,
    markup: Sequence[MarkupEntry] | None = None,
    passwords: Mapping[str, str] | None = None,
    scope: RedactionScope | None = None,
    extra_absent: Sequence[str] = (),
    verify: bool = True,
    forbidden_image_xrefs: Sequence[int] = (),
) -> Path:
    """Write *model* logical pages, apply non-redaction *markup*, then redact.

    Stages through a temp file next to *output_path*, verifies, then replaces
    the destination. Source paths on the model are never modified.
    """
    from pagedrop.core.pdf_writer import write_pdf

    output = Path(output_path)
    for i in range(model.logical_count()):
        reject_source_overwrite(output, model.page_at(i).source_path)
    if model.original_path:
        reject_source_overwrite(output, model.original_path)
    if not regions:
        raise RedactionError("No redaction regions to apply")

    staged = output.with_name(f".{output.stem}.redact-stage{output.suffix}")
    _delete_quiet(staged)
    try:
        # Assemble pages + ordinary markup without redaction (skipped by apply).
        write_pdf(model, str(staged), markup=markup, passwords=passwords)
        return redact_pdf(
            staged,
            output,
            regions,
            scope=scope,
            extra_absent=extra_absent,
            verify=verify,
            forbidden_image_xrefs=forbidden_image_xrefs,
        )
    finally:
        _delete_quiet(staged)


def _cli_verify() -> int:
    """Read verify payload from stdin; print JSON report; exit 0/2."""
    payload = json.loads(sys.stdin.read() or "{}")
    report = inspect_redaction_result(
        payload["path"],
        absent_text=payload.get("absent_text") or (),
        password=payload.get("password"),
        expect_no_redact_annots=bool(payload.get("expect_no_redact_annots", True)),
        expect_empty_metadata=bool(payload.get("expect_empty_metadata", False)),
        expect_no_attachments=bool(payload.get("expect_no_attachments", False)),
        forbidden_image_xrefs=payload.get("forbidden_image_xrefs") or (),
    )
    print(json.dumps({"failures": report.failures}))
    return 0 if report.ok else 2


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "--verify-json":
        return _cli_verify()
    print("Usage: python -m pagedrop.core.redact --verify-json < payload.json", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
