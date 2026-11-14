"""Is FM27 waiting for you? Read from its top-right button, using pixels only (nothing is clicked or read from memory).

While FM27 waits for you, the big blue button in the top-right corner ends in a "»" chevron, whatever it says:
Continue, Go To Match, Kick Off, Messages, Address the Team … (dimmed under a pop-up, it's still there). While it's
busy (processing days, preparing a match), the chevron is replaced by another icon or the button is gone. Measured on
127 recorded screens: waiting scores 0.8–1.0, everything else 0.47 or less.

The Watcher turns those readings into "FM27 needs you" alerts: one when the chevron comes back after FM27 has been busy
for a few seconds, so tapping around screens never triggers it.
"""
from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

# The chevron, cut from a recorded screen at 1280x800 (16x15 grey levels, with a little of the blue around it).
_T = np.frombuffer(base64.b64decode(
    "XV1VWF5lX1hZYl5eXl5eXV1fYlhkVWBYX15eXl5eXV2Qn3JbY66TVV5eXl5eXV2S57hiccHgjGBUYl5dXV1UrN27XmjM4X9iX2JhXV1ZZKHYuGh3ydaS"
    "VFhmXV1hVmak3q9hedTLhFxgXV1aXFpmveeWUYnoxGpXXV1kUFGF2dJ5YrfapV1cXV1dXYzS0nlfseieYFNhXV1Yfdjhdlmx6qdbXWlYXV165c57WLHg"
    "ql5eXl5eXV2hw4RWdcrDV15eXl5eXV1hbFhiWVhjXV5eXl5eXV1aXlViZF9kXF5eXl5eXV1YXl5fXlheXF5eXl5e"), np.uint8).reshape(16, 15)
TEMPLATE = (_T - _T.mean()) / np.linalg.norm(_T - _T.mean())
THRESHOLD = 0.75
# Where to look, in 1280x800 units from the top-right corner (FM27's UI scales with the window height).
SEARCH = (1215, 4, 1275, 40)       # the chevron's neighbourhood (it moves a few pixels between screens)
BUTTON = (1085, 4, 1275, 40)       # the whole button, shown on the phone with the alert
BUSY_FOR_ALERT_S = 4.0             # FM27 must have been busy at least this long before "needs you" is sent


def _crop(frame, box: tuple[int, int, int, int]) -> Image.Image:
    """Cut a 1280x800-unit box (anchored top-right) out of a capture frame, at 1280x800 scale."""
    k = frame.height / 800
    x0, y0, x1, y1 = box
    native = (round(frame.width - (1280 - x0) * k), round(y0 * k), round(frame.width - (1280 - x1) * k), round(y1 * k))
    img = Image.frombuffer("RGBA", (frame.width, frame.height), frame.bgra, "raw", "BGRA", 0, 1)
    return img.crop(native).resize((x1 - x0, y1 - y0), Image.BILINEAR)


def score(frame) -> float:
    """How strongly the top-right corner shows the "»" chevron: about 1 when FM27 waits for you, under 0.5 when not."""
    g = np.asarray(_crop(frame, SEARCH).convert("L"), np.float32)
    win = np.lib.stride_tricks.sliding_window_view(g, TEMPLATE.shape)          # every placement of the template
    win = win - win.mean(axis=(2, 3), keepdims=True)
    norm = np.sqrt((win * win).sum(axis=(2, 3)))
    corr = (win * TEMPLATE).sum(axis=(2, 3)) / np.maximum(norm, 1e-3)
    corr[norm < 1e-3] = -1.0                                                  # a flat colour isn't a chevron
    return float(corr.max())


def button_png(frame) -> str:
    """The top-right button as a small PNG (base64), so the phone can show what FM27 is waiting on."""
    buf = io.BytesIO()
    _crop(frame, BUTTON).convert("RGB").save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


class Watcher:
    """Turns readings into states ("waiting" / "busy") and decides when to alert.

    A state only changes after two readings in a row agree, so a passing animation can't flip it.
    """

    def __init__(self):
        self.state: str | None = None
        self.since = 0.0                 # when the current state began
        self._pending: str | None = None

    def update(self, waiting: bool, now: float) -> dict | None:
        """Feed one reading. Returns {"state", "alert"} when the state changes, else None."""
        new = "waiting" if waiting else "busy"
        if new == self.state:
            self._pending = None
            return None
        if self._pending != new:         # first reading of a change: wait for the next one to confirm it
            self._pending = new
            return None
        self._pending = None
        alert = new == "waiting" and self.state == "busy" and now - self.since >= BUSY_FOR_ALERT_S
        self.state, self.since = new, now
        return {"state": new, "alert": alert}
