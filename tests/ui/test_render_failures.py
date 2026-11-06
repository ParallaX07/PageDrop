"""A page that cannot be rendered never blocks the rest, and is reported once."""

from __future__ import annotations

import shutil

import pytest
from PyQt6.QtWidgets import QMessageBox

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_loader import PdfLoader
from pagedrop.ui import thumbnail_grid as thumbnail_grid_module
from pagedrop.ui.thumbnail_grid import ThumbnailGrid
from tests.conftest import file_sha256, wait_for_grid_loaded


def _has_thumbnail(grid: ThumbnailGrid, index: int) -> bool:
    return grid._cards[index]._source_pixmap is not None


def _mixed_grid(qtbot, tmp_path, five_page_pdf, *, delete_second: bool):
    """Pages 0,2,4 come from a good file; pages 1,3 from a second file."""
    good = tmp_path / "good.pdf"
    second = tmp_path / "second.pdf"
    shutil.copy(five_page_pdf, good)
    shutil.copy(five_page_pdf, second)
    refs = [
        PageRef(str(good), 0),
        PageRef(str(second), 0),
        PageRef(str(good), 1),
        PageRef(str(second), 1),
        PageRef(str(good), 2),
    ]
    model = PdfEditModel.with_pages(str(good), refs)
    grid = ThumbnailGrid()
    qtbot.addWidget(grid)
    grid.resize(900, 650)
    grid.show()
    if delete_second:
        second.unlink()
    errors: list[str] = []
    grid.rendering_error.connect(errors.append)
    grid.load_model(model, lambda path: PdfLoader(path))
    return grid, second, errors


@pytest.fixture
def modal_calls(monkeypatch):
    calls: list[str] = []
    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(
            QMessageBox,
            name,
            staticmethod(lambda *args, _n=name, **kwargs: calls.append(_n)),
        )
    return calls


def test_missing_source_does_not_block_other_pages(
    qtbot, tmp_path, five_page_pdf, modal_calls
):
    grid, _second, errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=True
    )
    wait_for_grid_loaded(qtbot, grid)

    assert [_has_thumbnail(grid, i) for i in range(5)] == [
        True, False, True, False, True
    ]
    assert len(errors) == 1
    assert modal_calls == []


def test_source_deleted_mid_session_notifies_once_across_zooms(
    qtbot, tmp_path, five_page_pdf, modal_calls
):
    grid, second, errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=False
    )
    wait_for_grid_loaded(qtbot, grid)
    assert errors == []
    assert all(_has_thumbnail(grid, i) for i in range(5))

    second.unlink()
    for width in (grid.thumbnail_width_px + 40, grid.thumbnail_width_px + 80):
        grid.set_thumbnail_zoom(width)
        wait_for_grid_loaded(qtbot, grid)
        target = grid._target_render_width()
        assert grid._page_render_width == [target] * 5

    assert len(errors) == 1
    assert modal_calls == []
    # Pages that still render were refreshed at the new width.
    assert all(_has_thumbnail(grid, i) for i in (0, 2, 4))


def test_failed_page_is_not_requested_again_at_same_width(
    qtbot, tmp_path, five_page_pdf, monkeypatch
):
    requested: list[tuple[str, int, int]] = []
    real = thumbnail_grid_module.render_ref_png

    def spy(ref, width_px, **kwargs):
        requested.append((ref.source_path, ref.source_index, width_px))
        return real(ref, width_px, **kwargs)

    monkeypatch.setattr(thumbnail_grid_module, "render_ref_png", spy)
    grid, second, _errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=True
    )
    wait_for_grid_loaded(qtbot, grid)
    first_width = grid._target_render_width()
    failed = [r for r in requested if r[0] == str(second)]
    assert {r[2] for r in failed} == {first_width}

    # Same width: scrolling or a follow-up pass must not retry the failed pages.
    requested.clear()
    assert grid._pages_needing_render() == []
    grid._start_rendering(silent=True, page_indices=list(range(5)))
    grid._render_zoom_quality()
    wait_for_grid_loaded(qtbot, grid)
    assert requested == []

    # A new width is a fresh attempt.
    grid.set_thumbnail_zoom(grid.thumbnail_width_px + 40)
    wait_for_grid_loaded(qtbot, grid)
    retried = {(r[0], r[1]) for r in requested if r[0] == str(second)}
    assert retried == {(str(second), 0), (str(second), 1)}
    assert {r[2] for r in requested} == {grid._target_render_width()}


def test_undecodable_png_counts_as_failed_page(qtbot, tmp_path, five_page_pdf, monkeypatch):
    real = thumbnail_grid_module.render_ref_png

    def garbage_for_page_1(ref, width_px, **kwargs):
        if ref.source_index == 1:
            return b"not a png"
        return real(ref, width_px, **kwargs)

    monkeypatch.setattr(thumbnail_grid_module, "render_ref_png", garbage_for_page_1)
    grid, _second, errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=False
    )
    wait_for_grid_loaded(qtbot, grid)

    assert not _has_thumbnail(grid, 2)
    assert not _has_thumbnail(grid, 3)
    assert all(_has_thumbnail(grid, i) for i in (0, 1, 4))
    assert len(errors) == 1
    assert grid._pages_needing_render() == []


def test_reload_of_same_model_does_not_notify_again(qtbot, tmp_path, five_page_pdf):
    grid, _second, errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=True
    )
    wait_for_grid_loaded(qtbot, grid)
    assert len(errors) == 1

    grid.load_model(grid._model, grid._get_loader)
    wait_for_grid_loaded(qtbot, grid)

    assert grid._page_render_width[1] > 0  # the failing pages were attempted again
    assert len(errors) == 1


def test_different_model_can_notify_again(qtbot, tmp_path, five_page_pdf):
    grid, _second, errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=True
    )
    wait_for_grid_loaded(qtbot, grid)
    assert len(errors) == 1

    grid.load_model(grid_model_for_missing(tmp_path), lambda path: PdfLoader(path))
    wait_for_grid_loaded(qtbot, grid)
    assert len(errors) == 2

    grid.clear()
    grid.load_model(grid_model_for_missing(tmp_path), lambda path: PdfLoader(path))
    wait_for_grid_loaded(qtbot, grid)
    assert len(errors) == 3


def test_failed_page_is_static_not_a_pulsing_skeleton(
    qtbot, tmp_path, five_page_pdf
):
    grid, second, _errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=True
    )
    wait_for_grid_loaded(qtbot, grid)

    failed = [grid._cards[1], grid._cards[3]]
    assert all(card._failed and not card._is_skeleton for card in failed)
    assert all(card._skeleton_pulse_anim is None for card in grid._cards)
    assert grid._skeleton_count == 0
    assert not grid._skeleton_pulse_active
    assert failed[0]._thumbnail_label.text() == "Page unavailable"
    assert "Page unavailable" in failed[0].accessibleDescription()

    # The file comes back and the width changes: the page renders normally.
    shutil.copy(five_page_pdf, second)
    grid.set_thumbnail_zoom(grid.thumbnail_width_px + 40)
    wait_for_grid_loaded(qtbot, grid)
    assert all(_has_thumbnail(grid, i) for i in range(5))
    assert not failed[0]._failed
    assert failed[0]._thumbnail_label.text() == ""
    assert "Page unavailable" not in failed[0].accessibleDescription()


def test_releasing_a_failed_card_returns_it_to_a_normal_skeleton(
    qtbot, tmp_path, five_page_pdf
):
    grid, _second, _errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=True
    )
    wait_for_grid_loaded(qtbot, grid)
    card = grid._cards[1]

    card.release_thumbnail()

    assert card._is_skeleton and not card._failed
    assert card._thumbnail_label.text() == ""
    assert "Page unavailable" not in card.accessibleDescription()


def grid_model_for_missing(tmp_path) -> PdfEditModel:
    missing = str(tmp_path / "never-existed.pdf")
    return PdfEditModel.with_pages(missing, [PageRef(missing, 0)])


def test_render_failure_shows_toast_not_modal(
    main_window, qtbot, five_page_pdf, tmp_path, modal_calls, monkeypatch
):
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window,
        "_show_toast",
        lambda message, *, kind="info", on_undo=None: toasts.append((message, kind)),
    )
    tab = main_window._active_tab()
    source_hash = file_sha256(five_page_pdf)
    tab.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, tab.thumbnail_grid)

    tab.thumbnail_grid.rendering_error.emit("Page 2: gone")

    assert [kind for _message, kind in toasts] == ["error"]
    assert modal_calls == []
    assert "Page 2: gone" in main_window._status_by_page[tab]
    assert file_sha256(five_page_pdf) == source_hash


def test_render_failure_on_inactive_tab_is_still_reported(
    main_window, qtbot, five_page_pdf, one_page_pdf, modal_calls, monkeypatch
):
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window,
        "_show_toast",
        lambda message, *, kind="info", on_undo=None: toasts.append((message, kind)),
    )
    first = main_window._active_tab()
    first.load_pdf(str(five_page_pdf))
    wait_for_grid_loaded(qtbot, first.thumbnail_grid)
    second = main_window._tab_manager.add_blank_tab()
    main_window._tab_manager.setCurrentWidget(second)
    assert main_window._active_tab() is second

    first.thumbnail_grid.rendering_error.emit("Page 1: gone")

    assert [kind for _message, kind in toasts] == ["error"]
    assert modal_calls == []


def test_failed_card_style_comes_from_a_property_not_a_palette(
    qtbot, tmp_path, five_page_pdf
):
    grid, _second, _errors = _mixed_grid(
        qtbot, tmp_path, five_page_pdf, delete_second=True
    )
    wait_for_grid_loaded(qtbot, grid)
    failed_label = grid._cards[1]._thumbnail_label
    ok_label = grid._cards[0]._thumbnail_label
    assert failed_label.property("failed") is True
    assert not ok_label.property("failed")

    grid._cards[1].release_thumbnail()
    assert failed_label.property("failed") is False
