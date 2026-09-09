from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

import fitz

from pagedrop.core.pdf_editor import PageRef
from pagedrop.core.jobs.cancel import CancelToken, check_cancel
from pagedrop.core.jobs.staging import JobStaging
from pagedrop.core.pdf_loader import open_pdf
from pagedrop.core.pdf_service import FITZ_LOCK
from pagedrop.core.pdf_writer import append_page_refs
from pagedrop.utils.temp_manager import TempManager


def plan_folder_export_paths(
    output_dir: str | Path, base_name: str, page_numbers: list[int]
) -> list[Path]:
    """Reserve stable, collision-free names for one folder-export batch."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    reserved = {path.name for path in directory.iterdir()}
    paths: list[Path] = []
    for page_number in page_numbers:
        name = f"{base_name}_page_{page_number:04d}.pdf"
        candidate = directory / name
        suffix = 2
        while candidate.name in reserved:
            candidate = directory / f"{Path(name).stem}_{suffix}.pdf"
            suffix += 1
        reserved.add(candidate.name)
        paths.append(candidate)
    return paths


def _validate_single_page_pdf(path: Path) -> None:
    with FITZ_LOCK:
        document = fitz.open(str(path))
        try:
            if document.page_count != 1:
                raise ValueError(f"Staged export is not a single-page PDF: {path}")
        finally:
            document.close()


def extract_page_refs_to_folder(
    refs: list[PageRef],
    output_dir: str | Path,
    base_name: str,
    *,
    passwords: Mapping[str, str] | None = None,
    cancel: CancelToken | None = None,
    temp_manager: TempManager | None = None,
) -> list[Path]:
    """Stage, validate, and exclusively publish one PDF per ref in order."""
    if not refs:
        return []
    destinations = plan_folder_export_paths(
        output_dir, base_name, list(range(1, len(refs) + 1))
    )
    staging = JobStaging(temp_manager or TempManager())
    docs: dict[str, fitz.Document] = {}
    staged: list[Path] = []
    promoted: list[Path] = []
    try:
        for index, ref in enumerate(refs):
            check_cancel(cancel)
            staged_path = staging.stage_file(f"page_{index + 1:04d}.pdf")
            with FITZ_LOCK:
                output = fitz.open()
                try:
                    append_page_refs(output, [ref], docs, passwords)
                    output.save(str(staged_path))
                finally:
                    output.close()
            _validate_single_page_pdf(staged_path)
            staged.append(staged_path)
        for staged_path, destination in zip(staged, destinations, strict=True):
            check_cancel(cancel)
            promoted.append(staging.promote_no_clobber(staged_path, destination))
        return promoted
    except Exception:
        for path in promoted:
            staging.remove_published(path)
        raise
    finally:
        with FITZ_LOCK:
            for document in docs.values():
                document.close()
        staging.cleanup()


def extract_page_refs_to_pdf(
    refs: list[PageRef],
    output_path: str | Path,
    *,
    passwords: Mapping[str, str] | None = None,
) -> Path:
    """Write all *refs* into one multi-page PDF (batched contiguous inserts).

    Use this when a single multi-page file is intended. One-file-per-page drag /
    folder export stays on ``extract_page_refs_to_files``.
    """
    if not refs:
        raise ValueError("No pages to extract")
    out_path = Path(output_path)
    with FITZ_LOCK:
        docs: dict[str, fitz.Document] = {}
        out = fitz.open()
        try:
            append_page_refs(out, refs, docs, passwords)
            out.save(str(out_path))
        finally:
            out.close()
            for doc in docs.values():
                doc.close()
    return out_path


def extract_page_refs_to_files(
    refs: list[PageRef],
    output_dir: Path,
    base_name: str,
    *,
    passwords: Mapping[str, str] | None = None,
) -> list[Path]:
    """Extract pages in *refs* order; output filenames use sequential 1-based indices.

    Each ref is its own single-page PDF (drag / export-to-folder contract). Source
    docs are opened once per path and shared across the loop; ``FITZ_LOCK`` is
    taken per page so thumbs/viewer can interleave mid multi-page extract.
    """
    # ponytail: sync extract before QDrag.exec — file:// URLs need real paths on
    # disk. Large multi-select freezes the GUI for N single-page saves (plus
    # disk I/O). Per-page FITZ_LOCK (O15-style) lets other fitz waiters in
    # between pages; sleep(0.001) after each so this thread does not reacquire
    # before waiters run. Ceiling: still sync on the GUI thread before drag.
    # Upgrade: not async after drag starts (breaks QDrag); if measured pain,
    # stage extracts on a worker *before* starting drag — do not invent a
    # parallel extract pipeline.
    docs: dict[str, fitz.Document] = {}
    out_paths: list[Path] = []
    try:
        for seq, ref in enumerate(refs, start=1):
            out_path = output_dir / f"{base_name}_page_{seq:04d}.pdf"
            with FITZ_LOCK:
                out = fitz.open()
                try:
                    # Single-page file — append_page_refs keeps rotation / password
                    # handling identical to the multi-page extract path.
                    append_page_refs(out, [ref], docs, passwords)
                    out.save(str(out_path))
                    out_paths.append(out_path)
                finally:
                    out.close()
            # Yield so FITZ_LOCK waiters (viewer / thumbs) can acquire between
            # pages — sleep(0) is not enough on CPython.
            time.sleep(0.001)
    finally:
        with FITZ_LOCK:
            for doc in docs.values():
                doc.close()
    return out_paths


def extract_pages_to_files(
    source_pdf: str,
    page_indices: list[int],
    output_dir: Path,
    base_name: str,
    *,
    password: str | None = None,
) -> list[Path]:
    with FITZ_LOCK:
        src = open_pdf(source_pdf, password=password)
        out_paths: list[Path] = []
        try:
            for idx in sorted(page_indices):
                out = fitz.open()
                try:
                    out.insert_pdf(src, from_page=idx, to_page=idx)
                    out_path = output_dir / f"{base_name}_page_{idx + 1:04d}.pdf"
                    out.save(str(out_path))
                    out_paths.append(out_path)
                finally:
                    out.close()
        finally:
            src.close()
    return out_paths
