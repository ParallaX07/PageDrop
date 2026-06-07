"""Phase 12 unit tests — PdfEditModel."""

from __future__ import annotations

from pagedrop.core.pdf_editor import PageRef, PdfEditModel


def _refs(path: str, count: int) -> list[PageRef]:
    return [PageRef(path, index) for index in range(count)]


def test_initial_model_matches_source_page_count():
    model = PdfEditModel("/docs/report.pdf", 5)
    assert model.logical_count() == 5
    assert model.original_path == "/docs/report.pdf"
    assert model.save_path is None
    assert not model.is_dirty()
    for index in range(5):
        ref = model.page_at(index)
        assert ref.source_path == "/docs/report.pdf"
        assert ref.source_index == index


def test_insert_pages_at_index():
    model = PdfEditModel("/a.pdf", 2)
    inserted = _refs("/b.pdf", 3)
    model.insert_pages(1, inserted)
    assert model.logical_count() == 5
    assert model.page_at(0).source_index == 0
    assert model.page_at(1).source_path == "/b.pdf"
    assert model.page_at(3).source_index == 2
    assert model.page_at(4).source_index == 1


def test_remove_pages():
    model = PdfEditModel("/a.pdf", 5)
    model.remove_pages([1, 3])
    assert model.logical_count() == 3
    assert [model.page_at(i).source_index for i in range(3)] == [0, 2, 4]


def test_move_pages_changes_order():
    model = PdfEditModel("/a.pdf", 5)
    model.move_pages([3, 4], 1)
    assert [model.page_at(i).source_index for i in range(5)] == [0, 3, 4, 1, 2]


def test_move_up_down():
    model = PdfEditModel("/a.pdf", 5)
    model.move_up([2])
    assert [model.page_at(i).source_index for i in range(5)] == [0, 2, 1, 3, 4]

    model.move_down([1])
    assert [model.page_at(i).source_index for i in range(5)] == [0, 1, 2, 3, 4]


def test_is_dirty_after_edit():
    model = PdfEditModel("/a.pdf", 3)
    assert not model.is_dirty()
    model.remove_pages([0])
    assert model.is_dirty()


def test_mark_saved_clears_dirty():
    model = PdfEditModel("/a.pdf", 3)
    model.remove_pages([0])
    assert model.is_dirty()
    model.mark_saved("/out/saved.pdf")
    assert not model.is_dirty()
    assert model.save_path == "/out/saved.pdf"
