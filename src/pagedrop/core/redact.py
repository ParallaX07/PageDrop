"""Security-grade PDF redaction (Phase 30).

Mark regions → apply redaction annotations → full non-incremental
garbage-collecting rewrite to a **new** path → verify in a **fresh process**.
Visual black boxes alone never pass. Failed verification deletes the staged
output so no promoted redacted copy remains.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fitz

from pagedrop.core.backends.process_tree import kill_process_tree, popen_owned
from pagedrop.core.jobs.cancel import CancelToken, check_cancel
from pagedrop.core.jobs.errors import JobCancelledError, JobError
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


@dataclass
class _VerifyPlan:
    """What the fresh-process verifier must check, captured before redaction."""

    regions: list[dict[str, Any]] = field(default_factory=list)
    raw_scan_text: list[str] = field(default_factory=list)
    # Output page -> image pixel digest -> copies allowed to remain on the page.
    image_digests: dict[int, dict[str, int]] = field(default_factory=dict)


def _rect_hit(a: fitz.Rect, b: fitz.Rect) -> bool:
    return not (a & b).is_empty


def _appears_outside_regions(
    doc: fitz.Document,
    secret: str,
    rects_by_page: Mapping[int, Sequence[fitz.Rect]],
) -> bool:
    """True if *secret* is found anywhere not covered by a region (pre-redaction)."""
    for index, page in enumerate(doc):
        if secret not in _normalize_secret(page.get_text("text") or ""):
            continue
        try:
            hits = page.search_for(secret)
        except Exception:
            return False  # Fail closed: keep the stricter raw scan.
        rects = rects_by_page.get(index, ())
        if any(not any(_rect_hit(h, r) for r in rects) for h in hits):
            return True
    return False


def _text_in_rect(page: fitz.Page, rect: fitz.Rect) -> str:
    """Text of the characters whose bbox centre lies inside *rect*.

    Glyphs that the rectangle only clips are kept by MuPDF's redaction, so they
    are neither captured as secrets nor reported as remaining.
    """
    lines: list[str] = []
    for block in page.get_text("rawdict", clip=rect).get("blocks", ()):
        for line in block.get("lines", ()):
            chars: list[str] = []
            for span in line.get("spans", ()):
                for ch in span.get("chars", ()):
                    x0, y0, x1, y1 = ch["bbox"]
                    if rect.x0 <= (x0 + x1) / 2 < rect.x1 and rect.y0 <= (y0 + y1) / 2 < rect.y1:
                        chars.append(ch["c"])
            lines.append("".join(chars))
    return _normalize_secret(" ".join(lines))


def _covered_pixels_uniform(
    doc: fitz.Document, info: Mapping[str, Any], area: fitz.Rect
) -> bool:
    """True if the image pixels under page-space *area* are a single colour.

    Blanking such pixels changes nothing, so they hide no information. Any
    doubt (inline image, decode failure) counts as not uniform.
    """
    xref = int(info.get("xref") or 0)
    if xref <= 0:
        return False
    try:
        pix = fitz.Pixmap(doc, xref)
        inverse = ~fitz.Matrix(*info["transform"])
        corners = [
            fitz.Point(x, y) * inverse
            for x in (area.x0, area.x1)
            for y in (area.y0, area.y1)
        ]
        xs = [p.x * pix.width for p in corners]
        ys = [p.y * pix.height for p in corners]
        clip = fitz.IRect(
            math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys))
        ) & pix.irect
        if clip.is_empty:
            return False
        ratio, _colour = pix.color_topusage(clip)
        return ratio >= 1.0
    except Exception:
        return False


def _region_image_digests(
    doc: fitz.Document, page: fitz.Page, rects: Sequence[fitz.Rect]
) -> dict[str, int]:
    """Pixel digest -> copies that may remain, for images the regions will blank.

    Counts, not sets: a logo drawn twice with one copy under a region must
    leave exactly one copy. Pixel digests (not raw stream bytes) survive the
    recompressing GC save. Images whose covered pixels are one colour are skipped.
    """
    total: dict[str, int] = {}
    touched: dict[str, int] = {}
    for info in page.get_image_info(hashes=True, xrefs=True):
        digest = bytes(info.get("digest") or b"").hex()
        if not digest:
            continue
        total[digest] = total.get(digest, 0) + 1
        bbox = fitz.Rect(info["bbox"])
        areas = [bbox & r for r in rects if _rect_hit(bbox, r)]
        if any(not _covered_pixels_uniform(doc, info, area) for area in areas):
            touched[digest] = touched.get(digest, 0) + 1
    return {d: total[d] - n for d, n in touched.items()}


def _plan_verification(
    doc: fitz.Document, regions: Sequence[RedactionRegion]
) -> _VerifyPlan:
    """Capture per-region secrets, raw-scan candidates and image digests."""
    plan = _VerifyPlan()
    rects_by_page: dict[int, list[fitz.Rect]] = {}
    for region in regions:
        if region.page_index < 0 or region.page_index >= doc.page_count:
            raise RedactionError(
                f"Page index {region.page_index} out of range ({doc.page_count} pages)"
            )
        rects_by_page.setdefault(region.page_index, []).append(fitz.Rect(*region.rect))

    scan_candidates: list[str] = []
    for region in regions:
        page = doc[region.page_index]
        captured = _text_in_rect(page, fitz.Rect(*region.rect))
        secrets: list[str] = []
        for raw in (captured, *region.expected_absent):
            secret = _normalize_secret(raw)
            if len(secret) >= 2 and secret not in secrets:
                secrets.append(secret)
        plan.regions.append(
            {"page": region.page_index, "rect": list(region.rect), "secrets": secrets}
        )
        scan_candidates.extend(s for s in secrets if len(s) >= 4)

    for secret in dict.fromkeys(scan_candidates):
        if not _appears_outside_regions(doc, secret, rects_by_page):
            plan.raw_scan_text.append(secret)

    for index, rects in rects_by_page.items():
        digests = _region_image_digests(doc, doc[index], rects)
        if digests:
            plan.image_digests[index] = digests
    return plan


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
    regions: Sequence[Mapping[str, Any]] = (),
    raw_scan_text: Sequence[str] = (),
    forbidden_image_digests: Mapping[int, Mapping[str, int]] | None = None,
) -> RedactionVerifyReport:
    """In-process inspection used by the fresh-process verifier.

    ``absent_text`` must be gone everywhere (text, search and raw bytes).
    ``regions`` (``page``, ``rect``, ``secrets``) are checked only where they
    were redacted, so the same text elsewhere does not fail. ``raw_scan_text``
    is scanned in the raw bytes only, and ``forbidden_image_digests`` maps an
    output page to ``{pixel digest: copies allowed to remain}``.
    """
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

        for secret in raw_scan_text:
            leaked = _file_contains_any(path_obj, _secret_byte_forms(secret))
            if leaked is not None:
                report.failures.append(
                    f"raw file bytes still contain {secret!r} ({leaked!r})"
                )

        for spec in regions:
            number = int(spec["page"])
            if not 0 <= number < doc.page_count:
                report.failures.append(f"redaction region page {number} out of range")
                continue
            page = doc[number]
            rect = fitz.Rect(*spec["rect"])
            left = _text_in_rect(page, rect)
            if left:
                report.failures.append(
                    f"text remains under redaction region on page {number}: {left!r}"
                )
            for secret in spec.get("secrets") or ():
                try:
                    hits = page.search_for(secret)
                except Exception as exc:
                    # Fail closed: search errors are not "no hits".
                    report.failures.append(
                        f"search_for failed for {secret!r}: {type(exc).__name__}"
                    )
                    continue
                if any(_rect_hit(hit, rect) for hit in hits):
                    report.failures.append(
                        f"search_for still hits {secret!r} in redaction region on page {number}"
                    )

        for number, digests in (forbidden_image_digests or {}).items():
            number = int(number)
            if not 0 <= number < doc.page_count:
                report.failures.append(f"image check page {number} out of range")
                continue
            counts: dict[str, int] = {}
            for info in doc[number].get_image_info(hashes=True):
                digest = bytes(info.get("digest") or b"").hex()
                counts[digest] = counts.get(digest, 0) + 1
            if any(counts.get(d, 0) > int(allowed) for d, allowed in digests.items()):
                report.failures.append(f"redacted image still present on page {number}")

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
    regions: Sequence[Mapping[str, Any]] = (),
    raw_scan_text: Sequence[str] = (),
    forbidden_image_digests: Mapping[int, Mapping[str, int]] | None = None,
    timeout: float = 60.0,
    cancel: CancelToken | None = None,
) -> RedactionVerifyReport:
    """Re-open *path* in a fresh interpreter and run ``inspect_redaction_result``.

    Cancelling (or timing out) kills the owned verifier process tree; cancel
    raises ``JobCancelledError``.
    """
    payload = {
        "path": str(Path(path).resolve()),
        "absent_text": list(absent_text),
        "password": password,
        "expect_no_redact_annots": expect_no_redact_annots,
        "expect_empty_metadata": expect_empty_metadata,
        "expect_no_attachments": expect_no_attachments,
        "forbidden_image_xrefs": list(forbidden_image_xrefs),
        "regions": list(regions),
        "raw_scan_text": list(raw_scan_text),
        "forbidden_image_digests": {
            str(k): dict(v) for k, v in (forbidden_image_digests or {}).items()
        },
    }
    check_cancel(cancel)
    try:
        proc = popen_owned(verify_argv())
    except OSError as exc:
        return RedactionVerifyReport(
            failures=[f"could not start fresh-process verifier: {exc}"]
        )
    deadline = time.monotonic() + timeout
    pending_input: str | None = json.dumps(payload)
    try:
        while True:
            check_cancel(cancel)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            try:
                stdout, stderr = proc.communicate(pending_input, timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                pending_input = None
    except (JobCancelledError, subprocess.TimeoutExpired) as exc:
        kill_process_tree(proc.pid)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if isinstance(exc, JobCancelledError):
            raise
        return RedactionVerifyReport(
            failures=[f"fresh-process verifier timed out after {timeout:.0f}s"]
        )
    except BaseException:
        kill_process_tree(proc.pid)
        raise
    if proc.returncode not in (0, 2):
        detail = (stderr or stdout or "").strip() or f"exit {proc.returncode}"
        return RedactionVerifyReport(
            failures=[f"fresh-process verifier crashed: {detail}"]
        )
    raw = (stdout or "").strip()
    if not raw:
        return RedactionVerifyReport(
            failures=["fresh-process verifier returned empty stdout"]
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return RedactionVerifyReport(
            failures=[f"fresh-process verifier returned non-JSON: {stdout!r}"]
        )
    if not isinstance(data, dict) or "failures" not in data:
        return RedactionVerifyReport(
            failures=[
                f"fresh-process verifier missing failures key: {stdout!r}"
            ]
        )
    failures = data["failures"]
    if not isinstance(failures, list):
        return RedactionVerifyReport(
            failures=[
                f"fresh-process verifier failures not a list: {stdout!r}"
            ]
        )
    return RedactionVerifyReport(failures=list(failures))


def _delete_quiet(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _verify_or_discard(
    output: Path,
    plan: _VerifyPlan,
    extra_absent: Sequence[str],
    scope: RedactionScope,
    *,
    password: str | None,
    forbidden_image_xrefs: Sequence[int],
    cancel: CancelToken | None,
) -> None:
    """Verify *output* in a fresh process; delete it on failure, cancel or error."""
    absent: list[str] = []
    for raw in extra_absent:
        secret = _normalize_secret(raw)
        if secret and secret not in absent:
            absent.append(secret)
    try:
        report = verify_redacted_pdf_fresh_process(
            output,
            absent_text=absent,
            password=password,
            expect_no_redact_annots=True,
            expect_empty_metadata=scope.strip_metadata,
            expect_no_attachments=scope.remove_attachments,
            forbidden_image_xrefs=forbidden_image_xrefs,
            regions=plan.regions,
            raw_scan_text=plan.raw_scan_text,
            forbidden_image_digests=plan.image_digests,
            cancel=cancel,
        )
    except BaseException:
        _delete_quiet(output)
        raise
    if not report.ok:
        _delete_quiet(output)
        raise RedactionVerifyError(
            "Redaction verification failed; no redacted copy was produced. "
            + "; ".join(report.failures),
            failures=report.failures,
        )


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
    cancel: CancelToken | None = None,
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
    # In-process MuPDF only — fresh-process verify stays outside the lock.
    with FITZ_LOCK:
        doc = open_pdf(str(source), password=password)
        try:
            plan = _plan_verification(doc, regions)
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

    _verify_or_discard(
        output,
        plan,
        extra_absent,
        effective_scope,
        password=password,
        forbidden_image_xrefs=forbidden_image_xrefs,
        cancel=cancel,
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
    cancel: CancelToken | None = None,
) -> Path:
    """Apply redaction to an already-open assembled document, then GC-save.

    Caller owns *doc* (not closed here). Used when Save As has already built a
    logical page list in memory. Verification still uses a fresh process.
    """
    output = Path(output_path)
    if not regions:
        raise RedactionError("No redaction regions to apply")
    effective_scope = scope or RedactionScope()
    plan = _plan_verification(doc, regions)
    try:
        _apply_regions(doc, regions)
        _apply_scope(doc, effective_scope)
        _gc_save(doc, output)
    except Exception:
        _delete_quiet(output)
        raise

    if not verify:
        return output

    _verify_or_discard(
        output,
        plan,
        extra_absent,
        effective_scope,
        password=password,
        forbidden_image_xrefs=forbidden_image_xrefs,
        cancel=cancel,
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
    cancel: CancelToken | None = None,
) -> Path:
    """Write *model* logical pages, apply non-redaction *markup*, then redact.

    Stages through a temp file next to *output_path*, verifies, then replaces
    the destination. Source paths on the model are never modified.
    """
    from pagedrop.core.pdf_writer import write_pdf

    output = Path(output_path)
    reject_source_overwrite(output, *model.source_paths())
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
            cancel=cancel,
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
        regions=payload.get("regions") or (),
        raw_scan_text=payload.get("raw_scan_text") or (),
        forbidden_image_digests=payload.get("forbidden_image_digests") or None,
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
