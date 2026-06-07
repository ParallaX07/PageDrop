"""Phase 19 unit tests — supported image formats."""

from __future__ import annotations

from pagedrop.core.supported_formats import (
    SUPPORTED_IMAGE_EXTENSIONS,
    is_pdf_path,
    is_supported_image,
)


def test_supported_image_extensions(tmp_path):
    for ext in SUPPORTED_IMAGE_EXTENSIONS:
        path = tmp_path / f"sample{ext}"
        path.touch()
        assert is_supported_image(path)

    upper = tmp_path / "photo.PNG"
    upper.touch()
    assert is_supported_image(upper)


def test_rejects_pdf_extension(tmp_path):
    pdf = tmp_path / "document.pdf"
    pdf.touch()

    assert not is_supported_image(pdf)
    assert is_pdf_path(pdf)
    assert not is_pdf_path(tmp_path / "photo.png")
