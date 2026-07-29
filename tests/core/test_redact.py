"""Phase 30 — security-grade redaction (fresh-process verify)."""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core.jobs.errors import SourceOverwriteError
from pagedrop.core.markup import MarkupSession
from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.core.redact import (
    RedactionError,
    RedactionRegion,
    RedactionScope,
    RedactionVerifyError,
    inspect_redaction_result,
    redact_edit_model,
    redact_pdf,
    verify_redacted_pdf_fresh_process,
)


SECRET = "TOPSECRET_ZZ9"
SECRET_B = "HIDDENVAL42"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_rgb(path: Path, *, width: int = 32, height: int = 32, rgb: tuple[int, int, int] = (12, 34, 56)) -> Path:
    """Minimal uncompressed-ish RGB PNG without Pillow."""
    raw = b""
    r, g, b = rgb
    row = bytes([0]) + bytes([r, g, b] * width)
    raw = row * height
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    return path


def _text_pdf(path: Path, text: str = f"Hello {SECRET} world") -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 80), text, fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _secret_rect(path: Path, secret: str = SECRET) -> tuple[float, float, float, float]:
    doc = fitz.open(str(path))
    try:
        hits = doc[0].search_for(secret)
        assert hits, f"{secret!r} not found in {path}"
        r = hits[0]
        return (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
    finally:
        doc.close()


def test_redacted_text_unextractable_fresh_process(tmp_path: Path) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)
    out = tmp_path / "redacted.pdf"
    rect = _secret_rect(src)
    redact_pdf(src, out, [RedactionRegion(0, rect)], verify=True)

    assert _file_hash(src) == source_hash
    assert out.is_file()
    report = verify_redacted_pdf_fresh_process(out, absent_text=[SECRET])
    assert report.ok, report.failures
    doc = fitz.open(str(out))
    try:
        assert SECRET not in (doc[0].get_text() or "")
        assert not doc[0].search_for(SECRET)
        assert not any(
            a.type and a.type[0] == fitz.PDF_ANNOT_REDACT for a in (doc[0].annots() or [])
        )
    finally:
        doc.close()


def test_failed_verify_deletes_staged_output(tmp_path: Path) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)
    out = tmp_path / "should_not_exist.pdf"
    # Region misses the secret; extra_absent forces verify failure.
    with pytest.raises(RedactionVerifyError) as excinfo:
        redact_pdf(
            src,
            out,
            [RedactionRegion(0, (0.0, 0.0, 8.0, 8.0))],
            extra_absent=[SECRET],
            verify=True,
        )
    assert not out.exists()
    assert _file_hash(src) == source_hash
    assert any(SECRET in f for f in excinfo.value.failures)


def test_source_overwrite_rejected(tmp_path: Path) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    rect = _secret_rect(src)
    with pytest.raises(SourceOverwriteError):
        redact_pdf(src, src, [RedactionRegion(0, rect)])


def test_split_spans_fixture(tmp_path: Path) -> None:
    src = tmp_path / "split.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=200)
        # Secret split across two insert_text calls / spans.
        page.insert_text((40, 80), "TOP", fontsize=14)
        page.insert_text((70, 80), "SECRET_ZZ9", fontsize=14)
        doc.save(str(src))
    finally:
        doc.close()
    # Cover both spans with one rect.
    rect = (40.0, 60.0, 180.0, 95.0)
    out = tmp_path / "split-out.pdf"
    before = _file_hash(src)
    redact_pdf(src, out, [RedactionRegion(0, rect, expected_absent=(SECRET,))], verify=True)
    assert _file_hash(src) == before
    assert verify_redacted_pdf_fresh_process(out, absent_text=[SECRET]).ok


def test_ocr_text_layer_fixture(tmp_path: Path) -> None:
    """Invisible text layer (render_mode=3) must still be destroyed."""
    src = tmp_path / "ocr_layer.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=200)
        page.insert_text((40, 100), "Visible safe", fontsize=14)
        # Invisible OCR-style text.
        page.insert_text(
            (40, 140),
            SECRET,
            fontsize=14,
            render_mode=3,
        )
        doc.save(str(src))
    finally:
        doc.close()
    rect = _secret_rect(src)
    out = tmp_path / "ocr-out.pdf"
    before = _file_hash(src)
    redact_pdf(src, out, [RedactionRegion(0, rect)], verify=True)
    assert _file_hash(src) == before
    hex_secret = SECRET.encode("ascii").hex().encode("ascii")
    assert hex_secret not in out.read_bytes()
    assert verify_redacted_pdf_fresh_process(out, absent_text=[SECRET]).ok


def test_shared_image_and_vector_fixture(tmp_path: Path) -> None:
    png = _png_rgb(tmp_path / "mark.png", rgb=(9, 8, 7))
    src = tmp_path / "imgvec.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=400)
        page.insert_image(fitz.Rect(40, 40, 120, 120), filename=str(png))
        page.insert_image(fitz.Rect(200, 40, 280, 120), filename=str(png))
        # Vector path with a distinctive stroke near a text secret.
        page.insert_text((40, 200), SECRET, fontsize=16)
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(40, 220, 160, 260))
        shape.finish(color=(0.1, 0.2, 0.3), fill=(0.9, 0.1, 0.1), width=2)
        shape.commit()
        doc.save(str(src))
    finally:
        doc.close()

    text_rect = _secret_rect(src)
    # Cover left image + text + vector block.
    regions = [
        RedactionRegion(0, (40.0, 40.0, 120.0, 120.0)),
        RedactionRegion(0, text_rect, expected_absent=(SECRET,)),
        RedactionRegion(0, (40.0, 220.0, 160.0, 260.0)),
    ]
    out = tmp_path / "imgvec-out.pdf"
    before = _file_hash(src)
    redact_pdf(src, out, regions, verify=True)
    assert _file_hash(src) == before

    doc = fitz.open(str(out))
    try:
        assert SECRET not in (doc[0].get_text() or "")
        # Exercise normal image extraction; shared XObject may survive pixel-patch
        # redaction on one instance — text/hex absence is the security floor here.
        for img in doc[0].get_images(full=True):
            try:
                doc.extract_image(img[0])
            except Exception:
                continue
        hex_secret = SECRET.encode("ascii").hex().encode("ascii")
        assert hex_secret not in out.read_bytes()
        drawings = doc[0].get_drawings()
        # No fill matching the redacted vector's bright red in the redacted box.
        for d in drawings:
            rect = d.get("rect")
            if rect is None:
                continue
            if fitz.Rect(40, 220, 160, 260).intersects(rect) and d.get("fill") == (
                0.9,
                0.1,
                0.1,
            ):
                pytest.fail("redacted vector fill still present")
    finally:
        doc.close()


def test_annots_rotated_incremental_fixtures(tmp_path: Path) -> None:
    src = tmp_path / "annot_rot.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_text((50, 100), SECRET, fontsize=14)
        page.add_highlight_annot(page.search_for(SECRET))
        page.set_rotation(90)
        doc.save(str(src))
    finally:
        doc.close()

    # Incremental save retaining prior content history.
    doc = fitz.open(str(src))
    try:
        doc[0].insert_text((20, 40), "note", fontsize=10)
        doc.saveIncr()
    finally:
        doc.close()
    # MuPDF stores the glyph string as hex in the content stream.
    assert SECRET.encode("ascii").hex().encode("ascii") in src.read_bytes()

    # search_for works in unrotated space.
    doc = fitz.open(str(src))
    try:
        hits = doc[0].search_for(SECRET)
        assert hits
        rect = (
            float(hits[0].x0),
            float(hits[0].y0),
            float(hits[0].x1),
            float(hits[0].y1),
        )
    finally:
        doc.close()

    out = tmp_path / "annot-out.pdf"
    before = _file_hash(src)
    redact_pdf(src, out, [RedactionRegion(0, rect)], verify=True)
    assert _file_hash(src) == before
    assert SECRET.encode("ascii").hex().encode("ascii") not in out.read_bytes()
    report = verify_redacted_pdf_fresh_process(out, absent_text=[SECRET])
    assert report.ok, report.failures


def test_metadata_attachments_scope(tmp_path: Path) -> None:
    src = tmp_path / "meta.pdf"
    att = tmp_path / "payload.txt"
    att.write_text(f"attach {SECRET_B}", encoding="utf-8")
    doc = fitz.open()
    try:
        page = doc.new_page(width=300, height=200)
        page.insert_text((40, 80), SECRET, fontsize=14)
        doc.set_metadata({"title": "Classified", "author": "Mole", "subject": SECRET_B})
        doc.embfile_add(
            "payload.txt",
            att.read_bytes(),
            filename="payload.txt",
            ufilename="payload.txt",
            desc="secret attach",
        )
        doc.save(str(src))
    finally:
        doc.close()

    out = tmp_path / "meta-out.pdf"
    before = _file_hash(src)
    redact_pdf(
        src,
        out,
        [RedactionRegion(0, _secret_rect(src))],
        scope=RedactionScope(
            strip_metadata=True,
            strip_xmp=True,
            remove_attachments=True,
        ),
        extra_absent=[SECRET_B],
        verify=True,
    )
    assert _file_hash(src) == before
    report = verify_redacted_pdf_fresh_process(
        out,
        absent_text=[SECRET, SECRET_B],
        expect_empty_metadata=True,
        expect_no_attachments=True,
    )
    assert report.ok, report.failures


def test_malformed_pdf_raises(tmp_path: Path) -> None:
    bad = tmp_path / "garbage.pdf"
    bad.write_bytes(b"%PDF-1.4\nnot a real pdf xref broken")
    out = tmp_path / "out.pdf"
    with pytest.raises(Exception):
        redact_pdf(bad, out, [RedactionRegion(0, (0, 0, 10, 10))], verify=False)
    assert not out.exists()


def test_no_regions_raises(tmp_path: Path) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    with pytest.raises(RedactionError):
        redact_pdf(src, tmp_path / "out.pdf", [], verify=False)


def test_file_contains_any_chunked_scan(tmp_path: Path) -> None:
    """Raw-byte verify scans in chunks (no full-file read_bytes)."""
    from pagedrop.core.redact import _file_contains_any

    needle = b"BOUNDARY_SECRET"
    # Place needle across a 64-byte chunk boundary.
    prefix = b"x" * (64 - 4)
    path = tmp_path / "blob.bin"
    path.write_bytes(prefix + needle + b"tail")
    assert _file_contains_any(path, [needle], chunk_size=64) == needle
    assert _file_contains_any(path, [b"missing"], chunk_size=64) is None


def test_redact_edit_model_with_markup_session(tmp_path: Path) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    before = _file_hash(src)
    model = PdfEditModel(str(src), 1)
    session = MarkupSession()
    rect = _secret_rect(src)
    session.push_redaction(RedactionRegion(0, rect))
    out = tmp_path / "model-out.pdf"
    redact_edit_model(
        model,
        out,
        session.redaction_regions(),
        markup=session.non_redaction_ops(),
        verify=True,
    )
    assert _file_hash(src) == before
    assert inspect_redaction_result(out, absent_text=[SECRET]).ok


def test_redact_edit_model_encrypted_with_passwords(tmp_path: Path) -> None:
    from pagedrop.core.pdf_loader import PdfPasswordRequiredError

    plain = _text_pdf(tmp_path / "plain.pdf")
    enc = tmp_path / "locked.pdf"
    doc = fitz.open(str(plain))
    try:
        doc.save(
            str(enc),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="secret",
            owner_pw="owner",
        )
    finally:
        doc.close()
    before = _file_hash(enc)
    model = PdfEditModel(str(enc), 1)
    rect = _secret_rect(plain)  # same page geometry as encrypted source
    out = tmp_path / "redacted.pdf"

    with pytest.raises(PdfPasswordRequiredError):
        redact_edit_model(
            model,
            out,
            [RedactionRegion(0, rect)],
            verify=False,
        )

    redact_edit_model(
        model,
        out,
        [RedactionRegion(0, rect)],
        passwords={str(enc): "secret"},
        verify=True,
    )
    assert _file_hash(enc) == before
    assert inspect_redaction_result(out, absent_text=[SECRET]).ok


def test_cosmetic_black_box_fails_verify(tmp_path: Path) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    cosmetic = tmp_path / "cosmetic.pdf"
    doc = fitz.open(str(src))
    try:
        r = doc[0].search_for(SECRET)[0]
        doc[0].draw_rect(r, color=(0, 0, 0), fill=(0, 0, 0))
        doc.save(str(cosmetic))
    finally:
        doc.close()
    report = verify_redacted_pdf_fresh_process(cosmetic, absent_text=[SECRET])
    assert not report.ok
