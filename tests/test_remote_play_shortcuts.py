"""Remote play: the phone's shortcut row and which keys it may send (no FM27, nothing pressed)."""
import json

import pytest

import app_config

pytest.importorskip("windows_capture")
from remote import inputs, server  # noqa: E402


def test_default_row_has_save_as_ctrl_s(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    keys = [s["key"] for s in server.load_shortcuts()]
    assert keys == ["space", "1", "2", "3", "n", "ctrl+s"]


def test_only_listed_combinations_are_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    (tmp_path / "remote_shortcuts.json").write_text(json.dumps([
        {"label": "Save", "key": "CTRL+S", "icon": "save"},
        {"label": "Quit", "key": "alt+f4"},
        {"label": "Inbox", "key": "ctrl+i"},
        {"label": "Mail", "key": "m", "icon": "mail"},
    ]), encoding="utf-8")
    assert [s["key"] for s in server.load_shortcuts()] == ["ctrl+s", "m"]


def test_unknown_key_is_refused_before_anything_is_sent():
    c = inputs.Controller()
    with pytest.raises(ValueError):
        c.key("alt+f4")
