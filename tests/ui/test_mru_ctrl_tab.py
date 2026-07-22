"""Phase 20 UI tests — MRU Ctrl+Tab toggle and cyclic Ctrl+Shift+Tab."""

from __future__ import annotations

from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QFileDialog

from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.pdf_tab import PdfTab
from tests.conftest import RENDER_TIMEOUT_MS
from tests.fixtures.generate_fixtures import generate_n_page


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


def _open_single(
    window: MainWindow,
    path,
    monkeypatch,
    *,
    target: str = "current",
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(path)], "PDF Files (*.pdf)"),
    )
    monkeypatch.setattr(window, "_ask_open_target", lambda _: target)
    window._open_pdf()


def _trigger_shortcut(window: MainWindow, sequence: str) -> None:
    target = QKeySequence(sequence)
    candidates = list(window.actions())
    registry = getattr(window, "_actions", None)
    if registry is not None:
        candidates.extend(registry.values())
    seen: set[int] = set()
    for action in candidates:
        key = id(action)
        if key in seen:
            continue
        seen.add(key)
        if action.shortcut() == target:
            action.trigger()
            return
    raise AssertionError(f"No action registered for {sequence}")


def _open_two_tabs(main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot) -> None:
    main_window.showMinimized()
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))
    _open_single(main_window, five_page_pdf, monkeypatch, target="new")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 1))


def test_ctrl_tab_toggles_between_last_two(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    _open_two_tabs(main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot)
    main_window._tab_manager.setCurrentIndex(0)

    _trigger_shortcut(main_window, "Ctrl+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 1,
        timeout=5000,
    )

    _trigger_shortcut(main_window, "Ctrl+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 0,
        timeout=5000,
    )


def test_ctrl_tab_after_manual_switch_updates_pair(
    main_window,
    one_page_pdf,
    five_page_pdf,
    pdf_fixtures_dir,
    monkeypatch,
    qtbot,
):
    two_page_pdf = pdf_fixtures_dir / "two_page.pdf"
    if not two_page_pdf.exists():
        generate_n_page(two_page_pdf, 2)

    main_window.showMinimized()
    for path, target in (
        (one_page_pdf, "current"),
        (two_page_pdf, "new"),
        (five_page_pdf, "new"),
    ):
        _open_single(main_window, path, monkeypatch, target=target)
        _wait_for_tab_loaded(qtbot, _tab_at(main_window, main_window._tab_manager.count() - 1))

    main_window._tab_manager.setCurrentIndex(0)
    assert main_window._tab_manager.currentIndex() == 0

    _trigger_shortcut(main_window, "Ctrl+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 2,
        timeout=5000,
    )

    _trigger_shortcut(main_window, "Ctrl+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 0,
        timeout=5000,
    )


def test_ctrl_shift_tab_still_cycles_backward(
    main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot
):
    _open_two_tabs(main_window, one_page_pdf, five_page_pdf, monkeypatch, qtbot)
    main_window._tab_manager.setCurrentIndex(1)

    _trigger_shortcut(main_window, "Ctrl+Shift+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 0,
        timeout=5000,
    )

    _trigger_shortcut(main_window, "Ctrl+Shift+Tab")
    qtbot.waitUntil(
        lambda: main_window._tab_manager.currentIndex() == 1,
        timeout=5000,
    )


def test_ctrl_tab_noop_with_one_tab(main_window, one_page_pdf, monkeypatch, qtbot):
    main_window.showMinimized()
    _open_single(main_window, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))

    assert main_window._tab_manager.count() == 1
    _trigger_shortcut(main_window, "Ctrl+Tab")
    qtbot.wait(100)
    assert main_window._tab_manager.currentIndex() == 0
