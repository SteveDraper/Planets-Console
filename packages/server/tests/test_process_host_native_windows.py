"""Win32 prototype declarations for the Windows process host message loop."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from types import SimpleNamespace

import pytest
from server.process_host.native_windows import CW_USEDEFAULT, declare_win32_prototypes

POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)


class _FakeDll:
    """Records ``argtypes`` / ``restype`` assigned to each looked-up function."""

    def __init__(self) -> None:
        self._functions: dict[str, SimpleNamespace] = {}

    def __getattr__(self, name: str) -> SimpleNamespace:
        return self._functions.setdefault(name, SimpleNamespace())


class _WindowClass(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT)]


class _Message(ctypes.Structure):
    _fields_ = [("message", wintypes.UINT)]


@pytest.fixture
def declared() -> tuple[_FakeDll, _FakeDll]:
    user32 = _FakeDll()
    kernel32 = _FakeDll()
    declare_win32_prototypes(user32, kernel32, wndclass_type=_WindowClass, msg_type=_Message)
    return user32, kernel32


def test_every_call_declares_argtypes_and_restype(declared):
    user32, kernel32 = declared
    expected_user32 = {
        "RegisterClassW",
        "CreateWindowExW",
        "ShowWindow",
        "DestroyWindow",
        "DefWindowProcW",
        "PostQuitMessage",
        "GetMessageW",
        "TranslateMessage",
        "DispatchMessageW",
    }
    assert set(user32._functions) == expected_user32
    assert set(kernel32._functions) == {"GetModuleHandleW"}
    for dll in (user32, kernel32):
        for function in dll._functions.values():
            assert hasattr(function, "argtypes")
            assert hasattr(function, "restype")


def test_handles_are_declared_pointer_sized(declared):
    user32, kernel32 = declared

    create_window = user32.CreateWindowExW
    assert len(create_window.argtypes) == 12
    window_handle_slots = (8, 9, 10, 11)  # parent, menu, hInstance, lpParam
    for slot in window_handle_slots:
        assert ctypes.sizeof(create_window.argtypes[slot]) == POINTER_SIZE
    assert ctypes.sizeof(create_window.restype) == POINTER_SIZE
    assert ctypes.sizeof(kernel32.GetModuleHandleW.restype) == POINTER_SIZE


def test_default_window_proc_accepts_pointer_sized_wparam_and_lparam(declared):
    user32, _ = declared

    default_proc = user32.DefWindowProcW
    hwnd, message, wparam, lparam = default_proc.argtypes
    assert ctypes.sizeof(hwnd) == POINTER_SIZE
    assert ctypes.sizeof(message) == ctypes.sizeof(ctypes.c_uint)
    assert ctypes.sizeof(wparam) == POINTER_SIZE
    assert ctypes.sizeof(lparam) == POINTER_SIZE
    assert ctypes.sizeof(default_proc.restype) == POINTER_SIZE
    assert ctypes.sizeof(user32.DispatchMessageW.restype) == POINTER_SIZE


def test_create_window_accepts_use_default_coordinates(declared):
    user32, _ = declared
    position_slot_x, position_slot_y = 4, 5
    for slot in (position_slot_x, position_slot_y):
        argtype = user32.CreateWindowExW.argtypes[slot]
        assert argtype(CW_USEDEFAULT).value == -(2**31)
