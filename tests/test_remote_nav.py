"""The circle gesture's Back/Forward: the mouse's side buttons, sent with the cursor over FM27."""
import pytest

from remote import inputs


def test_nav_sends_side_buttons(monkeypatch):
    sent, moves = [], []
    c = inputs.Controller()
    monkeypatch.setattr(c, "_target", lambda: 1)
    monkeypatch.setattr(c, "_move_to", lambda hwnd, x, y: moves.append((x, y)))
    monkeypatch.setattr(inputs, "_send", lambda *i: sent.extend((x.mi.dwFlags, x.mi.mouseData) for x in i))
    monkeypatch.setattr(inputs.time, "sleep", lambda s: None)
    c.nav("back", 100, 50)
    c.nav("forward", 10, 20)
    assert moves == [(100, 50), (10, 20)]
    assert sent == [(inputs.XDOWN, 1), (inputs.XUP, 1), (inputs.XDOWN, 2), (inputs.XUP, 2)]
    with pytest.raises(ValueError):
        c.nav("sideways", 0, 0)


def test_sideways_wheel(monkeypatch):
    sent = []
    c = inputs.Controller()
    monkeypatch.setattr(c, "_target", lambda: 1)
    monkeypatch.setattr(c, "_move_to", lambda hwnd, x, y: None)
    monkeypatch.setattr(inputs, "_send", lambda *i: sent.extend((x.mi.dwFlags, x.mi.mouseData) for x in i))
    monkeypatch.setattr(inputs.time, "sleep", lambda s: None)
    c.hwheel(5, 5, 2)
    c.hwheel(5, 5, -1)
    assert sent[:2] == [(inputs.HWHEEL, 120)] * 2
    assert sent[2][0] == inputs.HWHEEL and sent[2][1] in (-120, 2**32 - 120)    # a DWORD: -120 may come back unsigned
    c.hwheel(5, 5, 50)
    assert len(sent) == 13                                                     # capped at 10 notches a message
