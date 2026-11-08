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
