"""Remote play › "FM27 needs you": the top-right "»" detector and when it alerts (synthetic frames, no game)."""
import base64
import io

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("windows_capture")
from remote import fmstate  # noqa: E402


class Frame:
    def __init__(self, img: Image.Image):
        r, g, b, a = img.convert("RGBA").split()
        self.width, self.height = img.size
        self.bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()


def fm_screen(chevron: bool, size=(1920, 1200)) -> Frame:
    """A grey screen with FM27's blue top-right button, drawn at 1280x800 and scaled like FM27's UI."""
    img = Image.new("L", (1280, 800), 220)
    img.paste(94, (1100, 8, 1270, 36))                       # the button (its grey level, as the template sees it)
    if chevron:
        img.paste(Image.fromarray(fmstate._T), (1238, 13))   # the "»" where FM27 draws it
    return Frame(img.convert("RGB").resize(size))


@pytest.mark.parametrize("size", [(1280, 800), (1920, 1200), (2560, 1440)])
def test_chevron_means_waiting_at_any_window_size(size):
    assert fmstate.score(fm_screen(True, size)) >= fmstate.THRESHOLD
    assert fmstate.score(fm_screen(False, size)) < fmstate.THRESHOLD


def test_flat_or_dark_screens_are_busy():
    for level in (0, 128, 255):
        assert fmstate.score(Frame(Image.new("RGB", (1920, 1200), (level,) * 3))) < fmstate.THRESHOLD


def test_button_png_is_the_top_right_button():
    png = Image.open(io.BytesIO(base64.b64decode(fmstate.button_png(fm_screen(True)))))
    assert png.size == (190, 36)
    assert np.asarray(png.convert("L")).std() > 5           # not a blank picture


def test_alerts_only_after_being_busy_for_a_while():
    w, t = fmstate.Watcher(), 0.0

    def feed(waiting, seconds):
        nonlocal t
        events = []
        for _ in range(int(seconds / 0.5)):
            e = w.update(waiting, t)
            if e:
                events.append(e)
            t += 0.5
        return events

    assert feed(True, 2) == [{"state": "waiting", "alert": False}]         # first reading: no alert
    assert feed(False, 1.5) == [{"state": "busy", "alert": False}]
    assert feed(True, 2) == [{"state": "waiting", "alert": False}]         # busy only briefly: screen changes
    feed(False, 10)                                                         # processing days
    assert feed(True, 2) == [{"state": "waiting", "alert": True}]          # FM27 needs you


def test_one_odd_reading_does_not_flip_the_state():
    w = fmstate.Watcher()
    w.update(True, 0)
    w.update(True, 0.5)
    assert w.update(False, 1.0) is None and w.update(True, 1.5) is None and w.state == "waiting"
