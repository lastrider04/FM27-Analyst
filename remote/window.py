"""Finding the FM27 window and bringing it to the front (Windows only)."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:  # real pixels, not DPI-scaled ones, so capture and input coordinates agree
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    pass

TITLE = "Football Manager 27"
EXE = "fm.exe"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _exe_of(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return buf.value
    finally:
        kernel32.CloseHandle(h)


def find() -> int | None:
    """The visible main window of fm.exe, or None when FM27 isn't running."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _exe_of(hwnd).lower().rsplit("\\", 1)[-1] == EXE:
            r = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            if r.right > 200 and r.bottom > 200:        # skip the IME helper windows
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def client_size(hwnd: int) -> tuple[int, int]:
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right, r.bottom


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    pt = wintypes.POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def is_front(hwnd: int) -> bool:
    return user32.GetForegroundWindow() == hwnd


def bring_to_front(hwnd: int) -> bool:
    """FM27 only takes real input while it's the foreground window. A quick Alt tap is the documented way for a
    background process to be allowed to change the foreground window."""
    if is_front(hwnd) and not user32.IsIconic(hwnd):
        return True
    user32.keybd_event(0x12, 0, 0, 0)        # Alt down
    user32.keybd_event(0x12, 0, 2, 0)        # Alt up
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)           # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    for _ in range(20):
        if is_front(hwnd):
            return True
        time.sleep(0.02)
    return False
