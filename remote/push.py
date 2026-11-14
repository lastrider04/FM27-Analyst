"""Phone notifications (Web Push): "FM27 needs you" reaches a phone even when the remote-play page is closed.

How it works: the phone's browser makes a subscription (an address at Google's, Apple's or Mozilla's push service plus
encryption keys) and gives it to the PC. When FM27 stops and waits, the PC encrypts a small message and posts it to
that address, signed with this PC's own VAPID key. The push service wakes the phone, and the page's service worker
(static/sw.js) shows the notification.

Web Push needs an https page, so it works on the Tailscale address (tls.py), not on plain http over Wi-Fi.
On an iPhone it also needs the page added to the Home Screen (iOS 16.4+), and notifications allowed from there.

Kept in data/ (never committed): remote_vapid.pem (this PC's private signing key) and remote_push.json (each paired
phone's subscriptions).
"""
from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from urllib.parse import urlparse

import app_config

# Push services a subscription may point at. Anything else is refused, so a phone can't make the PC post elsewhere.
PUSH_HOSTS = ("fcm.googleapis.com", "push.apple.com", "push.services.mozilla.com", "notify.windows.com")
DEFAULT_SUBJECT = "mailto:fm27-remote@example.com"   # VAPID contact; generic on purpose (set remote_play.push_subject)
TTL_S = 15 * 60                                      # a "needs you" older than this isn't worth delivering
_lock = threading.Lock()


def _vapid_file() -> Path:
    return app_config.DATA / "remote_vapid.pem"


def _subs_file() -> Path:
    return app_config.DATA / "remote_push.json"


def _vapid():
    from py_vapid import Vapid02
    path = _vapid_file()
    with _lock:
        if not path.exists():
            v = Vapid02()
            v.generate_keys()
            path.parent.mkdir(parents=True, exist_ok=True)
            v.save_key(str(path))
        return Vapid02.from_file(str(path))


def public_key() -> str:
    """The key the phone subscribes with (applicationServerKey): base64url of the raw P-256 point."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    raw = _vapid().public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def valid(sub) -> bool:
    if not isinstance(sub, dict) or not isinstance(sub.get("keys"), dict):
        return False
    u = urlparse(str(sub.get("endpoint", "")))
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)
            and all(isinstance(sub["keys"].get(k), str) and 0 < len(sub["keys"][k]) < 200 for k in ("p256dh", "auth")))


def _load() -> dict[str, list[dict]]:
    try:
        return json.loads(_subs_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(subs: dict) -> None:
    _subs_file().parent.mkdir(parents=True, exist_ok=True)
    _subs_file().write_text(json.dumps(subs, indent=1), encoding="utf-8")


def subscribe(device_id: str, sub: dict) -> None:
    sub = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}}
    with _lock:
        subs = _load()
        mine = [s for s in subs.get(device_id, []) if s["endpoint"] != sub["endpoint"]]
        subs[device_id] = (mine + [sub])[-3:]          # a few per phone (browser and Home Screen app)
        _save(subs)


def unsubscribe(device_id: str, endpoint: str | None = None) -> None:
    with _lock:
        subs = _load()
        left = [s for s in subs.get(device_id, []) if endpoint and s["endpoint"] != endpoint]
        if left:
            subs[device_id] = left
        else:
            subs.pop(device_id, None)
        _save(subs)


def devices() -> set[str]:
    return set(_load())


def forget_unpaired(paired_ids: set[str]) -> None:
    """Drop subscriptions of phones that were unpaired."""
    with _lock:
        subs = _load()
        kept = {d: s for d, s in subs.items() if d in paired_ids or d == "local"}
        if kept != subs:
            _save(kept)


def send(device_ids: set[str], title: str, body: str, tag: str = "fm27-needs-you") -> int:
    """Push to every subscription of these phones. Returns how many were delivered. Blocking (call in a thread)."""
    from pywebpush import WebPushException, webpush
    payload = json.dumps({"title": title, "body": body, "tag": tag})
    subject = str(app_config.load_config().get("remote_play", {}).get("push_subject") or DEFAULT_SUBJECT)
    vapid = _vapid()
    sent, gone = 0, []
    for dev, subs in _load().items():
        if dev not in device_ids:
            continue
        for sub in subs:
            try:
                webpush(sub, payload, vapid_private_key=vapid, vapid_claims={"sub": subject}, ttl=TTL_S, timeout=10)
                sent += 1
            except WebPushException as e:
                status = getattr(e.response, "status_code", None)
                if status in (404, 410):                 # the phone dropped this subscription
                    gone.append((dev, sub["endpoint"]))
                print(f"[remote] push to {dev} failed: {status or e}")
            except Exception as e:  # noqa: BLE001  (network)
                print(f"[remote] push to {dev} failed: {e}")
    for dev, endpoint in gone:
        unsubscribe(dev, endpoint)
    return sent
