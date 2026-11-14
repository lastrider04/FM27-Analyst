"""Remote play › phone notifications (Web Push) and Tailscale HTTPS. No network: nothing is actually pushed."""
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("windows_capture")
pytest.importorskip("pywebpush")
import app_config  # noqa: E402
from remote import auth, push, server, tls  # noqa: E402

from tests.test_remote_play_analyst import _bare_hub  # noqa: E402

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
       "keys": {"p256dh": "BOr" + "x" * 80, "auth": "y" * 22}}
PAGE = {"X-FM-Remote": "1", "Origin": "http://testserver", "Host": "testserver"}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    return tmp_path


def test_only_real_push_services_are_accepted():
    assert push.valid(SUB)
    assert push.valid(SUB | {"endpoint": "https://web.push.apple.com/QGx"})
    assert push.valid(SUB | {"endpoint": "https://wns2-db5p.notify.windows.com/w/?token=1"})
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example/x", "https://fcm.googleapis.com.evil.io/x",
                "https://10.0.0.1/x"):
        assert not push.valid(SUB | {"endpoint": bad}), bad
    assert not push.valid({"endpoint": SUB["endpoint"]}) and not push.valid("nope")


def test_subscriptions_are_kept_per_phone(data):
    push.subscribe("phone1", SUB)
    push.subscribe("phone1", SUB)                                   # same endpoint again: still one
    push.subscribe("phone2", SUB | {"endpoint": "https://web.push.apple.com/2"})
    assert push.devices() == {"phone1", "phone2"}
    push.unsubscribe("phone1", SUB["endpoint"])
    assert push.devices() == {"phone2"}


def test_vapid_key_is_made_once_and_reused(data):
    k = push.public_key()
    assert len(k) == 87 and push.public_key() == k                 # 65-byte P-256 point, base64url
    assert (data / "remote_vapid.pem").exists()


def test_push_routes_need_pairing_and_the_page(data, monkeypatch):
    monkeypatch.setattr(server.Hub, "__init__", lambda self, lan: _bare_hub(self, lan))
    monkeypatch.setattr(auth, "device_for", lambda cookies, ip, lan: (None, "pair"))
    c = TestClient(server.create_app(lan=False))
    assert c.get("/api/push/key").status_code == 401
    assert c.post("/api/push/subscribe", json={"subscription": SUB}, headers=PAGE).status_code == 401
    monkeypatch.setattr(auth, "device_for", lambda cookies, ip, lan: ({"id": "phone1", "name": "Pixel"}, ""))
    assert c.post("/api/push/subscribe", json={"subscription": SUB}).status_code == 403          # no page header
    bad = SUB | {"endpoint": "https://evil.example/x"}
    assert c.post("/api/push/subscribe", json={"subscription": bad}, headers=PAGE).status_code == 400
    assert c.post("/api/push/subscribe", json={"subscription": SUB}, headers=PAGE).json()["ok"]
    assert push.devices() == {"phone1"}
    assert c.get("/sw.js").headers["content-type"].startswith("text/javascript")


def test_https_url():
    assert tls.url({"host": "pc.tail1.ts.net", "port": 443}) == "https://pc.tail1.ts.net"
    assert tls.url({"host": "pc.tail1.ts.net", "port": 8778}) == "https://pc.tail1.ts.net:8778"


def test_send_encrypts_signs_and_drops_dead_subscriptions(data, monkeypatch):
    import base64

    import requests
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    phone_key = ec.generate_private_key(ec.SECP256R1()).public_key()   # what a browser would give
    live = {"endpoint": "https://fcm.googleapis.com/fcm/send/live",
            "keys": {"p256dh": b64(phone_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
                     "auth": b64(b"0123456789abcdef")}}
    dead = live | {"endpoint": "https://fcm.googleapis.com/fcm/send/dead"}
    push.subscribe("phone1", live)
    push.subscribe("phone1", dead)
    push.subscribe("phone2", live | {"endpoint": "https://fcm.googleapis.com/fcm/send/other"})
    posts = []

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        posts.append((url, headers, data))
        r = requests.Response()
        r.status_code = 410 if url.endswith("dead") else 201
        return r

    monkeypatch.setattr(requests, "post", fake_post)
    assert push.send({"phone1"}, "FM27 needs you", "waiting") == 1
    assert {u.rsplit("/", 1)[1] for u, _, _ in posts} == {"live", "dead"}          # phone2 not asked
    url, headers, body = posts[0]
    assert headers["authorization"].startswith("vapid t=") and headers["content-encoding"] == "aes128gcm"
    assert b"FM27" not in body                                                       # encrypted
    assert [s["endpoint"].rsplit("/", 1)[1] for s in push._load()["phone1"]] == ["live"]   # 410 dropped
