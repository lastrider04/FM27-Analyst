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
        if path.startswith("/local/pair-code"):
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


def test_phone_companion_only_reads_where_to_go(rp, phone):
    assert remote.allowed("GET", "/api/remoteplay")
    for method, path in (("PUT", "/api/remoteplay"), ("POST", "/api/remoteplay/code"),
                         ("DELETE", "/api/remoteplay/devices/abc"), ("PUT", "/api/remote/devices/abc")):
        assert not remote.allowed(method, path), (method, path)
    me = web_app._rp_status(phone={"id": phone})
    assert me == {"running": True, "name": "Pixel",
                  "networks": {"wifi": {"allowed": False, "available": True},
                               "tailscale": {"allowed": False, "available": True}}}   # nothing about other phones


@pytest.fixture
def phone(tmp_path, monkeypatch):
    import app_config
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    remote.DEVICES.add("Pixel", "google")
    return remote.DEVICES.listing()[0]["id"]


def test_phone_app_opens_remote_play_only_where_allowed(rp, phone, monkeypatch):
    class Req:
        class state:
            remote_device = {"id": phone}
    assert remote.allowed("POST", "/api/remoteplay/pair/wifi") and remote.allowed("POST", "/api/remoteplay/pair/tailscale")
    with pytest.raises(Exception) as e:
        web_app.remoteplay_pair("wifi", Req)
    assert e.value.status_code == 403
    c = TestClient(web_app.app)
    c.put(f"/api/remote/devices/{phone}", json={"rp_wifi": True})
    assert remote.DEVICES.get(phone)["rp_wifi"] is True and not remote.DEVICES.get(phone).get("rp_tailscale")
    assert web_app.remoteplay_pair("wifi", Req)["url"] == "http://192.168.1.5:8777/#pair=ABCD2345&name=Pixel"
    assert ("GET", f"/local/pair-code?link={phone}") in rp
    with pytest.raises(Exception):
        web_app.remoteplay_pair("tailscale", Req)


def test_remote_play_honours_the_phone_app_switches(phone, monkeypatch):
    from remote import auth
    linked = {"id": "rp1", "name": "Pixel", "link": phone}
    monkeypatch.setattr(auth.DEVICES, "find", lambda token: dict(linked))
    assert auth.network("100.95.1.2") == "tailscale" and auth.network("192.168.1.9") == "wifi"
    dev, why = auth.device_for({"fm_remote": "t"}, "192.168.1.9", lan=True)
    assert dev is None and "home Wi-Fi is off" in why
    remote.DEVICES.update(phone, rp_wifi=True)
    assert auth.device_for({"fm_remote": "t"}, "192.168.1.9", lan=True)[0]["id"] == "rp1"
    assert "Tailscale is off" in auth.device_for({"fm_remote": "t"}, "100.95.1.2", lan=True)[1]
    remote.DEVICES.revoke(phone)
    assert "removed" in auth.device_for({"fm_remote": "t"}, "192.168.1.9", lan=True)[1]
    linked.pop("link")                                    # paired with a code from the PC: no per-network limit
    assert auth.device_for({"fm_remote": "t"}, "100.95.1.2", lan=True)[0]["id"] == "rp1"


def test_remote_play_knows_where_the_analyst_is(monkeypatch):
    import app_config
    from remote.server import Hub
    cfg = app_config.load_config()
    cfg["remote"].update(enabled=True, public_url="https://fm.example.com/", port=8776)
    monkeypatch.setattr(app_config, "load_config", lambda: cfg)
    assert Hub.analyst_link() == {"url": "https://fm.example.com", "port": 8776}
    cfg["remote"]["enabled"] = False
    assert Hub.analyst_link() is None
