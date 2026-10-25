"""Phase 30 — security-grade redaction (fresh-process verify)."""

from __future__ import annotations

import struct
import subprocess
import sys
import zlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core import redact as redact_module
from pagedrop.core.jobs.cancel import CancelToken
from pagedrop.core.jobs.errors import JobCancelledError, SourceOverwriteError
from pagedrop.core.markup import MarkupSession
from pagedrop.core.pdf_loader import PdfCorruptError
from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.redact import (
    REDACT_VERIFY_FLAG,
    RedactionError,
    RedactionRegion,
    RedactionScope,
    RedactionVerifyError,
    inspect_redaction_result,
    redact_edit_model,
    redact_pdf,
    verify_argv,
    verify_redacted_pdf_fresh_process,
)
from tests.conftest import file_sha256


SECRET = "TOPSECRET_ZZ9"
SECRET_B = "HIDDENVAL42"


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
    source_hash = file_sha256(src)
    out = tmp_path / "redacted.pdf"
    rect = _secret_rect(src)
    redact_pdf(src, out, [RedactionRegion(0, rect)], verify=True)

    assert file_sha256(src) == source_hash
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
    source_hash = file_sha256(src)
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
    assert file_sha256(src) == source_hash
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
    before = file_sha256(src)
    redact_pdf(src, out, [RedactionRegion(0, rect, expected_absent=(SECRET,))], verify=True)
    assert file_sha256(src) == before
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
    before = file_sha256(src)
    redact_pdf(src, out, [RedactionRegion(0, rect)], verify=True)
    assert file_sha256(src) == before
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
    before = file_sha256(src)
    redact_pdf(src, out, regions, verify=True)
    assert file_sha256(src) == before

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


@pytest.mark.parametrize("rotation", [90, 270])
def test_annots_rotated_incremental_fixtures(tmp_path: Path, rotation: int) -> None:
    src = tmp_path / "annot_rot.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_text((50, 100), SECRET, fontsize=14)
        page.add_highlight_annot(page.search_for(SECRET))
        page.set_rotation(rotation)
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
    before = file_sha256(src)
    redact_pdf(src, out, [RedactionRegion(0, rect)], verify=True)
    assert file_sha256(src) == before
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
    before = file_sha256(src)
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
    assert file_sha256(src) == before
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
    with pytest.raises(PdfCorruptError):
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
    before = file_sha256(src)
    model = PdfEditModel(str(src), 1)
    session = MarkupSession()
    rect = _secret_rect(src)
    session.push_redaction(RedactionRegion(0, rect), model.instance_id_at(0))
    out = tmp_path / "model-out.pdf"
    redact_edit_model(
        model,
        out,
        session.redaction_regions(model),
        markup=session.non_redaction_ops(model),
        verify=True,
    )
    assert file_sha256(src) == before
    assert inspect_redaction_result(out, absent_text=[SECRET]).ok


def test_redaction_target_resolves_after_reorder_and_is_dropped_on_delete(tmp_path: Path) -> None:
    source = _text_pdf(tmp_path / "source.pdf")
    model = PdfEditModel(str(source), 1)
    model.insert_pages(0, [model.page_at(0)])
    session = MarkupSession()
    secret_id = model.instance_id_at(1)
    session.push_redaction(RedactionRegion(1, _secret_rect(source)), secret_id)
    model.move_pages([1], 0)
    assert session.redaction_regions(model)[0].page_index == 0
    model.remove_pages([0])
    assert session.redaction_regions(model) == []
    assert model.undo()
    assert session.redaction_regions(model)[0].page_index == 0


def test_redact_edit_model_rejects_imported_source(tmp_path: Path) -> None:
    source_a = _text_pdf(tmp_path / "a.pdf")
    source_b = _text_pdf(tmp_path / "b.pdf")
    hash_a = file_sha256(source_a)
    hash_b = file_sha256(source_b)
    model = PdfEditModel(str(source_a), 1)
    model.insert_pages(1, [PageRef(str(source_b), 0)])
    model.remove_pages([1])

    with pytest.raises(SourceOverwriteError):
        redact_edit_model(
            model,
            source_b,
            [RedactionRegion(0, _secret_rect(source_a))],
            verify=False,
        )

    assert file_sha256(source_a) == hash_a
    assert file_sha256(source_b) == hash_b


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
    before = file_sha256(enc)
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
    assert file_sha256(enc) == before
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


def test_inspect_search_for_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Secret absent from extractable text so the verify arm reaches search_for.
    src = _text_pdf(tmp_path / "clean.pdf", text="Hello world")

    def _boom(self: fitz.Page, *_a: object, **_k: object) -> list:
        raise RuntimeError("search broken")

    monkeypatch.setattr(fitz.Page, "search_for", _boom)
    report = inspect_redaction_result(str(src), absent_text=[SECRET])
    assert not report.ok
    assert any("search_for failed" in f for f in report.failures)


def test_verify_argv_module_form() -> None:
    assert verify_argv()[-3:] == ["-m", "pagedrop.core.redact", "--verify-json"]


def test_verify_argv_frozen_form(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\PageDrop\pagedrop.exe")
    assert verify_argv() == [
        r"C:\PageDrop\pagedrop.exe",
        REDACT_VERIFY_FLAG,
        "--verify-json",
    ]


def test_verify_empty_stdout_is_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = _text_pdf(tmp_path / "src.pdf")

    class _Proc:
        returncode = 0
        pid = 0
        args: list[str] = []

        def communicate(self, *_a: object, **_k: object) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(
        "pagedrop.core.redact.popen_owned",
        lambda *_a, **_k: _Proc(),
    )
    report = verify_redacted_pdf_fresh_process(src, absent_text=[SECRET])
    assert not report.ok
    assert any("empty stdout" in f for f in report.failures)


def _page_pdf(path: Path, lines: list[tuple[tuple[float, float], str]]) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        for point, text in lines:
            page.insert_text(point, text, fontsize=14)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _hits(path: Path, needle: str) -> list[fitz.Rect]:
    doc = fitz.open(str(path))
    try:
        return list(doc[0].search_for(needle))
    finally:
        doc.close()


@pytest.fixture
def verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record real fresh-process verifier runs (it is never bypassed)."""
    calls: list[object] = []
    real = redact_module.verify_redacted_pdf_fresh_process

    def _spy(*args: object, **kwargs: object):
        report = real(*args, **kwargs)
        calls.append(report)
        return report

    monkeypatch.setattr(redact_module, "verify_redacted_pdf_fresh_process", _spy)
    return calls


@pytest.mark.parametrize("needle, lines", [
    ("John Smith", [((40, 80), "John Smith"), ((40, 160), "Contact John Smith today")]),
    ("42", [((40, 80), "Total 42"), ((40, 160), "Page 42 of 99")]),
])
def test_text_repeated_elsewhere_redacts_and_verifies(
    tmp_path: Path, verify_calls: list[object], needle: str, lines: list
) -> None:
    src = _page_pdf(tmp_path / "src.pdf", lines)
    before = file_sha256(src)
    first = _hits(src, needle)[0]
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [RedactionRegion(0, tuple(first))], verify=True)

    assert file_sha256(src) == before
    assert out.resolve() != src.resolve()
    assert len(verify_calls) == 1 and verify_calls[0].ok
    remaining = _hits(out, needle)
    assert len(remaining) == 1 and remaining[0].y0 > first.y1
    doc = fitz.open(str(out))
    try:
        assert not doc[0].get_textbox(first).strip()
    finally:
        doc.close()


def test_tight_region_next_to_neighbouring_text_verifies(tmp_path: Path) -> None:
    src = _page_pdf(tmp_path / "src.pdf", [((40, 80), f"AAA {SECRET} BBB")])
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [RedactionRegion(0, _secret_rect(src))], verify=True)
    assert file_sha256(src) == before
    assert not _hits(out, SECRET)
    doc = fitz.open(str(out))
    try:
        text = doc[0].get_text()
    finally:
        doc.close()
    assert "AAA" in text and "BBB" in text


def test_extra_absent_is_checked_document_wide(tmp_path: Path) -> None:
    src = _page_pdf(tmp_path / "src.pdf", [((40, 80), "John Smith"), ((40, 160), "John Smith")])
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    with pytest.raises(RedactionVerifyError):
        redact_pdf(
            src, out, [RedactionRegion(0, tuple(_hits(src, "John Smith")[0]))],
            extra_absent=["John Smith"], verify=True,
        )
    assert not out.exists() and file_sha256(src) == before


def test_surviving_region_text_fails_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(redact_module, "_TEXT", fitz.PDF_REDACT_TEXT_NONE)
    with pytest.raises(RedactionVerifyError) as excinfo:
        redact_pdf(src, out, [RedactionRegion(0, _secret_rect(src))], verify=True)
    assert not out.exists()
    assert file_sha256(src) == before
    assert any("region" in f for f in excinfo.value.failures)


def _pattern_pixmap(white_left: int = 0, size: int = 64) -> fitz.Pixmap:
    """Non-uniform RGB pixmap, optionally with a plain white left margin."""
    data = bytearray()
    for y in range(size):
        for x in range(size):
            if x < white_left:
                data += b"\xff\xff\xff"
            else:
                data += bytes(((x * 7) % 256, (y * 13) % 256, ((x + y) * 5) % 256))
    return fitz.Pixmap(fitz.csRGB, size, size, bytes(data), False)


def _scanned_pdf(path: Path, tmp_path: Path, *, copies: int = 1, white_left: int = 0) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        pix = _pattern_pixmap(white_left)
        if copies == 1:
            page.insert_image(page.rect, pixmap=pix)
        else:
            for i in range(copies):
                page.insert_image(fitz.Rect(20 + i * 190, 40, 190 + i * 190, 200), pixmap=pix)
        doc.save(str(path))
        return path
    finally:
        doc.close()


def _page_image_digests(path: Path) -> list[str]:
    doc = fitz.open(str(path))
    try:
        return [i["digest"].hex() for i in doc[0].get_image_info(hashes=True)]
    finally:
        doc.close()


def test_scanned_page_region_replaces_image_and_verifies(
    tmp_path: Path, verify_calls: list[object]
) -> None:
    src = _scanned_pdf(tmp_path / "scan.pdf", tmp_path)
    before = file_sha256(src)
    original = _page_image_digests(src)
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [RedactionRegion(0, (50.0, 50.0, 200.0, 150.0))], verify=True)
    assert file_sha256(src) == before
    assert out.resolve() != src.resolve()
    assert len(verify_calls) == 1 and verify_calls[0].ok
    assert not set(original) & set(_page_image_digests(out))


def test_scanned_page_fails_when_image_not_redacted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = _scanned_pdf(tmp_path / "scan.pdf", tmp_path)
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(redact_module, "_IMAGES", fitz.PDF_REDACT_IMAGE_NONE)
    with pytest.raises(RedactionVerifyError) as excinfo:
        redact_pdf(src, out, [RedactionRegion(0, (50.0, 50.0, 200.0, 150.0))], verify=True)
    assert not out.exists()
    assert file_sha256(src) == before
    assert any("image" in f for f in excinfo.value.failures)


def test_cancel_during_verification_kills_child_and_deletes_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    token = CancelToken()
    spawned: list[subprocess.Popen[str]] = []
    real_popen = redact_module.popen_owned

    def _spawn(argv: list[str], **kwargs: object) -> subprocess.Popen[str]:
        proc = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        spawned.append(proc)
        token.cancel()  # cancel right after the child exists
        return proc

    monkeypatch.setattr(redact_module, "popen_owned", _spawn)
    with pytest.raises(JobCancelledError):
        redact_pdf(src, out, [RedactionRegion(0, _secret_rect(src))], verify=True, cancel=token)
    assert len(spawned) == 1 and spawned[0].poll() is not None
    assert not out.exists()
    assert file_sha256(src) == before


def test_region_over_white_scan_margin_verifies(tmp_path: Path, verify_calls: list[object]) -> None:
    src = _scanned_pdf(tmp_path / "scan.pdf", tmp_path, white_left=16)
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [RedactionRegion(0, (10.0, 50.0, 80.0, 150.0))], verify=True)
    assert file_sha256(src) == before and out.resolve() != src.resolve()
    assert len(verify_calls) == 1 and verify_calls[0].ok


def test_white_background_image_behind_text_verifies(
    tmp_path: Path, verify_calls: list[object]
) -> None:
    white = _png_rgb(tmp_path / "white.png", width=16, height=16, rgb=(255, 255, 255))
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=400, height=300)
        page.insert_image(page.rect, filename=str(white))
        page.insert_text((40, 80), f"Hello {SECRET} world", fontsize=14)
        doc.save(str(src))
    finally:
        doc.close()
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [RedactionRegion(0, _secret_rect(src))], verify=True)
    assert file_sha256(src) == before and out.resolve() != src.resolve()
    assert len(verify_calls) == 1 and verify_calls[0].ok
    assert not _hits(out, SECRET)


def test_repeated_image_one_copy_redacted_verifies_and_fails_when_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = _scanned_pdf(tmp_path / "tiles.pdf", tmp_path, copies=2)
    before = file_sha256(src)
    region = RedactionRegion(0, (40.0, 60.0, 120.0, 140.0))
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [region], verify=True)
    assert file_sha256(src) == before and out.resolve() != src.resolve()
    original = _page_image_digests(src)
    assert original[0] == original[1]
    assert _page_image_digests(out).count(original[0]) == 1

    monkeypatch.setattr(redact_module, "_IMAGES", fitz.PDF_REDACT_IMAGE_NONE)
    failed = tmp_path / "failed.pdf"
    with pytest.raises(RedactionVerifyError):
        redact_pdf(src, failed, [region], verify=True)
    assert not failed.exists() and file_sha256(src) == before


def _glyph_edge_pdf(path: Path) -> tuple[Path, fitz.Rect]:
    _page_pdf(path, [((40, 80), "ALPHA BRAVO CHARLIE")])
    word = _hits(path, "BRAVO")[0]
    # Reach 0.5pt into the glyphs on both sides (a space is about 3.9pt wide).
    return path, fitz.Rect(word.x0 - 4.4, word.y0, word.x1 + 4.4, word.y1)


def test_region_clipping_neighbouring_glyphs_verifies(
    tmp_path: Path, verify_calls: list[object]
) -> None:
    src, rect = _glyph_edge_pdf(tmp_path / "src.pdf")
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    redact_pdf(src, out, [RedactionRegion(0, tuple(rect))], verify=True)
    assert file_sha256(src) == before and out.resolve() != src.resolve()
    assert len(verify_calls) == 1 and verify_calls[0].ok
    doc = fitz.open(str(out))
    try:
        text = doc[0].get_text()
    finally:
        doc.close()
    assert "BRAVO" not in text and "ALPHA" in text and "CHARLIE" in text


def test_region_over_secret_fails_when_text_removal_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src, rect = _glyph_edge_pdf(tmp_path / "src.pdf")
    before = file_sha256(src)
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(redact_module, "_TEXT", fitz.PDF_REDACT_TEXT_NONE)
    with pytest.raises(RedactionVerifyError):
        redact_pdf(src, out, [RedactionRegion(0, tuple(rect))], verify=True)
    assert not out.exists() and file_sha256(src) == before


@pytest.mark.parametrize("failure", [OSError("spawn failed"), RuntimeError("boom")])
def test_verifier_launch_failure_deletes_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Exception
) -> None:
    src = _text_pdf(tmp_path / "src.pdf")
    before = file_sha256(src)
    out = tmp_path / "out.pdf"

    def _boom(*_a: object, **_k: object) -> None:
        raise failure

    monkeypatch.setattr(redact_module, "popen_owned", _boom)
    expected = RedactionVerifyError if isinstance(failure, OSError) else RuntimeError
    with pytest.raises(expected):
        redact_pdf(src, out, [RedactionRegion(0, _secret_rect(src))], verify=True)
    assert not out.exists()
    assert file_sha256(src) == before
