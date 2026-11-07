"""The app installs no application-wide Python event filter; each filter is scoped."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from pagedrop.ui import accessibility
from pagedrop.ui.main_window import MainWindow
from pagedrop.ui.update_checker import UpdateCoordinator
from pagedrop.ui.update_presenter import UpdatePresenter
from tests.conftest import wait_for_pdf_loaded


class _KeyEater(QPushButton):
    """Consumes every key press, so only a filter on this widget can see it first."""

    def keyPressEvent(self, event):  # noqa: N802
        event.accept()


def _mouse(kind, local, global_pos, button=Qt.MouseButton.LeftButton, buttons=None):
    if buttons is None:
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    return QMouseEvent(
        kind, QPointF(*local), QPointF(*global_pos), button, buttons, Qt.KeyboardModifier.NoModifier
    )


def test_window_presenter_and_accessibility_install_no_application_filter(
    qapp, qtbot, isolated_settings, monkeypatch
):
    installed = []
    original = qapp.installEventFilter

    def record(watcher):
        installed.append(watcher)
        original(watcher)

    monkeypatch.setattr(qapp, "installEventFilter", record)

    window = MainWindow()
    qtbot.addWidget(window)

    class Manager(QObject):
        def __init__(self):
            super().__init__()
            self.primary = window
            self.windows = [window]
            self.update_coordinator = UpdateCoordinator(qapp, supported=True, check=lambda *_: None)

    manager = Manager()
    presenter = UpdatePresenter(manager)
    accessibility.install_accessibility(qapp)
    window.show()
    qtbot.waitExposed(window)

    assert installed == []
    manager.update_coordinator.stop()
    presenter.deleteLater()
    window._temp_manager.cleanup()


def test_colour_scheme_change_reapplies_the_stylesheet_once_installed(qapp, monkeypatch):
    accessibility.install_accessibility(qapp)
    calls = []
    monkeypatch.setattr(accessibility, "apply_app_stylesheet", lambda app=None: calls.append(app))

    QGuiApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert len(calls) == 1

    accessibility.install_accessibility(qapp)  # install-once: no second connection
    calls.clear()
    QGuiApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert len(calls) == 1


def test_page_shortcuts_follow_focus_between_widgets(main_window, five_page_pdf, qtbot):
    main_window._load_pdf(str(five_page_pdf))
    wait_for_pdf_loaded(qtbot, main_window, timeout=15000)
    main_window.show()
    qtbot.waitExposed(main_window)
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window, timeout=5000)
    grid = main_window._thumbnail_grid

    first = _KeyEater("first", main_window)
    second = _KeyEater("second", main_window)
    for button in (first, second):
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.show()

    first.setFocus()
    qtbot.waitUntil(lambda: main_window._key_filter_widget is first)
    before = grid.thumbnail_width_px
    qtbot.keyClick(first, Qt.Key.Key_Plus, Qt.KeyboardModifier.NoModifier)
    assert grid.thumbnail_width_px > before

    second.setFocus()
    qtbot.waitUntil(lambda: main_window._key_filter_widget is second)
    before = grid.thumbnail_width_px
    qtbot.keyClick(second, Qt.Key.Key_Minus, Qt.KeyboardModifier.NoModifier)
    assert grid.thumbnail_width_px < before


def test_key_filter_is_removed_when_focus_leaves_the_window(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    qtbot.waitUntil(lambda: QApplication.activeWindow() is main_window, timeout=5000)
    inside = QPushButton("inside", main_window)
    inside.show()
    outside = QWidget()
    qtbot.addWidget(outside)

    main_window._on_focus_changed(None, inside)
    assert main_window._key_filter_widget is inside
    main_window._on_focus_changed(inside, outside)
    assert main_window._key_filter_widget is None

    main_window._on_focus_changed(None, inside)
    main_window.close()
    assert main_window._key_filter_widget is None


def test_window_handle_receives_edge_events_without_an_application_filter(
    main_window, qtbot, monkeypatch
):
    main_window.show()
    qtbot.waitExposed(main_window)
    monkeypatch.setattr(main_window, "_uses_qt_edge_resize", lambda: True)
    handle = main_window.windowHandle()
    hover = _mouse(
        QEvent.Type.MouseMove, (3, 300), (3, 300), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton
    )
    try:
        QApplication.sendEvent(handle, hover)
        assert QApplication.overrideCursor().shape() == Qt.CursorShape.SizeHorCursor
    finally:
        main_window._clear_edge_state()
    assert QApplication.overrideCursor() is None


def test_title_bar_press_is_tracked_through_its_own_filter(main_window):
    press = _mouse(QEvent.Type.MouseButtonPress, (5, 5), (5, 5))
    QApplication.sendEvent(main_window._title_bar, press)
    assert main_window._title_press_pos is not None
    release = _mouse(QEvent.Type.MouseButtonRelease, (5, 5), (5, 5))
    QApplication.sendEvent(main_window._title_bar, release)
    assert main_window._title_press_pos is None
