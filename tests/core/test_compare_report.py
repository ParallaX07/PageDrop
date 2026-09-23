from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core import compare_report, pdf_tools
from pagedrop.core.jobs import CancelToken, JobCancelledError
from tests.fixtures.generate_fixtures import generate_compare_pair


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


@pytest.mark.parametrize("layout", ["split", "alternating"])
@pytest.mark.parametrize(
    ("include_summary", "include_revisions"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_acceptance_matrix_uses_reusable_fitz_fixtures(
    tmp_path: Path,
    layout: compare_report.CompareLayout,
    include_summary: bool,
    include_revisions: bool,
) -> None:
    original_path, revised_path = generate_compare_pair(tmp_path / "fixtures")
    source_hashes = (_hash(original_path), _hash(revised_path))
    report = pdf_tools.compare_pdf_text_diff(str(original_path), str(revised_path))
    output_path = tmp_path / f"acceptance-{layout}-{include_summary}-{include_revisions}.pdf"

    _write(
        original_path,
        revised_path,
        output_path,
        layout=layout,
        include_summary=include_summary,
        include_revisions=include_revisions,
    )

    output = fitz.open(str(output_path))
    try:
        kinds = {change.kind for change in report.changes}
        assert {"deleted", "added", "modified"} <= kinds
        assert report.changed_page_pair_count == 5
        extracted = "\n".join(page.get_text() for page in output)
        assert "Unchanged page" in extracted
        assert "No extractable text on this page" in extracted
        assert "No corresponding page" in extracted
        assert "extra revised page" in extracted
        assert "Shared replace-before" in extracted
        assert "Shared replace-after" in extracted
        titles = [entry[1] for entry in output.get_toc()]
        comparison_count = 8 if layout == "split" else 16
        assert titles[0] == (
            "Original 1 / Revised 1" if layout == "split" else "Original 1"
        )
        placeholder_title = "No Original page" if layout == "split" else "No corresponding page"
        assert any(placeholder_title in title for title in titles[:comparison_count])
        assert titles[comparison_count:] == [
            *(["Summary"] if include_summary else []),
            *(["Revisions"] if include_revisions else []),
        ]
        assert ("Summary" in titles) is include_summary
        assert ("Revisions" in titles) is include_revisions
        if include_summary:
            assert f"Changed page-pair count: {report.changed_page_pair_count}" in extracted
            assert f"Removed groups: {report.deleted_count}" in extracted
            assert f"Added groups: {report.added_count}" in extracted
            assert f"Replaced groups: {report.modified_count}" in extracted
        if include_revisions:
            assert "Before" in extracted
            assert "After" in extracted
            assert all(marker in extracted for marker in ("before", "café", "after", "naïve"))
    finally:
        output.close()

    assert (_hash(original_path), _hash(revised_path)) == source_hashes


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
        assert len(output) == 4
        assert all(page.search_for("No text changes detected") for page in output[:2])
        assert output[0].search_for("same")
        assert output[1].search_for("Text comparison, matched by page number")
        assert output[2].search_for("Summary")
        assert output[3].search_for("Revisions")
        assert [entry[1] for entry in output.get_toc()] == [
            "Original 1 / Revised 1",
            "Original 2 / Revised 2",
            "Summary",
            "Revisions",
        ]
    finally:
        output.close()


@pytest.mark.parametrize("layout", ["split", "alternating"])
@pytest.mark.parametrize(
    ("include_summary", "include_revisions"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_summary_revisions_flags_preserve_section_order(
    tmp_path: Path,
    layout: compare_report.CompareLayout,
    include_summary: bool,
    include_revisions: bool,
) -> None:
    original_path = _make_pdf(
        tmp_path / "original.pdf", [{"size": (220, 130), "text": "before"}]
    )
    revised_path = _make_pdf(
        tmp_path / "revised.pdf", [{"size": (220, 130), "text": "after"}]
    )
    output_path = tmp_path / f"{layout}-{include_summary}-{include_revisions}.pdf"

    _write(
        original_path,
        revised_path,
        output_path,
        layout=layout,
        include_summary=include_summary,
        include_revisions=include_revisions,
    )

    output = fitz.open(str(output_path))
    try:
        comparison_pages = 1 if layout == "split" else 2
        expected_titles = (
            ["Original 1 / Revised 1"]
            if layout == "split"
            else ["Original 1", "Revised 1"]
        )
        if include_summary:
            expected_titles.append("Summary")
        if include_revisions:
            expected_titles.append("Revisions")
        assert len(output.get_toc()) == len(expected_titles)
        assert [entry[1] for entry in output.get_toc()] == expected_titles
        assert len(output) >= comparison_pages + int(include_summary) + int(include_revisions)
        if include_summary:
            assert output[comparison_pages].search_for("Compared page-pair count: 1")
        if include_revisions:
            revisions_page = comparison_pages + int(include_summary)
            assert output[revisions_page].search_for("Revision 1: Replaced")
    finally:
        output.close()


def test_summary_uses_group_and_changed_pair_counts(tmp_path: Path) -> None:
    original_path = _make_pdf(
        tmp_path / "original.pdf",
        [{"size": (240, 140), "text": "one two three four"}, {"size": (240, 140), "text": "same"}],
    )
    revised_path = _make_pdf(
        tmp_path / "revised.pdf",
        [{"size": (240, 140), "text": "one changed three four"}, {"size": (240, 140), "text": "same"}],
    )
    output_path = tmp_path / "summary.pdf"

    report = _write(
        original_path,
        revised_path,
        output_path,
        layout="split",
        include_summary=True,
    )

    output = fitz.open(str(output_path))
    try:
        summary = "\n".join(page.get_text() for page in output)
        assert f"Compared page-pair count: 2" in summary
        assert f"Changed page-pair count: {report.changed_page_pair_count}" in summary
        assert f"Removed groups: {report.deleted_count}" in summary
        assert f"Added groups: {report.added_count}" in summary
        assert f"Replaced groups: {report.modified_count}" in summary
    finally:
        output.close()


def test_revisions_escape_unicode_and_paginate_without_truncation(tmp_path: Path) -> None:
    original_path = _make_pdf(tmp_path / "original.pdf", [{"size": (240, 140)}])
    revised_path = _make_pdf(tmp_path / "revised.pdf", [{"size": (240, 140)}])
    output_path = tmp_path / "revisions.pdf"
    before = "before <tag> & café Ω " * 600
    after = "after <tag> & naïve 世界 " * 600
    report = pdf_tools.CompareReport(
        changes=(
            pdf_tools.CompareChange(
                kind="modified",
                page_a=0,
                page_b=0,
                text="display label is not used",
                before_text=before,
                after_text=after,
            ),
        ),
        page_count_a=1,
        page_count_b=1,
    )
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
            layout="alternating",
            include_revisions=True,
        )
    finally:
        original.close()
        revised.close()

    output = fitz.open(str(output_path))
    try:
        extracted = "\n".join(page.get_text() for page in output)
        assert "before <tag> & café Ω" in extracted
        assert "after <tag> & naïve 世界" in extracted
        assert "Revision 1: Replaced" in extracted
        assert "Revisions (continued)" in extracted
        appendix_text = "\n".join(page.get_text() for page in output[2:])
        assert appendix_text.count("before") == 600
        assert appendix_text.count("after") == 600
        assert len(output) > 3
        assert output.get_toc()[-1][1:] == ["Revisions", 3]
    finally:
        output.close()


def test_many_revisions_flow_across_shared_pages(tmp_path: Path) -> None:
    original_path = _make_pdf(tmp_path / "original.pdf", [{"size": (240, 140)}])
    revised_path = _make_pdf(tmp_path / "revised.pdf", [{"size": (240, 140)}])
    source_hashes = (_hash(original_path), _hash(revised_path))
    output_path = tmp_path / "compact.pdf"
    report = pdf_tools.CompareReport(
        changes=tuple(
            pdf_tools.CompareChange(
                kind="modified",
                page_a=0,
                page_b=0,
                text="",
                before_text=f"old wording {number}",
                after_text=f"new wording {number}",
            )
            for number in range(1, 84)
        ),
        page_count_a=1,
        page_count_b=1,
    )
    with fitz.open(str(original_path)) as original, fitz.open(str(revised_path)) as revised:
        compare_report.write_compare_report(
            original,
            revised,
            report,
            original_path.name,
            revised_path.name,
            output_path,
            include_revisions=True,
        )

    with fitz.open(str(output_path)) as output:
        assert len(output) < 15
        revision_pages = [page.get_text() for page in output[1:]]
        revisions = "\n".join(revision_pages)
        assert "Revision 1: Replaced" in revisions
        assert "Revision 83: Replaced" in revisions
        assert "old wording 83" in revisions
        assert "new wording 83" in revisions
        for number in range(1, 84):
            assert f"Revision {number}: Replaced" in revisions
            assert f"old wording {number}" in revisions
            assert f"new wording {number}" in revisions
        assert output.get_toc()[-1][1:] == ["Revisions", 2]
    assert (_hash(original_path), _hash(revised_path)) == source_hashes


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
