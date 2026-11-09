"""Document panel: facts about the open document."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtWidgets import QLabel, QListWidget

from pagedrop.core.pdf_editor import PdfEditModel
from pagedrop.ui import document_panel as panel_module
from pagedrop.ui.document_panel import EMPTY_TEXT, NOT_SAVED_TEXT, UNAVAILABLE_TEXT, DocumentPanel


def _make(qtbot) -> DocumentPanel:
    panel = DocumentPanel()
    qtbot.addWidget(panel)
    panel.resize(300, 300)
    panel.show()
    return panel


def _list(panel: DocumentPanel) -> QListWidget:
    found = panel.findChild(QListWidget)
    assert found is not None
    return found


def _expected_size(path: Path) -> str:
    return QLocale().formattedDataSize(
        path.stat().st_size, 1, QLocale.DataSizeFormat.DataSizeTraditionalFormat
    )


def test_rows_appear_in_order(qtbot, five_page_pdf: Path):
    panel = _make(qtbot)
    panel.set_document(5, five_page_pdf)
    view = _list(panel)
    assert [view.item(i).text() for i in range(view.count())] == [
        "Pages",
        "Size",
        "Location",
        "Selection",
    ]


def test_counts_follow_the_edit_model_after_edits(qtbot, five_page_pdf: Path):
    model = PdfEditModel(str(five_page_pdf), 5)
    panel = _make(qtbot)
    panel.set_document(model.logical_count(), five_page_pdf)
    assert panel.facts()["Pages"] == "5"
    model.remove_pages([0, 1])
    panel.set_page_count(model.logical_count())
    assert panel.facts()["Pages"] == "3"
    model.undo()
    panel.set_page_count(model.logical_count())
    assert panel.facts()["Pages"] == "5"


def test_size_and_location_come_from_the_file(qtbot, five_page_pdf: Path):
    panel = _make(qtbot)
    panel.set_document(5, five_page_pdf)
    facts = panel.facts()
    assert facts["Size"] == _expected_size(five_page_pdf)
    assert facts["Location"] == str(five_page_pdf.parent)
    location = _list(panel).item(2)
    assert location.toolTip() == str(five_page_pdf)
    assert location.data(Qt.ItemDataRole.AccessibleTextRole) == f"Location: {five_page_pdf.parent}"
    assert os.stat(five_page_pdf).st_size > 0


def test_unsaved_document_has_no_size_or_location(qtbot):
    panel = _make(qtbot)
    panel.set_document(2, None)
    assert panel.facts()["Size"] == NOT_SAVED_TEXT
    assert panel.facts()["Location"] == NOT_SAVED_TEXT
    assert panel.facts()["Pages"] == "2"


def test_missing_or_unreadable_file_shows_unavailable(qtbot, tmp_path: Path):
    panel = _make(qtbot)
    panel.set_document(2, tmp_path / "gone.pdf")
    assert panel.facts()["Size"] == UNAVAILABLE_TEXT
    assert panel.facts()["Location"] == str(tmp_path)


def test_stat_failure_does_not_crash(qtbot, five_page_pdf: Path, monkeypatch):
    def denied(_path):
        raise PermissionError("denied")

    monkeypatch.setattr(panel_module.os, "stat", denied)
    panel = _make(qtbot)
    panel.set_document(5, five_page_pdf)
    assert panel.facts()["Size"] == UNAVAILABLE_TEXT


def test_selection_text(qtbot):
    panel = _make(qtbot)
    panel.set_document(12, None)
    assert panel.facts()["Selection"] == "None"
    panel.set_selection(3, 12)
    assert panel.facts()["Selection"] == "3 of 12 pages"
    panel.set_selection(1, 1)
    assert panel.facts()["Selection"] == "1 of 1 page"
    panel.set_selection(0, 12)
    assert panel.facts()["Selection"] == "None"
    assert _list(panel).item(3).data(Qt.ItemDataRole.AccessibleTextRole) == "Selection: None"


def test_clear_returns_to_the_empty_state(qtbot, five_page_pdf: Path):
    panel = _make(qtbot)
    panel.set_document(5, five_page_pdf)
    assert panel.status_text() == ""
    panel.clear()
    assert panel.status_text() == EMPTY_TEXT
    assert not _list(panel).isVisible()
    assert panel.facts() == dict.fromkeys(("Pages", "Size", "Location", "Selection"), "")
    status = next(lbl for lbl in panel.findChildren(QLabel) if lbl.objectName() == "PanelStatus")
    assert status.accessibleName() == EMPTY_TEXT
    panel.set_document(5, five_page_pdf)
    assert _list(panel).isVisible()


def test_accessible_names_and_row_text(qtbot, five_page_pdf: Path):
    panel = _make(qtbot)
    panel.set_document(5, five_page_pdf)
    view = _list(panel)
    assert panel.objectName() == "DocumentPanel"
    assert panel.accessibleName() == "Document"
    assert view.accessibleName() == "Document"
    assert view.item(0).data(Qt.ItemDataRole.AccessibleTextRole) == "Pages: 5"
    assert view.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == f"Size: {_expected_size(five_page_pdf)}"


def test_rows_are_reachable_by_keyboard(qtbot, five_page_pdf: Path):
    panel = _make(qtbot)
    panel.set_document(5, five_page_pdf)
    view = _list(panel)
    assert view.focusPolicy() == Qt.FocusPolicy.StrongFocus
    view.setFocus()
    view.setCurrentRow(0)
    qtbot.keyClick(view, Qt.Key.Key_Down)
    qtbot.keyClick(view, Qt.Key.Key_Down)
    assert view.currentRow() == 2


# --- inside a real tab ---------------------------------------------------------


def _open_tab(window, qtbot, path: Path):
    from tests.conftest import wait_for_pdf_loaded

    window._load_pdf(str(path))
    wait_for_pdf_loaded(qtbot, window)
    return window._active_tab()


def test_tab_panel_shows_the_loaded_file(main_window, qtbot, five_page_pdf: Path):
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    facts = tab.document_panel.facts()
    assert facts["Pages"] == "5"
    assert facts["Size"] == _expected_size(five_page_pdf)
    assert facts["Location"] == str(five_page_pdf.parent)
    assert facts["Selection"] == "None"


def test_pages_follow_the_logical_count_through_edits(main_window, qtbot, five_page_pdf: Path, monkeypatch):
    monkeypatch.setattr("pagedrop.ui.pdf_tab.confirm_delete_pages", lambda *a, **k: True)
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    panel = tab.document_panel
    grid = tab.thumbnail_grid

    grid.selection_manager.set_selection({0, 1})
    assert tab.delete_selected_pages()
    assert panel.facts()["Pages"] == "3"
    assert tab.loader.page_count == 5  # the raw count is not what is shown

    assert tab.undo_edit()
    assert panel.facts()["Pages"] == "5"

    grid.selection_manager.set_selection({2})
    assert tab.duplicate_selected_pages() == 1
    assert panel.facts()["Pages"] == "6"

    assert tab.undo_edit()
    assert panel.facts()["Pages"] == "5"
    assert tab.redo_edit()
    assert panel.facts()["Pages"] == "6"


def test_selection_row_follows_the_grid(main_window, qtbot, five_page_pdf: Path):
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    panel = tab.document_panel
    tab.thumbnail_grid.selection_manager.set_selection({0, 2})
    assert panel.facts()["Selection"] == "2 of 5 pages"
    tab.thumbnail_grid.selection_manager.set_selection(set())
    assert panel.facts()["Selection"] == "None"


def test_selection_total_uses_the_logical_count_after_a_delete(
    main_window, qtbot, five_page_pdf: Path, monkeypatch
):
    monkeypatch.setattr("pagedrop.ui.pdf_tab.confirm_delete_pages", lambda *a, **k: True)
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    tab.thumbnail_grid.selection_manager.set_selection({0, 1})
    assert tab.delete_selected_pages()
    tab.thumbnail_grid.selection_manager.set_selection({0})
    assert tab.document_panel.facts()["Selection"] == "1 of 3 pages"


def test_opening_another_document_resets_the_panel(
    main_window, qtbot, five_page_pdf: Path, bookmarked_pdf: Path
):
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    tab.thumbnail_grid.selection_manager.set_selection({0, 1})
    tab = _open_tab(main_window, qtbot, bookmarked_pdf)
    facts = tab.document_panel.facts()
    assert facts["Pages"] == "8"
    assert facts["Selection"] == "None"
    assert facts["Location"] == str(bookmarked_pdf.parent)


def test_location_follows_save_as_to_a_new_path(
    main_window, qtbot, five_page_pdf: Path, tmp_path: Path, monkeypatch
):
    from PyQt6.QtWidgets import QFileDialog

    from tests.conftest import file_sha256

    monkeypatch.setattr("pagedrop.ui.pdf_tab.confirm_delete_pages", lambda *a, **k: True)
    source_hash = file_sha256(five_page_pdf)
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    tab.thumbnail_grid.selection_manager.set_selection({0})
    assert tab.delete_selected_pages()
    target_dir = tmp_path / "elsewhere"
    target_dir.mkdir()
    output = target_dir / "saved.pdf"
    assert output != five_page_pdf
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(output), "PDF Files (*.pdf)")
    )

    assert main_window._save_as(tab) is True
    qtbot.waitUntil(lambda: tab not in main_window._editor_busy, timeout=15_000)

    assert output.is_file()
    assert file_sha256(five_page_pdf) == source_hash
    facts = tab.document_panel.facts()
    assert facts["Location"] == str(target_dir)
    assert facts["Size"] == _expected_size(output)
    assert facts["Pages"] == "4"


def test_tabs_without_a_real_file_show_no_location(
    main_window, qtbot, five_page_pdf: Path, tmp_path: Path
):
    from pagedrop.core.pdf_editor import PageRef

    main_window.show()
    blank = main_window._tab_manager.add_blank_tab()
    blank.init_from_page_refs([PageRef(str(five_page_pdf), 0), PageRef(str(five_page_pdf), 1)])
    facts = blank.document_panel.facts()
    assert facts["Pages"] == "2"
    assert facts["Location"] == NOT_SAVED_TEXT
    assert facts["Size"] == NOT_SAVED_TEXT


def test_staged_temp_file_is_never_shown_as_the_location(main_window, qtbot, five_page_pdf: Path):
    import shutil

    staged = Path(main_window._temp_manager.get_dir()) / "staged.pdf"
    shutil.copyfile(five_page_pdf, staged)
    tab = _open_tab(main_window, qtbot, staged)
    assert tab.document_panel.facts()["Location"] == NOT_SAVED_TEXT


def test_closing_the_document_clears_the_panel(main_window, qtbot, five_page_pdf: Path):
    tab = _open_tab(main_window, qtbot, five_page_pdf)
    tab.close_loader()
    assert tab.document_panel.status_text() == EMPTY_TEXT


def test_title_and_status_sit_at_the_top_without_a_document(qtbot):
    panel = _make(qtbot)
    panel.resize(300, 600)
    panel.clear()
    title = next(lbl for lbl in panel.findChildren(QLabel) if lbl.objectName() == "PanelTitle")
    assert not _list(panel).isVisible()
    assert title.y() == panel.layout().contentsMargins().top()
    # Neither label is stretched, so its text really is at the top.
    assert title.height() <= title.sizeHint().height()
    assert panel._status.height() <= panel._status.heightForWidth(panel._status.width())
    assert panel._status.isVisible()
    assert panel._status.y() == title.geometry().bottom() + 1 + panel.layout().spacing()
