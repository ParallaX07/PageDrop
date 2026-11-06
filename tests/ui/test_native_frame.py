"""Native Windows frame handling, exercised with synthetic window messages.

These run on every platform: the Win32 wrappers are patched and the messages
are real structures in memory, passed the way Qt passes them. They do not
prove behaviour on a real Windows desktop.
"""

from __future__ import annotations

import ctypes
import sys

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QByteArray, QPoint, Qt

from pagedrop.ui import native_frame as nf

ORIGIN = (200, 100)
THICKNESS = (8, 9)
EVENT_TYPE = b"windows_generic_MSG"


def pack(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


class Sender:
    """Builds MSG structures and feeds them to a window's nativeEvent."""

    def __init__(self, window):
        self.window = window
        self.keep = []

    def send(self, message, wparam=0, lparam=0, event_type=None):
        msg = nf.MSG(int(self.window.winId()), message, wparam, lparam, 0, 0, 0)
        self.keep.append(msg)
        event_type = QByteArray(EVENT_TYPE) if event_type is None else event_type
        return self.window.nativeEvent(event_type, sip.voidptr(ctypes.addressof(msg)))

    def hit(self, x, y, ratio=1.0, origin=ORIGIN):
        """Hit-test a window-local logical point, as Windows sends it in screen pixels."""
        screen = (origin[0] + round(x * ratio), origin[1] + round(y * ratio))
        handled, result = self.send(nf.WM_NCHITTEST, 0, pack(*screen))
        assert handled
        return result


@pytest.fixture
def native(main_window, qtbot, monkeypatch):
    monkeypatch.setattr(main_window, "_uses_native_frame", lambda: True)
    monkeypatch.setattr(nf, "apply_frame_styles", lambda hwnd: None)
    monkeypatch.setattr(nf, "window_origin", lambda hwnd: ORIGIN)
    monkeypatch.setattr(nf, "resize_frame_thickness", lambda hwnd: THICKNESS)
    monkeypatch.setattr(nf, "is_zoomed", lambda hwnd: False)
    monkeypatch.setattr(nf, "track_nonclient_leave", lambda hwnd: None)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    return Sender(main_window)


def center_in_window(window, widget):
    return widget.mapTo(window, widget.rect().center())


def blank_title_point(window):
    menubar = window._menu_bar
    blank = menubar.mapTo(window, QPoint(menubar.width() - 3, menubar.height() // 2))
    assert menubar.actionAt(menubar.mapFrom(window, blank)) is None
    return blank


def test_lparam_point_sign_extends_negative_coordinates():
    assert nf.lparam_point(pack(-1, -1200)) == (-1, -1200)
    assert nf.lparam_point(pack(1919, 1079)) == (1919, 1079)
    assert nf.lparam_point(pack(-32768, 32767)) == (-32768, 32767)


def test_msg_layout_matches_64_bit_offsets():
    assert nf.MSG.message.offset == 8
    assert nf.MSG.wParam.offset == 16
    assert nf.MSG.lParam.offset == 24
    msg = nf.MSG(1, 0x84, 7, -5, 0, 0, 0)
    read = nf.read_message(ctypes.addressof(msg))
    assert (read.message, read.wParam, read.lParam) == (0x84, 7, -5)
    assert nf.NCCALCSIZE_PARAMS.rgrc.offset == 0
    assert ctypes.sizeof(nf.RECT) == 16


@pytest.mark.parametrize("ratio", [1.0, 1.5])
def test_every_edge_and_corner_maps_to_its_hit_value(native, main_window, monkeypatch, ratio):
    monkeypatch.setattr(main_window, "devicePixelRatioF", lambda: ratio)
    w, h = main_window.width(), main_window.height()
    cases = {
        nf.HTLEFT: (1, h // 2),
        nf.HTRIGHT: (w - 2, h // 2),
        nf.HTTOP: (w // 2, 1),
        nf.HTBOTTOM: (w // 2, h - 2),
        nf.HTTOPLEFT: (1, 1),
        nf.HTTOPRIGHT: (w - 2, 1),
        nf.HTBOTTOMLEFT: (1, h - 2),
        nf.HTBOTTOMRIGHT: (w - 2, h - 2),
    }
    for expected, (x, y) in cases.items():
        assert native.hit(x, y, ratio) == expected


def test_edge_wins_over_the_title_area(native, main_window):
    blank = blank_title_point(main_window)
    assert native.hit(blank.x(), blank.y()) == nf.HTCAPTION
    assert native.hit(blank.x(), 1) == nf.HTTOP


def test_maximized_window_has_no_edge_values(native, main_window, monkeypatch):
    monkeypatch.setattr(main_window, "isMaximized", lambda: True)
    w, h = main_window.width(), main_window.height()
    for x, y in ((1, h // 2), (w - 2, h // 2), (1, 1), (w - 2, h - 2), (w // 2, h - 2)):
        assert native.hit(x, y) not in {
            nf.HTLEFT, nf.HTRIGHT, nf.HTTOP, nf.HTBOTTOM,
            nf.HTTOPLEFT, nf.HTTOPRIGHT, nf.HTBOTTOMLEFT, nf.HTBOTTOMRIGHT,
        }


def test_title_bar_regions_map_to_caption_buttons_or_client(native, main_window):
    window = main_window
    maximize = center_in_window(window, window._maximize_button)
    assert native.hit(maximize.x(), maximize.y()) == nf.HTMAXBUTTON
    for name in ("WindowMinimize", "WindowClose"):
        button = window._window_controls.findChild(type(window._maximize_button), name)
        point = center_in_window(window, button)
        assert native.hit(point.x(), point.y()) == nf.HTCLIENT

    menubar = window._menu_bar
    action = menubar.actionGeometry(menubar.actions()[0]).center()
    point = menubar.mapTo(window, action)
    assert native.hit(point.x(), point.y()) == nf.HTCLIENT

    blank = blank_title_point(window)
    assert native.hit(blank.x(), blank.y()) == nf.HTCAPTION

    title = center_in_window(window, window._title_label)
    if window._title_label.width() > 0:
        assert native.hit(title.x(), title.y()) == nf.HTCAPTION

    assert native.hit(window.width() // 2, window.height() // 2) == nf.HTCLIENT


def test_hit_test_converts_physical_pixels_with_origin_and_scale(native, main_window, monkeypatch):
    monkeypatch.setattr(main_window, "devicePixelRatioF", lambda: 1.5)
    point = center_in_window(main_window, main_window._maximize_button)
    # A window left of the primary monitor; an ignored origin or scale misses the button.
    monkeypatch.setattr(nf, "window_origin", lambda hwnd: (-1500, 40))
    assert native.hit(point.x(), point.y(), 1.5, origin=(-1500, 40)) == nf.HTMAXBUTTON


def test_calc_size_leaves_a_normal_window_unchanged(native):
    params = nf.NCCALCSIZE_PARAMS()
    params.rgrc[0] = nf.RECT(10, 20, 810, 620)
    handled, result = native.send(nf.WM_NCCALCSIZE, 1, ctypes.addressof(params))
    assert (handled, result) == (True, 0)
    rect = params.rgrc[0]
    assert (rect.left, rect.top, rect.right, rect.bottom) == (10, 20, 810, 620)


def test_calc_size_insets_a_maximized_window_on_all_sides(native, monkeypatch):
    monkeypatch.setattr(nf, "is_zoomed", lambda hwnd: True)
    params = nf.NCCALCSIZE_PARAMS()
    params.rgrc[0] = nf.RECT(-8, -9, 1928, 1089)
    handled, result = native.send(nf.WM_NCCALCSIZE, 1, ctypes.addressof(params))
    assert (handled, result) == (True, 0)
    rect = params.rgrc[0]
    assert (rect.left, rect.top, rect.right, rect.bottom) == (0, 0, 1920, 1080)


def test_calc_size_without_params_insets_the_bare_rect(native, monkeypatch):
    monkeypatch.setattr(nf, "is_zoomed", lambda hwnd: True)
    rect = nf.RECT(-8, -9, 1928, 1089)
    handled, result = native.send(nf.WM_NCCALCSIZE, 0, ctypes.addressof(rect))
    assert (handled, result) == (True, 0)
    assert (rect.left, rect.top, rect.right, rect.bottom) == (0, 0, 1920, 1080)


def test_maximize_button_press_and_release_toggles_once(native, main_window, monkeypatch):
    toggles = []
    monkeypatch.setattr(main_window, "_toggle_maximized", lambda: toggles.append(1))
    button = main_window._maximize_button
    assert native.send(nf.WM_NCLBUTTONDOWN, nf.HTMAXBUTTON) == (True, 0)
    assert button.isDown()
    assert toggles == []
    assert native.send(nf.WM_NCLBUTTONUP, nf.HTMAXBUTTON) == (True, 0)
    assert not button.isDown()
    assert toggles == [1]
    # A release with no matching press is swallowed and does nothing.
    assert native.send(nf.WM_NCLBUTTONUP, nf.HTMAXBUTTON)[0] is True
    assert toggles == [1]


def test_other_caption_presses_are_left_to_windows(native, main_window, monkeypatch):
    toggles = []
    monkeypatch.setattr(main_window, "_toggle_maximized", lambda: toggles.append(1))
    assert not native.send(nf.WM_NCLBUTTONDOWN, nf.HTCAPTION)[0]
    assert not native.send(nf.WM_NCLBUTTONUP, nf.HTCAPTION)[0]
    assert toggles == []
    assert not main_window._maximize_button.isDown()


def test_maximize_hover_is_set_and_cleared_by_move_and_leave(native, main_window, monkeypatch):
    tracked = []
    monkeypatch.setattr(nf, "track_nonclient_leave", tracked.append)
    button = main_window._maximize_button

    handled, _ = native.send(nf.WM_NCMOUSEMOVE, nf.HTMAXBUTTON)
    assert not handled  # left to Windows so the snap flyout can appear
    assert button.property("nativeHover") is True
    assert len(tracked) == 1
    native.send(nf.WM_NCMOUSEMOVE, nf.HTMAXBUTTON)
    assert len(tracked) == 1

    button.setDown(True)
    native.send(nf.WM_NCMOUSEMOVE, nf.HTCAPTION)
    assert button.property("nativeHover") is False
    assert not button.isDown()

    native.send(nf.WM_NCMOUSEMOVE, nf.HTMAXBUTTON)
    assert button.property("nativeHover") is True
    native.send(nf.WM_NCMOUSELEAVE)
    assert button.property("nativeHover") is False


def test_native_hover_has_a_stylesheet_rule_in_both_themes():
    from pagedrop.ui.theme import app_stylesheet

    for light in (False, True):
        sheet = app_stylesheet(light=light)
        assert 'QToolButton#WindowMaximize[nativeHover="true"]' in sheet


def test_frame_styles_apply_once_on_first_show_when_native(main_window, qtbot, monkeypatch):
    applied = []
    monkeypatch.setattr(main_window, "_uses_native_frame", lambda: True)
    monkeypatch.setattr(nf, "apply_frame_styles", applied.append)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    main_window.hide()
    main_window.show()
    assert applied == [int(main_window.winId())]


def test_frame_styles_are_skipped_when_not_native(main_window, qtbot, monkeypatch):
    applied = []
    monkeypatch.setattr(nf, "apply_frame_styles", applied.append)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert applied == []


def test_failed_style_application_is_logged_and_the_window_still_shows(
    main_window, qtbot, monkeypatch
):
    logged = []

    def boom(hwnd):
        raise OSError("no frame")

    monkeypatch.setattr(main_window, "_uses_native_frame", lambda: True)
    monkeypatch.setattr(nf, "apply_frame_styles", boom)
    monkeypatch.setattr(
        "pagedrop.ui.main_window.log_failure", lambda op, exc, **ctx: logged.append((op, exc))
    )
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert main_window.isVisible()
    assert len(logged) == 1 and isinstance(logged[0][1], OSError)
    assert main_window._native_frame_failed


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows predicate")
def test_failed_styles_hand_edge_resize_back_to_qt(main_window, qtbot, monkeypatch):
    main_window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    monkeypatch.setattr(nf, "IS_WINDOWS", True)
    monkeypatch.setattr(
        nf, "apply_frame_styles", lambda hwnd: (_ for _ in ()).throw(OSError("no frame"))
    )
    monkeypatch.setattr("pagedrop.ui.main_window.log_failure", lambda *a, **k: None)
    monkeypatch.setattr("pagedrop.ui.main_window.sys.platform", "win32")
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert not main_window._uses_native_frame()
    assert main_window._uses_qt_edge_resize()


def test_native_message_error_is_logged_once_and_falls_through(native, main_window, monkeypatch):
    logged = []

    def boom(hwnd):
        raise OSError("no rect")

    monkeypatch.setattr(nf, "window_origin", boom)
    monkeypatch.setattr(
        "pagedrop.ui.main_window.log_failure", lambda op, exc, **ctx: logged.append(exc)
    )
    assert not native.send(nf.WM_NCHITTEST, 0, pack(300, 200))[0]
    assert not native.send(nf.WM_NCHITTEST, 0, pack(300, 200))[0]
    assert len(logged) == 1


def test_other_event_types_and_messages_fall_through(native):
    msg = nf.MSG(0, nf.WM_NCHITTEST, 0, pack(300, 200), 0, 0, 0)
    handled, _ = native.window.nativeEvent(
        QByteArray(b"xcb_generic_event_t"), sip.voidptr(ctypes.addressof(msg))
    )
    assert not handled
    assert not native.send(0x0200)[0]  # WM_MOUSEMOVE
    # Plain bytes are accepted as the event type too.
    assert native.send(nf.WM_NCHITTEST, 0, pack(300, 200), event_type=EVENT_TYPE)[0]


def test_real_predicate_falls_through_without_touching_win32(main_window, qtbot, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Win32 wrapper called")

    for name in (
        "window_origin", "apply_frame_styles", "resize_frame_thickness",
        "is_zoomed", "track_nonclient_leave",
    ):
        monkeypatch.setattr(nf, name, forbidden)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert not main_window._uses_native_frame()
    sender = Sender(main_window)
    for message in (nf.WM_NCHITTEST, nf.WM_NCCALCSIZE, nf.WM_NCLBUTTONDOWN):
        assert not sender.send(message, nf.HTMAXBUTTON, pack(300, 200))[0]


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows predicate")
def test_qt_edge_resize_stays_off_on_windows(main_window, qtbot, monkeypatch):
    main_window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    main_window.show()
    qtbot.waitExposed(main_window, timeout=5000)
    assert main_window._uses_qt_edge_resize()
    monkeypatch.setattr("pagedrop.ui.main_window.sys.platform", "win32")
    assert not main_window._uses_qt_edge_resize()
