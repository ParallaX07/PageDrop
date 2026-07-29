from __future__ import annotations

import hashlib
import threading
from pathlib import Path
import zipfile

import fitz
import pytest

from pagedrop.core import pdf_tools
from pagedrop.core.jobs import (
    CancelToken,
    JobCancelledError,
    JobSpec,
    SerializedJobRunner,
)
from pagedrop.core.organize_jobs import register_organize_handlers
from pagedrop.utils.temp_manager import TempManager


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_text_pdf(
    path: Path,
    *,
    page_texts: list[str],
    page_size: tuple[float, float] = (200, 200),
    text_pos: tuple[float, float] | None = (50, 80),
) -> Path:
    doc = fitz.open()
    try:
        w, h = page_size
        for text in page_texts:
            page = doc.new_page(width=w, height=h)
            if text_pos is not None:
                x, y = text_pos
            else:
                x, y = (w / 2.0, h / 2.0)
            page.insert_text((x, y), text, fontsize=18)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _make_single_page_with_two_labels(
    path: Path,
    *,
    page_size: tuple[float, float] = (200, 200),
    left_label: str,
    right_label: str,
    left_pos: tuple[float, float],
    right_pos: tuple[float, float],
) -> Path:
    doc = fitz.open()
    try:
        w, h = page_size
        page = doc.new_page(width=w, height=h)
        page.insert_text(left_pos, left_label, fontsize=18)
        page.insert_text(right_pos, right_label, fontsize=18)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _make_single_page_with_quadrant_labels(
    path: Path,
    *,
    page_size: tuple[float, float] = (200, 200),
    tl: str,
    br: str,
) -> Path:
    doc = fitz.open()
    try:
        w, h = page_size
        page = doc.new_page(width=w, height=h)
        page.insert_text((50, 50), tl, fontsize=18)
        page.insert_text((150, 150), br, fontsize=18)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_split_extract_ranges_to_folder(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_text_pdf(src, page_texts=[f"P{i}" for i in range(6)], page_size=(200, 200))
    source_hash = _file_hash(src)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out_paths = pdf_tools.extract_ranges_to_folder(
        str(src),
        [(0, 1), (2, 5)],
        out_dir,
        base_name="doc",
    )

    assert [p.name for p in out_paths] == ["doc_range_0001-0002.pdf", "doc_range_0003-0006.pdf"]
    assert _file_hash(src) == source_hash

    first = fitz.open(str(out_paths[0]))
    try:
        assert first.page_count == 2
        assert first[0].search_for("P0")
        assert first[1].search_for("P1")
    finally:
        first.close()

    second = fitz.open(str(out_paths[1]))
    try:
        assert second.page_count == 4
        assert second[0].search_for("P2")
        assert second[-1].search_for("P5")
    finally:
        second.close()


def test_alternate_pdfs_page_order(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _make_text_pdf(a, page_texts=["A0", "A1", "A2"], page_size=(200, 200))
    _make_text_pdf(b, page_texts=["B0", "B1", "B2"], page_size=(200, 200))

    out = tmp_path / "alt.pdf"
    pdf_tools.alternate_pdfs(str(a), str(b), str(out), start_with_a=True)

    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 6
        expected = ["A0", "B0", "A1", "B1", "A2", "B2"]
        for idx, label in enumerate(expected):
            assert doc[idx].search_for(label), f"missing {label} on page {idx}"
    finally:
        doc.close()


def test_reverse_pages_and_add_blank(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_text_pdf(src, page_texts=["R0", "R1", "R2"], page_size=(200, 200))
    source_hash = _file_hash(src)

    out = tmp_path / "rev.pdf"
    pdf_tools.reverse_pdf_pages(str(src), str(out), add_blank_page=True)

    assert _file_hash(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 4
        assert doc[0].search_for("R2")
        assert doc[1].search_for("R1")
        assert doc[2].search_for("R0")
        assert doc[3].get_text().strip() == ""
    finally:
        doc.close()


def test_n_up_layout_row_major(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_text_pdf(src, page_texts=["N0", "N1", "N2", "N3"], page_size=(200, 200), text_pos=(20, 20))
    source_hash = _file_hash(src)

    out = tmp_path / "nup.pdf"
    pdf_tools.n_up_pdf(str(src), str(out), rows=2, cols=2, margin_pt=0.0)

    assert _file_hash(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 1
        page = doc[0]
        w = page.rect.width
        h = page.rect.height
        cell_w = w / 2.0
        cell_h = h / 2.0

        expected_cells = {
            "N0": (0, 0),
            "N1": (1, 0),
            "N2": (0, 1),
            "N3": (1, 1),
        }

        for label, (col, row) in expected_cells.items():
            rects = page.search_for(label)
            assert rects, f"missing {label}"
            r = rects[0]
            cx = (r.x0 + r.x1) / 2.0
            cy = (r.y0 + r.y1) / 2.0
            assert col * cell_w <= cx <= (col + 1) * cell_w
            assert row * cell_h <= cy <= (row + 1) * cell_h
    finally:
        doc.close()


def test_divide_vertical_left_right(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_single_page_with_two_labels(
        src,
        left_label="LEFT",
        right_label="RIGHT",
        left_pos=(40, 80),
        # Keep the text fully inside the page so `search_for()` can index it.
        right_pos=(140, 80),
        page_size=(200, 200),
    )

    out = tmp_path / "div.pdf"
    pdf_tools.divide_pdf_pages(str(src), str(out), direction="vertical")

    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 2
        assert doc[0].search_for("LEFT")
        assert not doc[0].search_for("RIGHT")
        assert doc[1].search_for("RIGHT")
        assert not doc[1].search_for("LEFT")
    finally:
        doc.close()


def test_posterize_quadrants(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_single_page_with_quadrant_labels(src, tl="TL", br="BR", page_size=(200, 200))

    out = tmp_path / "post.pdf"
    pdf_tools.posterize_pdf(str(src), str(out), rows=2, cols=2)

    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 4
        # posterize order: r0c0, r0c1, r1c0, r1c1
        assert doc[0].search_for("TL")
        assert not doc[1].search_for("TL")
        assert doc[3].search_for("BR")
        assert not doc[2].search_for("BR")
    finally:
        doc.close()


def test_combine_to_single_long_page(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_text_pdf(
        src,
        page_texts=["FIRST", "SECOND"],
        page_size=(200, 200),
        text_pos=(20, 20),
    )

    out = tmp_path / "long.pdf"
    pdf_tools.combine_pages_to_single_long(str(src), str(out))

    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 1
        page = doc[0]
        rects_first = page.search_for("FIRST")
        rects_second = page.search_for("SECOND")
        assert rects_first
        assert rects_second
        assert rects_first[0].y0 < rects_second[0].y0
    finally:
        doc.close()


def test_normalize_page_size_fit(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=100)
        page.insert_text((20, 50), "X", fontsize=18)
        doc.save(str(src))
    finally:
        doc.close()

    out = tmp_path / "norm.pdf"
    pdf_tools.normalize_pdf_page_size(str(src), str(out), 300, 300, strategy="fit", margins_pt=0.0)

    out_doc = fitz.open(str(out))
    try:
        assert out_doc.page_count == 1
        rect = out_doc[0].rect
        assert abs(rect.width - 300) < 0.5
        assert abs(rect.height - 300) < 0.5
        assert out_doc[0].search_for("X")
    finally:
        out_doc.close()


def test_attachments_add_extract_remove(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = _file_hash(src)

    out_added = tmp_path / "with_attach.pdf"
    pdf_tools.attachment_add(
        str(src),
        str(out_added),
        name="note.txt",
        data=b"hello",
        filename="note.txt",
        overwrite=False,
    )
    assert _file_hash(src) == source_hash

    names = [a.name for a in pdf_tools.attachments_list(str(out_added))]
    assert "note.txt" in names

    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    extracted_path = pdf_tools.attachment_extract(str(out_added), "note.txt", extracted_dir)
    assert extracted_path.read_bytes() == b"hello"

    out_removed = tmp_path / "removed.pdf"
    pdf_tools.attachment_remove(str(out_added), str(out_removed), name="note.txt")

    names2 = [a.name for a in pdf_tools.attachments_list(str(out_removed))]
    assert "note.txt" not in names2


def test_attachment_add_remove_encrypted_with_password(tmp_path: Path) -> None:
    from pagedrop.core.pdf_loader import PdfPasswordRequiredError
    from tests.core.test_jobs import _encrypted_pdf

    enc = tmp_path / "locked.pdf"
    _encrypted_pdf(enc, password="secret")
    source_hash = _file_hash(enc)

    out_added = tmp_path / "with_attach.pdf"
    with pytest.raises(PdfPasswordRequiredError):
        pdf_tools.attachment_add(
            str(enc),
            str(out_added),
            name="note.txt",
            data=b"hello",
        )
    pdf_tools.attachment_add(
        str(enc),
        str(out_added),
        name="note.txt",
        data=b"hello",
        password="secret",
    )
    assert _file_hash(enc) == source_hash
    assert "note.txt" in [
        a.name
        for a in pdf_tools.attachments_list(str(out_added))
    ]

    locked_added = tmp_path / "locked_added.pdf"
    doc = fitz.open(str(out_added))
    try:
        doc.save(
            str(locked_added),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="secret",
            owner_pw="owner",
        )
    finally:
        doc.close()
    locked_hash = _file_hash(locked_added)
    out_removed = tmp_path / "removed.pdf"
    with pytest.raises(PdfPasswordRequiredError):
        pdf_tools.attachment_remove(
            str(locked_added), str(out_removed), name="note.txt"
        )
    pdf_tools.attachment_remove(
        str(locked_added),
        str(out_removed),
        name="note.txt",
        password="secret",
    )
    assert _file_hash(locked_added) == locked_hash
    assert "note.txt" not in [
        a.name for a in pdf_tools.attachments_list(str(out_removed))
    ]


def test_attachment_extract_all_zip(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = _file_hash(src)

    with_attach = tmp_path / "with_attach.pdf"
    pdf_tools.attachment_add(
        str(src),
        str(with_attach),
        name="note.txt",
        data=b"hello",
        filename="note.txt",
        overwrite=False,
    )
    with_two = tmp_path / "with_two.pdf"
    pdf_tools.attachment_add(
        str(with_attach),
        str(with_two),
        name="data.bin",
        data=b"\x00\x01\x02",
        filename="data.bin",
        overwrite=False,
    )
    attached_hash = _file_hash(with_two)

    out_zip = tmp_path / "out" / "src_attachments.zip"
    result = pdf_tools.attachment_extract_all_zip(str(with_two), out_zip)
    assert result == out_zip
    assert out_zip.is_file()
    assert _file_hash(with_two) == attached_hash
    assert _file_hash(src) == source_hash

    with zipfile.ZipFile(out_zip) as zf:
        assert set(zf.namelist()) == {"note.txt", "data.bin"}
        assert zf.read("note.txt") == b"hello"
        assert zf.read("data.bin") == b"\x00\x01\x02"

    empty = tmp_path / "empty.pdf"
    empty.write_bytes(src.read_bytes())
    with pytest.raises(FileNotFoundError, match="No attachments"):
        pdf_tools.attachment_extract_all_zip(str(empty), tmp_path / "empty.zip")


def test_attachment_extract_job_runner(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(str(src))
    finally:
        doc.close()

    out_added = tmp_path / "with_attach.pdf"
    pdf_tools.attachment_add(
        str(src),
        str(out_added),
        name="note.txt",
        data=b"hello",
        filename="note.txt",
        overwrite=False,
    )
    with_two = tmp_path / "with_two.pdf"
    pdf_tools.attachment_add(
        str(out_added),
        str(with_two),
        name="data.bin",
        data=b"bytes",
        filename="data.bin",
        overwrite=False,
    )

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_organize_handlers(runner)

        out = tmp_path / "extracted" / "with_two_attachments.zip"
        result = runner.run(
            JobSpec.create(
                "attachment_extract",
                inputs=[str(with_two)],
                output=out,
                options={},
            ),
        )
        assert result == out
        assert out.is_file()
        with zipfile.ZipFile(out) as zf:
            assert set(zf.namelist()) == {"note.txt", "data.bin"}
            assert zf.read("note.txt") == b"hello"
            assert zf.read("data.bin") == b"bytes"

        out_cancel = tmp_path / "extracted_cancel" / "with_two_attachments.zip"
        token = CancelToken()
        token.cancel()
        with pytest.raises(JobCancelledError):
            runner.run(
                JobSpec.create(
                    "attachment_extract",
                    inputs=[str(with_two)],
                    output=out_cancel,
                    options={},
                ),
                cancel=token,
            )
        assert not out_cancel.exists()
    finally:
        temp.cleanup()


def test_attachment_extract_uses_job_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: attachment extract must run under FITZ_LOCK.

    Also verifies cooperative cancel leaves no promoted output and cleans the
    staged job directory (partial writes).
    """
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.save(str(src))
    finally:
        doc.close()

    out_added = tmp_path / "with_attach.pdf"
    pdf_tools.attachment_add(
        str(src),
        str(out_added),
        name="note.txt",
        data=b"hello",
        filename="note.txt",
        overwrite=False,
    )

    class TrackingLock:
        def __init__(self) -> None:
            self.locked = False
            self.enter_count = 0

        def __enter__(self) -> "TrackingLock":
            self.locked = True
            self.enter_count += 1
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.locked = False

    lock = TrackingLock()
    # SerializedJobRunner imports FITZ_LOCK at module import time; patch the runner module.
    import pagedrop.core.jobs.runner as runner_module

    monkeypatch.setattr(runner_module, "FITZ_LOCK", lock)

    started = threading.Event()
    allow_finish = threading.Event()
    staged_dir: Path | None = None

    def fake_attachment_extract_all_zip(
        source_pdf: str,
        output_zip: str | Path,
        *,
        password: str | None = None,
    ) -> Path:
        nonlocal staged_dir
        assert lock.locked, "attachment_extract_all_zip must run under FITZ_LOCK"
        started.set()

        out = Path(output_zip)
        staged_dir = out.parent
        out.parent.mkdir(parents=True, exist_ok=True)
        # Simulate partial staged output while the handler is still running.
        with zipfile.ZipFile(out, "w") as zf:
            zf.writestr("note.txt", b"hello")

        # Wait until the test cancels; runner will observe cancel after handler returns.
        allow_finish.wait(timeout=5)
        return out

    monkeypatch.setattr(
        pdf_tools, "attachment_extract_all_zip", fake_attachment_extract_all_zip
    )

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_organize_handlers(runner)

        out_cancel = tmp_path / "extracted_cancel_mid" / "src_attachments.zip"
        token = CancelToken()

        err: list[BaseException] = []

        def run_job() -> None:
            try:
                runner.run(
                    JobSpec.create(
                        "attachment_extract",
                        inputs=[str(out_added)],
                        output=out_cancel,
                        options={},
                    ),
                    cancel=token,
                )
            except JobCancelledError:
                return
            except BaseException as exc:  # pragma: no cover
                err.append(exc)
                raise
            else:  # pragma: no cover
                err.append(RuntimeError("Expected JobCancelledError"))

        t = threading.Thread(target=run_job, daemon=True)
        t.start()

        assert started.wait(timeout=5), "attachment_extract handler never ran"
        token.cancel()
        allow_finish.set()
        t.join(timeout=10)

        assert not out_cancel.exists()
        assert lock.enter_count >= 1
        assert staged_dir is not None
        assert not staged_dir.exists(), "staged job dir must be cleaned on cancel"
        assert not err
    finally:
        temp.cleanup()


def test_metadata_set_strip_and_xmp_v1(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=200, height=200)
        doc.set_metadata({"title": "old", "author": "me"})
        doc.set_xml_metadata('<x:xmpmeta xmlns:x="adobe:ns:meta/">t</x:xmpmeta>')
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = _file_hash(src)

    out_set = tmp_path / "set.pdf"
    pdf_tools.metadata_set(str(src), str(out_set), updates={"title": "new"})
    assert _file_hash(src) == source_hash
    meta = pdf_tools.metadata_get(str(out_set))
    assert meta["title"] == "new"

    out_strip = tmp_path / "strip.pdf"
    pdf_tools.metadata_strip(str(out_set), str(out_strip), strip_xmp_v1=True)
    meta2 = pdf_tools.metadata_get(str(out_strip))
    assert meta2["title"] == ""
    assert pdf_tools.xmp_get(str(out_strip)) == ""


def test_page_labels_get_set(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        for _ in range(5):
            doc.new_page(width=200, height=200)
        labels = [{"startpage": 0, "prefix": "P", "style": "D", "firstpagenum": 1}]
        doc.set_page_labels(labels)
        doc.save(str(src))
    finally:
        doc.close()

    out = tmp_path / "labels.pdf"
    pdf_tools.page_labels_set(str(src), str(out), labels=pdf_tools.page_labels_get(str(src)))
    got = pdf_tools.page_labels_get(str(out))
    assert got == [{"startpage": 0, "prefix": "P", "style": "D", "firstpagenum": 1}]


def test_zip_pdfs_members(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_text_pdf(src, page_texts=[f"P{i}" for i in range(3)], page_size=(200, 200))
    source_hash = _file_hash(src)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    parts = pdf_tools.extract_ranges_to_folder(
        str(src),
        [(0, 0), (1, 2)],
        out_dir,
        base_name="doc",
    )
    zip_path = tmp_path / "bundle.zip"
    pdf_tools.zip_pdfs(parts, zip_path)
    assert _file_hash(src) == source_hash

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = sorted(zf.namelist())
    assert names == sorted([p.name for p in parts])


def test_compare_pdfs_heatmap(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((100, 100), "A", fontsize=22)
        doc.save(str(a))
    finally:
        doc.close()

    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((100, 100), "B", fontsize=22)
        doc.save(str(b))
    finally:
        doc.close()
    hash_a = _file_hash(a)
    hash_b = _file_hash(b)

    heatmap = tmp_path / "heatmap.pdf"
    result = pdf_tools.compare_pdfs_heatmap(
        str(a),
        str(b),
        heatmap,
        dpi=80,
        sample_grid=(4, 4),
        byte_diff_threshold=5,
    )
    assert heatmap.exists()
    assert result.page_diffs and result.page_diffs[0] > 0.0
    assert _file_hash(a) == hash_a
    assert _file_hash(b) == hash_b

    out_doc = fitz.open(str(heatmap))
    try:
        assert out_doc.page_count == 1
        # Base page shows PDF A content; red overlays mark diffs (not blank white).
        assert out_doc[0].search_for("A")
        assert out_doc[0].get_drawings()
    finally:
        out_doc.close()


def test_compare_job_writes_overall_diff_ratio_sidecar(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"

    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((100, 100), "A", fontsize=22)
        doc.save(str(a))
    finally:
        doc.close()

    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((100, 100), "B", fontsize=22)
        doc.save(str(b))
    finally:
        doc.close()

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_organize_handlers(runner)
        out = tmp_path / "heatmap_compare.pdf"

        result = runner.run(
            JobSpec.create(
                "compare",
                inputs=[str(a), str(b)],
                output=out,
                options={"dpi": 40},
            )
        )
        assert result == out
        assert out.is_file()

        ratio_path = out.with_suffix(".compare_ratio.txt")
        assert ratio_path.exists()
        ratio = float(ratio_path.read_text(encoding="utf-8").strip())
        assert 0.0 <= ratio <= 1.0
    finally:
        temp.cleanup()


def test_compare_detects_thin_deleted_text_line(tmp_path: Path) -> None:
    """Regression: sparse 3×3 probes miss a single deleted text line on a letter page."""
    a = tmp_path / "full.pdf"
    b = tmp_path / "truncated.pdf"
    long_line = (
        "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM, "
        "Zustand, TanStack Query, Tailwind CSS v4, shadcn/ui"
    )
    short_line = "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM,"

    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 260), long_line, fontsize=10)
        doc.save(str(a))
    finally:
        doc.close()

    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 260), short_line, fontsize=10)
        doc.save(str(b))
    finally:
        doc.close()

    heatmap = tmp_path / "heat.pdf"
    # Old 12×12 + 9-point sampling reported 0.0 on this class of diff.
    result = pdf_tools.compare_pdfs_heatmap(
        str(a),
        str(b),
        heatmap,
        dpi=120,
        sample_grid=(12, 12),
        byte_diff_threshold=20,
    )
    assert result.page_diffs[0] > 0.0

    out_doc = fitz.open(str(heatmap))
    try:
        red = [
            d
            for d in out_doc[0].get_drawings()
            if d.get("fill") and d["fill"][0] > 0.9 and d["fill"][1] < 0.1
        ]
        assert red, "deleted text tail must produce red overlay cells"
        # insert_text y is the baseline; overlay cells are coarse (12×12).
        assert any(d["rect"].y0 <= 260 <= d["rect"].y1 for d in red)
    finally:
        out_doc.close()


def test_compare_text_diff_truncation_and_identical(tmp_path: Path) -> None:
    a = tmp_path / "full.pdf"
    b = tmp_path / "truncated.pdf"
    long_line = (
        "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM, "
        "Zustand, TanStack Query, Tailwind CSS v4, shadcn/ui"
    )
    short_line = "Tech Stack: Electron 30, React 18, Express 5, SQLite, Drizzle ORM,"

    for path, text in ((a, long_line), (b, short_line)):
        doc = fitz.open()
        try:
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 260), text, fontsize=10)
            doc.save(str(path))
        finally:
            doc.close()

    hash_a = _file_hash(a)
    hash_b = _file_hash(b)
    report = pdf_tools.compare_pdf_text_diff(str(a), str(b))
    assert _file_hash(a) == hash_a
    assert _file_hash(b) == hash_b
    assert report.deleted_count == 1
    assert report.added_count == 0
    assert report.modified_count == 0
    change = report.changes[0]
    assert change.kind == "deleted"
    assert "Zustand" in change.text
    assert change.rects_a
    assert any(r[1] <= 260 <= r[3] for r in change.rects_a)

    identical = pdf_tools.compare_pdf_text_diff(str(a), str(a))
    assert identical.changes == ()
    assert identical.deleted_count == 0


def test_compare_keeps_pixmap_cache_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Compare streams page pairs at a clamped DPI — never full-document pixmap caches."""
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    page_count = 6
    _make_text_pdf(a, page_texts=[f"A{i}" for i in range(page_count)], page_size=(600, 600))
    _make_text_pdf(b, page_texts=[f"B{i}" for i in range(page_count)], page_size=(600, 600))

    widths: list[int] = []
    real_get_pixmap = fitz.Page.get_pixmap

    def tracking_get_pixmap(self, *args, **kwargs):
        pix = real_get_pixmap(self, *args, **kwargs)
        widths.append(pix.width)
        return pix

    monkeypatch.setattr(fitz.Page, "get_pixmap", tracking_get_pixmap)

    heatmap = tmp_path / "heatmap.pdf"
    # High DPI would exceed COMPARE_MAX_RENDER_WIDTH_PX without the clamp.
    result = pdf_tools.compare_pdfs_heatmap(
        str(a),
        str(b),
        heatmap,
        dpi=720,
        sample_grid=(4, 4),
        byte_diff_threshold=5,
    )

    assert widths
    assert max(widths) <= pdf_tools.COMPARE_MAX_RENDER_WIDTH_PX
    # One pair per page (streaming), not a retained full-doc pixmap list.
    assert len(widths) == page_count * 2
    assert len(result.page_diffs) == page_count
    out_doc = fitz.open(str(heatmap))
    try:
        assert out_doc.page_count == page_count
    finally:
        out_doc.close()


def test_n_up_cancel_mid_loop_cleans_staged(tmp_path, monkeypatch):
    """Cancel during N-up sheet loop must not promote and must scrub staging."""
    src = _make_text_pdf(
        tmp_path / "src.pdf",
        page_texts=["A", "B", "C", "D", "E", "F", "G", "H"],
    )
    src_hash = _file_hash(src)
    out = tmp_path / "nup.pdf"
    token = CancelToken()
    checks = {"n": 0}
    real_check = pdf_tools._check_cancel

    def counting_check(cancel):
        checks["n"] += 1
        if checks["n"] >= 2:
            token.cancel()
        real_check(cancel)

    monkeypatch.setattr(pdf_tools, "_check_cancel", counting_check)

    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_organize_handlers(runner)
        with pytest.raises(JobCancelledError):
            runner.run(
                JobSpec.create(
                    "n_up",
                    inputs=[str(src)],
                    output=out,
                    options={"rows": 1, "cols": 1, "margin_pt": 0.0},
                ),
                cancel=token,
            )
        assert not out.exists()
        assert not any(temp._dir.glob("job_*"))
        assert _file_hash(src) == src_hash
    finally:
        temp.cleanup()


def test_compare_heatmap_cancel_mid_page(tmp_path, monkeypatch):
    """Cancel between compare pages must not write the heatmap output."""
    a = _make_text_pdf(tmp_path / "a.pdf", page_texts=["A1", "A2", "A3"])
    b = _make_text_pdf(tmp_path / "b.pdf", page_texts=["B1", "B2", "B3"])
    heatmap = tmp_path / "heatmap.pdf"
    token = CancelToken()
    checks = {"n": 0}
    real_check = pdf_tools._check_cancel

    def counting_check(cancel):
        checks["n"] += 1
        if checks["n"] >= 2:
            token.cancel()
        real_check(cancel)

    monkeypatch.setattr(pdf_tools, "_check_cancel", counting_check)
    with pytest.raises(JobCancelledError):
        pdf_tools.compare_pdfs_heatmap(
            str(a),
            str(b),
            heatmap,
            dpi=72,
            sample_grid=(4, 4),
            cancel=token,
        )
    assert not heatmap.exists()


def test_compare_text_diff_cancel_mid_page(tmp_path, monkeypatch):
    """Cancel between text-diff pages must raise and leave sources unchanged."""
    a = _make_text_pdf(tmp_path / "a.pdf", page_texts=["A1", "A2", "A3", "A4"])
    b = _make_text_pdf(tmp_path / "b.pdf", page_texts=["B1", "B2", "B3", "B4"])
    hash_a = _file_hash(a)
    hash_b = _file_hash(b)
    token = CancelToken()
    checks = {"n": 0}
    real_check = pdf_tools._check_cancel

    def counting_check(cancel):
        checks["n"] += 1
        if checks["n"] >= 2:
            token.cancel()
        real_check(cancel)

    monkeypatch.setattr(pdf_tools, "_check_cancel", counting_check)
    with pytest.raises(JobCancelledError):
        pdf_tools.compare_pdf_text_diff(str(a), str(b), cancel=token)
    assert checks["n"] >= 2
    assert _file_hash(a) == hash_a
    assert _file_hash(b) == hash_b

