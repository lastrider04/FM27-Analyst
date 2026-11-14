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
