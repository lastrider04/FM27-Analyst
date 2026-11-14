"""Starting and stopping remote play as a background process of its own.

Remote play always runs as its own process (never inside the analyst's), so a problem in one can't take the other
down. `python -m remote start` and the analyst's start-up (when "remote_play": {"enabled": true} is in
data/config.json) both come here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8777


def running(port: int = DEFAULT_PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/shortcuts", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def start(lan: bool = True, port: int = DEFAULT_PORT, wait: float = 15) -> bool:
    """Start remote play in the background unless it's already running. True when it's up."""
    if running(port):
        return True
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    args = [str(exe), "-m", "remote", "--port", str(port)] + (["--lan"] if lan else [])
    flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW: outlives its starter
    import app_config
    app_config.DATA.mkdir(parents=True, exist_ok=True)
    log = open(app_config.DATA / "remote.log", "a", encoding="utf-8")
    subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags,
                     close_fds=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    log.close()                                     # the child keeps its own handle
    deadline = time.time() + wait
    while time.time() < deadline:
        if running(port):
            return True
        time.sleep(0.5)
    return False


def stop(port: int = DEFAULT_PORT) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/local/quit", method="POST",
                                     headers={"X-FM-Remote": "1"})
        urllib.request.urlopen(req, timeout=3).close()
    except OSError:
        pass
    for _ in range(20):
        if not running(port):
            return True
        time.sleep(0.25)
    return False


def start_with_analyst(cfg: dict) -> None:
    """Called from the analyst's start-up: start remote play too, if it's switched on in the config."""
    rp = cfg.get("remote_play") or {}
    if not rp.get("enabled"):
        return
    port = int(rp.get("port") or DEFAULT_PORT)
    ok = start(lan=bool(rp.get("lan", True)), port=port)
    print(f"remote play: {'running' if ok else 'failed to start'} on port {port}", flush=True)
