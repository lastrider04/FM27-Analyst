"""The analyst's Remote tab: managing remote play from the dashboard (remote play itself is faked; nothing starts)."""
import pytest
from fastapi.testclient import TestClient

from web import app as web_app
from web import remote

INFO = {"https": "https://pc.tail1.ts.net", "lan": ["http://192.168.1.5:8777"], "connected": [], "fm": "waiting",
        "paused": False, "devices": [{"id": "abc", "name": "Pixel", "last_seen": 1, "notifications": True}]}


@pytest.fixture
def rp(monkeypatch):
    from remote import launcher
    calls = []
    monkeypatch.setattr(launcher, "running", lambda port=8777: True)

    def local(path, method="GET", timeout=5.0):
        calls.append((method, path))
        if path == "/local/info":
            return INFO
        if path == "/local/pair-code":
            return {"code": "ABCD2345"}
        if path.startswith("/local/revoke/"):
            return {"ok": path.endswith("/abc")}
        raise AssertionError(path)

    monkeypatch.setattr(web_app, "_rp_local", local)
    return calls


def test_pc_sees_everything(rp):
    r = TestClient(web_app.app).get("/api/remoteplay").json()
    assert r["running"] and r["https"] == INFO["https"] and r["devices"][0]["name"] == "Pixel"
    assert "enabled" in r and "missing" in r


def test_pairing_code_links_to_the_https_address(rp):
    p = TestClient(web_app.app).post("/api/remoteplay/code").json()
    assert p["code"] == "ABCD-2345" and p["url"] == "https://pc.tail1.ts.net/#pair=ABCD2345"


def test_unpair_goes_to_remote_play(rp):
    c = TestClient(web_app.app)
    assert c.delete("/api/remoteplay/devices/abc").status_code == 200
    assert c.delete("/api/remoteplay/devices/nope").status_code == 404
    assert ("POST", "/local/revoke/abc") in rp


def test_start_with_the_analyst_is_saved(rp):
    import app_config
    TestClient(web_app.app).put("/api/remoteplay", json={"enabled": True})
    assert app_config.load_config()["remote_play"]["enabled"] is True


def test_phone_companion_only_reads_where_to_go(rp):
    assert remote.allowed("GET", "/api/remoteplay")
    for method, path in (("PUT", "/api/remoteplay"), ("POST", "/api/remoteplay/code"),
                         ("DELETE", "/api/remoteplay/devices/abc")):
        assert not remote.allowed(method, path), (method, path)
    phone = web_app._rp_status(phone=True)
    assert phone == {"running": True, "https": INFO["https"], "lan": INFO["lan"]}       # no phones list, no settings


def test_phone_app_pairs_itself_in_one_tap(rp):
    assert remote.allowed("POST", "/api/remoteplay/pair")
    p = TestClient(web_app.app).post("/api/remoteplay/pair").json()
    assert p["url"] == "https://pc.tail1.ts.net/#pair=ABCD2345&name=Phone"


def test_remote_play_knows_where_the_analyst_is(monkeypatch):
    import app_config
    from remote.server import Hub
    cfg = app_config.load_config()
    cfg["remote"].update(enabled=True, public_url="https://fm.example.com/", port=8776)
    monkeypatch.setattr(app_config, "load_config", lambda: cfg)
    assert Hub.analyst_link() == {"url": "https://fm.example.com", "port": 8776}
    cfg["remote"]["enabled"] = False
    assert Hub.analyst_link() is None
