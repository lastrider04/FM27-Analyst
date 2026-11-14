"""Who may control FM27.

Local mode (the default) listens on 127.0.0.1 only: just this PC can connect, for testing in a browser.

LAN mode (--lan) is for phones on home Wi-Fi or Tailscale. A phone pairs once with a one-time code shown on the PC
(8 characters, single use, 10 minutes; pairing pauses after 5 wrong codes in 15 minutes). That gives it a random
token in an HttpOnly cookie; only its SHA-256 is kept (data/remote_devices.json). Remote play pairs separately from
the analyst's phone app on purpose: those cookies belong to the analyst's address (often a public domain behind
a proxy), and controlling the PC is a bigger permission than reading the dashboard.

Also in LAN mode:
  - only private addresses may connect (home network 10/8, 172.16/12, 192.168/16; Tailscale 100.64/10; this PC);
    remote play is never meant to be reachable from the internet;
  - every WebSocket and POST must come from this server's own page (Origin == Host, plus the X-FM-Remote header on
    POSTs). Browsers don't apply CORS to WebSockets, so without this any website could drive FM27.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from web.remote import Devices, Limiter, device_name, new_pair_code, use_pair_code  # noqa: F401  (re-exported)

import app_config

COOKIE = "fm_remote"
CSRF_HEADER = "x-fm-remote"
DEVICE_DAYS = 180

PRIVATE_NETS = [ipaddress.ip_network(n) for n in
                ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                 "::1/128", "fd00::/8", "fe80::/10", "fd7a:115c:a1e0::/48")]


class RemoteDevices(Devices):
    """Phones paired for remote play (same format as the analyst's devices.json, separate file)."""

    @property
    def path(self):
        return app_config.DATA / "remote_devices.json"


DEVICES = RemoteDevices()
LIMIT = Limiter()


def private_address(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in net for net in PRIVATE_NETS)


def same_origin(headers: dict) -> bool:
    origin = headers.get("origin")
    return bool(origin) and urlparse(origin).netloc == headers.get("host", "")


def device_for(cookies: dict, client_ip: str, lan: bool) -> tuple[dict | None, str]:
    """(device, reason). This PC is always trusted; anyone else needs a paired phone."""
    if client_ip in ("127.0.0.1", "::1"):
        return {"id": "local", "name": "This PC"}, ""
    if not lan or not private_address(client_ip):
        return None, "Remote play only accepts your home network or Tailscale."
    dev = DEVICES.find(cookies.get(COOKIE))
    if dev is None:
        return None, "pair"
    return dev, ""
