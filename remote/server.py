"""The remote-play server: one page plus one WebSocket per phone.

Server → phone:
  {"t": "status", ...}                     FM27 running?, window size, paused?, a message
  {"t": "frame", "seq", "kind", x, y, w, h} then one binary JPEG. kind "base" is the whole window (low-res when
                                           zoomed in), "detail" is the zoomed-in region at the phone's resolution.
  {"t": "fm", "state", "alert", [img]}     FM27 "waiting" for you or "busy"; alert when it stops being busy
                                           (Phase 3, fmstate.py); img is its top-right button as a PNG
Phone → server (JSON):
  {"t": "view", x, y, w, h, out}           the visible FM27 region and how many device pixels wide it's drawn
  {"t": "ack", "seq"}                      a frame was drawn; at most two frames are in flight
  {"t": "click"|"press"|"drag"|"release"|"move", x, y, [button, double]}
  {"t": "wheel", x, y, n}  {"t": "text", s}  {"t": "key", k}
Video (Phase 2, WebRTC):
  phone → {"t": "rtc-offer", sdp, type, quality}   server → {"t": "rtc-answer", sdp, type} (or {"t": "rtc-error", msg})
                                                  quality: low / normal / high (5 / 10 / 16 Mbit/s)
  phone → {"t": "rtc-stop"}                       back to JPEG frames
  While video is on, no JPEG frames are sent.
"""
from __future__ import annotations

import asyncio
import math
import ctypes
import json
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, window
from .capture import Capturer, encode
from .inputs import Controller

STATIC = Path(__file__).parent / "static"
MIN_INTERVAL = 1 / 15          # at most 15 frames a second (Phase 2 moves matches to hardware-encoded video)
BASE_W = 960                   # the low-res whole-window picture kept behind a zoomed-in view
BASE_EVERY = 1.5               # seconds between base refreshes while zoomed in
MARGIN = 0.15                  # extra around a zoomed region, so a small pan doesn't show an empty edge
MAX_OUT = 1920
REVOKE_CHECK_S = 3             # how often a connected phone's pairing is re-checked


class Hub:
    def __init__(self, lan: bool):
        self.lan = lan
        self.capturer = Capturer()
        self.controller = Controller()
        self.clients: set["Client"] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.banner = None                       # created on startup (a window on the PC)
        self.encoders: dict = {}                 # quality -> video.Encoder, shared by the phones watching at it
        self.fm = {"t": "fm", "state": None}     # FM27 waiting for you, or busy (fmstate.py); sent to new phones
        self.https_url: str | None = None        # https://….ts.net when Tailscale HTTPS is up (tls.py)

    async def watch_fm(self) -> None:
        """Phase 3: tell the phones when FM27 stops being busy and needs them (the "»" on its top-right button)."""
        from . import fmstate
        watcher, last_seq = fmstate.Watcher(), 0
        while True:
            await asyncio.sleep(0.5)
            f = self.capturer.frame
            if f is None or f.seq == last_seq:   # nothing new on screen: nothing can have changed
                continue
            last_seq = f.seq
            try:
                waiting = await asyncio.to_thread(fmstate.score, f) >= fmstate.THRESHOLD
                event = watcher.update(waiting, time.monotonic())
                if event is None:
                    continue
                msg = {"t": "fm", **event}
                if event["state"] == "waiting":
                    msg["img"] = await asyncio.to_thread(fmstate.button_png, f)
            except Exception as e:  # noqa: BLE001  (a bad frame must never stop the watcher)
                print(f"[remote] FM state check failed: {e}")
                continue
            self.fm = msg | {"alert": False}
            if event["alert"]:
                print("[remote] FM27 is waiting for you")
                asyncio.ensure_future(self.push_needs_you())
            for c in list(self.clients):
                await c.send_json(msg)

    async def push_needs_you(self) -> None:
        """Phone notifications for phones that aren't looking at the page (those get the in-page alert)."""
        from . import push
        try:
            looking = {c.device.get("id") for c in self.clients if c.visible and not c.closed}
            paired = {d["id"] for d in await asyncio.to_thread(auth.DEVICES.listing)} | {"local"}
            targets = (await asyncio.to_thread(push.devices) & paired) - looking   # unpaired phones get nothing
            if targets:
                sent = await asyncio.to_thread(push.send, targets, "FM27 needs you",
                                               "FM27 has stopped and is waiting for you.")
                print(f"[remote] notified {sent} phone(s)")
        except Exception as e:  # noqa: BLE001  (pywebpush missing, network …)
            print(f"[remote] notification failed: {e}")

    def update_banner(self) -> None:
        if self.banner is None:
            return
        if self.controller.paused:
            self.banner.show("Remote play paused  ·  Ctrl+Alt+End resumes", warn=True)
            return
        names = sorted({c.device["name"] for c in self.clients if c.device.get("id") != "local"})
        if names:
            self.banner.show(f"Remote play: {', '.join(names)} connected  ·  Ctrl+Alt+End pauses")
        else:
            self.banner.hide()

    @staticmethod
    def analyst_link() -> dict | None:
        """Where the analyst's phone app is (its public address, or its port on this PC), for the Analyst button."""
        try:
            import app_config
            cfg = app_config.load_config().get("remote", {})
        except Exception:
            return None
        if not cfg.get("enabled"):
            return None
        return {"url": (cfg.get("public_url") or "").rstrip("/") or None, "port": int(cfg.get("port") or 8776)}

    def status(self, msg: str = "") -> dict:
        f = self.capturer.frame
        return {"t": "status", "fm": window.find() is not None, "capture": self.capturer.status,
                "w": f.width if f else None, "h": f.height if f else None,
                "paused": self.controller.paused, "https": self.https_url,
                "analyst": self.analyst_link(), "msg": msg}

    def broadcast_status(self, msg: str = "") -> None:
        if not self.loop:
            return
        for c in list(self.clients):
            self.loop.call_soon_threadsafe(asyncio.ensure_future, c.send_json(self.status(msg)))

    def toggle_pause(self) -> None:
        self.controller.paused = not self.controller.paused
        if self.controller.paused:
            self.controller.release_all()      # runs on the hotkey thread, so taking the input lock is fine
        state = "paused" if self.controller.paused else "resumed"
        print(f"[remote] control {state} from the PC (Ctrl+Alt+End)")
        self.update_banner()
        self.broadcast_status(f"Control {state} on the PC.")


class Client:
    def __init__(self, hub: Hub, ws: WebSocket, device: dict):
        self.hub, self.ws, self.device = hub, ws, device
        self.view: tuple[int, int, int, int] | None = None
        self.out = 1080
        self.view_changed = asyncio.Event()
        self.in_flight = 0
        self.acked = asyncio.Event()
        self.send_lock = asyncio.Lock()
        self.closed = False
        self.video = None                        # a video.VideoSession while the phone watches WebRTC video
        self.visible = True                      # the page is in front (it says when it's hidden)

    async def start_video(self, msg: dict) -> None:
        await self.stop_video()
        session = None
        try:
            from .video import BITRATES, Encoder, VideoSession
            quality = msg.get("quality") if msg.get("quality") in BITRATES else "normal"
            if quality not in self.hub.encoders:     # one per quality for all phones; idle when nobody watches
                self.hub.encoders[quality] = Encoder(self.hub.capturer, BITRATES[quality])
            session = VideoSession(self.hub.encoders[quality])
            answer = await session.answer(str(msg.get("sdp", "")), str(msg.get("type", "offer")))
        except Exception as e:  # noqa: BLE001  (aiortc missing, bad offer, no encoder …)
            print(f"[remote] {self.device['name']}: video failed: {e}")
            if session is not None:
                await session.close()
            await self.send_json({"t": "rtc-error", "msg": str(e)[:200]})
            return
        self.video = session
        print(f"[remote] {self.device['name']}: video on ({quality})")
        await self.send_json({"t": "rtc-answer", **answer})

    async def stop_video(self) -> None:
        session, self.video = self.video, None
        if session is not None:
            print(f"[remote] {self.device['name']}: video off {session.track.encoder.stats()}")
            await session.close()

    async def send_json(self, obj: dict) -> None:
        if self.closed:
            return
        async with self.send_lock:
            try:
                await self.ws.send_text(json.dumps(obj))
            except Exception:
                self.closed = True

    async def send_frame(self, meta: dict, jpeg: bytes) -> None:
        async with self.send_lock:
            await self.ws.send_text(json.dumps(meta))
            await self.ws.send_bytes(jpeg)
        self.in_flight += 1

    # ------------------------------------------------------------- streaming
    async def stream(self) -> None:
        cap = self.hub.capturer
        last_seq, last_base, last_sent, last_view = 0, 0.0, 0.0, None
        while not self.closed:
            if self.video is not None:             # the phone is watching video instead
                await asyncio.sleep(0.2)
                last_view = None                   # send a fresh picture straight away if video stops
                continue
            while self.in_flight >= 2 and not self.closed:
                self.acked.clear()
                try:
                    await asyncio.wait_for(self.acked.wait(), 3)
                except asyncio.TimeoutError:
                    self.in_flight = 0             # a lost ack must not freeze the stream
            wait = MIN_INTERVAL - (time.monotonic() - last_sent)
            if wait > 0:
                await asyncio.sleep(wait)
            frame = await asyncio.to_thread(cap.wait_newer, last_seq, 0.5)
            view_moved = self.view != last_view
            if frame is None:
                if not view_moved or cap.frame is None:
                    continue
                frame = cap.frame                  # the picture didn't change, but the phone zoomed or panned
            last_seq, last_view = frame.seq, self.view
            zoomed = self.view is not None and self.view[2] < frame.width * 0.87
            now = time.monotonic()
            if not zoomed:
                jpeg, reg = await asyncio.to_thread(encode, frame, None, min(self.out, MAX_OUT), 70)
                await self.send_frame({"t": "frame", "seq": frame.seq, "kind": "base", "x": reg[0], "y": reg[1],
                                       "w": reg[2], "h": reg[3], "fw": frame.width, "fh": frame.height}, jpeg)
                last_base = now
            else:
                if now - last_base > BASE_EVERY or view_moved and now - last_base > 0.5:
                    jpeg, reg = await asyncio.to_thread(encode, frame, None, BASE_W, 60)
                    await self.send_frame({"t": "frame", "seq": frame.seq, "kind": "base", "x": 0, "y": 0,
                                           "w": reg[2], "h": reg[3], "fw": frame.width, "fh": frame.height}, jpeg)
                    last_base = now
                x, y, w, h = self.view
                mx, my = int(w * MARGIN), int(h * MARGIN)
                region = (x - mx, y - my, w + 2 * mx, h + 2 * my)
                out = min(MAX_OUT, int(self.out * region[2] / max(1, w)))
                jpeg, reg = await asyncio.to_thread(encode, frame, region, out, 75)
                await self.send_frame({"t": "frame", "seq": frame.seq, "kind": "detail", "x": reg[0], "y": reg[1],
                                       "w": reg[2], "h": reg[3], "fw": frame.width, "fh": frame.height}, jpeg)
            last_sent = time.monotonic()

    # ------------------------------------------------------------- input
    async def handle(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "ack":
            self.in_flight = max(0, self.in_flight - 1)
            self.acked.set()
            return
        if t == "visible":
            self.visible = bool(msg.get("v"))
            return
        if t == "view":
            try:
                self.view = tuple(int(float(msg[k])) for k in ("x", "y", "w", "h"))
                self.out = max(160, min(MAX_OUT * 2, int(float(msg.get("out", 1080)))))
            except (KeyError, TypeError, ValueError):
                return
            return
        if t == "rtc-offer":
            await self.start_video(msg)
            return
        if t == "rtc-stop":
            await self.stop_video()
            return
        c = self.hub.controller
        try:                            # a bad position from the phone is ignored, never allowed to drop the connection
            x, y = float(msg.get("x") or 0), float(msg.get("y") or 0)
        except (TypeError, ValueError):
            return
        if not (math.isfinite(x) and math.isfinite(y)):
            return
        actions = {
            "click": lambda: c.click(x, y, "right" if msg.get("button") == "right" else "left", bool(msg.get("double"))),
            "press": lambda: c.press(x, y),
            "drag": lambda: c.drag(x, y),
            "release": lambda: c.release(x, y),
            "move": lambda: c.move(x, y),
            "wheel": lambda: c.wheel(x, y, int(msg.get("n", 0))),
            "text": lambda: c.text(str(msg.get("s", ""))),
            "key": lambda: c.key(str(msg.get("k", ""))),
            "nav": lambda: c.nav(str(msg.get("dir", "")), x, y),
        }
        fn = actions.get(t)
        if fn is None:
            return
        try:
            await asyncio.to_thread(fn)
        except (PermissionError, LookupError, RuntimeError, ValueError, TypeError) as e:
            await self.send_json(self.hub.status(str(e)))


DEFAULT_SHORTCUTS = [
    {"label": "Continue", "key": "space", "icon": "continue", "primary": True},
    {"label": "Portal", "key": "1", "icon": "home"},
    {"label": "Squad", "key": "2", "icon": "squad"},
    {"label": "Tactics", "key": "3", "icon": "tactics"},
    {"label": "News", "key": "n", "icon": "news"},
    {"label": "Save", "key": "ctrl+s", "icon": "save"},
]
# key: a-z, 0-9, f1-f12, space, enter … or one of the allowed combinations (ctrl+s)
# icon: one of the page's drawn icons (continue, home, squad, tactics, news, save, mail, calendar, training,
# transfers, search), or up to 3 characters of text


def load_shortcuts() -> list[dict]:
    """The phone's shortcut row: data/remote_shortcuts.json when present (a list like DEFAULT_SHORTCUTS), else the
    defaults. Entries with a key the remote doesn't send are dropped; at most 8."""
    import app_config
    from .inputs import COMBOS, KEYS
    path = app_config.DATA / "remote_shortcuts.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else DEFAULT_SHORTCUTS
    except (OSError, ValueError) as e:
        print(f"[remote] {path.name} unreadable ({e}); using the default shortcuts")
        items = DEFAULT_SHORTCUTS
    out = []
    for s in items if isinstance(items, list) else []:
        if not isinstance(s, dict) or str(s.get("key", "")).lower() not in KEYS.keys() | COMBOS.keys():
            continue
        out.append({"label": str(s.get("label", s["key"]))[:12], "key": str(s["key"]).lower(),
                    "icon": str(s.get("icon", ""))[:12], "primary": bool(s.get("primary"))})
    return out[:8] or DEFAULT_SHORTCUTS


class PairBody(BaseModel):
    code: str
    name: str = ""


def create_app(lan: bool) -> FastAPI:
    hub = Hub(lan)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.hub = hub
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.on_event("startup")
    async def _startup():
        hub.loop = asyncio.get_running_loop()
        hub.capturer.start()
        hub.fm_task = asyncio.create_task(hub.watch_fm())
        start_hotkey(hub)
        try:
            from .banner import Banner
            hub.banner = Banner()
        except Exception as e:                   # the banner is a courtesy; never stop remote play over it
            print(f"[remote] no PC banner: {e}")

    @app.on_event("shutdown")
    async def _shutdown():
        hub.capturer.stop()

    @app.middleware("http")
    async def only_private(request: Request, call_next):
        ip = request.client.host if request.client else ""
        if hub.lan and not auth.private_address(ip):
            return PlainTextResponse("Remote play only accepts your home network or Tailscale.", status_code=403)
        return await call_next(request)

    @app.get("/sw.js")
    def service_worker():
        """The service worker that shows phone notifications. Served from / so it covers the whole page."""
        return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    def paired_post(request: Request) -> dict:
        headers = {k.lower(): v for k, v in request.headers.items()}
        if headers.get(auth.CSRF_HEADER) != "1" or not auth.same_origin(headers):
            raise HTTPException(403, "Blocked: request didn't come from the remote-play page.")
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        return device

    @app.get("/api/push/key")
    async def push_key(request: Request):
        """This PC's public push key, for the phone to subscribe with."""
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        from . import push
        return {"key": await asyncio.to_thread(push.public_key)}

    @app.post("/api/push/subscribe")
    async def push_subscribe(request: Request):
        """Alerts on: keep this phone's push subscription, and send a test notification."""
        device = paired_post(request)
        from . import push
        body = await request.json()
        sub = body.get("subscription") if isinstance(body, dict) else None
        if not push.valid(sub):
            raise HTTPException(400, "Not a push subscription from a known push service.")
        await asyncio.to_thread(push.subscribe, device["id"], sub)
        print(f"[remote] {device['name']}: notifications on")
        sent = 0
        if body.get("test"):
            sent = await asyncio.to_thread(push.send, {device["id"]}, "Notifications are on",
                                           "You'll get one when FM27 stops and needs you.", "fm27-test")
        return {"ok": True, "test_sent": sent}

    @app.post("/api/push/unsubscribe")
    async def push_unsubscribe(request: Request):
        device = paired_post(request)
        from . import push
        body = await request.json()
        endpoint = body.get("endpoint") if isinstance(body, dict) else None
        await asyncio.to_thread(push.unsubscribe, device["id"], endpoint if isinstance(endpoint, str) else None)
        print(f"[remote] {device['name']}: notifications off")
        return {"ok": True}

    def pc_only(request: Request, change: bool = False) -> None:
        """/local/* is for this PC (the CLI and the analyst's Remote tab). Changes also need the X-FM-Remote header,
        so a web page open on this PC can't make them (browsers won't send it cross-site without a preflight)."""
        if (request.client.host if request.client else "") not in ("127.0.0.1", "::1"):
            raise HTTPException(403)
        if change and request.headers.get(auth.CSRF_HEADER) != "1":
            raise HTTPException(403)

    @app.get("/local/info")
    def local_info(request: Request):
        """Status for the CLI and the analyst's Remote tab: addresses, paired phones, who's connected."""
        pc_only(request)
        from . import push
        from .__main__ import addresses
        notified = push.devices()
        return {
            "https": hub.https_url,
            "lan": [f"http://{ip}:{request.url.port or 8777}" for ip in addresses()],
            "devices": [{"id": d["id"], "name": d["name"], "last_seen": d.get("last_seen"),
                         "notifications": d["id"] in notified, "link": d.get("link")}
                        for d in auth.DEVICES.listing()],
            "connected": sorted({c.device["name"] for c in hub.clients if c.device.get("id") != "local"}),
            "fm": hub.fm.get("state"),
            "paused": hub.controller.paused,
        }

    @app.post("/local/revoke/{device_id}")
    def local_revoke(device_id: str, request: Request):
        """Unpair a phone (the analyst's Remote tab). It's cut off within seconds and gets no more notifications."""
        pc_only(request, change=True)
        from . import push
        ok = auth.DEVICES.revoke(device_id)
        push.unsubscribe(device_id)
        print(f"[remote] unpaired {device_id} from the analyst" if ok else f"[remote] no device {device_id}")
        return {"ok": ok}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/shortcuts")
    def shortcuts():
        return {"shortcuts": load_shortcuts()}

    @app.get("/api/analyst")
    async def analyst_summary(request: Request):
        """The FM27 analyst's next-match advice (Picks panel). Paired phones only; read-only."""
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        from . import analyst
        try:
            return await asyncio.to_thread(analyst.summary)
        except analyst.AnalystUnavailable as e:
            raise HTTPException(503, str(e))

    @app.get("/api/crest/{club_id}")
    async def crest(club_id: int, request: Request):
        """A club crest for the App panel, from the analyst's logo pack. Paired phones only."""
        from fastapi.responses import Response
        from . import analyst
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        got = await asyncio.to_thread(analyst.crest, club_id)
        if got is None:
            raise HTTPException(404)
        return Response(got[0], media_type=got[1], headers={"Cache-Control": "private, max-age=604800"})

    @app.get("/api/analyst/{part}")
    async def analyst_part(part: str, request: Request):
        """Phase 4 native screens: the squad or fixtures, from the FM27 analyst. Paired phones only; read-only."""
        from . import analyst
        fn = {"squad": analyst.squad, "fixtures": analyst.fixtures}.get(part)
        if fn is None:
            raise HTTPException(404)
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        try:
            return await asyncio.to_thread(fn)
        except analyst.AnalystUnavailable as e:
            raise HTTPException(503, str(e))

    @app.get("/api/coach")
    async def coach_status(request: Request, conversation: str | None = None):
        """App panel › coach: is the AI coach set up, and (optionally) a saved conversation to reopen. Paired only."""
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        from . import analyst
        try:
            out = await asyncio.to_thread(analyst.coach_status)
        except analyst.AnalystUnavailable as e:
            raise HTTPException(503, str(e))
        if conversation:
            out["conversation"] = await asyncio.to_thread(analyst.coach_conversation, conversation[:80])
        return out

    @app.post("/api/coach")
    async def coach_chat(request: Request):
        """App panel › coach: ask the analyst's AI coach; its answer streams back as server-sent events.
        Paired phones, from the remote-play page only (the question goes to the provider set in the analyst)."""
        from fastapi.responses import StreamingResponse
        device = paired_post(request)
        try:
            body = await request.json()
            msgs = [{"role": str(m["role"]), "content": str(m["content"])[:8000]}
                    for m in body.get("messages", [])[-24:] if m.get("role") in ("user", "assistant")]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(400, "Bad request.")
        cid = body.get("conversation_id")
        req = {"messages": msgs, "page": "overview", "conversation_id": str(cid)[:80] if cid else None}
        from . import analyst
        try:
            stream = await asyncio.to_thread(analyst.coach_stream, req)
        except analyst.AnalystUnavailable as e:
            raise HTTPException(503, str(e))
        print(f"[remote] {device['name']}: asked the coach")
        return StreamingResponse(stream, media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/analyst/capture")
    async def analyst_capture(request: Request):
        """Picks panel › Update: the analyst captures FM27 now. Paired phones, from the remote-play page only."""
        headers = {k.lower(): v for k, v in request.headers.items()}
        if headers.get(auth.CSRF_HEADER) != "1" or not auth.same_origin(headers):
            raise HTTPException(403, "Blocked: request didn't come from the remote-play page.")
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        from . import analyst
        try:
            started = await asyncio.to_thread(analyst.start_capture)
        except analyst.AnalystUnavailable as e:
            raise HTTPException(503, str(e))
        print(f"[remote] {device['name']}: analyst capture requested")
        return started

    @app.get("/api/analyst/capture")
    async def analyst_capture_state(request: Request):
        device, _ = auth.device_for(request.cookies, request.client.host if request.client else "", hub.lan)
        if device is None:
            raise HTTPException(401, "Pair this phone first.")
        from . import analyst
        try:
            return await asyncio.to_thread(analyst.capture_state)
        except analyst.AnalystUnavailable as e:
            raise HTTPException(503, str(e))

    @app.post("/local/quit")
    def local_quit(request: Request):
        """Stop remote play (python -m remote stop, or the analyst's Remote tab), from this PC only."""
        pc_only(request, change=True)
        print("[remote] stopping (python -m remote stop)")
        hub.controller.release_all()
        threading.Timer(0.3, lambda: os._exit(0)).start()
        return {"ok": True}

    code_links: dict[str, str] = {}     # pairing code -> the phone-app device it was made for

    @app.get("/local/pair-code")
    def local_pair_code(request: Request, link: str = ""):
        """A fresh one-time pairing code, for this PC only (python -m remote code, the analyst). With link (a phone-app
        device id) the phone it pairs is tied to that device's remote-play permissions in the analyst."""
        pc_only(request)
        code = auth.new_pair_code()
        if link:
            code_links[code] = link[:32]
        print(f"[remote] pairing code: {code[:4]}-{code[4:]} (single use, 10 minutes)"
              + (" from the phone app" if link else ""))
        return {"code": code, "minutes": 10}

    @app.post("/api/pair")
    async def pair(request: Request, body: PairBody):
        headers = {k.lower(): v for k, v in request.headers.items()}
        if headers.get(auth.CSRF_HEADER) != "1" or not auth.same_origin(headers):
            raise HTTPException(403, "Blocked: request didn't come from the remote-play page.")
        try:
            auth.LIMIT.check()
        except HTTPException:
            raise HTTPException(429, "Too many wrong codes. Pairing is paused for 15 minutes.")
        if not auth.use_pair_code(body.code):
            auth.LIMIT.fail()
            raise HTTPException(400, "That code is wrong or has expired. Get a new one on the PC.")
        name = auth.device_name(body.name, request)
        link = code_links.pop(auth.norm_code(body.code), None)
        token = auth.DEVICES.add(name, "phone app", link=link) if link else auth.DEVICES.add(name, "code")
        print(f"[remote] paired: {name}")
        resp = JSONResponse({"ok": True, "name": name})
        resp.set_cookie(auth.COOKIE, token, max_age=auth.DEVICE_DAYS * 86400, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/")
        return resp

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        headers = {k.lower(): v for k, v in ws.headers.items()}
        if not auth.same_origin(headers):
            await ws.close(code=1008)
            return
        device, reason = auth.device_for(ws.cookies, ws.client.host if ws.client else "", hub.lan)
        await ws.accept()
        if device is None:
            await ws.send_text(json.dumps({"t": "denied", "pair": reason == "pair", "msg": reason}))
            await ws.close(code=1008)
            return
        client = Client(hub, ws, device)
        hub.clients.add(client)
        hub.update_banner()
        print(f"[remote] {device['name']} connected")
        await client.send_json(hub.status())
        if hub.fm.get("state"):
            await client.send_json(hub.fm)
        streamer = asyncio.create_task(client.stream())
        ip = ws.client.host if ws.client else ""

        async def watchdog():
            """Unpairing on the PC, or turning remote play off for this phone in the analyst, cuts it off within
            seconds."""
            while not client.closed:
                await asyncio.sleep(REVOKE_CHECK_S)
                if device.get("id") == "local":
                    continue
                still, why = await asyncio.to_thread(auth.device_for, ws.cookies, ip, hub.lan)
                if still is None:
                    print(f"[remote] {device['name']} is no longer allowed: disconnecting it")
                    await client.send_json({"t": "denied", "pair": why == "pair", "msg": "This phone was unpaired "
                                            "on the PC. Pair it again to continue." if why == "pair" else why})
                    client.closed = True
                    await asyncio.to_thread(hub.controller.release_all)
                    try:
                        await ws.close(code=1008)
                    except Exception:
                        pass
                    return

        guard = asyncio.create_task(watchdog())
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > (20000 if raw.startswith('{"t":"rtc-offer"') else 2000):   # an SDP offer is ~5 KB
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    await client.handle(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            client.closed = True
            streamer.cancel()
            guard.cancel()
            await client.stop_video()
            hub.clients.discard(client)
            hub.update_banner()
            await asyncio.to_thread(hub.controller.release_all)
            print(f"[remote] {device['name']} disconnected")

    return app


# ---------------------------------------------------------------- kill switch on the PC
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, VK_END, WM_HOTKEY = 0x0001, 0x0002, 0x4000, 0x23, 0x0312


def start_hotkey(hub: Hub) -> None:
    """Ctrl+Alt+End on the PC pauses (and resumes) all phone control at once."""

    def run():
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_END):
            print("[remote] couldn't register Ctrl+Alt+End (in use by another app); the kill switch is unavailable")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                hub.toggle_pause()

    threading.Thread(target=run, daemon=True, name="remote-hotkey").start()
