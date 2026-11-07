"""Command-palette ranking and QAction ownership."""

from __future__ import annotations

from PyQt6.QtGui import QAction, QKeySequence

from pagedrop.ui.command_palette import CommandPalette, ranked_actions


def _action(label: str, category: str = "Document", *, enabled: bool = True) -> QAction:
    action = QAction(label)
    action.setEnabled(enabled)
    action.setProperty("commandCategory", category)
    return action


def test_ranked_actions_prefers_exact_prefix_substring_then_subsequence(qtbot) -> None:
    exact = _action("Merge")
    prefix = _action("Merge PDFs")
    substring = _action("Open merged PDF")
    subsequence = _action("Move, erase, regroup, export")
    assert ranked_actions([subsequence, substring, prefix, exact], "merge") == [
        exact,
        prefix,
        substring,
        subsequence,
    ]


def test_palette_groups_synonyms_shortcuts_and_unavailable_reason(qtbot) -> None:
    merge = _action("Merge PDFs", "Tools")
    merge.setProperty("commandSynonyms", ["combine"])
    merge.setShortcut(QKeySequence("Ctrl+M"))
    disabled = _action("Delete selected pages", "Pages", enabled=False)
    disabled.setProperty("unavailableReason", "Select a page first")
    palette = CommandPalette([merge, disabled])
    qtbot.addWidget(palette)

    palette._refilter("combine")
    assert [palette._list.item(i).text() for i in range(palette._list.count())] == [
        "Tools", "Merge PDFs\tCtrl+M"
    ]
    palette._refilter("delete")
    assert "Select a page first" == palette._list.item(1).toolTip()
    palette._refilter("nothing")
    assert palette._list.item(palette._list.count() - 1).text() == "No commands match “nothing”"


def test_palette_triggers_original_action(qtbot) -> None:
    calls: list[bool] = []
    action = _action("Open PDF")
    action.triggered.connect(lambda: calls.append(True))
    palette = CommandPalette([action])
    qtbot.addWidget(palette)
    palette._activate_current()
    assert calls == [True]


def _selectable_palette(qtbot):
    from PyQt6.QtCore import Qt

    first = _action("Alpha", "Tools")
    second = _action("Bravo", "Tools")
    blocked = _action("Charlie", "Pages", enabled=False)
    blocked.setProperty("unavailableReason", "Select a page first")
    third = _action("Delta", "View")
    palette = CommandPalette([first, second, blocked, third])
    qtbot.addWidget(palette)
    palette.show()
    # Query that matches everything so the unavailable row is listed.
    palette._refilter("a")
    return palette, Qt


def _selectable_rows(palette) -> list[int]:
    return [i for i, action in enumerate(palette._item_actions) if action is not None]


def test_palette_arrows_hop_over_headers_and_unavailable_rows(qtbot) -> None:
    palette, Qt = _selectable_palette(qtbot)
    rows = _selectable_rows(palette)
    assert len(rows) >= 3
    assert any(a is None for a in palette._item_actions[rows[0] : rows[-1]])

    palette._list.setCurrentRow(rows[0])
    visited = [palette._list.currentRow()]
    for _ in rows[1:]:
        qtbot.keyClick(palette, Qt.Key.Key_Down)
        visited.append(palette._list.currentRow())
    assert visited == rows

    qtbot.keyClick(palette, Qt.Key.Key_Down)
    assert palette._list.currentRow() == rows[-1]

    for expected in reversed(rows[:-1]):
        qtbot.keyClick(palette, Qt.Key.Key_Up)
        assert palette._list.currentRow() == expected
    qtbot.keyClick(palette, Qt.Key.Key_Up)
    assert palette._list.currentRow() == rows[0]


def test_palette_arrows_do_nothing_without_selectable_rows(qtbot) -> None:
    from PyQt6.QtCore import Qt

    blocked = _action("Charlie", "Pages", enabled=False)
    blocked.setProperty("unavailableReason", "Select a page first")
    palette = CommandPalette([blocked])
    qtbot.addWidget(palette)
    palette.show()
    palette._refilter("charlie")
    assert _selectable_rows(palette) == []
    before = palette._list.currentRow()

    qtbot.keyClick(palette, Qt.Key.Key_Down)
    qtbot.keyClick(palette, Qt.Key.Key_Up)

    assert palette._list.currentRow() == before
    palette._refilter("zzz")
    qtbot.keyClick(palette, Qt.Key.Key_Down)
    qtbot.keyClick(palette, Qt.Key.Key_Up)
