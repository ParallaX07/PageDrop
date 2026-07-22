"""Phase 18 UI tests — open PDF in new window targets."""

from __future__ import annotations

from pathlib import Path

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


def _ensure_window_manager(qapp):
    from pagedrop.ui.window_manager import WindowManager

    return WindowManager(qapp)


def _windows_added(manager, before: frozenset) -> list:
    return [window for window in manager.windows if window not in before]


def _open_single(
    window: MainWindow,
    path: Path,
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


def _open_multi(
    window: MainWindow,
    paths: list[Path],
    monkeypatch,
    *,
    target: str = "tabs",
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (
            [str(path) for path in paths],
            "PDF Files (*.pdf)",
        ),
    )
    monkeypatch.setattr(window, "_ask_multi_open_target", lambda _: target)
    window._open_pdf()


def test_single_file_open_new_window_prompt(main_window, one_page_pdf, monkeypatch):
    monkeypatch.setattr(
        main_window,
        "_ask_open_target",
        lambda path: "window" if Path(path).name == one_page_pdf.name else None,
    )
    called: list[str] = []
    monkeypatch.setattr(
        main_window,
        "_open_in_new_window",
        lambda path: called.append(path),
    )

    main_window._open_single_pdf(str(one_page_pdf))

    assert called == [str(one_page_pdf)]


def test_open_in_new_window_loads_pdf(
    one_page_pdf,
    five_page_pdf,
    monkeypatch,
    qtbot,
    qapp,
):
    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    _open_single(source, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(source, 0))

    initial_count = len(manager.windows)
    windows_before = frozenset(manager.windows)
    _open_single(source, five_page_pdf, monkeypatch, target="window")
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + 1,
        timeout=5000,
    )

    new_window = _windows_added(manager, windows_before)[0]
    qtbot.addWidget(new_window)
    tab = _tab_at(new_window, 0)
    _wait_for_tab_loaded(qtbot, tab)

    assert tab.pdf_path == str(five_page_pdf)
    assert _tab_at(source, 0).pdf_path == str(one_page_pdf)


def test_open_in_current_tab_blank_unchanged(main_window, five_page_pdf, monkeypatch, qtbot):
    assert _tab_at(main_window, 0).is_blank

    _open_single(main_window, five_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(main_window, 0))

    assert main_window._tab_manager.count() == 1
    assert _tab_at(main_window, 0).pdf_path == str(five_page_pdf)


def test_multi_select_open_each_in_new_window(
    one_page_pdf,
    five_page_pdf,
    pdf_fixtures_dir,
    monkeypatch,
    qtbot,
    qapp,
):
    two_page_pdf = pdf_fixtures_dir / "two_page.pdf"
    if not two_page_pdf.exists():
        generate_n_page(two_page_pdf, 2)

    manager = _ensure_window_manager(qapp)
    source = manager.open_new_window()
    qtbot.addWidget(source)
    source.showMinimized()

    paths = [one_page_pdf, two_page_pdf, five_page_pdf]
    # Prompt only when the active tab already has content.
    _open_single(source, one_page_pdf, monkeypatch, target="current")
    _wait_for_tab_loaded(qtbot, _tab_at(source, 0))

    initial_count = len(manager.windows)
    windows_before = frozenset(manager.windows)
    _open_multi(source, paths, monkeypatch, target="windows")
    qtbot.waitUntil(
        lambda: len(manager.windows) == initial_count + len(paths),
        timeout=5000,
    )

    new_windows = _windows_added(manager, windows_before)
    assert len(new_windows) == len(paths)

    loaded_paths: list[str] = []
    for window in new_windows:
        qtbot.addWidget(window)
        tab = _tab_at(window, 0)
        _wait_for_tab_loaded(qtbot, tab)
        assert tab.pdf_path is not None
        loaded_paths.append(tab.pdf_path)

    assert set(loaded_paths) == {str(path) for path in paths}
    assert _tab_at(source, 0).pdf_path == str(one_page_pdf)
