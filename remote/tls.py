"""HTTPS for remote play over Tailscale.

Phone notifications (Web Push) and "Add to Home Screen" as a real app only work on https pages, so remote play also
listens on this PC's Tailscale address with a certificate from `tailscale cert`
(https://desktop-….ts.net). It never changes Tailscale's settings: no `tailscale serve` or funnel. A proxy on this PC
would make every phone look like "This PC" to pairing; serving HTTPS here keeps each phone's own address, so pairing
still applies.

The certificate (Let's Encrypt, about 90 days) is fetched again at every start; `tailscale cert` only renews it when
it's close to expiring. It's kept in data/tls/, which is never committed.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path

DEFAULT_PORT = 443
FALLBACK_PORT = 8778
NO_WINDOW = 0x08000000


def tailscale_exe() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    default = Path(r"C:\Program Files\Tailscale\tailscale.exe")
    return str(default) if default.exists() else None


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)


def free_port(ip: str, preferred: int) -> int | None:
    for port in (preferred, FALLBACK_PORT):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((ip, port))
                return port
            except OSError:
                continue
    return None


def tailscale_https(data: Path, port: int = DEFAULT_PORT) -> tuple[dict | None, str]:
    """({"host", "ip", "port", "cert", "key"}, "") ready to serve, or (None, why not)."""
    exe = tailscale_exe()
    if not exe:
        return None, "Tailscale isn't installed"
    try:
        status = json.loads(_run([exe, "status", "--json"], 15).stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return None, f"Tailscale didn't answer ({e})"
    if status.get("BackendState") != "Running":
        return None, f"Tailscale isn't connected ({status.get('BackendState') or 'off'})"
    host = (status.get("CertDomains") or [None])[0]
    if not host:
        return None, "HTTPS certificates are off for this tailnet (Tailscale admin console › DNS › HTTPS Certificates)"
    ip = next((a for a in (status.get("Self") or {}).get("TailscaleIPs") or [] if "." in a), None)
    if not ip:
        return None, "no Tailscale IPv4 address"
    out = data / "tls"
    out.mkdir(parents=True, exist_ok=True)
    cert, key = out / "remote.crt", out / "remote.key"
    try:
        r = _run([exe, "cert", "--cert-file", str(cert), "--key-file", str(key), host], 90)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"tailscale cert failed ({e})"
    if r.returncode != 0 or not cert.exists() or not key.exists():
        return None, f"tailscale cert failed: {(r.stderr or r.stdout).strip()[:200]}"
    chosen = free_port(ip, port)
    if chosen is None:
        return None, f"ports {port} and {FALLBACK_PORT} are in use on {ip}"
    return {"host": host, "ip": ip, "port": chosen, "cert": str(cert), "key": str(key)}, ""


def url(info: dict) -> str:
    return f"https://{info['host']}" + ("" if info["port"] == 443 else f":{info['port']}")


def tailscale_state() -> dict:
    """Is Tailscale on this PC, and connected? {installed, connected, host (MagicDNS name), ip, why}. Read-only:
    it only runs `tailscale status`, never changes anything."""
    exe = tailscale_exe()
    if not exe:
        return {"installed": False, "connected": False, "host": None, "ip": None, "why": "Tailscale isn't installed"}
    try:
        status = json.loads(_run([exe, "status", "--json"], 8).stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"installed": True, "connected": False, "host": None, "ip": None, "why": f"Tailscale didn't answer ({e})"}
    state = status.get("BackendState") or "off"
    me = status.get("Self") or {}
    host = (me.get("DNSName") or "").rstrip(".") or None
    ip = next((a for a in me.get("TailscaleIPs") or [] if "." in a), None)
    connected = state == "Running" and bool(ip)
    return {"installed": True, "connected": connected, "host": host if connected else None, "ip": ip if connected else None,
            "https": bool(status.get("CertDomains")), "why": "" if connected else f"Tailscale isn't connected ({state})"}
