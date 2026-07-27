"""Phase 25 unit tests — native import/export conversions."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import fitz
import pytest

from pagedrop.core import native_conversions as nc
from pagedrop.core.capabilities import OPENPYXL, PI_HEIF, PILLOW, clear_cache
from pagedrop.core.jobs.errors import BackendUnavailableError
from pagedrop.core.supported_formats import (
    EXPORT_FROM_PDF_FORMATS,
    IMPORT_TO_PDF_FORMATS,
    export_from_pdf_dialog_filter,
    export_format,
    import_extensions,
    import_format_for_path,
    import_to_pdf_dialog_filter,
    is_native_import_path,
    is_supported_image,
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_text_pdf(path: Path, texts: list[str]) -> Path:
    doc = fitz.open()
    try:
        for text in texts:
            page = doc.new_page(width=200, height=200)
            page.insert_text((40, 80), text, fontsize=16)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _make_table_pdf(path: Path) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        rows, cols = 3, 2
        x0, y0, cw, ch = 50, 50, 120, 40
        for r in range(rows + 1):
            page.draw_line((x0, y0 + r * ch), (x0 + cols * cw, y0 + r * ch))
        for c in range(cols + 1):
            page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + rows * ch))
        data = [["Name", "Age"], ["Ada", "36"], ["Bob", "41"]]
        for r, row in enumerate(data):
            for c, val in enumerate(row):
                page.insert_text((x0 + 8 + c * cw, y0 + 28 + r * ch), val, fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_import_export_registries_cover_phase25_formats():
    import_ids = {spec.id for spec in IMPORT_TO_PDF_FORMATS}
    assert {
        "svg",
        "xps",
        "epub",
        "mobi",
        "fb2",
        "cbz",
        "text",
        "markdown",
        "html",
        "heic",
    } <= import_ids

    export_ids = {spec.id for spec in EXPORT_FROM_PDF_FORMATS}
    assert {
        "png",
        "jpeg",
        "webp",
        "tiff",
        "svg",
        "text",
        "json",
        "xml",
        "cbz",
        "csv",
        "tables_json",
        "xlsx",
    } <= export_ids

    assert export_format("tiff").capability_id == PILLOW
    assert export_format("xlsx").capability_id == OPENPYXL
    assert import_format_for_path("photo.HEIC").capability_id == PI_HEIF
    assert not is_supported_image("photo.heic")


def test_dialog_filters_omit_gated_codecs_when_absent(monkeypatch):
    clear_cache()

    class _Absent:
        available = False

    monkeypatch.setattr(
        "pagedrop.core.supported_formats.probe",
        lambda capability_id, refresh=False: _Absent(),
    )
    filt = import_to_pdf_dialog_filter(available_only=True)
    assert "*.heic" not in filt
    assert "*.svg" in filt
    assert "*.heic" in import_to_pdf_dialog_filter(available_only=False)

    export_filt = export_from_pdf_dialog_filter(available_only=True)
    assert "*.tiff" not in export_filt
    assert "*.xlsx" not in export_filt
    assert "*.png" in export_filt


def test_pdf_to_png_page_count(tmp_path):
    source = _make_text_pdf(tmp_path / "src.pdf", ["A", "B", "C"])
    before = _file_hash(source)
    out_dir = tmp_path / "png"
    written = nc.export_pdf(source, out_dir, format_id="png", dpi=72)
    assert len(written) == 3
    assert all(p.suffix == ".png" and p.is_file() for p in written)
    assert _file_hash(source) == before


def test_pdf_to_text_contains_known_string(tmp_path):
    source = _make_text_pdf(tmp_path / "src.pdf", ["Hello PageDrop"])
    before = _file_hash(source)
    out = tmp_path / "out.txt"
    written = nc.export_pdf(source, out, format_id="text")
    assert written == [out]
    assert "Hello PageDrop" in out.read_text(encoding="utf-8")
    assert _file_hash(source) == before


def test_table_to_csv(tmp_path):
    source = _make_table_pdf(tmp_path / "table.pdf")
    before = _file_hash(source)
    out = tmp_path / "tables.csv"
    written = nc.export_pdf(source, out, format_id="csv")
    text = written[0].read_text(encoding="utf-8")
    assert "Ada" in text and "36" in text
    assert _file_hash(source) == before


def test_source_hash_unchanged(tmp_path):
    """Exports and imports must never mutate the user's source bytes."""
    source = _make_text_pdf(tmp_path / "src.pdf", ["Keep", "Intact"])
    before = _file_hash(source)
    nc.export_pdf(source, tmp_path / "png_out", format_id="png", dpi=72)
    nc.export_pdf(source, tmp_path / "out.txt", format_id="text")
    assert _file_hash(source) == before

    svg = tmp_path / "shape.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
        '<rect width="40" height="40" fill="red"/></svg>',
        encoding="utf-8",
    )
    before_svg = _file_hash(svg)
    nc.import_to_pdf(svg, tmp_path / "shape.pdf")
    assert _file_hash(svg) == before_svg

    txt = tmp_path / "notes.txt"
    txt.write_text("Line one\nLine two\n", encoding="utf-8")
    before_txt = _file_hash(txt)
    pdf = tmp_path / "notes.pdf"
    nc.import_to_pdf(txt, pdf)
    doc = fitz.open(pdf)
    try:
        assert "Line one" in doc[0].get_text()
    finally:
        doc.close()
    assert _file_hash(txt) == before_txt


def test_markdown_and_html_via_story(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("# Title\n\nHello **world**\n", encoding="utf-8")
    out = tmp_path / "doc.pdf"
    nc.import_to_pdf(md, out)
    doc = fitz.open(out)
    try:
        text = doc[0].get_text()
        assert "Title" in text and "Hello" in text
    finally:
        doc.close()

    html_path = tmp_path / "doc.html"
    html_path.write_text(
        "<html><body><h1>Hi</h1><p>PageDrop</p></body></html>",
        encoding="utf-8",
    )
    html_pdf = tmp_path / "html.pdf"
    nc.import_to_pdf(html_path, html_pdf)
    doc = fitz.open(html_pdf)
    try:
        assert "PageDrop" in doc[0].get_text()
    finally:
        doc.close()


def test_cbz_round_trip_export_import(tmp_path):
    source = _make_text_pdf(tmp_path / "src.pdf", ["One", "Two"])
    before = _file_hash(source)
    cbz = tmp_path / "pages.cbz"
    written = nc.export_pdf(source, cbz, format_id="cbz", dpi=72)
    assert written == [cbz]
    with zipfile.ZipFile(cbz) as zf:
        names = sorted(zf.namelist())
        assert names == ["001.png", "002.png"]
    assert _file_hash(source) == before

    back = tmp_path / "from_cbz.pdf"
    nc.import_to_pdf(cbz, back)
    assert fitz.open(back).page_count == 2


def test_webp_export(tmp_path):
    source = _make_text_pdf(tmp_path / "src.pdf", ["WebP"])
    out_dir = tmp_path / "webp"
    written = nc.export_pdf(source, out_dir, format_id="webp", dpi=72)
    assert len(written) == 1
    assert written[0].suffix == ".webp"
    assert written[0].stat().st_size > 0


def test_tiff_export_requires_pillow_when_absent(tmp_path, monkeypatch):
    source = _make_text_pdf(tmp_path / "src.pdf", ["Tiff"])
    clear_cache()

    class _Absent:
        available = False
        detail = "Pillow not installed"

        def __init__(self) -> None:
            from pagedrop.core.capabilities import AbsenceReason

            self.reason = AbsenceReason.CODEC_MISSING

    monkeypatch.setattr(
        "pagedrop.core.native_conversions.probe",
        lambda capability_id, refresh=False: _Absent()
        if capability_id == PILLOW
        else type("S", (), {"available": True, "reason": None, "detail": ""})(),
    )
    with pytest.raises(BackendUnavailableError) as excinfo:
        nc.export_pdf(source, tmp_path / "out", format_id="tiff")
    assert excinfo.value.capability_id == PILLOW


def test_tiff_export_uses_pillow_when_present(tmp_path):
    pytest.importorskip("PIL")
    clear_cache()
    source = _make_text_pdf(tmp_path / "src.pdf", ["Tiff"])
    before = _file_hash(source)
    written = nc.export_pdf(source, tmp_path / "tiff_out", format_id="tiff", dpi=72)
    assert written[0].suffix == ".tiff"
    assert written[0].is_file()
    assert _file_hash(source) == before


def test_xlsx_export_requires_openpyxl_when_absent(tmp_path, monkeypatch):
    source = _make_table_pdf(tmp_path / "table.pdf")
    clear_cache()

    class _Absent:
        available = False
        detail = "openpyxl not installed"

        def __init__(self) -> None:
            from pagedrop.core.capabilities import AbsenceReason

            self.reason = AbsenceReason.CODEC_MISSING

    monkeypatch.setattr(
        "pagedrop.core.native_conversions.probe",
        lambda capability_id, refresh=False: _Absent()
        if capability_id == OPENPYXL
        else type("S", (), {"available": True, "reason": None, "detail": ""})(),
    )
    with pytest.raises(BackendUnavailableError) as excinfo:
        nc.export_pdf(source, tmp_path / "out.xlsx", format_id="xlsx")
    assert excinfo.value.capability_id == OPENPYXL


def test_heic_import_requires_pi_heif(tmp_path, monkeypatch):
    heic = tmp_path / "photo.heic"
    heic.write_bytes(b"not-a-real-heic")
    clear_cache()

    class _Absent:
        available = False
        detail = "missing"

        def __init__(self) -> None:
            from pagedrop.core.capabilities import AbsenceReason

            self.reason = AbsenceReason.CODEC_MISSING

    monkeypatch.setattr(
        "pagedrop.core.native_conversions.probe",
        lambda capability_id, refresh=False: _Absent()
        if capability_id == PI_HEIF
        else type("S", (), {"available": True, "reason": None, "detail": ""})(),
    )
    monkeypatch.setattr(
        "pagedrop.core.supported_formats.probe",
        lambda capability_id, refresh=False: _Absent()
        if capability_id == PI_HEIF
        else type("S", (), {"available": True, "reason": None, "detail": ""})(),
    )
    assert not is_native_import_path(heic, available_only=True)
    assert heic.suffix.lower() in import_extensions(available_only=False)
    with pytest.raises(BackendUnavailableError):
        nc.import_to_pdf(heic, tmp_path / "photo.pdf")


def test_json_xml_structure_export(tmp_path):
    source = _make_text_pdf(tmp_path / "src.pdf", ["Struct"])
    js = tmp_path / "out.json"
    nc.export_pdf(source, js, format_id="json")
    assert "Struct" in js.read_text(encoding="utf-8")
    xml_path = tmp_path / "out.xml"
    nc.export_pdf(source, xml_path, format_id="xml")
    assert "page" in xml_path.read_text(encoding="utf-8")


def test_rejects_source_overwrite(tmp_path):
    source = _make_text_pdf(tmp_path / "src.pdf", ["X"])
    with pytest.raises(Exception):
        nc.export_pdf(source, source, format_id="text", overwrite=True)
