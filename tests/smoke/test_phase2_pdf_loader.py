"""Phase 2 smoke tests — PdfLoader end-to-end sanity."""

from __future__ import annotations

from pathlib import Path

import pytest

from pagedrop.core.pdf_loader import PdfLoader


@pytest.fixture
def render_output_dir(tmp_path):
    output = tmp_path / "renders"
    output.mkdir()
    yield output


def test_smoke_render_all_pages_to_disk(five_page_pdf, render_output_dir):
    loader = PdfLoader(str(five_page_pdf))
    try:
        assert loader.page_count == 5
        for index in range(loader.page_count):
            png = loader.render_page(index)
            assert png[:4] == b"\x89PNG"
            out_file = render_output_dir / f"page_{index}.png"
            out_file.write_bytes(png)
            assert out_file.stat().st_size > 0
    finally:
        loader.close()


def test_smoke_core_tests_reachable():
    """Ensure core loader test module imports (included in phase 2 gate)."""
    import tests.core.test_pdf_loader as core_tests  # noqa: F401

    assert hasattr(core_tests, "test_page_count")
