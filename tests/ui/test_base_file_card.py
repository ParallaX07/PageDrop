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
