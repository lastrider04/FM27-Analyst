"""A small banner on the PC while a phone controls FM27 (or while control is paused).

It sits at the bottom centre of the screen, always on top, and never takes focus or clicks: FM27 must stay the
foreground window (it only accepts input then), and the phone's clicks must pass straight through. It isn't in the
phone's picture, because the stream captures only the FM27 window.

A single plain Win32 popup (no child windows, unlike Tk), so "layered + transparent" really makes it click-through.
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = (
    0x00000008, 0x00000020, 0x00000080, 0x00080000, 0x08000000)
WM_PAINT, WM_DESTROY, WM_APP = 0x000F, 0x0002, 0x8000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
LWA_ALPHA = 0x2
DT_CENTER, DT_VCENTER, DT_SINGLELINE = 0x1, 0x4, 0x20
TRANSPARENT_BK = 1
PAD_X, PAD_Y, BOTTOM_GAP = 18, 9, 60
BLUE, AMBER, WHITE = 0xD84E1D, 0x0953B4, 0xFFFFFF       # COLORREF is 0x00BBGGRR


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.SIZE)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class Banner:
    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.hwnd = None
        self.text, self.colour = "", BLUE
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="remote-banner")
        self.thread.start()
        self.ready.wait(3)

    def show(self, text: str, warn: bool = False) -> None:
        self._post((text, AMBER if warn else BLUE))

    def hide(self) -> None:
        self._post(None)

    def _post(self, item) -> None:
        self.q.put(item)
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP, 0, 0)

    # ------------------------------------------------------------- the window's own thread
    def _run(self) -> None:
        self._proc = WNDPROC(self._wndproc)      # keep a reference: ctypes callbacks must outlive the window
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._proc, hInstance=hinst,
                         lpszClassName="FM27RemoteBanner")
        user32.RegisterClassExW(ctypes.byref(wc))
        ex = WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(ex, "FM27RemoteBanner", "FM27 remote play", WS_POPUP,
                                           0, 0, 10, 10, None, None, hinst, None)
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 235, LWA_ALPHA)
        self.font = gdi32.CreateFontW(-15, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _apply(self) -> None:
        item = None
        got = False
        while True:                                  # only the latest request matters
            try:
                item = self.q.get_nowait()
                got = True
            except queue.Empty:
                break
        if not got:
            return
        if item is None:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            return
        self.text, self.colour = item
        dc = user32.GetDC(self.hwnd)
        old = gdi32.SelectObject(dc, self.font)
        size = wintypes.SIZE()
        gdi32.GetTextExtentPoint32W(dc, self.text, len(self.text), ctypes.byref(size))
        gdi32.SelectObject(dc, old)
        user32.ReleaseDC(self.hwnd, dc)
        w, h = size.cx + 2 * PAD_X, size.cy + 2 * PAD_Y
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, (sw - w) // 2, sh - h - BOTTOM_GAP, w, h,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)
        user32.InvalidateRect(self.hwnd, None, True)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_APP:
            self._apply()
            return 0
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            dc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            brush = gdi32.CreateSolidBrush(self.colour)
            user32.FillRect(dc, ctypes.byref(rect), brush)
            gdi32.DeleteObject(brush)
            old = gdi32.SelectObject(dc, self.font)
            gdi32.SetBkMode(dc, TRANSPARENT_BK)
            gdi32.SetTextColor(dc, WHITE)
            user32.DrawTextW(dc, self.text, -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE)
            gdi32.SelectObject(dc, old)
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
