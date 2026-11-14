"""Settings anyone can change in the app (no files to edit): remote play's shortcut row and the crest folder."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app_config
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    from web import app as web_app
    return TestClient(web_app.app), tmp_path


def test_shortcut_row_save_validate_reset(env):
    c, data = env
    d = c.get("/api/remoteplay/shortcuts").json()
    assert not d["custom"] and d["shortcuts"][0]["key"] == "space" and "ctrl+s" in d["keys"]

    r = c.put("/api/remoteplay/shortcuts", json={"shortcuts": [
        {"label": "Go", "key": "Space", "icon": "continue"}, {"label": "", "key": "f5", "icon": ""}]})
    assert r.status_code == 200
    saved = json.loads((data / "remote_shortcuts.json").read_text(encoding="utf-8"))
    assert saved == [{"label": "Go", "key": "space", "icon": "continue", "primary": True},
                     {"label": "F5", "key": "f5", "icon": ""}]
    assert r.json()["custom"] and [s["key"] for s in r.json()["shortcuts"]] == ["space", "f5"]

    assert c.put("/api/remoteplay/shortcuts", json={"shortcuts": [{"label": "x", "key": "alt+f4"}]}).status_code == 400
    assert c.put("/api/remoteplay/shortcuts", json={"shortcuts": []}).status_code == 400
    assert c.put("/api/remoteplay/shortcuts", json={"shortcuts": [{"label": "a", "key": "a"}] * 9}).status_code == 400

    assert not c.put("/api/remoteplay/shortcuts", json={"shortcuts": None}).json()["custom"]
    assert not (data / "remote_shortcuts.json").exists()


def test_crest_folder(env, monkeypatch):
    c, data = env
    from web import crests
    monkeypatch.setattr(crests, "rescan", lambda: None)
    assert c.put("/api/crests", json={"folder": str(data / "nope")}).status_code == 400
    g = data / "graphics"
    g.mkdir()
    r = c.put("/api/crests", json={"folder": f'"{g}"'})              # pasted with quotes from Explorer
    assert r.status_code == 200 and r.json()["custom"] == str(g)
    assert crests.graphics_dirs() == [g]
    assert c.put("/api/crests", json={"folder": ""}).json()["custom"] == ""
