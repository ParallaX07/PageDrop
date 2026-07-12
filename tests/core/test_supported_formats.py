"""Phase 19 unit tests — supported image formats."""

from __future__ import annotations

from pagedrop.core.supported_formats import (
    SUPPORTED_IMAGE_EXTENSIONS,
    image_paths_from_mime,
    is_pdf_path,
    is_supported_image,
    local_paths_from_mime,
    pdf_paths_from_mime,
)


class _FakeUrl:
    def __init__(self, path: str, *, local: bool = True) -> None:
        self._path = path
        self._local = local

    def isLocalFile(self) -> bool:
        return self._local

    def toLocalFile(self) -> str:
        return self._path


class _FakeMime:
    def __init__(self, paths: list[str]) -> None:
        self._urls = [_FakeUrl(path) for path in paths]

    def hasUrls(self) -> bool:
        return bool(self._urls)

    def urls(self) -> list[_FakeUrl]:
        return self._urls


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


def test_local_paths_from_mime_filters(tmp_path):
    png = str(tmp_path / "a.png")
    pdf = str(tmp_path / "b.pdf")
    txt = str(tmp_path / "c.txt")
    mime = _FakeMime([pdf, png, txt])

    assert local_paths_from_mime(mime) == [pdf, png, txt]
    assert image_paths_from_mime(mime) == [png]
    assert pdf_paths_from_mime(mime) == [pdf]
