"""Capturing the FM27 window with Windows Graphics Capture.

WGC captures just the FM27 window, even when other windows cover it, and only delivers a frame when the picture
changes (Phase 0). The latest frame is kept as raw BGRA bytes; clients encode the part they need.
"""
from __future__ import annotations

import io
import threading
import time

from PIL import Image

from . import window


class Frame:
    __slots__ = ("seq", "width", "height", "bgra", "at")

    def __init__(self, seq: int, width: int, height: int, bgra: bytes):
        self.seq, self.width, self.height, self.bgra, self.at = seq, width, height, bgra, time.time()

    def image(self) -> Image.Image:
        return Image.frombuffer("RGBA", (self.width, self.height), self.bgra, "raw", "BGRA", 0, 1)


def encode(frame: Frame, region: tuple[int, int, int, int] | None, out_w: int, quality: int = 70) -> tuple[bytes, tuple]:
    """JPEG of a region (x, y, w, h in FM27 pixels; None = the whole window), scaled to at most out_w pixels wide
    and never upscaled. Returns the bytes and the region actually used."""
    x, y, w, h = region or (0, 0, frame.width, frame.height)
    x, y = max(0, min(x, frame.width - 1)), max(0, min(y, frame.height - 1))
    w, h = max(1, min(w, frame.width - x)), max(1, min(h, frame.height - y))
    img = frame.image().crop((x, y, x + w, y + h)).convert("RGB")
    out_w = max(64, min(int(out_w), w))
    if out_w < w:
        img = img.resize((out_w, max(1, round(h * out_w / w))), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue(), (x, y, w, h)


class Capturer:
    """Keeps the latest FM27 frame. Restarts by itself when FM27 starts, closes or is restarted."""

    def __init__(self):
        self.frame: Frame | None = None
        self.seq = 0
        self.cond = threading.Condition()
        self.status = "starting"
        self._stop = threading.Event()
        self._control = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="fm27-capture")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        ctl = self._control
        if ctl is not None:
            try:
                ctl.stop()
            except Exception:
                pass

    def wait_newer(self, seq: int, timeout: float) -> Frame | None:
        """The latest frame if it's newer than seq, waiting up to timeout for one."""
        with self.cond:
            if self.frame is None or self.frame.seq <= seq:
                self.cond.wait(timeout)
            f = self.frame
            return f if f is not None and f.seq > seq else None

    def _publish(self, width: int, height: int, data: bytes) -> None:
        with self.cond:
            self.seq += 1
            self.frame = Frame(self.seq, width, height, data)
            self.cond.notify_all()

    def _run(self) -> None:
        from windows_capture import WindowsCapture

        while not self._stop.is_set():
            hwnd = window.find()
            if not hwnd:
                self.status = "FM27 isn't running"
                self._stop.wait(2)
                continue
            self.status = "capturing"
            done = threading.Event()
            try:
                cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd)
            except Exception as e:                 # e.g. the window vanished between find() and here
                self.status = f"capture failed: {e}"
                self._stop.wait(2)
                continue

            @cap.event
            def on_frame_arrived(frame, control):
                if self._stop.is_set():
                    control.stop()
                    return
                buf = frame.frame_buffer          # (h, w, 4) BGRA, only valid inside this callback
                self._publish(buf.shape[1], buf.shape[0], buf.tobytes())

            @cap.event
            def on_closed():
                done.set()

            try:
                self._control = cap.start_free_threaded()
                while not done.is_set() and not self._stop.is_set():
                    done.wait(1)
                    if not window.find():          # FM27 closed: start over and wait for it
                        break
            except Exception as e:
                self.status = f"capture failed: {e}"
            finally:
                try:
                    if self._control is not None:
                        self._control.stop()
                except Exception:
                    pass
                self._control = None
            self._stop.wait(1)
        self.status = "stopped"
