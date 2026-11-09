"""Sections pane: outline-to-page mapping and the background-loaded widget."""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QListWidget

from pagedrop.core.pdf_editor import PageRef, PdfEditModel
from pagedrop.core.pdf_service import OutlineItem, outline_for_paths
from pagedrop.ui import section_index as section_module
from pagedrop.ui.list_row_delegate import VALUE_ROLE
from pagedrop.ui.editor_jobs import _SIGNALS, editor_job_pool
from pagedrop.ui.section_index import (
    EMPTY_TEXT,
    FAILED_TEXT,
    LOADING_TEXT,
    SectionIndex,
    build_section_rows,
)
from pagedrop.ui.theme import DARK, LIGHT, index_qcolor

A = "/docs/a.pdf"
B = "/docs/b.pdf"


def _item(title: str, index: int, level: int = 1, path: str = A) -> OutlineItem:
    return OutlineItem(level, title, path, index)


def _pages(count: int, path: str = A) -> list[PageRef]:
    return [PageRef(path, i) for i in range(count)]


def _order(path: str, indices: list[int]) -> list[PageRef]:
    return [PageRef(path, i) for i in indices]


ITEMS = [
    _item("Introduction", 0),
    _item("Background", 1, level=2),
    _item("Method", 2),
    _item("Data", 3, level=2),
    _item("Results", 5),
]


def _summary(rows):
    return [(r.title, r.first_logical, r.label) for r in rows]


# --- mapping --------------------------------------------------------------


def test_sections_cover_pages_up_to_the_next_top_level_bookmark():
    rows = build_section_rows(ITEMS, _pages(8))
    assert _summary(rows) == [
        ("Introduction", 0, "1–2"),
        ("Method", 2, "3–5"),
        ("Results", 5, "6–8"),
    ]
    assert rows[0].accessible_text == "Introduction, pages 1 to 2"


def test_single_page_section_uses_singular_label():
    rows = build_section_rows([_item("Only", 0)], _pages(1))
    assert _summary(rows) == [("Only", 0, "1")]
    assert rows[0].accessible_text == "Only, page 1"


def test_no_bookmarks_gives_no_rows():
    assert build_section_rows([], _pages(5)) == []


def test_nested_levels_and_bad_destinations_are_ignored():
    items = [_item("Nested only", 0, level=2), _item("Broken", -1), _item("Real", 1)]
    assert _summary(build_section_rows(items, _pages(3))) == [("Real", 1, "2–3")]


def test_pages_before_the_first_bookmark_belong_to_no_section():
    rows = build_section_rows([_item("Late", 2)], _pages(4))
    assert _summary(rows) == [("Late", 2, "3–4")]


def test_blank_title_gets_a_fallback():
    assert build_section_rows([_item("  ", 0)], _pages(1))[0].title == "Untitled section"


def test_reorder_keeping_a_section_together_follows_its_new_position():
    # Method (source 2-4) moved to the front.
    pages = _order(A, [2, 3, 4, 0, 1, 5, 6, 7])
    assert _summary(build_section_rows(ITEMS, pages)) == [
        ("Introduction", 3, "4–5"),
        ("Method", 0, "1–3"),
        ("Results", 5, "6–8"),
    ]


def test_reorder_splitting_a_section_shows_its_first_page_only():
    pages = _order(A, [0, 2, 1, 3, 4, 5, 6, 7])
    rows = build_section_rows(ITEMS, pages)
    intro = rows[0]
    assert (intro.title, intro.first_logical, intro.label) == ("Introduction", 0, "1")
    assert intro.accessible_text == "Introduction, page 1"
    # Method keeps logical 1, 3, 4: not a run, so first page only.
    assert (rows[1].first_logical, rows[1].label) == (1, "2")


def test_first_page_is_the_lowest_logical_index_after_reorder():
    pages = _order(A, [5, 6, 7, 2, 3, 4, 1, 0])
    intro = build_section_rows(ITEMS, pages)[0]
    assert (intro.first_logical, intro.label) == (6, "7–8")


def test_deleting_part_of_a_section_shrinks_it():
    pages = _order(A, [0, 1, 2, 4, 5, 6, 7])  # source 3 deleted
    rows = build_section_rows(ITEMS, pages)
    assert [(r.title, r.label) for r in rows] == [
        ("Introduction", "1–2"),
        ("Method", "3–4"),
        ("Results", "5–7"),
    ]


def test_deleting_the_start_page_keeps_the_remaining_pages():
    pages = _order(A, [0, 1, 3, 4, 5, 6, 7])  # source 2 deleted
    method = build_section_rows(ITEMS, pages)[1]
    assert (method.first_logical, method.label) == (2, "3–4")


def test_deleting_a_whole_section_drops_its_row():
    pages = _order(A, [0, 1, 5, 6, 7])
    assert [r.title for r in build_section_rows(ITEMS, pages)] == ["Introduction", "Results"]
    assert build_section_rows(ITEMS, []) == []


def test_duplicate_next_to_original_extends_the_run():
    pages = _order(A, [0, 0, 1, 2, 3, 4, 5, 6, 7])
    assert build_section_rows(ITEMS, pages)[0].label == "1–3"


def test_distant_duplicate_makes_the_section_non_contiguous():
    pages = _order(A, [0, 1, 2, 3, 4, 5, 6, 7, 1])
    intro = build_section_rows(ITEMS, pages)[0]
    assert (intro.first_logical, intro.label) == (0, "1")


def test_two_bookmarks_on_one_page_both_survive():
    items = [_item("Overview", 0), _item("Introduction", 0), _item("Method", 2)]
    rows = build_section_rows(items, _pages(4))
    assert _summary(rows) == [
        ("Overview", 0, "1"),
        ("Introduction", 0, "1–2"),
        ("Method", 2, "3–4"),
    ]


def test_sections_from_several_sources_are_mapped_independently():
    items = [_item("S1", 0), _item("S2", 2), _item("T1", 0, path=B)]
    pages = [
        PageRef(A, 0),
        PageRef(A, 1),
        PageRef(B, 0),
        PageRef(A, 2),
        PageRef(A, 3),
        PageRef(B, 1),
        PageRef(B, 2),
    ]
    assert _summary(build_section_rows(items, pages)) == [
        ("S1", 0, "1–2"),
        ("S2", 3, "4–5"),
        ("T1", 2, "3"),
    ]


def test_mapping_handles_thousands_of_pages():
    items = [_item(f"S{i}", i * 10) for i in range(500)]
    rows = build_section_rows(items, _pages(5000))
    assert len(rows) == 500
    assert rows[499].label == "4991–5000"


# --- widget ---------------------------------------------------------------


def _settled(widget: SectionIndex) -> bool:
    return widget.status_text() != LOADING_TEXT


def _make(qtbot) -> SectionIndex:
    widget = SectionIndex()
    qtbot.addWidget(widget)
    widget.resize(200, 400)
    widget.show()
    return widget


def _list(widget: SectionIndex) -> QListWidget:
    found = widget.findChild(QListWidget)
    assert found is not None
    return found


def _titles(widget: SectionIndex) -> list[str]:
    view = _list(widget)
    return [view.item(i).text() for i in range(view.count())]


def test_widget_identity_and_semantics(qtbot):
    widget = _make(qtbot)
    view = _list(widget)
    assert widget.objectName() == "SectionIndex"
    assert widget.accessibleName() == "Sections"
    assert view.accessibleName() == "Sections"
    assert view.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert view.selectionMode() == QListWidget.SelectionMode.SingleSelection


def test_outline_loads_in_the_background_and_maps_through_the_edit_model(qtbot, bookmarked_pdf: Path):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _make(qtbot)
    widget.refresh(model.iter_pages())
    widget.load([bookmarked_pdf], None)
    assert widget.status_text() == LOADING_TEXT

    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)

    assert widget.status_text() == ""
    assert _titles(widget) == ["Introduction", "Method", "Results"]
    view = _list(widget)
    assert view.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == "Method, pages 3 to 5"
    assert view.item(1).toolTip() == "Method"


def test_refresh_follows_edits_without_reloading(qtbot, bookmarked_pdf: Path, monkeypatch):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _make(qtbot)
    widget.refresh(model.iter_pages())
    widget.load([bookmarked_pdf])
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)

    def forbidden(*_a, **_k):
        raise AssertionError("refresh must not read the document")

    monkeypatch.setattr(section_module, "outline_for_paths", forbidden)

    model.remove_pages([2, 3, 4])  # all of Method
    widget.refresh(model.iter_pages())
    assert _titles(widget) == ["Introduction", "Results"]

    model.undo()
    model.move_pages([2, 3, 4], 0)
    widget.refresh(model.iter_pages())
    assert _titles(widget) == ["Introduction", "Method", "Results"]
    assert _list(widget).item(1).data(Qt.ItemDataRole.AccessibleTextRole).startswith("Method, page")


def test_document_without_bookmarks_shows_one_quiet_line(qtbot, five_page_pdf: Path):
    model = PdfEditModel(str(five_page_pdf), 5)
    widget = _make(qtbot)
    widget.refresh(model.iter_pages())
    widget.load([five_page_pdf])
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)
    assert widget.status_text() == EMPTY_TEXT
    assert widget.row_count() == 0
    assert not _list(widget).isVisible()


def test_title_and_status_sit_at_the_top_when_the_list_is_hidden(qtbot, five_page_pdf: Path):
    widget = _make(qtbot)
    widget.resize(240, 600)
    widget.refresh(_pages(5))
    title = next(
        lbl for lbl in widget.findChildren(type(widget._status)) if lbl.objectName() == "PanelTitle"
    )
    margin = widget.layout().contentsMargins().top()

    def assert_at_top() -> None:
        assert title.y() == margin
        # Neither label is stretched, so its text really is at the top.
        assert title.height() <= title.sizeHint().height()
        status = widget._status
        assert status.isVisible()
        assert status.height() <= status.heightForWidth(status.width())
        assert status.y() == title.geometry().bottom() + 1 + widget.layout().spacing()

    # Loading, then the empty line for a document without bookmarks.
    widget.load([five_page_pdf])
    assert widget.status_text() == LOADING_TEXT
    assert_at_top()
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)
    assert widget.status_text() == EMPTY_TEXT
    assert not _list(widget).isVisible()
    assert_at_top()


def test_deleting_every_section_page_shows_the_empty_line(qtbot, bookmarked_pdf: Path):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _make(qtbot)
    widget.refresh(model.iter_pages())
    widget.load([bookmarked_pdf])
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)
    model.remove_pages(list(range(8)))
    widget.refresh(model.iter_pages())
    assert widget.status_text() == EMPTY_TEXT


def test_failed_load_is_reported_and_logged(qtbot, five_page_pdf: Path, monkeypatch):
    logged: list[str] = []

    def boom(*_a, **_k):
        raise RuntimeError("unreadable outline")

    monkeypatch.setattr(section_module, "outline_for_paths", boom)
    monkeypatch.setattr(section_module, "log_failure", lambda op, exc, **_k: logged.append(str(exc)))
    widget = _make(qtbot)
    widget.refresh(_pages(3))
    widget.load([five_page_pdf])
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)
    assert widget.status_text() == FAILED_TEXT
    assert logged == ["unreadable outline"]


def test_status_line_is_visible_to_screen_readers(qtbot):
    widget = _make(qtbot)
    widget.refresh(_pages(1))
    widget.load([])  # nothing to read: settles on the empty line
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)
    label = next(
        lbl for lbl in widget.findChildren(type(widget._status)) if lbl.objectName() == "PanelStatus"
    )
    assert label.isVisible()
    assert label.accessibleName() == EMPTY_TEXT


class _Gate:
    """Outline reader that blocks per path until released."""

    def __init__(self) -> None:
        self.release = {}
        self.started = {}

    def watch(self, name: str) -> None:
        self.release[name] = threading.Event()
        self.started[name] = threading.Event()

    def __call__(self, paths, **_kw):
        name = Path(paths[0]).name
        self.started[name].set()
        assert self.release[name].wait(10)
        return [OutlineItem(1, f"From {name}", str(paths[0]), 0)]


def _drain_pool() -> None:
    assert editor_job_pool().waitForDone(10000)
    QApplication.processEvents()


def test_older_load_result_is_ignored(qtbot, monkeypatch, tmp_path: Path):
    gate = _Gate()
    gate.watch("a.pdf")
    gate.watch("b.pdf")
    monkeypatch.setattr(section_module, "outline_for_paths", gate)
    path_a, path_b = tmp_path / "a.pdf", tmp_path / "b.pdf"

    widget = _make(qtbot)
    widget.refresh(_pages(1, str(path_a)) + _pages(1, str(path_b)))
    widget.load([path_a])
    qtbot.waitUntil(gate.started["a.pdf"].is_set, timeout=5000)
    widget.load([path_b])

    gate.release["a.pdf"].set()
    qtbot.waitUntil(gate.started["b.pdf"].is_set, timeout=5000)
    QApplication.processEvents()  # deliver the stale result
    assert widget.status_text() == LOADING_TEXT
    assert widget.row_count() == 0

    gate.release["b.pdf"].set()
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)
    assert _titles(widget) == ["From b.pdf"]
    _drain_pool()
    assert _titles(widget) == ["From b.pdf"]


def test_clear_during_load_leaves_the_pane_empty(qtbot, monkeypatch, tmp_path: Path):
    gate = _Gate()
    gate.watch("a.pdf")
    monkeypatch.setattr(section_module, "outline_for_paths", gate)
    path = tmp_path / "a.pdf"
    widget = _make(qtbot)
    widget.refresh(_pages(1, str(path)))
    widget.load([path])
    qtbot.waitUntil(gate.started["a.pdf"].is_set, timeout=5000)
    widget.clear()
    assert widget.status_text() == ""
    gate.release["a.pdf"].set()
    _drain_pool()
    assert widget.status_text() == ""
    assert widget.row_count() == 0


def test_a_stale_job_does_not_open_the_pdf(qtbot, monkeypatch, tmp_path: Path):
    calls: list[object] = []
    monkeypatch.setattr(section_module, "outline_for_paths", lambda *a, **k: calls.append(a))
    queued = []
    monkeypatch.setattr(section_module, "start_editor_worker", queued.append)
    widget = _make(qtbot)
    widget.load([tmp_path / "a.pdf"])
    assert len(queued) == 1

    widget.clear()
    queued[0].run()
    QApplication.processEvents()

    assert calls == []
    assert widget.status_text() == ""
    assert widget.row_count() == 0


def test_result_after_the_widget_is_destroyed_is_dropped(qtbot, monkeypatch, tmp_path: Path):
    gate = _Gate()
    gate.watch("a.pdf")
    monkeypatch.setattr(section_module, "outline_for_paths", gate)
    path = tmp_path / "a.pdf"
    widget = SectionIndex()
    widget.refresh(_pages(1, str(path)))
    widget.load([path])
    qtbot.waitUntil(gate.started["a.pdf"].is_set, timeout=5000)
    sip.delete(widget)
    gate.release["a.pdf"].set()
    _drain_pool()
    qtbot.waitUntil(lambda: not _SIGNALS, timeout=5000)


def _click(qtbot, view: QListWidget, row: int) -> None:
    qtbot.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualItemRect(view.item(row)).center()
    )


def _loaded_widget(qtbot, path: Path, model: PdfEditModel) -> SectionIndex:
    widget = _make(qtbot)
    widget.refresh(model.iter_pages())
    widget.load([path])
    qtbot.waitUntil(lambda: _settled(widget), timeout=10000)
    return widget


def test_click_emits_the_logical_page_of_the_section(qtbot, bookmarked_pdf: Path):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    model.move_pages([5, 6, 7], 0)  # Results first
    widget = _loaded_widget(qtbot, bookmarked_pdf, model)
    view = _list(widget)
    with qtbot.waitSignal(widget.section_activated, timeout=2000) as signal:
        _click(qtbot, view, 2)  # rows keep outline order, so Results is third
    assert view.item(2).text() == "Results"
    assert signal.args == [0]


def test_keyboard_activation_emits_and_repeats_harmlessly(qtbot, bookmarked_pdf: Path):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _loaded_widget(qtbot, bookmarked_pdf, model)
    view = _list(widget)
    got: list[int] = []
    widget.section_activated.connect(got.append)
    view.setFocus()
    view.setCurrentRow(1)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert got == [2, 2]
    qtbot.keyClick(view, Qt.Key.Key_Down)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert got[-1] == 5
    assert view.item(0).data(Qt.ItemDataRole.AccessibleTextRole) == "Introduction, pages 1 to 2"


def _swatch_found(widget: SectionIndex, colour) -> bool:
    image = _list(widget).viewport().grab().toImage()
    target = colour.rgb()
    return any(
        image.pixel(x, y) == target for y in range(image.height()) for x in range(image.width())
    )


def test_index_colour_square_follows_name_and_theme(qtbot, bookmarked_pdf: Path, monkeypatch):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _loaded_widget(qtbot, bookmarked_pdf, model)
    widget.set_index_colour("index_clay")
    monkeypatch.setattr("pagedrop.ui.settings.light_theme", lambda: False)
    assert _swatch_found(widget, index_qcolor("index_clay"))
    assert not _swatch_found(widget, index_qcolor("index_teal"))

    monkeypatch.setattr("pagedrop.ui.settings.light_theme", lambda: True)
    widget.repaint()
    assert LIGHT.index_clay != DARK.index_clay
    assert _swatch_found(widget, index_qcolor("index_clay"))

    widget.set_index_colour("index_teal")
    assert _swatch_found(widget, index_qcolor("index_teal"))


def test_outline_helper_returns_all_levels_so_the_pane_must_filter(bookmarked_pdf: Path):
    items = outline_for_paths([str(bookmarked_pdf)])
    assert {i.level for i in items} == {1, 2, 3}
    assert [r.title for r in build_section_rows(items, _pages(8, str(bookmarked_pdf)))] == [
        "Introduction",
        "Method",
        "Results",
    ]


def test_unrelated_edit_keeps_rows_and_current_row(qtbot, bookmarked_pdf: Path):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _loaded_widget(qtbot, bookmarked_pdf, model)
    view = _list(widget)
    view.setCurrentRow(1)
    before = [view.item(i) for i in range(view.count())]

    model.rotate_pages([0], 90)  # changes a page, not any section's pages
    widget.refresh(model.iter_pages())

    assert view.currentRow() == 1
    assert all(view.item(i) is item for i, item in enumerate(before))


def test_changed_mapping_updates_labels_and_keeps_the_current_row(qtbot, bookmarked_pdf: Path):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _loaded_widget(qtbot, bookmarked_pdf, model)
    view = _list(widget)
    view.setCurrentRow(1)
    assert view.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == "Method, pages 3 to 5"

    model.remove_pages([0])
    widget.refresh(model.iter_pages())

    assert _titles(widget) == ["Introduction", "Method", "Results"]
    assert view.currentItem().text() == "Method"
    assert view.currentRow() == 1
    assert view.item(0).data(VALUE_ROLE) == "1"
    assert view.item(1).data(VALUE_ROLE) == "2–4"
    assert view.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == "Method, pages 2 to 4"


def test_current_row_is_dropped_when_its_section_disappears(qtbot, bookmarked_pdf: Path):
    model = PdfEditModel(str(bookmarked_pdf), 8)
    widget = _loaded_widget(qtbot, bookmarked_pdf, model)
    view = _list(widget)
    view.setCurrentRow(1)
    model.remove_pages([2, 3, 4])
    widget.refresh(model.iter_pages())
    assert _titles(widget) == ["Introduction", "Results"]
    assert view.currentItem() is None or view.currentItem().text() != "Method"


# --- inside a real tab ---------------------------------------------------------


def _open_tab(window, qtbot, path: Path):
    window._load_pdf(str(path))
    from tests.conftest import wait_for_pdf_loaded

    wait_for_pdf_loaded(qtbot, window)
    tab = window._active_tab()
    tab.section_index.set_index_colour("index_slate")
    return tab


def _rows(tab) -> list[tuple[str, str]]:
    view = _list(tab.section_index)
    return [(view.item(i).text(), view.item(i).data(VALUE_ROLE)) for i in range(view.count())]


def _wait_for_rows(qtbot, tab, count: int = 3) -> None:
    qtbot.waitUntil(lambda: tab.section_index.row_count() == count, timeout=10_000)


def test_tab_lists_sections_after_load(main_window, qtbot, bookmarked_pdf: Path):
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    _wait_for_rows(qtbot, tab)
    assert _rows(tab) == [("Introduction", "1–2"), ("Method", "3–5"), ("Results", "6–8")]


def test_tab_without_bookmarks_shows_the_quiet_line(main_window, qtbot, five_page_pdf: Path):
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    qtbot.waitUntil(lambda: tab.section_index.status_text() == EMPTY_TEXT, timeout=10_000)
    assert tab.section_index.row_count() == 0


def test_reordering_through_the_tab_remaps_sections(main_window, qtbot, bookmarked_pdf: Path):
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    _wait_for_rows(qtbot, tab)
    tab.thumbnail_grid.selection_manager.set_selection({0, 1})
    assert tab.move_selected_pages_down()
    # Introduction moved down one place, which split Method: it shows its first page only.
    assert _rows(tab) == [("Introduction", "2–3"), ("Method", "1"), ("Results", "6–8")]


def test_delete_undo_and_redo_update_the_labels(main_window, qtbot, bookmarked_pdf: Path, monkeypatch):
    monkeypatch.setattr("pagedrop.ui.pdf_tab.confirm_delete_pages", lambda *a, **k: True)
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    _wait_for_rows(qtbot, tab)
    original = _rows(tab)

    tab.thumbnail_grid.selection_manager.select_single(0)
    assert tab.delete_selected_pages()
    deleted = [("Introduction", "1"), ("Method", "2–4"), ("Results", "5–7")]
    assert _rows(tab) == deleted

    assert tab.undo_edit()
    assert _rows(tab) == original
    assert tab.redo_edit()
    assert _rows(tab) == deleted


def test_outline_is_read_again_only_when_the_source_set_changes(
    main_window, qtbot, bookmarked_pdf: Path, five_page_pdf: Path, monkeypatch
):
    from pagedrop.core.pdf_editor import PageRef

    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    _wait_for_rows(qtbot, tab)
    loads: list[list] = []
    real_load = tab.section_index.load
    monkeypatch.setattr(
        tab.section_index, "load", lambda paths, pw=None: (loads.append(list(paths)), real_load(paths, pw))
    )

    tab.thumbnail_grid.selection_manager.set_selection({0})
    tab.rotate_selected_pages(90)
    assert tab.move_selected_pages_down()
    assert loads == []

    tab.edit_model.insert_pages(0, [PageRef(str(five_page_pdf), 0)])
    tab._sync_dirty_from_model()
    assert len(loads) == 1
    assert sorted(loads[0]) == sorted([str(bookmarked_pdf), str(five_page_pdf)])
    _wait_for_rows(qtbot, tab)


def test_activating_a_section_moves_focus_without_changing_the_selection(
    main_window, qtbot, bookmarked_pdf: Path
):
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    _wait_for_rows(qtbot, tab)
    grid = tab.thumbnail_grid
    grid.selection_manager.set_selection({1})
    view = _list(tab.section_index)

    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    qtbot.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualItemRect(view.item(2)).center()
    )
    assert grid._focused_index == 5
    assert grid.selection_manager.selection == {1}

    qtbot.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualItemRect(view.item(1)).center()
    )
    assert grid._focused_index == 2
    assert grid.selection_manager.selection == {1}


def test_activating_a_section_in_the_viewer_goes_to_that_page(main_window, qtbot, bookmarked_pdf: Path):
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    _wait_for_rows(qtbot, tab)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    tab.show_preview_at(0)
    qtbot.waitUntil(tab.is_viewer_mode)
    calls: list[int] = []
    real = tab.preview_widget.go_to_page
    tab.preview_widget.go_to_page = lambda index, **kw: (calls.append(index), real(index, **kw))[1]

    view = _list(tab.section_index)
    qtbot.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualItemRect(view.item(2)).center()
    )
    assert calls == [5]
    assert tab.preview_widget.current_page == 5


def test_out_of_range_section_page_is_ignored(main_window, qtbot, bookmarked_pdf: Path):
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    grid = tab.thumbnail_grid
    focused = grid._focused_index
    tab.section_index.section_activated.emit(99)
    tab.section_index.section_activated.emit(-1)
    assert grid._focused_index == focused


def test_closing_the_document_empties_the_pane(main_window, qtbot, bookmarked_pdf: Path):
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    _wait_for_rows(qtbot, tab)
    tab.close_loader()
    assert tab.section_index.row_count() == 0
    assert tab.section_index.status_text() == ""


def test_password_protected_document_still_lists_its_sections(
    main_window, qtbot, tmp_path: Path, monkeypatch
):
    import fitz

    from pagedrop.ui.settings import settings_file_path
    from tests.conftest import wait_for_pdf_loaded

    locked = tmp_path / "locked.pdf"
    doc = fitz.open()
    try:
        for _ in range(4):
            doc.new_page(width=200, height=200)
        doc.set_toc([[1, "Opening", 1], [1, "Closing", 3]])
        doc.save(
            str(locked),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw="hunter2",
            owner_pw="owner",
        )
    finally:
        doc.close()
    asked: list[str] = []

    def answer(filename: str, incorrect: bool = False) -> str:
        asked.append(filename)
        return "hunter2"

    monkeypatch.setattr(main_window, "_prompt_pdf_password", answer)
    main_window._load_pdf(str(locked))
    wait_for_pdf_loaded(qtbot, main_window)
    tab = main_window._active_tab()

    qtbot.waitUntil(lambda: tab.section_index.row_count() == 2, timeout=10_000)
    assert tab.section_index.status_text() != FAILED_TEXT
    assert _rows(tab) == [("Opening", "1–2"), ("Closing", "3–4")]
    assert asked == ["locked.pdf"]
    # The password lives in memory only.
    ini = Path(settings_file_path())
    assert not ini.exists() or b"hunter2" not in ini.read_bytes()
