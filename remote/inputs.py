"""Mouse and keyboard input for FM27 through SendInput.

Phase 0 showed FM27 (Unity) ignores posted window messages and only reacts to real input while it's the foreground
window, so every action brings it to the front first. Coordinates are FM27 client pixels; they're clipped to the
window, so a phone can never click anywhere else on the PC. The mouse wheel only registers after a real mouse-move
event, so every pointer action starts with one.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from . import window

user32 = window.user32

MOVE, LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP, WHEEL, ABSOLUTE, VIRTUALDESK = (
    0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0800, 0x8000, 0x4000)
KEYUP, UNICODE, SCANCODE = 0x0002, 0x0004, 0x0008
XDOWN, XUP = 0x0080, 0x0100
NAV_BUTTONS = {"back": 0x0001, "forward": 0x0002}    # the mouse's side buttons (XBUTTON1/2): FM27's Back and Forward
PRESS_HOLD_S = 0.15       # button held this long before a drag starts moving
DRAG_STEP_PX = 12         # drag moves are split into steps no bigger than this
DRAG_STEP_S = 0.006

# the keys the phone toolbar and keyboard can send (no system keys: no Win, no Alt+Tab, no Ctrl+Alt+Del)
KEYS = {"enter": 0x0D, "escape": 0x1B, "backspace": 0x08, "tab": 0x09, "space": 0x20, "delete": 0x2E,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "pageup": 0x21, "pagedown": 0x22,
        "home": 0x24, "end": 0x23}
# single keys for FM27's shortcuts (sent as real key presses, not text): a-z, 0-9, F1-F12. Never with modifiers.
KEYS.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
KEYS.update({f"f{n}": 0x6F + n for n in range(1, 13)})
EXTENDED = {0x2E, 0x25, 0x26, 0x27, 0x28, 0x21, 0x22, 0x24, 0x23}
VK_CONTROL = 0x11
# the only key combinations allowed, each one an FM27 command (kept to a list so nothing like Alt+F4 can be sent)
COMBOS = {"ctrl+s": (VK_CONTROL, ord("S"))}          # save the game


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    i = INPUT(type=0)
    i.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    i = INPUT(type=1)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


class Controller:
    """Turns phone actions into input for FM27. One lock so two phones can't interleave a drag."""

    def __init__(self):
        self.lock = threading.Lock()
        self.paused = False          # set by the kill-switch hotkey on the PC
        self.button_down: str | None = None
        self.pressed_at = 0.0
        self.pos: tuple[int, int] | None = None    # last cursor position we sent, in FM27 pixels

    # ------------------------------------------------------------- helpers
    def _target(self) -> int:
        if self.paused:
            raise PermissionError("Remote control is paused on the PC (Ctrl+Alt+End).")
        hwnd = window.find()
        if not hwnd:
            raise LookupError("FM27 isn't running.")
        if not window.bring_to_front(hwnd):
            raise RuntimeError("Couldn't bring FM27 to the front.")
        return hwnd

    @staticmethod
    def _clip(hwnd: int, x: float, y: float) -> tuple[int, int]:
        w, h = window.client_size(hwnd)
        return min(max(int(x), 0), w - 1), min(max(int(y), 0), h - 1)

    def _move_to(self, hwnd: int, x: float, y: float) -> None:
        """A real absolute mouse-move input event (not SetCursorPos): Unity needs genuine move events for hover,
        the wheel and, with the button held, drag-and-drop."""
        cx, cy = self._clip(hwnd, x, y)
        sx, sy = window.client_to_screen(hwnd, cx, cy)
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)     # virtual desktop origin
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)     # and size (all monitors)
        nx = round((sx - vx) * 65535 / max(1, vw - 1))
        ny = round((sy - vy) * 65535 / max(1, vh - 1))
        _send(_mouse(MOVE | ABSOLUTE | VIRTUALDESK, nx, ny))
        self.pos = (cx, cy)

    def _glide_to(self, hwnd: int, x: float, y: float) -> None:
        """Move in small steps while the button is held, like a hand on a mouse. One big jump can skip Unity's
        drag start or land a dragged item without passing over the places in between."""
        x0, y0 = self.pos or (x, y)
        dist = max(abs(x - x0), abs(y - y0))
        steps = max(1, min(40, int(dist // DRAG_STEP_PX) + 1))
        for i in range(1, steps + 1):
            self._move_to(hwnd, x0 + (x - x0) * i / steps, y0 + (y - y0) * i / steps)
            time.sleep(DRAG_STEP_S)

    # ------------------------------------------------------------- actions
    def move(self, x: float, y: float) -> None:
        with self.lock:
            self._move_to(self._target(), x, y)

    def click(self, x: float, y: float, button: str = "left", double: bool = False) -> None:
        down, up = (RIGHTDOWN, RIGHTUP) if button == "right" else (LEFTDOWN, LEFTUP)
        with self.lock:
            self._move_to(self._target(), x, y)
            time.sleep(0.03)
            for n in range(2 if double else 1):
                _send(_mouse(down))
                time.sleep(0.03)
                _send(_mouse(up))
                if double and n == 0:
                    time.sleep(0.06)

    def nav(self, direction: str, x: float, y: float) -> None:
        """Back or Forward, as the mouse's side buttons with the cursor over FM27 (where the gesture was drawn)."""
        button = NAV_BUTTONS.get(direction)
        if button is None:
            raise ValueError(f"Unknown direction: {direction}")
        with self.lock:
            self._move_to(self._target(), x, y)
            time.sleep(0.03)
            _send(_mouse(XDOWN, data=button))
            time.sleep(0.03)
            _send(_mouse(XUP, data=button))

    def press(self, x: float, y: float) -> None:
        """Hold the left button down (Drag mode: the phone sends this as soon as a finger touches)."""
        with self.lock:
            hwnd = self._target()
            if self.button_down:                      # a lost release: let go first
                _send(_mouse(LEFTUP))
            self._move_to(hwnd, x, y)
            time.sleep(0.03)
            _send(_mouse(LEFTDOWN))
            self.button_down = "left"
            self.pressed_at = time.monotonic()

    def drag(self, x: float, y: float) -> None:
        with self.lock:
            if not self.button_down:
                return
            hwnd = self._target()
            wait = PRESS_HOLD_S - (time.monotonic() - self.pressed_at)
            if wait > 0:                              # held still briefly before moving, as a hand would
                time.sleep(wait)
            self._glide_to(hwnd, x, y)

    def release(self, x: float, y: float) -> None:
        with self.lock:
            if not self.button_down:
                return
            hwnd = self._target()
            self._glide_to(hwnd, x, y)
            time.sleep(0.05)                          # let the drop target register the hover
            _send(_mouse(LEFTUP))
            self.button_down = None

    def wheel(self, x: float, y: float, notches: int) -> None:
        """notches > 0 scrolls up (away from you), < 0 down, like a mouse wheel."""
        notches = max(-10, min(10, int(notches)))
        with self.lock:
            self._move_to(self._target(), x, y)
            for _ in range(abs(notches)):
                _send(_mouse(WHEEL, data=120 if notches > 0 else -120))
                time.sleep(0.02)

    def text(self, s: str) -> None:
        s = s[:200]
        with self.lock:
            self._target()
            for ch in s:
                if ch == "\n":
                    self._vk(KEYS["enter"])
                    continue
                for unit in _utf16(ch):
                    _send(_key(scan=unit, flags=UNICODE), _key(scan=unit, flags=UNICODE | KEYUP))
                time.sleep(0.01)

    def key(self, name: str) -> None:
        if name in COMBOS:
            mod, vk = COMBOS[name]
            with self.lock:
                self._target()
                ms, s = user32.MapVirtualKeyW(mod, 0), user32.MapVirtualKeyW(vk, 0)
                _send(_key(mod, ms), _key(vk, s), _key(vk, s, KEYUP), _key(mod, ms, KEYUP))
            return
        vk = KEYS.get(name)
        if vk is None:
            raise ValueError(f"Unknown key: {name}")
        with self.lock:
            self._target()
            self._vk(vk)

    @staticmethod
    def _vk(vk: int) -> None:
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001 if vk in EXTENDED else 0
        _send(_key(vk, scan, ext), _key(vk, scan, ext | KEYUP))

    def release_all(self) -> None:
        """A phone disconnected mid-drag: never leave the button held down."""
        with self.lock:
            if self.button_down:
                _send(_mouse(LEFTUP))
                self.button_down = None


def _utf16(ch: str) -> list[int]:
    b = ch.encode("utf-16-le")
    return [int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)]
