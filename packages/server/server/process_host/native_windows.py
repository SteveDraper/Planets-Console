"""Windows GUI-subsystem host: unowned HWND taskbar button, Close / Alt-F4."""

from __future__ import annotations

import ctypes
import logging
from typing import Protocol

from server.package_identity import APP_USER_MODEL_ID, CONSOLE_PACKAGE_DISPLAY_NAME

_LOGGER = logging.getLogger("server.process_host.native_windows")
_KEEP_WNDPROC: list[object] = []

WS_OVERLAPPED = 0x00000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_EX_APPWINDOW = 0x00040000
SW_SHOWMINNOACTIVE = 7
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_SYSCOMMAND = 0x0112
SC_CLOSE = 0xF060
SC_RESTORE = 0xF120
SC_MAXIMIZE = 0xF030
CW_USEDEFAULT = 0x80000000


class WindowsHostCallbacks(Protocol):
    def request_stop(self) -> None: ...

    def reopen_browser(self) -> None: ...


def apply_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Set the process AppUserModelID before creating windows."""
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def _sys_command(wparam: int) -> int:
    return int(wparam) & 0xFFF0


def run_win32_loop(callbacks: WindowsHostCallbacks) -> None:
    """Block on a hidden/minimized unowned HWND until Close / Alt-F4."""
    from ctypes import wintypes

    apply_app_user_model_id()
    user32 = ctypes.windll.user32
    lresult = ctypes.c_ssize_t
    wndproc_type = ctypes.WINFUNCTYPE(
        lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc_type),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    class_name = "PlanetsConsoleProcessHost"
    wndproc = wndproc_type(_make_wnd_proc(callbacks, user32))
    wc = WNDCLASSW()
    wc.lpfnWndProc = wndproc
    wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc.lpszClassName = class_name
    atom = user32.RegisterClassW(ctypes.byref(wc))
    if not atom:
        raise ctypes.WinError()
    hwnd = user32.CreateWindowExW(
        WS_EX_APPWINDOW,
        class_name,
        CONSOLE_PACKAGE_DISPLAY_NAME,
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT,
        CW_USEDEFAULT,
        1,
        1,
        None,
        None,
        wc.hInstance,
        None,
    )
    if not hwnd:
        raise ctypes.WinError()
    user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
    # WNDPROC must remain referenced for the lifetime of the window.
    _KEEP_WNDPROC.append(wndproc)
    _LOGGER.info("Starting Win32 message loop")
    msg = MSG()
    while True:
        result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if result == 0:
            break
        if result == -1:
            raise ctypes.WinError()
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def _make_wnd_proc(callbacks: WindowsHostCallbacks, user32: object):
    def wnd_proc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == WM_SYSCOMMAND:
            command = _sys_command(wparam)
            if command in (SC_RESTORE, SC_MAXIMIZE):
                callbacks.reopen_browser()
                user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
                return 0
            if command == SC_CLOSE:
                callbacks.request_stop()
                user32.DestroyWindow(hwnd)
                return 0
        if message == WM_CLOSE:
            callbacks.request_stop()
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    return wnd_proc
