"""Status floats over the active content instead of living in a bottom bar."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent, QStatusTipEvent
from PyQt6.QtWidgets import QApplication, QWidget

import pagedrop.ui.main_window as main_window_module
from pagedrop.core.drag_mime import (
    INTERNAL_PAGE_MIME,
    PAGE_TRANSFER_MIME,
    encode_page_indices,
    encode_page_refs,
)
from pagedrop.ui.floating_status import FLOAT_GAP, FLOAT_MARGIN
from pagedrop.ui.page_card import PageCard
from tests.conftest import wait_for_pdf_loaded
from tests.fixtures.generate_fixtures import generate_n_page


def _open(main_window, pdf, qtbot, *, width: int = 1200, height: int = 700):
    main_window._load_pdf(str(pdf))
    wait_for_pdf_loaded(qtbot, main_window, timeout=15000)
    main_window.resize(width, height)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    tab = main_window._active_tab()
    # The floating items are placed once the area has its real size.
    qtbot.waitUntil(lambda: main_window._thumbnail_zoom_host.isVisible())
    # Fitting the columns reports the new size; let that settle first.
    grid = tab.thumbnail_grid
    qtbot.waitUntil(lambda: not grid._autofit_pending and not grid._autofit_timer.isActive())
    qtbot.waitUntil(lambda: main_window._floating.message() == "", timeout=10000)
    return tab


def _area(main_window) -> QRect:
    """The active content area in the coordinates of the tab area."""
    stack = main_window._active_tab().content_stack
    return QRect(stack.mapTo(main_window._tab_manager, QPoint(0, 0)), stack.size())


def _pill(main_window):
    return main_window._floating.pill


def _file_mime(pdf) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(pdf))])
    return mime


def _drop(
    target: QWidget,
    mime: QMimeData,
    pos: QPoint,
    action: Qt.DropAction = Qt.DropAction.CopyAction,
) -> QDropEvent:
    """Drag in, then drop, the way the window system delivers them."""
    args = (QPointF(pos), action, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    enter = QDragEnterEvent(pos, *args[1:])
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted()
    drop = QDropEvent(*args)
    QApplication.sendEvent(target, drop)
    return drop


# --- the bar is gone ---------------------------------------------------------


def test_status_bar_is_hidden_in_grid_and_pages_view(main_window, five_page_pdf, qtbot):
    tab = _open(main_window, five_page_pdf, qtbot)
    assert main_window.statusBar().isHidden()
    assert not main_window.statusBar().isVisible()

    tab.show_preview_at(0)
    main_window._sync_toolbar_from_active_tab()
    assert main_window.statusBar().isHidden()
    assert not main_window.statusBar().isVisible()
    # The bar still stores the latest text for anything that reads it.
    main_window._idle_status("Page 1 of 5")
    assert main_window.statusBar().currentMessage() == "Page 1 of 5"


# --- what floats -------------------------------------------------------------


def test_transient_message_floats_then_clears(main_window, five_page_pdf, qtbot, monkeypatch):
    monkeypatch.setattr(main_window_module, "STATUS_TRANSIENT_MS", 30)
    _open(main_window, five_page_pdf, qtbot)
    assert main_window._floating.message() == ""
    assert not _pill(main_window).isVisible()

    main_window._transient_status("Rotated 1 page left")
    assert _pill(main_window).isVisible()
    assert main_window._floating.message() == "Rotated 1 page left"
    assert main_window.statusBar().currentMessage() == "Rotated 1 page left"

    qtbot.waitUntil(lambda: not _pill(main_window).isVisible())
    assert main_window._floating.message() == ""


def test_progress_message_stays_until_replaced(main_window, five_page_pdf, qtbot, monkeypatch):
    monkeypatch.setattr(main_window_module, "STATUS_TRANSIENT_MS", 30)
    _open(main_window, five_page_pdf, qtbot)

    main_window._persistent_status("Rendering page 3 of 8…")
    assert not main_window._transient_status_timer.isActive()
    assert main_window._floating.message() == "Rendering page 3 of 8…"
    # Longer than the dismiss interval: still there.
    qtbot.wait(120)
    assert _pill(main_window).isVisible()

    main_window._persistent_status("Rendering page 4 of 8…")
    assert main_window._floating.message() == "Rendering page 4 of 8…"

    main_window._idle_status("Loaded 8 pages")
    assert not _pill(main_window).isVisible()
    assert main_window.statusBar().currentMessage() == "Loaded 8 pages"


def test_persistent_message_without_ellipsis_dismisses_itself(
    main_window, five_page_pdf, qtbot, monkeypatch
):
    monkeypatch.setattr(main_window_module, "STATUS_TRANSIENT_MS", 30)
    _open(main_window, five_page_pdf, qtbot)

    main_window._persistent_status("Saved to copy.pdf")
    assert main_window._floating.message() == "Saved to copy.pdf"
    assert main_window._transient_status_timer.isActive()
    qtbot.waitUntil(lambda: not _pill(main_window).isVisible())


def test_idle_text_never_floats_and_clears_a_message(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot)
    for text in ("Ready", "Loaded 5 pages", "Page 2 of 5"):
        main_window._idle_status(text)
        assert not _pill(main_window).isVisible()
        assert main_window.statusBar().currentMessage() == text

    main_window._transient_status("Deleted 1 page")
    assert _pill(main_window).isVisible()
    main_window._restore_active_status()
    assert not _pill(main_window).isVisible()
    # The timer's idle text is what the bar holds afterwards.
    assert main_window.statusBar().currentMessage() == "Deleted 1 page"


def test_hover_status_tip_does_not_float(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot)
    QApplication.sendEvent(main_window, QStatusTipEvent("Rotate the selected pages left"))
    assert main_window.statusBar().currentMessage() == "Rotate the selected pages left"
    assert not _pill(main_window).isVisible()

    main_window._transient_status("Rotated 1 page left")
    QApplication.sendEvent(main_window, QStatusTipEvent("Delete the selected pages"))
    # The outcome stays; the hover text is only stored.
    assert main_window._floating.message() == "Rotated 1 page left"


def test_size_readout_text_does_not_float(main_window, five_page_pdf, qtbot, monkeypatch):
    tab = _open(main_window, five_page_pdf, qtbot)
    floated: list[str] = []
    original = main_window._floating.show_message
    monkeypatch.setattr(
        main_window._floating, "show_message", lambda text: floated.append(text) or original(text)
    )
    main_window._transient_status("Rotated 1 page left")
    new_size = tab.zoom_level + 40
    tab.set_zoom_level(new_size, manual=True)
    # The control already shows the size, so its message replaces the notice quietly.
    qtbot.waitUntil(lambda: not _pill(main_window).isVisible())
    assert not [text for text in floated if text.startswith("Thumbnail size")]
    assert main_window._zoom_controls._value_label.text() == f"{new_size}px"


def test_dragging_a_card_without_a_document_floats_the_notice(main_window, qtbot):
    card = PageCard(0, main_window)
    qtbot.addWidget(card)
    card._drag_start_pos = QPoint(0, 0)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(4, 4),
        QPointF(4, 4),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(card, move)
    assert main_window.statusBar().currentMessage() == "Open a PDF first"
    assert main_window._floating.message() == "Open a PDF first"


def test_toast_carries_the_message_alone(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot)
    main_window._transient_status("Duplicated 2 pages")
    assert _pill(main_window).isVisible()
    main_window._show_toast("Duplicated 2 pages", kind="success")
    assert main_window._toast.isVisible()
    assert not _pill(main_window).isVisible()
    # The stored status is untouched.
    assert main_window.statusBar().currentMessage() == "Duplicated 2 pages"
    assert main_window._status_by_page[main_window._active_tab()] == "Duplicated 2 pages"


def test_switching_tabs_clears_the_message(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot)
    first = main_window._active_tab()
    main_window._new_blank_tab()
    second = main_window._active_tab()
    assert second is not first

    main_window._transient_status("Duplicated 2 pages")
    assert _pill(main_window).isVisible()
    main_window._tab_manager.setCurrentWidget(first)
    assert not _pill(main_window).isVisible()
    # The stored text per page keeps working as before.
    assert main_window._status_by_page[second] == "Duplicated 2 pages"


# --- where it floats ---------------------------------------------------------


def test_floating_items_sit_inside_the_active_content_area(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot)
    main_window._transient_status("Duplicated 2 pages")
    area = _area(main_window)
    pill = _pill(main_window).geometry()
    host = main_window._thumbnail_zoom_host.geometry()

    assert area.contains(pill) and area.contains(host)
    assert pill.center().x() == pytest.approx(area.center().x(), abs=1)
    assert area.bottom() + 1 - pill.bottom() - 1 == FLOAT_MARGIN
    assert area.right() + 1 - host.right() - 1 == FLOAT_MARGIN
    assert area.bottom() + 1 - host.bottom() - 1 == FLOAT_MARGIN
    # Side panes are excluded, so the area is narrower than the whole tab.
    assert area.width() < main_window._tab_manager.width()


def test_floating_items_follow_a_sidebar_closing(main_window, five_page_pdf, qtbot):
    tab = _open(main_window, five_page_pdf, qtbot)
    main_window._transient_status("Duplicated 2 pages")
    before_area = _area(main_window)
    before_host = main_window._thumbnail_zoom_host.geometry()

    tab.set_workspace_pane_visible("document", False)
    qtbot.waitUntil(lambda: _area(main_window).width() > before_area.width())

    area = _area(main_window)
    host = main_window._thumbnail_zoom_host.geometry()
    qtbot.waitUntil(lambda: main_window._thumbnail_zoom_host.geometry().right() > before_host.right())
    host = main_window._thumbnail_zoom_host.geometry()
    assert area.contains(host)
    assert area.right() + 1 - host.right() - 1 == FLOAT_MARGIN
    assert _pill(main_window).geometry().center().x() == pytest.approx(area.center().x(), abs=1)

    tab.set_workspace_pane_visible("sections", False)
    qtbot.waitUntil(lambda: _area(main_window).left() < area.left())
    area = _area(main_window)
    assert _pill(main_window).geometry().center().x() == pytest.approx(area.center().x(), abs=1)


def test_short_message_is_one_line_and_a_long_one_wraps_inside_the_area(
    main_window, five_page_pdf, qtbot
):
    _open(main_window, five_page_pdf, qtbot, width=1280)
    label = main_window._floating._label
    line = label.fontMetrics().lineSpacing()

    main_window._transient_status("Markup added. Save As to keep")
    qtbot.waitUntil(lambda: label.height() > 0)
    assert label.height() < 2 * line
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()

    main_window.resize(480, 700)
    long_text = "Extracted 3 pages to a new window and kept the original open as well. " * 2
    main_window._transient_status(long_text)
    qtbot.waitUntil(lambda: label.height() >= 2 * line)
    assert _area(main_window).contains(_pill(main_window).geometry())
    assert _pill(main_window).width() <= _area(main_window).width() - 2 * FLOAT_MARGIN


def test_message_stacks_above_the_size_control_when_they_would_overlap(
    main_window, five_page_pdf, qtbot
):
    _open(main_window, five_page_pdf, qtbot, width=1200)
    main_window._transient_status("Duplicated 2 pages")
    pill = _pill(main_window)
    host = main_window._thumbnail_zoom_host
    # Wide: beside each other on the same baseline.
    assert pill.geometry().bottom() == host.geometry().bottom()
    assert not pill.geometry().intersects(host.geometry())

    main_window.resize(560, 700)
    main_window._transient_status("Extracted 3 pages to new window and kept the original")
    qtbot.waitUntil(lambda: pill.geometry().bottom() < host.geometry().top())
    assert not pill.geometry().intersects(host.geometry())
    assert _area(main_window).contains(pill.geometry())


def test_toast_clears_the_size_control(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot, width=560)
    host = main_window._thumbnail_zoom_host
    assert host.isVisible()
    main_window._show_toast(
        "Extracted 3 pages to a new window and kept the original document", kind="success"
    )
    toast = main_window._toast
    qtbot.waitUntil(lambda: toast.isVisible() and toast.motion_t == 0.0)
    card = toast.findChild(QWidget, "ToastOverlayCard")

    def _rect(widget: QWidget) -> QRect:
        return QRect(widget.mapTo(main_window, QPoint(0, 0)), widget.size())

    assert not _rect(card).intersects(_rect(host))
    assert _rect(host).top() - _rect(card).bottom() - 1 >= FLOAT_GAP


def test_size_control_floats_only_in_the_grid_with_a_document(
    main_window, five_page_pdf, qtbot
):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert main_window._thumbnail_zoom_host.isHidden()

    tab = _open(main_window, five_page_pdf, qtbot)
    assert main_window._thumbnail_zoom_host.isVisible()
    assert main_window._thumbnail_zoom_host.parentWidget() is main_window._tab_manager

    tab.show_preview_at(0)
    main_window._sync_toolbar_from_active_tab()
    assert main_window._thumbnail_zoom_host.isHidden()

    tab.close_preview()
    main_window._sync_toolbar_from_active_tab()
    assert main_window._thumbnail_zoom_host.isVisible()

    main_window._new_blank_tab()
    assert main_window._thumbnail_zoom_host.isHidden()


def test_tool_tab_floats_over_its_whole_page(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    page = QWidget()
    page.tab_title = "Demo tool"
    main_window.open_tool_page(page, page_id="demo-tool")
    assert main_window._floating_anchor() is page

    main_window._transient_status("Something happened")
    qtbot.waitUntil(lambda: _pill(main_window).isVisible())
    origin = page.mapTo(main_window._tab_manager, QPoint(0, 0))
    area = QRect(origin, page.size())
    assert area.contains(_pill(main_window).geometry())
    assert main_window._thumbnail_zoom_host.isHidden()


def test_anchor_follows_the_active_tab_and_survives_a_closed_tab(
    main_window, five_page_pdf, qtbot
):
    first = _open(main_window, five_page_pdf, qtbot)
    main_window._new_blank_tab()
    second = main_window._active_tab()
    assert main_window._floating._anchor is second.content_stack

    main_window._tab_manager.close_tab(main_window._tab_manager.indexOf(second))
    assert main_window._active_tab() is first
    assert main_window._floating._anchor is first.content_stack
    main_window._transient_status("Tab closed")
    assert _area(main_window).contains(_pill(main_window).geometry())


# --- mouse and drops ---------------------------------------------------------


def test_message_does_not_block_clicks_or_drops(
    main_window, five_page_pdf, qtbot, monkeypatch, tmp_path
):
    tab = _open(main_window, five_page_pdf, qtbot)
    grid = tab.thumbnail_grid
    main_window._transient_status("Duplicated 2 pages")
    pill = _pill(main_window)
    assert pill.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    point = pill.geometry().center()
    hit = main_window._tab_manager.childAt(point)
    assert hit is not None and hit is not pill and not pill.isAncestorOf(hit)
    assert tab.content_stack.isAncestorOf(hit)

    inserted: list[tuple[list[str], int]] = []
    monkeypatch.setattr(
        grid, "insert_pdf_pages", lambda paths, index: inserted.append((paths, index)) or True
    )
    extra = tmp_path / "extra.pdf"
    generate_n_page(extra, 2)
    # The window system hands a drop to the nearest widget that accepts them.
    target = hit
    while not target.acceptDrops():
        target = target.parentWidget()
    spot = target.mapFromGlobal(main_window._tab_manager.mapToGlobal(point))
    event = _drop(target, _file_mime(extra), spot)
    assert event.isAccepted()
    assert [paths for paths, _index in inserted] == [[extra.as_posix()]]


def test_size_control_forwards_a_file_drop_to_the_grid(
    main_window, five_page_pdf, qtbot, monkeypatch, tmp_path
):
    tab = _open(main_window, five_page_pdf, qtbot)
    grid = tab.thumbnail_grid
    host = main_window._thumbnail_zoom_host
    extra = tmp_path / "extra.pdf"
    generate_n_page(extra, 2)

    inserted: list[tuple[list[str], int]] = []
    monkeypatch.setattr(
        grid, "insert_pdf_pages", lambda paths, index: inserted.append((paths, index)) or True
    )
    spot = QPoint(host.width() // 2, host.height() // 2)
    event = _drop(host, _file_mime(extra), spot)
    assert event.isAccepted()
    assert [paths for paths, _index in inserted] == [[extra.as_posix()]]

    # The pointer is mapped into the grid, not left in the control's own corner.
    mapped = grid.viewport().mapFromGlobal(host.mapToGlobal(spot))
    expected = grid.drop_index_at_pos(grid._container.mapFrom(grid, mapped))
    assert inserted[0][1] == expected


def test_size_control_forwards_page_drags_to_the_grid(
    main_window, five_page_pdf, qtbot, monkeypatch
):
    tab = _open(main_window, five_page_pdf, qtbot)
    grid = tab.thumbnail_grid
    host = main_window._thumbnail_zoom_host
    refs = [grid._model.page_at(1)]
    spot = QPoint(host.width() // 2, host.height() // 2)
    mapped = grid.viewport().mapFromGlobal(host.mapToGlobal(spot))
    expected = grid.drop_index_at_pos(grid._container.mapFrom(grid, mapped))

    # A page dragged in from another document.
    transfers: list[int] = []
    monkeypatch.setattr(
        grid,
        "_handle_page_transfer",
        lambda refs, index, **kwargs: transfers.append(index) or True,
    )
    mime = QMimeData()
    mime.setData(PAGE_TRANSFER_MIME, encode_page_refs(refs))
    event = _drop(host, mime, spot)
    assert event.isAccepted()
    assert transfers == [expected]

    # A page of this grid dropped back onto it.
    reorders: list[tuple[list[int], int]] = []
    monkeypatch.setattr(grid, "_grid_for_widget", lambda _widget: grid)
    monkeypatch.setattr(
        grid, "reorder_pages_by_drop", lambda indices, index: reorders.append((indices, index)) or True
    )
    mime = QMimeData()
    mime.setData(INTERNAL_PAGE_MIME, encode_page_indices([0]))
    event = _drop(host, mime, spot, Qt.DropAction.MoveAction)
    assert event.isAccepted()
    assert reorders == [([0], expected)]


# --- prompts stacked with the message ---------------------------------------


def test_move_undo_prompt_floats_and_its_button_undoes(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot)
    undone: list[bool] = []
    main_window._offer_move_undo(2, lambda: undone.append(True) or True)
    main_window._transient_status("Moved 2 pages")
    prompt = main_window._move_undo_widget
    assert prompt.isVisible()
    assert prompt.parentWidget() is main_window._tab_manager
    area = _area(main_window)
    assert area.contains(prompt.geometry())
    # Stacked in the same column as the message, not on top of it.
    assert not prompt.geometry().intersects(_pill(main_window).geometry())
    assert prompt.geometry().center().x() == pytest.approx(area.center().x(), abs=1)

    button = main_window._move_undo_button
    point = button.mapTo(main_window._tab_manager, button.rect().center())
    assert main_window._tab_manager.childAt(point) is button
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert undone == [True]
    assert not prompt.isVisible()
    assert main_window._status_by_page[main_window._active_tab()] == "Move undone"


def test_progress_bar_floats_in_the_column(main_window, five_page_pdf, qtbot):
    _open(main_window, five_page_pdf, qtbot)
    bar = main_window._progress_bar
    bar.setRange(0, 10)
    bar.show()
    main_window._persistent_status("Rendering page 3 of 10…")
    area = _area(main_window)
    assert bar.parentWidget() is main_window._tab_manager
    assert area.contains(bar.geometry())
    assert not bar.geometry().intersects(_pill(main_window).geometry())
    assert bar.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


# --- scrolling ---------------------------------------------------------------


def test_last_row_scrolls_clear_of_the_size_control(main_window, tmp_path, qtbot):
    many = tmp_path / "many.pdf"
    generate_n_page(many, 30)
    tab = _open(main_window, many, qtbot, width=900, height=600)
    grid = tab.thumbnail_grid
    host = main_window._thumbnail_zoom_host
    bar = grid.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 0)

    bar.setValue(bar.maximum())
    qtbot.waitUntil(lambda: bar.value() == bar.maximum())
    last = grid._cards[-1]
    bottom = last.mapTo(main_window._tab_manager, last.rect().bottomLeft()).y()
    assert bottom < host.geometry().top()

    # Columns still come from the width alone.
    margins = grid._layout.contentsMargins()
    assert margins.left() == margins.right()
    assert grid.fitted_thumbnail_width() >= 0
