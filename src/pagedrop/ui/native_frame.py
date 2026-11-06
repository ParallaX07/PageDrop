"""Win32 helpers that let a frameless window keep the native frame behaviour.

Everything here is pure ctypes. The module imports on any platform; the
wrappers at the bottom are the only code that reaches the Win32 libraries and
they are only meant to be called when ``IS_WINDOWS`` is true.
"""

from __future__ import annotations

import ctypes
import functools
import sys

from PyQt6.QtCore import Qt

IS_WINDOWS = sys.platform == "win32"

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCMOUSELEAVE = 0x02A2

HTCLIENT = 1
HTCAPTION = 2
HTMAXBUTTON = 9
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

WS_MAXIMIZEBOX = 0x00010000
WS_MINIMIZEBOX = 0x00020000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_CAPTION = 0x00C00000
FRAME_STYLES = WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU

GWL_STYLE = -16

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

SM_CXSIZEFRAME = 32
SM_CYSIZEFRAME = 33
SM_CXPADDEDBORDER = 92

TME_LEAVE = 0x00000002
TME_NONCLIENT = 0x00000010

DEFAULT_DPI = 96


# ctypes.wintypes.MSG has the wrong field widths off Windows, so the layouts
# are spelled out here and stay identical on every platform.
class MSG(ctypes.Structure):
    _fields_ = (
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("pt_x", ctypes.c_int32),
        ("pt_y", ctypes.c_int32),
    )


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_int32),
        ("top", ctypes.c_int32),
        ("right", ctypes.c_int32),
        ("bottom", ctypes.c_int32),
    )


class NCCALCSIZE_PARAMS(ctypes.Structure):  # noqa: N801
    _fields_ = (("rgrc", RECT * 3), ("lppos", ctypes.c_void_p))


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = (
        ("cbSize", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("hwndTrack", ctypes.c_void_p),
        ("dwHoverTime", ctypes.c_uint32),
    )


def read_message(address: int) -> MSG:
    """View the MSG that Qt hands to ``nativeEvent`` as a ctypes structure."""
    return MSG.from_address(int(address))


def lparam_point(lparam: int) -> tuple[int, int]:
    """Split a packed lParam into signed x and y (negative on a left/upper monitor)."""
    return (
        ctypes.c_int16(lparam & 0xFFFF).value,
        ctypes.c_int16((lparam >> 16) & 0xFFFF).value,
    )


def hit_test_for_edges(edges: Qt.Edge) -> int:
    """Map Qt edge flags to the matching resize hit-test code, or 0 for none."""
    left = bool(edges & Qt.Edge.LeftEdge)
    right = bool(edges & Qt.Edge.RightEdge)
    top = bool(edges & Qt.Edge.TopEdge)
    bottom = bool(edges & Qt.Edge.BottomEdge)
    if top:
        return HTTOPLEFT if left else HTTOPRIGHT if right else HTTOP
    if bottom:
        return HTBOTTOMLEFT if left else HTBOTTOMRIGHT if right else HTBOTTOM
    return HTLEFT if left else HTRIGHT if right else 0


def calc_size_rect(wparam: int, lparam: int) -> RECT:
    """Return the proposed window rectangle of a WM_NCCALCSIZE message.

    With wParam true lParam points at NCCALCSIZE_PARAMS whose first rectangle is
    the proposed window; otherwise lParam points at that rectangle directly.
    """
    if wparam:
        return NCCALCSIZE_PARAMS.from_address(lparam).rgrc[0]
    return RECT.from_address(lparam)


def inset_rect(rect: RECT, thickness_x: int, thickness_y: int) -> None:
    """Shrink a rectangle in place by the given thickness on every side."""
    rect.left += thickness_x
    rect.right -= thickness_x
    rect.top += thickness_y
    rect.bottom -= thickness_y


@functools.cache
def _user32():
    # A private library handle: argtypes set here must not leak to other users.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = ctypes.c_void_p
    user32.GetWindowRect.argtypes = (hwnd, ctypes.POINTER(RECT))
    user32.GetWindowRect.restype = ctypes.c_int
    get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    get_long.argtypes = (hwnd, ctypes.c_int)
    get_long.restype = ctypes.c_ssize_t
    set_long.argtypes = (hwnd, ctypes.c_int, ctypes.c_ssize_t)
    set_long.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = (
        hwnd,
        hwnd,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    )
    user32.SetWindowPos.restype = ctypes.c_int
    user32.GetDpiForWindow.argtypes = (hwnd,)
    user32.GetDpiForWindow.restype = ctypes.c_uint
    user32.GetSystemMetricsForDpi.argtypes = (ctypes.c_int, ctypes.c_uint)
    user32.GetSystemMetricsForDpi.restype = ctypes.c_int
    user32.IsZoomed.argtypes = (hwnd,)
    user32.IsZoomed.restype = ctypes.c_int
    user32.TrackMouseEvent.argtypes = (ctypes.POINTER(TRACKMOUSEEVENT),)
    user32.TrackMouseEvent.restype = ctypes.c_int
    return user32, get_long, set_long


def window_origin(hwnd: int) -> tuple[int, int]:
    """Top-left of the window in physical screen pixels."""
    user32, _, _ = _user32()
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    return rect.left, rect.top


def is_zoomed(hwnd: int) -> bool:
    """Ask Windows whether the window is maximized.

    WM_NCCALCSIZE for a maximize arrives before Qt has updated its own window
    state, so Qt's ``isMaximized()`` cannot be trusted for that message.
    """
    user32, _, _ = _user32()
    return bool(user32.IsZoomed(hwnd))


def apply_frame_styles(hwnd: int) -> None:
    """Add the native frame styles so snapping and edge resize work."""
    user32, get_long, set_long = _user32()
    style = get_long(hwnd, GWL_STYLE)
    if not style:
        raise ctypes.WinError(ctypes.get_last_error())
    set_long(hwnd, GWL_STYLE, (style | FRAME_STYLES) & 0xFFFFFFFF)
    flags = SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
    if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, flags):
        raise ctypes.WinError(ctypes.get_last_error())


def resize_frame_thickness(hwnd: int) -> tuple[int, int]:
    """Horizontal and vertical resize-frame thickness in physical pixels."""
    user32, _, _ = _user32()
    dpi = user32.GetDpiForWindow(hwnd) or DEFAULT_DPI
    padded = user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
    return (
        user32.GetSystemMetricsForDpi(SM_CXSIZEFRAME, dpi) + padded,
        user32.GetSystemMetricsForDpi(SM_CYSIZEFRAME, dpi) + padded,
    )


def track_nonclient_leave(hwnd: int) -> None:
    """Ask Windows to send WM_NCMOUSELEAVE when the pointer leaves the frame."""
    user32, _, _ = _user32()
    track = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE | TME_NONCLIENT, hwnd, 0)
    if not user32.TrackMouseEvent(ctypes.byref(track)):
        raise ctypes.WinError(ctypes.get_last_error())
