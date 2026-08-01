"""Sanity check — Merge/Convert cards share InternalReorderFileCard drag shell."""

from __future__ import annotations

from pagedrop.ui.base_file_card import BaseFileCard, InternalReorderFileCard
from pagedrop.ui.convert_file_card import ConvertFileCard
from pagedrop.ui.merge_file_card import MergeFileCard
from pagedrop.ui.page_card import PageCard


def test_card_inheritance():
    assert issubclass(PageCard, BaseFileCard)
    assert issubclass(MergeFileCard, InternalReorderFileCard)
    assert issubclass(ConvertFileCard, InternalReorderFileCard)
    assert issubclass(InternalReorderFileCard, BaseFileCard)


def test_merge_and_convert_emit_file_index(qtbot):
    merge = MergeFileCard(2, "/tmp/a.pdf", 3)
    convert = ConvertFileCard(4, "/tmp/b.png", (100, 200))
    qtbot.addWidget(merge)
    qtbot.addWidget(convert)

    assert merge._item_index() == 2
    assert convert._item_index() == 4
    assert merge.toolTip() == "/tmp/a.pdf"
    assert "100 × 200" in convert.toolTip()


def test_file_cards_have_accessible_names(qtbot):
    merge = MergeFileCard(0, "/tmp/report.pdf", 3)
    convert = ConvertFileCard(1, "/tmp/photo.png", (100, 200))
    qtbot.addWidget(merge)
    qtbot.addWidget(convert)

    assert merge.accessibleName() == "report.pdf"
    assert "3 pages" in merge.accessibleDescription()
    assert convert.accessibleName() == "photo.png"
    assert "100 × 200" in convert.accessibleDescription()


def test_file_card_title_single_line_elide(qtbot):
    """R14: Merge/Convert titles stay one line — no wrap that rags the grid."""
    long_name = "very-long-merge-filename-" + ("x" * 60) + ".pdf"
    card = MergeFileCard(0, f"/tmp/{long_name}", 2)
    qtbot.addWidget(card)

    assert not card._title_label.wordWrap()
    assert card._title_label.maximumWidth() > 0
    assert card._title_label.text() != long_name
    assert "…" in card._title_label.text()
    assert card.toolTip() == f"/tmp/{long_name}"
    assert card.accessibleName() == long_name

    card.set_card_width(120, refresh_thumbnail=False)
    assert card._title_label.maximumWidth() <= 120
    assert "…" in card._title_label.text()
