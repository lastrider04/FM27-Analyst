"""python -m remote [--lan] [--port 8777]     run remote play here (--lan: phones on home Wi-Fi / Tailscale)
   python -m remote start [--port 8777]        start it in the background (home Wi-Fi / Tailscale), no window
   python -m remote stop                       stop the background one
   python -m remote code                       a one-time pairing code for a phone (the server must be running)
   python -m remote devices                    list phones paired for remote play
   python -m remote revoke ID                  unpair a phone

Under pythonw (no console) output goes to data/remote.log.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app_config  # noqa: E402


def addresses() -> list[str]:
    """This PC's IPv4 addresses that a phone could use: home network and Tailscale (100.64/10)."""
    from remote.auth import private_address
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if private_address(ip) and not ip.startswith("127."))


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m remote", description="Control FM27 from your phone.")
    p.add_argument("command", nargs="?", default="serve",
                   choices=["serve", "start", "stop", "code", "devices", "revoke"])
    p.add_argument("device_id", nargs="?")
    p.add_argument("--lan", action="store_true",
                   help="also accept paired phones on home Wi-Fi and Tailscale; default is this PC only")
    p.add_argument("--port", type=int, default=8777)
    p.add_argument("--data", help="data folder (default: ./data)")
    a = p.parse_args()
    if a.data:
        app_config.DATA = Path(a.data).resolve()
    app_config.DATA.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:             # pythonw: no console
        log = open(app_config.DATA / "remote.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    from remote.auth import DEVICES

    if a.command in ("start", "stop"):
        from remote import launcher
        if a.command == "start":
            ok = launcher.start(lan=True, port=a.port)
            print(f"Remote play {'is running' if ok else 'did not start (see data/remote.log)'} on port {a.port}.")
            for ip in addresses() if ok else []:
                print(f"  open http://{ip}:{a.port} on the phone")
            if ok:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/local/info", timeout=5) as r:
                        https = json.load(r).get("https")
                except OSError:
                    https = None
                print(f"  open {https} on the phone (Tailscale, HTTPS: phone notifications work there)" if https
                      else "  no HTTPS over Tailscale (see data/remote.log): phone notifications need it")
        else:
            print("Remote play stopped." if launcher.stop(a.port) else "Remote play didn't stop.")
        return
    if a.command == "code":
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/local/pair-code", timeout=5) as r:
                code = json.load(r)["code"]
        except OSError:
            sys.exit(f"Remote play isn't running on port {a.port}. Start it first: python -m remote --lan")
        print(f"Pairing code: {code[:4]}-{code[4:]}  (single use, valid 10 minutes)")
        return
    if a.command == "devices":
        devs = DEVICES.listing()
        if not devs:
            print("No phones paired for remote play yet. Get a code with: python -m remote code")
        for d in devs:
            print(f"{d['id']}  {d['name']}")
        return
    if a.command == "revoke":
        if not a.device_id:
            p.error("revoke needs a device id (see: python -m remote devices)")
        print("unpaired" if DEVICES.revoke(a.device_id) else "no such device")
        return

    import asyncio

    import uvicorn
    from remote import tls
    from remote.server import create_app

    host = "0.0.0.0" if a.lan else "127.0.0.1"
    app = create_app(a.lan)
    opts = dict(log_level="warning", ws_max_size=1 << 16, log_config=None)
    servers = [uvicorn.Server(uvicorn.Config(app, host=host, port=a.port, **opts))]
    print(f"[remote] FM27 remote play on port {a.port}, "
          f"{'this PC + paired phones on home Wi-Fi / Tailscale' if a.lan else 'this PC only'}.")
    if a.lan:
        for ip in addresses():
            print(f"[remote]   open http://{ip}:{a.port} on the phone")
        # Tailscale HTTPS: needed for phone notifications. Same app and hub; only one server runs start-up.
        https, why = tls.tailscale_https(app_config.DATA, int(app_config.load_config().get("remote_play", {})
                                                               .get("https_port", tls.DEFAULT_PORT)))
        if https:
            servers.append(uvicorn.Server(uvicorn.Config(app, host=https["ip"], port=https["port"], lifespan="off",
                                                         ssl_certfile=https["cert"], ssl_keyfile=https["key"], **opts)))
            app.state.hub.https_url = tls.url(https)
            print(f"[remote]   open {tls.url(https)} on the phone (Tailscale, HTTPS: notifications work there)")
        else:
            print(f"[remote]   no HTTPS over Tailscale: {why}")
    print("[remote] Ctrl+Alt+End pauses control.", flush=True)

    async def serve_all():
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(serve_all())

if __name__ == "__main__":
    main()
