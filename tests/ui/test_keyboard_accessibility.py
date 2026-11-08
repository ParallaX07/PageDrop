"""Keyboard accessibility — toolbar arrows, tab order, menu mnemonics."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QToolButton

from pagedrop.ui.keyboard_nav import focusable_toolbar_widgets
from pagedrop.ui.tool_shell import ToolShellWindow
from pagedrop.ui.tools_window import ToolsWindow
from tests.conftest import RENDER_TIMEOUT_MS, wait_for_pdf_loaded


def _toolbar_tool_buttons(toolbar) -> list[QToolButton]:
    """All QToolButtons for toolbar actions (ignore visibility/enabled)."""
    buttons: list[QToolButton] = []
    for action in toolbar.actions():
        widget = toolbar.widgetForAction(action)
        if isinstance(widget, QToolButton):
            buttons.append(widget)
    return buttons


def test_menu_mnemonics_are_unambiguous(main_window):
    menubar = main_window.menuBar()
    top_labels = [action.text() for action in menubar.actions()]
    assert "&File" in top_labels
    assert "&Pages" in top_labels
    assert "&Tools" in top_labels
    assert "&Merge PDFs" not in top_labels
    assert "&Create PDF" not in top_labels
    tools_menu = main_window._tools_menu_action.menu()
    tools_labels = [a.text() for a in tools_menu.actions() if not a.isSeparator()]
    assert tools_labels == ["&Merge PDFs", "&Create PDF", "All &tools"]

    file_menu = next(
        action.menu()
        for action in menubar.actions()
        if action.text().replace("&", "") == "File"
    )
    file_labels = [
        action.text()
        for action in file_menu.actions()
        if not action.isSeparator()
    ]
    assert "&Open PDF" in file_labels
    assert "&Close tab" in file_labels
    assert "Save &as" in file_labels
    assert "New &window" in file_labels
    assert "E&xit" in file_labels

    def mnemonic_letters(labels: list[str]) -> list[str]:
        letters: list[str] = []
        for label in labels:
            amp = label.find("&")
            if amp >= 0 and amp + 1 < len(label):
                letters.append(label[amp + 1].casefold())
        return letters

    top_mnemonics = mnemonic_letters(top_labels)
    assert len(top_mnemonics) == len(set(top_mnemonics))
    file_mnemonics = mnemonic_letters(file_labels)
    assert len(file_mnemonics) == len(set(file_mnemonics))


def test_toolbar_arrow_keys_move_focus(main_window, five_page_pdf, qtbot):
    toolbar = main_window._toolbar
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None)

    # show() — showMinimized can leave toolbar children !isVisible() on some WPAs.
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)

    buttons = [
        w for w in focusable_toolbar_widgets(toolbar) if isinstance(w, QToolButton)
    ]
    assert len(buttons) >= 2

    buttons[0].setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(lambda: buttons[0].hasFocus(), timeout=2000)

    qtbot.keyClick(buttons[0], Qt.Key.Key_Right)
    assert buttons[1].hasFocus()

    qtbot.keyClick(buttons[1], Qt.Key.Key_Left)
    assert buttons[0].hasFocus()


def test_status_bar_is_not_tab_focusable(main_window):
    assert main_window.statusBar().focusPolicy() == Qt.FocusPolicy.NoFocus
    assert main_window._progress_bar.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_toolbar_buttons_use_strong_focus(main_window, five_page_pdf, qtbot):
    toolbar = main_window._toolbar
    assert hasattr(toolbar, "_pagedrop_arrow_nav")

    buttons = _toolbar_tool_buttons(toolbar)
    assert buttons
    for button in buttons:
        assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus

    assert toolbar.isHidden()
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert focusable_toolbar_widgets(toolbar)


def test_toolbar_overflow_menu_restores_focus_to_its_invoker(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    qtbot.waitUntil(lambda: main_window._active_tab().loader is not None)
    # Keep More on the toolbar, outside Qt's width-dependent extension menu.
    main_window.resize(main_window._toolbar.sizeHint().width() + 100, 680)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)

    invoker = main_window._toolbar_overflow
    qtbot.waitUntil(lambda: invoker.isVisible() and invoker.isEnabled())
    invoker.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(invoker.hasFocus)
    menu = invoker.menu()
    assert menu is not None
    menu.popup(invoker.mapToGlobal(invoker.rect().bottomLeft()))
    qtbot.waitUntil(menu.isVisible)
    menu.hide()
    qtbot.waitUntil(invoker.hasFocus)


def test_viewer_tab_order_and_escape_returns_to_grid(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    tab = main_window._active_tab()
    assert tab is not None
    main_window._open_preview()
    qtbot.waitUntil(
        lambda: tab.is_viewer_mode() and len(tab.viewer_widget._tiles) >= 1,
        timeout=RENDER_TIMEOUT_MS,
    )
    viewer = tab.viewer_widget

    viewer._search_edit.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.keyClick(viewer._search_edit, Qt.Key.Key_Tab)
    previous = next(
        button
        for button in viewer._find_group.findChildren(QToolButton)
        if button.accessibleName() == "Previous search result"
    )
    qtbot.waitUntil(previous.hasFocus, timeout=2000)

    viewer.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.keyClick(viewer, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not tab.is_viewer_mode(), timeout=2000)
    assert tab.content_stack.currentWidget() is tab.thumbnail_grid


def test_tools_hub_toolbar_arrow_keys(qtbot):
    window = ToolsWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window, timeout=5000)

    toolbar = window._toolbar
    assert hasattr(toolbar, "_pagedrop_arrow_nav")
    # Search stays a normal line edit (arrows move the caret); Compact gets StrongFocus.
    assert window._compact_btn.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert window._compact_btn in focusable_toolbar_widgets(toolbar)


def test_tool_shell_run_lives_in_actions_row(qtbot):
    """R11: Run sits in #ToolShellActions — not a one-button QToolBar."""
    from PyQt6.QtWidgets import QPushButton, QToolBar

    shell = ToolShellWindow(title="Demo", description="Test shell")
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell, timeout=5000)
    assert shell._actions_host.objectName() == "ToolShellActions"
    assert shell._actions_host.isVisible()
    assert shell._run_btn.parentWidget() is shell._actions_host
    assert shell._run_btn.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert shell.findChild(QToolBar, "ToolShellToolbar") is None
    # Only one Run button on the shell.
    runs = [
        w
        for w in shell.findChildren(QPushButton)
        if w.objectName() == "ToolbarPrimary" and w.text() == "Run"
    ]
    assert runs == [shell._run_btn]


def _show(qtbot, window) -> None:
    window.show()
    qtbot.waitExposed(window, timeout=5000)


def test_status_controls_stay_focusable_after_show(main_window, qtbot):
    _show(qtbot, main_window)
    for widget in (
        main_window._move_undo_button,
        *main_window._zoom_controls.focus_widgets(),
    ):
        assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert main_window.statusBar().focusPolicy() == Qt.FocusPolicy.NoFocus
    assert main_window._progress_bar.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_tab_chain_runs_toolbar_then_content_then_status_controls(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window, timeout=15000)
    _show(qtbot, main_window)

    content = main_window._tab_manager
    assert focusable_toolbar_widgets(main_window._toolbar)
    assert main_window._toolbar.isAncestorOf(content.previousInFocusChain())

    # Walk forward from the content: its whole subtree comes first, then the
    # status-bar controls in order.
    chain = [content]
    while len(chain) < 2000:
        nxt = chain[-1].nextInFocusChain()
        if nxt is content:
            break
        chain.append(nxt)
    status = [main_window._move_undo_button, *main_window._zoom_controls.focus_widgets()]
    positions = [chain.index(w) for w in status]
    assert positions == sorted(positions)
    assert all(content.isAncestorOf(w) for w in chain[1 : positions[0]])


def _two_loaded_windows(qtbot, qapp, pdf_path):
    from tests.ui.test_window_manager import (
        _ensure_window_manager,
        _tab_at,
        _wait_for_tab_loaded,
    )

    manager = _ensure_window_manager(qapp)
    window_a = manager.open_new_window()
    window_b = manager.open_new_window()
    qtbot.addWidget(window_a)
    qtbot.addWidget(window_b)
    tabs = []
    for window in (window_a, window_b):
        tab = _tab_at(window, 0)
        window._load_pdf(str(pdf_path), tab=tab)
        _wait_for_tab_loaded(qtbot, tab)
        tab.set_zoom_level(160)
        tabs.append(tab)
    tabs[0].thumbnail_grid.selection_manager.select_single(1)
    tabs[1].thumbnail_grid.selection_manager.select_single(2)
    return window_a, window_b, tabs[0], tabs[1]


def _focus(qtbot, widget) -> None:
    widget.window().activateWindow()
    widget.setFocus()
    qtbot.waitUntil(widget.hasFocus, timeout=3000)


def test_text_input_in_one_window_does_not_drive_any_grid(
    qtbot, qapp, five_page_pdf, isolated_settings
):
    from PyQt6.QtWidgets import QLineEdit

    window_a, window_b, tab_a, tab_b = _two_loaded_windows(qtbot, qapp, five_page_pdf)
    window_a.show()
    window_b.show()
    qtbot.waitExposed(window_b, timeout=5000)
    field = QLineEdit(window_b)
    field.show()
    _focus(qtbot, field)

    zoom_a, zoom_b = tab_a.zoom_level, tab_b.zoom_level
    selection_a = set(tab_a.thumbnail_grid.selection_manager.selection)
    selection_b = set(tab_b.thumbnail_grid.selection_manager.selection)

    qtbot.keyClicks(field, "-")
    qtbot.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)

    assert tab_a.zoom_level == zoom_a
    assert tab_b.zoom_level == zoom_b
    assert set(tab_a.thumbnail_grid.selection_manager.selection) == selection_a
    assert set(tab_b.thumbnail_grid.selection_manager.selection) == selection_b
    assert field.text() == "-"
    assert field.selectedText() == "-"


def test_spin_box_focus_blocks_grid_zoom(main_window, five_page_pdf, qtbot):
    from PyQt6.QtWidgets import QSpinBox

    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window, timeout=15000)
    _show(qtbot, main_window)
    tab = main_window._active_tab()
    tab.set_zoom_level(160)
    spin = QSpinBox(main_window)
    spin.setMinimum(-50)
    spin.show()
    _focus(qtbot, spin)

    qtbot.keyClick(spin, Qt.Key.Key_Minus)

    assert tab.zoom_level == 160


def test_minus_key_zooms_only_the_window_it_targets(
    qtbot, qapp, five_page_pdf, isolated_settings
):
    window_a, window_b, tab_a, tab_b = _two_loaded_windows(qtbot, qapp, five_page_pdf)
    window_a.show()
    window_b.show()
    qtbot.waitExposed(window_b, timeout=5000)

    _focus(qtbot, tab_b.thumbnail_grid)
    qtbot.keyClick(tab_b.thumbnail_grid, Qt.Key.Key_Minus)
    assert tab_b.zoom_level < 160
    assert tab_a.zoom_level == 160

    tab_b.set_zoom_level(160)
    _focus(qtbot, tab_a.thumbnail_grid)
    qtbot.keyClick(tab_a.thumbnail_grid, Qt.Key.Key_Minus)
    assert tab_a.zoom_level < 160
    assert tab_b.zoom_level == 160


def test_grid_shortcuts_still_work_through_key_events(
    main_window, five_page_pdf, qtbot
):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window, timeout=15000)
    _show(qtbot, main_window)
    tab = main_window._active_tab()
    grid = tab.thumbnail_grid
    tab.set_zoom_level(160)
    _focus(qtbot, grid)

    qtbot.keyClick(grid, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(grid.selection_manager.selection) == 5

    qtbot.keyClick(grid, Qt.Key.Key_Plus, Qt.KeyboardModifier.ShiftModifier)
    assert tab.zoom_level > 160
    larger = tab.zoom_level
    qtbot.keyClick(grid, Qt.Key.Key_Minus)
    assert tab.zoom_level < larger


def _focus_band(widget):
    """The region that carries the focus ring: a check/radio indicator, else the edge."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QCheckBox, QRadioButton, QStyle, QStyleOptionButton

    full = widget.rect()
    if isinstance(widget, QCheckBox | QRadioButton):
        option = QStyleOptionButton()
        option.initFrom(widget)
        option.rect = full
        element = (
            QStyle.SubElement.SE_CheckBoxIndicator
            if isinstance(widget, QCheckBox)
            else QStyle.SubElement.SE_RadioButtonIndicator
        )
        return widget.style().subElementRect(element, option, widget), False
    return QRect(full), True


def _ring_pixels(widget, colour: str) -> int:
    """Pixels of ``colour`` in the widget's focus band (edge ring or indicator)."""
    from PyQt6.QtGui import QColor

    band, edge_only = _focus_band(widget)
    img = widget.grab().toImage()
    target = QColor(colour).rgb()
    depth = 3
    count = 0
    for y in range(band.top(), band.bottom() + 1):
        for x in range(band.left(), band.right() + 1):
            on_edge = (
                x - band.left() < depth
                or band.right() - x < depth
                or y - band.top() < depth
                or band.bottom() - y < depth
            )
            if (on_edge or not edge_only) and img.pixelColor(x, y).rgb() == target:
                count += 1
    return count


@pytest.mark.parametrize("light", [False, True])
def test_preferences_tab_traversal_shows_focus_on_every_control(
    qtbot, isolated_settings, light
):
    from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget

    from pagedrop.ui.preferences_dialog import PreferencesDialog
    from pagedrop.ui.theme import app_stylesheet

    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(app_stylesheet(light=light))
    dialog = PreferencesDialog()
    try:
        dialog._advanced_button.click()
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog.activateWindow()
        qtbot.waitUntil(
            lambda: dialog.isActiveWindow() and dialog.focusWidget() is not None,
            timeout=2000,
        )

        expected = {
            w
            for w in dialog.findChildren(QWidget)
            if w.focusPolicy() & Qt.FocusPolicy.TabFocus
            and w.isVisible()
            and w.isEnabled()
        }
        ring = _ring_for_theme(light)
        start = dialog.focusWidget()
        visited: list[QWidget] = []
        no_ring: list[str] = []
        for _ in range(len(expected) + 2):
            current = dialog.focusWidget()
            assert current is not None and current.isVisible() and current.isEnabled()
            visited.append(current)
            focused = _ring_pixels(current, ring)
            current.clearFocus()
            QApplication.processEvents()
            resting = _ring_pixels(current, ring)
            current.setFocus(Qt.FocusReason.TabFocusReason)
            qtbot.waitUntil(current.hasFocus, timeout=1000)
            scroll = dialog.findChild(QScrollArea, "PreferencesScroll")
            if scroll.isAncestorOf(current):
                qtbot.waitUntil(
                    lambda c=current, s=scroll: s.viewport().rect().contains(
                        c.mapTo(s.viewport(), c.rect().center())
                    ),
                    timeout=1000,
                )
            # The ring can share the label colour, so count only what focus adds.
            if focused < resting + 8:
                no_ring.append(f"{type(current).__name__}:{current.objectName()}")
            qtbot.keyClick(current, Qt.Key.Key_Tab)
            qtbot.waitUntil(lambda c=current: dialog.focusWidget() is not c, timeout=1000)
            if dialog.focusWidget() is start:
                break
        else:
            pytest.fail("Tab never returned to the first control")

        assert expected <= set(visited), expected - set(visited)
        assert not no_ring, no_ring
    finally:
        # Delete the dialog before the sheet is restored; a restyle with the
        # dialog still alive crashes later restyles intermittently.
        dialog.close()
        dialog.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.setStyleSheet(previous)


def _ring_for_theme(light: bool) -> str:
    from pagedrop.ui.theme import FOCUS_RING, FOCUS_RING_LIGHT

    return FOCUS_RING_LIGHT if light else FOCUS_RING
