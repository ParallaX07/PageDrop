from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core import compare_report, pdf_tools
from pagedrop.core.jobs import CancelToken, JobCancelledError


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(path: Path, pages: list[dict]) -> Path:
    document = fitz.open()
    try:
        for spec in pages:
            page = document.new_page(width=spec["size"][0], height=spec["size"][1])
            if spec.get("text"):
                page.insert_text(spec.get("pos", (24, 48)), spec["text"], fontsize=16)
            if spec.get("content"):
                page.draw_rect(fitz.Rect(20, 20, 80, 60), fill=(0.2, 0.4, 0.8), color=None)
            if spec.get("crop"):
                page.set_cropbox(fitz.Rect(*spec["crop"]))
            if spec.get("rotation"):
                page.set_rotation(spec["rotation"])
        document.save(str(path))
    finally:
        document.close()
    return path


def _write(
    original_path: Path,
    revised_path: Path,
    output_path: Path,
    *,
    layout: compare_report.CompareLayout,
    include_summary: bool = False,
    include_revisions: bool = False,
) -> pdf_tools.CompareReport:
    report = pdf_tools.compare_pdf_text_diff(str(original_path), str(revised_path))
    original = fitz.open(str(original_path))
    revised = fitz.open(str(revised_path))
    try:
        compare_report.write_compare_report(
            original,
            revised,
            report,
            original_path.name,
            revised_path.name,
            output_path,
            layout=layout,
            include_summary=include_summary,
            include_revisions=include_revisions,
        )
    finally:
        original.close()
        revised.close()
    return report


def test_split_report_preserves_native_pages_text_and_sources(tmp_path: Path) -> None:
    original_path = _make_pdf(
        tmp_path / "original.pdf",
        [
            {"size": (200, 100), "text": "before", "rotation": 90},
            {"size": (300, 140), "crop": (10, 8, 260, 120)},
        ],
    )
    revised_path = _make_pdf(
        tmp_path / "revised.pdf",
        [
            {"size": (200, 100), "text": "after", "rotation": 90},
            {"size": (180, 110), "content": True},
            {"size": (150, 90), "text": "added"},
        ],
    )
    original_hash = _hash(original_path)
    revised_hash = _hash(revised_path)
    output_path = tmp_path / "split.pdf"

    report = _write(original_path, revised_path, output_path, layout="split")

    original = fitz.open(str(original_path))
    revised = fitz.open(str(revised_path))
    output = fitz.open(str(output_path))
    try:
        assert len(output) == 3
        assert output[0].rect.width == pytest.approx(
            original[0].rect.width
            + compare_report._GUTTER_PT
            + revised[0].rect.width
        )
        assert output[0].rect.height == pytest.approx(
            compare_report._HEADER_PT
            + max(original[0].rect.height, revised[0].rect.height)
            + compare_report._FOOTER_PT
        )
        assert output[0].search_for("before")
        assert output[0].search_for("after")
        assert output[1].search_for("No extractable text on this page")
        assert output[2].search_for("No corresponding page")
        assert output[2].search_for("added")
        assert [entry[2] for entry in output.get_toc()] == [1, 2, 3]
        assert output.get_toc()[0][1] == "Original 1 / Revised 1"
        assert report.modified_count == 1
        fills = [drawing["fill"] for drawing in output[0].get_drawings()]
        assert any(fill[0] > 0.7 and fill[1] < 0.3 for fill in fills if fill)
        assert any(fill[1] > 0.4 and fill[0] < 0.3 for fill in fills if fill)
        change = next(change for change in report.changes if change.kind == "modified")
        expected = compare_report.transform_rect(
            fitz.Rect(change.rects_a[0]) * original[0].rotation_matrix,
            compare_report.displayed_page_rect(original[0]),
            fitz.Rect(0, compare_report._HEADER_PT, original[0].rect.width, compare_report._HEADER_PT + original[0].rect.height),
        )
        assert any(
            drawing["rect"] == expected
            for drawing in output[0].get_drawings()
            if drawing.get("fill") and drawing["fill"][0] > 0.7
        )
    finally:
        original.close()
        revised.close()
        output.close()

    assert _hash(original_path) == original_hash
    assert _hash(revised_path) == revised_hash


def test_alternating_report_orders_pages_and_places_highlights(tmp_path: Path) -> None:
    original_path = _make_pdf(
        tmp_path / "original.pdf",
        [{"size": (220, 130), "text": "old"}],
    )
    revised_path = _make_pdf(
        tmp_path / "revised.pdf",
        [
            {"size": (180, 100), "text": "new"},
            {"size": (160, 90), "text": "second"},
        ],
    )
    output_path = tmp_path / "alternating.pdf"
    original_hash = _hash(original_path)
    revised_hash = _hash(revised_path)

    _write(original_path, revised_path, output_path, layout="alternating")

    output = fitz.open(str(output_path))
    try:
        assert len(output) == 4
        assert output[0].search_for("old")
        assert output[1].search_for("new")
        assert output[2].search_for("No corresponding page")
        assert output[3].search_for("second")
        assert [entry[1] for entry in output.get_toc()] == [
            "Original 1",
            "Revised 1",
            "Original 2 — No corresponding page",
            "Revised 2",
        ]
        assert output[0].rect.width == pytest.approx(220)
        assert output[1].rect.width == pytest.approx(180)
        assert output[2].rect.width == pytest.approx(160)
    finally:
        output.close()
    assert _hash(original_path) == original_hash
    assert _hash(revised_path) == revised_hash


def test_unchanged_report_includes_all_pages_and_empty_state(tmp_path: Path) -> None:
    original_path = _make_pdf(
        tmp_path / "original.pdf",
        [{"size": (200, 100), "text": "same"}, {"size": (120, 180)}],
    )
    revised_path = _make_pdf(
        tmp_path / "revised.pdf",
        [{"size": (200, 100), "text": "same"}, {"size": (120, 180)}],
    )
    output_path = tmp_path / "unchanged.pdf"

    report = _write(
        original_path,
        revised_path,
        output_path,
        layout="split",
        include_summary=True,
        include_revisions=True,
    )

    output = fitz.open(str(output_path))
    try:
        assert not report.changes
        assert len(output) == 2
        assert all(page.search_for("No text changes detected") for page in output)
        assert output[0].search_for("same")
        assert output[1].search_for("Text comparison, matched by page number")
    finally:
        output.close()


def test_cancel_preserves_existing_output_and_cleans_stage(tmp_path: Path) -> None:
    original_path = _make_pdf(tmp_path / "original.pdf", [{"size": (200, 100), "text": "A"}])
    revised_path = _make_pdf(tmp_path / "revised.pdf", [{"size": (200, 100), "text": "B"}])
    output_path = tmp_path / "report.pdf"
    output_path.write_bytes(b"existing report")
    token = CancelToken()
    token.cancel()
    report = pdf_tools.compare_pdf_text_diff(str(original_path), str(revised_path))
    original = fitz.open(str(original_path))
    revised = fitz.open(str(revised_path))
    try:
        with pytest.raises(JobCancelledError):
            compare_report.write_compare_report(
                original,
                revised,
                report,
                original_path.name,
                revised_path.name,
                output_path,
                cancel=token,
            )
    finally:
        original.close()
        revised.close()
    assert output_path.read_bytes() == b"existing report"
    assert not list(tmp_path.glob(".report.pdf.*.stage"))
