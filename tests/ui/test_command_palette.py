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
