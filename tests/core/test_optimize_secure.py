"""Phase 27 core — compress, repair, encrypt/decrypt, sanitize."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from pagedrop.core import optimize_secure as ops
from pagedrop.core.jobs.errors import SourceOverwriteError
from pagedrop.core.jobs import JobSpec, SerializedJobRunner
from pagedrop.core.optimize_secure_jobs import register_optimize_secure_handlers
from pagedrop.core.pdf_tools import metadata_get, normalize_pdf_page_size
from pagedrop.utils.temp_manager import TempManager


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pdf(
    path: Path,
    *,
    text: str = "hello",
    title: str = "Secret Title",
    author: str = "Author",
) -> Path:
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), text, fontsize=18)
        doc.set_metadata({"title": title, "author": author, "creator": "PageDropTest"})
        doc.save(str(path))
        return path
    finally:
        doc.close()


def test_save_profiles_documented() -> None:
    assert set(ops.SAVE_PROFILES) == {"fast", "lossless", "max"}
    lossless = ops.resolve_save_profile("lossless")
    assert lossless.garbage == 3
    assert lossless.clean is True
    assert lossless.deflate is True
    assert ops.resolve_save_profile(lossless) is lossless
    with pytest.raises(ValueError, match="Unknown save profile"):
        ops.resolve_save_profile("linearize")  # type: ignore[arg-type]


def test_lossy_presets_documented_dpi_and_quality() -> None:
    assert set(ops.LOSSY_PROFILES) == {"screen", "ebook", "print"}
    screen = ops.resolve_lossy_profile("screen")
    assert screen.dpi == 72
    assert screen.jpeg_quality == 50
    assert screen.dpi_threshold == 100
    assert screen.dpi_threshold > screen.dpi
    ebook = ops.resolve_lossy_profile("ebook")
    assert ebook.dpi == 150 and ebook.jpeg_quality == 70
    print_p = ops.resolve_lossy_profile("print")
    assert print_p.dpi == 300 and print_p.jpeg_quality == 85
    assert ops.resolve_lossy_profile(screen) is screen
    with pytest.raises(ValueError, match="Unknown lossy profile"):
        ops.resolve_lossy_profile("ultra")  # type: ignore[arg-type]


def _make_image_heavy_pdf(path: Path, *, width: int = 2400, height: int = 3200) -> Path:
    """Embed a large RGB image so lossless deflate barely helps vs lossy JPEG."""
    # Low-periodicity samples so Flate stays large; JPEG+downsample wins.
    samples = bytearray(width * height * 3)
    for i in range(0, len(samples), 3):
        samples[i] = (i * 17 + (i >> 8)) % 256
        samples[i + 1] = (i * 31 + (i >> 4)) % 256
        samples[i + 2] = (i * 47 + i) % 256
    pix = fitz.Pixmap(fitz.csRGB, width, height, bytes(samples), 0)
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, pixmap=pix)
        doc.save(str(path), deflate=False)
        return path
    finally:
        doc.close()


def test_compress_never_overwrites_source(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)
    with pytest.raises(SourceOverwriteError):
        ops.compress_pdf(str(src), str(src))
    assert _file_hash(src) == source_hash


def test_compress_smoke_openable_and_source_unchanged(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="compress me " * 40)
    source_hash = _file_hash(src)
    out = tmp_path / "out.pdf"
    ops.compress_pdf(str(src), str(out), profile="lossless")
    assert _file_hash(src) == source_hash
    assert out.is_file()
    assert out.stat().st_size <= src.stat().st_size
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 1
        assert "compress" in doc[0].get_text()
    finally:
        doc.close()


def test_compress_lossy_screen_shrinks_image_heavy(tmp_path: Path) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf")
    source_hash = _file_hash(src)
    lossless_out = tmp_path / "lossless.pdf"
    lossy_out = tmp_path / "screen.pdf"
    ops.compress_pdf(str(src), str(lossless_out), profile="lossless")
    ops.compress_pdf(str(src), str(lossy_out), profile="screen")
    assert _file_hash(src) == source_hash
    assert lossy_out.stat().st_size < lossless_out.stat().st_size
    assert lossy_out.stat().st_size < src.stat().st_size
    with fitz.open(str(lossy_out)) as doc:
        assert doc.page_count == 1
        assert doc[0].get_images()


def test_compress_job_handler_accepts_lossy_profile_params(tmp_path: Path) -> None:
    src = _make_image_heavy_pdf(tmp_path / "scan.pdf")
    source_hash = _file_hash(src)
    out = tmp_path / "job_out.pdf"
    temp = TempManager()
    try:
        runner = SerializedJobRunner(temp)
        register_optimize_secure_handlers(runner)
        runner.run(
            JobSpec.create(
                "compress",
                inputs=[str(src)],
                output=str(out),
                options={
                    "profile": "screen",
                    "dpi": 72,
                    "jpeg_quality": 40,
                    "dpi_threshold": 100,
                },
            )
        )
    finally:
        temp.cleanup()
    assert _file_hash(src) == source_hash
    assert out.is_file()
    assert out.stat().st_size < src.stat().st_size
    with fitz.open(str(out)) as doc:
        assert doc.page_count == 1


def test_repair_rewrite_surfaces_is_repaired(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)
    out = tmp_path / "repaired.pdf"
    result = ops.repair_pdf(str(src), str(out))
    assert result.output_path == str(out)
    assert isinstance(result.was_repaired, bool)
    # Clean synthetic PDFs are typically not repaired.
    assert result.was_repaired is False
    assert _file_hash(src) == source_hash
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 1
    finally:
        doc.close()


def test_encrypt_round_trip_and_wrong_password(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf", text="classified")
    source_hash = _file_hash(src)
    enc = tmp_path / "enc.pdf"
    ops.encrypt_pdf(
        str(src),
        str(enc),
        user_password="user-secret",
        owner_password="owner-secret",
        permissions=ops.PdfPermissions(allow_print=True, allow_copy=False),
    )
    assert _file_hash(src) == source_hash

    locked = fitz.open(str(enc))
    try:
        assert locked.needs_pass
        assert locked.authenticate("wrong") == 0
        assert locked.authenticate("user-secret") != 0
        assert "classified" in locked[0].get_text()
    finally:
        locked.close()

    dec = tmp_path / "dec.pdf"
    ops.decrypt_pdf(str(enc), str(dec), password="user-secret")
    unlocked = fitz.open(str(dec))
    try:
        assert not unlocked.needs_pass
        assert "classified" in unlocked[0].get_text()
    finally:
        unlocked.close()
    assert _file_hash(src) == source_hash


def test_encrypt_rejects_empty_password(tmp_path: Path) -> None:
    src = _make_pdf(tmp_path / "src.pdf")
    with pytest.raises(ValueError, match="user_password"):
        ops.encrypt_pdf(str(src), str(tmp_path / "out.pdf"), user_password="")


def test_sanitize_metadata_and_optional_annotations(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=200, height=200)
        page.insert_text((40, 80), "keep text", fontsize=18)
        page.add_highlight_annot(fitz.Rect(30, 60, 120, 90))
        doc.set_metadata(
            {"title": "Drop Me", "author": "Secret", "subject": "subj", "keywords": "k"}
        )
        doc.set_xml_metadata("<x:xmpmeta xmlns:x='adobe:ns:meta/'/>")
        doc.save(str(src))
    finally:
        doc.close()
    source_hash = _file_hash(src)

    meta_only = tmp_path / "meta.pdf"
    ops.sanitize_pdf(str(src), str(meta_only), strip_annotations=False)
    assert _file_hash(src) == source_hash
    cleaned = metadata_get(str(meta_only))
    assert cleaned.get("title") in ("", None)
    assert cleaned.get("author") in ("", None)
    with fitz.open(str(meta_only)) as out:
        assert out.get_xml_metadata() in ("", None)
        assert list(out[0].annots() or [])  # annotations kept

    scrubbed = tmp_path / "scrubbed.pdf"
    ops.sanitize_pdf(str(src), str(scrubbed), strip_annotations=True)
    with fitz.open(str(scrubbed)) as out:
        assert list(out[0].annots() or []) == []
        assert "keep text" in out[0].get_text()
    assert _file_hash(src) == source_hash


def test_fix_page_size_covered_by_phase24(tmp_path: Path) -> None:
    """Phase 27 reuses Phase 24 normalize — not a second implementation."""
    src = _make_pdf(tmp_path / "src.pdf")
    source_hash = _file_hash(src)
    out = tmp_path / "sized.pdf"
    normalize_pdf_page_size(str(src), str(out), 300, 400, strategy="fit")
    assert _file_hash(src) == source_hash
    with fitz.open(str(out)) as doc:
        rect = doc[0].rect
        assert abs(rect.width - 300) < 0.5
        assert abs(rect.height - 400) < 0.5
