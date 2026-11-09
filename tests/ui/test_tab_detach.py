"""WC4 / Phase 18 — tab tear-off and Move to New Window (minimal smoke)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QDrag, QMouseEvent
from PyQt6.QtWidgets import QApplication

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from pagedrop.ui.theme import index_qcolor
from tests.conftest import RENDER_TIMEOUT_MS


def _tab_at(window: MainWindow, index: int) -> PdfTab:
    widget = window._tab_manager.widget(index)
    assert isinstance(widget, PdfTab)
    return widget


def _wait_for_tab_loaded(qtbot, tab: PdfTab, *, timeout: int = RENDER_TIMEOUT_MS) -> None:
    qtbot.waitUntil(
        lambda: (
            tab.loader is not None
            and tab.thumbnail_grid._last_rendered_width_px
            == tab.thumbnail_grid._thumbnail_width_px
            and tab.thumbnail_grid._render_pool.activeThreadCount() == 0
            and len(tab.thumbnail_grid._cards) == tab.loader.page_count
        ),
        timeout=timeout,
    )


def _ensure_window_manager(qapp):
    from pagedrop.ui.window_manager import WindowManager

    return WindowManager(qapp)


def _windows_added(manager, before: frozenset) -> list:
    return [window for window in manager.windows if window not in before]


def test_detach_tab_creates_new_window_with_same_pdf(
    one_page_pdf,
    five_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    tab_a = source._tab_manager.add_blank_tab()
    source._load_pdf(str(one_page_pdf), tab=tab_a)
    tab_b = source._tab_manager.add_blank_tab()
    source._load_pdf(str(five_page_pdf), tab=tab_b)
    source._tab_manager.removeTab(0)
    _wait_for_tab_loaded(qtbot, tab_a)
    _wait_for_tab_loaded(qtbot, tab_b)

    tab_a.thumbnail_grid.selection_manager.select_single(0)
    tab_a.set_zoom_level(140)
    tab_b_index = source._tab_manager.indexOf(tab_b)

    initial_count = len(manager.windows)
    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(tab_b_index)
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )

    assert source._tab_manager.count() == 1
    assert _tab_at(source, 0).pdf_path == str(one_page_pdf)

    detached = _windows_added(manager, windows_before)[0]
    qtbot.addWidget(detached)
    assert detached._tab_manager.count() == 1
    detached_tab = _tab_at(detached, 0)
    assert detached_tab.pdf_path == str(five_page_pdf)
    assert detached_tab.loader is tab_b.loader
    assert detached_tab.zoom_level == tab_b.zoom_level
    assert detached_tab.thumbnail_grid.selection_manager.selection == set()
    assert source._toolbar.parentWidget() is _tab_at(source, 0)
    assert detached._toolbar.parentWidget() is detached_tab
    assert source.windowTitle().endswith("(1 page)")
    assert detached.windowTitle().endswith("(5 pages)")


def test_detached_tab_keeps_its_colour_and_leaves_the_new_counter_alone(
    one_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    source._tab_manager.add_blank_tab()
    moving = _tab_at(source, 1)
    source._load_pdf(str(one_page_pdf), tab=moving)
    _wait_for_tab_loaded(qtbot, moving)
    assert moving.index_colour == "index_teal"

    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(1)
    qtbot.waitUntil(
        lambda: len(_windows_added(manager, windows_before)) == 1,
        timeout=5000,
    )
    detached = _windows_added(manager, windows_before)[0]
    qtbot.addWidget(detached)

    assert _tab_at(detached, 0) is moving
    assert moving.index_colour == "index_teal"
    assert detached._tab_manager._tab_index_colour(0) == "index_teal"
    # The adopted tab did not use up a colour: the first new tab starts at clay.
    fresh = detached._tab_manager.add_blank_tab()
    assert fresh.index_colour == "index_clay"


def test_order_chip_keeps_the_documents_colour_after_detach(
    one_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    source._tab_manager.add_blank_tab()
    moving = _tab_at(source, 1)
    source._load_pdf(str(one_page_pdf), tab=moving)
    _wait_for_tab_loaded(qtbot, moving)
    card = moving.thumbnail_grid._cards[0]
    moving.thumbnail_grid.selection_manager.select_single(0)
    teal = index_qcolor("index_teal")
    assert card._order_chip.fill_colour() == teal

    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(1)
    qtbot.waitUntil(
        lambda: len(_windows_added(manager, windows_before)) == 1,
        timeout=5000,
    )
    detached = _windows_added(manager, windows_before)[0]
    qtbot.addWidget(detached)

    assert _tab_at(detached, 0) is moving
    assert card._order_chip.fill_colour() == teal
    chip = card._order_chip
    assert not chip.isHidden()
    assert chip.grab().toImage().pixelColor(4, chip.height() // 2) == teal


def test_move_to_new_window_context_menu(
    one_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    tab = _tab_at(source, 0)
    source._load_pdf(str(one_page_pdf), tab=tab)
    _wait_for_tab_loaded(qtbot, tab)

    initial_count = len(manager.windows)
    windows_before = frozenset(manager.windows)
    source._tab_manager.move_to_new_window_requested.emit(0)
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )

    assert source._tab_manager.count() == 1
    assert _tab_at(source, 0).is_blank

    detached = _windows_added(manager, windows_before)[0]
    assert _tab_at(detached, 0).pdf_path == str(one_page_pdf)


def _detached_tab_with_source_closed_later(qtbot, qapp, pdf_path, *, register=True):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    if register:
        qtbot.addWidget(source)
    source.showMinimized()
    tab = _tab_at(source, 0)
    source._load_pdf(str(pdf_path), tab=tab)
    _wait_for_tab_loaded(qtbot, tab)
    windows_before = frozenset(manager.windows)
    source._detach_tab_to_new_window(0)
    qtbot.waitUntil(lambda: len(manager.windows) == len(windows_before) + 1)
    detached = _windows_added(manager, windows_before)[0]
    if register:
        qtbot.addWidget(detached)
    return source, detached, tab


def _drag_first_page(qtbot, tab: PdfTab, monkeypatch) -> list[Path]:
    dropped: list[Path] = []

    def fake_exec(drag, *args, **kwargs):
        dropped.extend(Path(url.toLocalFile()) for url in drag.mimeData().urls())
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(QDrag, "exec", fake_exec)
    grid = tab.thumbnail_grid
    grid.selection_manager.select_single(0)
    card = grid._cards[0]
    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseMove(card, pos=QPoint(200, 200))
    return dropped


def test_detached_tab_uses_the_new_windows_temp_manager(
    five_page_pdf, qtbot, qapp
):
    source, detached, tab = _detached_tab_with_source_closed_later(
        qtbot, qapp, five_page_pdf
    )

    assert source._temp_manager is not detached._temp_manager
    assert tab._temp_manager is detached._temp_manager
    assert tab.thumbnail_grid._temp_manager is detached._temp_manager
    assert tab.thumbnail_grid._cards
    assert all(
        card._temp_manager is detached._temp_manager
        for card in tab.thumbnail_grid._cards
    )


def test_drag_after_source_window_closes_lives_in_new_windows_root(
    five_page_pdf, qtbot, qapp, monkeypatch
):
    # Both windows are closed (and freed) by the test itself.
    source, detached, tab = _detached_tab_with_source_closed_later(
        qtbot, qapp, five_page_pdf, register=False
    )
    source_root = source._temp_manager.get_dir()
    new_root = detached._temp_manager.get_dir()
    source.close()
    assert not source_root.exists()

    # Cards created after the move (a reload) belong to the new window too.
    tab.thumbnail_grid.reload_from_model()
    dropped = _drag_first_page(qtbot, tab, monkeypatch)

    assert len(dropped) == 1
    assert dropped[0].is_file()
    assert new_root in dropped[0].parents
    assert not source_root.exists()

    detached.close()
    assert not dropped[0].exists()
    assert not new_root.exists()


def _send_mouse(bar, kind, local: QPoint, global_pos: QPoint) -> None:
    """Deliver a real mouse event (QTest.mouseMove is a no-op offscreen)."""
    left = Qt.MouseButton.LeftButton
    release = kind == QEvent.Type.MouseButtonRelease
    QApplication.sendEvent(
        bar,
        QMouseEvent(
            kind,
            QPointF(local),
            QPointF(global_pos),
            left if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton if release else left,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    QApplication.processEvents()


def test_dragging_a_tab_out_of_the_window_after_reordering_detaches_that_tab(
    one_page_pdf,
    five_page_pdf,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.show()
    qtbot.waitExposed(source)

    tab_a = source._tab_manager.add_blank_tab()
    source._load_pdf(str(one_page_pdf), tab=tab_a)
    tab_b = source._tab_manager.add_blank_tab()
    source._load_pdf(str(five_page_pdf), tab=tab_b)
    source._tab_manager.removeTab(0)
    _wait_for_tab_loaded(qtbot, tab_a)
    _wait_for_tab_loaded(qtbot, tab_b)
    bar = source._tab_manager.tabBar()
    assert bar.isMovable()

    start = bar.tabRect(0).center()
    press_global = bar.mapToGlobal(start)
    _send_mouse(bar, QEvent.Type.MouseButtonPress, start, press_global)
    # Drag within the bar over the second tab: the dragged tab is reordered.
    for dx in range(5, bar.tabRect(0).width(), 15):
        _send_mouse(bar, QEvent.Type.MouseMove, start + QPoint(dx, 0), press_global + QPoint(dx, 0))
    qtbot.waitUntil(lambda: source._tab_manager.indexOf(tab_a) == 1, timeout=3000)
    moving = bar._moving_tab
    assert moving is not None and moving.isVisible()

    # Past the threshold and outside the window: the drag arms a detach.
    frame = source.frameGeometry()
    outside = QPoint(frame.right() + 300, frame.bottom() + 300)
    windows_before = frozenset(manager.windows)
    _send_mouse(bar, QEvent.Type.MouseMove, start + QPoint(40, 0), outside)
    assert bar._detach_armed
    assert bar.tabToolTip(1) == "Release to open in new window"
    _send_mouse(bar, QEvent.Type.MouseButtonRelease, start + QPoint(40, 0), outside)

    qtbot.waitUntil(
        lambda: len(_windows_added(manager, windows_before)) == 1,
        timeout=5000,
    )
    detached = _windows_added(manager, windows_before)[0]
    qtbot.addWidget(detached)
    assert _tab_at(detached, 0) is tab_a
    assert source._tab_manager.count() == 1
    assert _tab_at(source, 0) is tab_b
    qtbot.waitUntil(lambda: not moving.isVisible(), timeout=3000)
    assert not bar._detach_armed


def test_refused_detach_still_ends_the_tab_drag(one_page_pdf, qtbot, qapp):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.show()
    qtbot.waitExposed(source)
    tab = source._tab_manager.add_blank_tab()
    source._load_pdf(str(one_page_pdf), tab=tab)
    _wait_for_tab_loaded(qtbot, tab)
    source._window_manager = None  # the detach is refused and the tab stays
    bar = source._tab_manager.tabBar()

    start = bar.tabRect(source._tab_manager.indexOf(tab)).center()
    press_global = bar.mapToGlobal(start)
    _send_mouse(bar, QEvent.Type.MouseButtonPress, start, press_global)
    for dx in (5, 20, 40):
        _send_mouse(bar, QEvent.Type.MouseMove, start + QPoint(dx, 0), press_global + QPoint(dx, 0))
    moving = bar._moving_tab
    assert moving is not None and moving.isVisible()

    frame = source.frameGeometry()
    outside = QPoint(frame.right() + 300, frame.bottom() + 300)
    _send_mouse(bar, QEvent.Type.MouseMove, start + QPoint(40, 0), outside)
    _send_mouse(bar, QEvent.Type.MouseButtonRelease, start + QPoint(40, 0), outside)

    assert source._tab_manager.indexOf(tab) >= 0
    qtbot.waitUntil(lambda: not moving.isVisible(), timeout=3000)
