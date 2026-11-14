// FM27 Remote: shows the FM27 window and turns touches into mouse and keyboard input on the PC.
//
// Gestures
//   tap                 left click (right click when "Right" is on)
//   double-tap          zoom in 2.5x on that spot / back to fit
//   pinch               zoom (1x to 5x) around your fingers; two fingers also pan
//   one-finger drag     pan when zoomed in; with "Drag" on it drags with the mouse button held; with "Scroll" on
//                       it turns the mouse wheel
//   press and hold      magnifier: slide to aim precisely, lift to click there
//   minimap             tap or drag to jump around while zoomed in
//   draw a circle       anticlockwise = FM27's Back, clockwise = Forward (one finger, a full turn)
"use strict";

const $ = (id) => document.getElementById(id);
const stage = $("stage"), cv = $("screen"), ctx = cv.getContext("2d");
const mini = $("minimap"), mctx = mini.getContext("2d");
const loupe = $("loupe"), lctx = loupe.getContext("2d");
const statusEl = $("status"), zoomEl = $("zoomlevel"), kbd = $("kbd");

const MAX_ZOOM = 5, DOUBLE_ZOOM = 2.5, TAP_SLOP = 10, HOLD_MS = 450, DOUBLE_MS = 260, WHEEL_STEP = 36;

let ws = null, denied = false, pendingMeta = null;
let fw = 1920, fh = 1200;                 // FM27 window size in FM pixels
let base = null, detail = null;           // {img, x, y, w, h, seq}
let cw = 0, ch = 0, dpr = 1;              // stage size in CSS pixels
let scale = 1, tx = 0, ty = 0;            // screen = fm * scale + t (CSS pixels)
let fitted = true;
const modes = { right: false, drag: false, scroll: false };

// Two ways to point:
//   Touch: tap where you want to click (the picture is the screen).
//   Mouse: a cursor on the picture; one finger slides it like a trackpad, a tap clicks where it is,
//          press-and-hold then slide drags with the button held.
let mouseMode = false;
try { mouseMode = localStorage.getItem("fm27remote.mouse") === "1"; } catch { /* storage blocked */ }
const cursor = { x: 960, y: 600 };       // FM27 pixels
let cursorDown = false;
const MOUSE_SPEED = 1.4;                 // cursor travel per finger travel, relative to the picture

// ------------------------------------------------------------------ status line
let statusTimer = 0;
function status(text, warn = false, sticky = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("warn", warn);
  statusEl.classList.remove("hide");
  clearTimeout(statusTimer);
  if (!sticky) statusTimer = setTimeout(() => statusEl.classList.add("hide"), 2500);
}

// ------------------------------------------------------------------ view maths
const fitScale = () => Math.min(cw / fw, ch / fh);
const zoom = () => scale / fitScale();
const toFm = (sx, sy) => ({ x: (sx - tx) / scale, y: (sy - ty) / scale });

function clampView() {
  const s0 = fitScale();
  scale = Math.min(Math.max(scale, s0), s0 * MAX_ZOOM);
  const w = fw * scale, h = fh * scale;
  tx = w <= cw ? (cw - w) / 2 : Math.min(0, Math.max(cw - w, tx));
  ty = h <= ch ? (ch - h) / 2 : Math.min(0, Math.max(ch - h, ty));
  fitted = zoom() < 1.02;
}

function fit() {
  scale = fitScale(); tx = 0; ty = 0; clampView(); viewChanged();
}

function zoomAt(sx, sy, newScale) {
  const p = toFm(sx, sy);
  scale = newScale;
  tx = sx - p.x * scale; ty = sy - p.y * scale;
  clampView(); viewChanged();
}

function centreOn(fx, fy) {
  tx = cw / 2 - fx * scale; ty = ch / 2 - fy * scale; clampView(); viewChanged();
}

function visibleRegion() {
  const a = toFm(0, 0), b = toFm(cw, ch);
  const x = Math.max(0, a.x), y = Math.max(0, a.y);
  const w = Math.min(fw, b.x) - x, h = Math.min(fh, b.y) - y;
  return { x, y, w, h };
}

let viewTimer = 0, lastViewSent = "";
function viewChanged() {
  draw();
  if (viewTimer) return;
  viewTimer = setTimeout(() => {
    viewTimer = 0;
    const r = visibleRegion();
    const out = Math.round(r.w * scale * dpr);
    const msg = { t: "view", x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h), out };
    const key = JSON.stringify(msg);
    if (key !== lastViewSent) { lastViewSent = key; send(msg); }
  }, 90);
}

// ------------------------------------------------------------------ drawing
function resize() {
  const r = stage.getBoundingClientRect();
  const keepCentre = cw ? toFm(cw / 2, ch / 2) : null, z = cw ? zoom() : 1;
  cw = r.width; ch = r.height; dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr);
  scale = fitScale() * z;
  if (keepCentre && !fitted) centreOn(keepCentre.x, keepCentre.y); else fit();
}

let drawQueued = false;
function draw() {
  if (drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(() => {
    drawQueued = false;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#0d1013";
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * tx, dpr * ty);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = zoom() > 2 ? "low" : "high";
    if (base) ctx.drawImage(base.img, base.x, base.y, base.w, base.h);
    if (detail && !fitted) ctx.drawImage(detail.img, detail.x, detail.y, detail.w, detail.h);
    if (mouseMode) drawCursor();
    drawMinimap();
    zoomEl.hidden = fitted;
    zoomEl.textContent = zoom().toFixed(1) + "×";
  });
}

function drawCursor() {           // an arrow at the Mouse-mode cursor, the same size on screen at any zoom
  const k = 1 / scale, x = cursor.x, y = cursor.y;
  ctx.save();
  ctx.translate(x, y); ctx.scale(k, k);
  ctx.beginPath();
  ctx.moveTo(0, 0); ctx.lineTo(0, 22); ctx.lineTo(5.5, 17); ctx.lineTo(9.5, 26); ctx.lineTo(13, 24.5);
  ctx.lineTo(9, 15.5); ctx.lineTo(16, 15.5); ctx.closePath();
  ctx.fillStyle = cursorDown ? "#3d7cf5" : "#fff"; ctx.fill();
  ctx.lineWidth = 1.6; ctx.strokeStyle = "#000"; ctx.stroke();
  ctx.restore();
}

function drawMinimap() {
  mini.hidden = fitted || !base;
  if (mini.hidden) return;
  const w = MINI_W, h = Math.round(w * fh / fw), r = window.devicePixelRatio || 1;
  if (mini.width !== w * r) { mini.width = w * r; mini.height = h * r; mini.style.height = h + "px"; }
  placeMinimap();
  if (mouseMode) dodgeCursor();
  mctx.setTransform(r, 0, 0, r, 0, 0);
  mctx.drawImage(base.img, 0, 0, w, h);
  const v = visibleRegion(), k = w / fw;
  mctx.strokeStyle = "#3d7cf5"; mctx.lineWidth = 2;
  mctx.strokeRect(v.x * k + 1, v.y * k + 1, v.w * k - 2, v.h * k - 2);
}

// ------------------------------------------------------------------ connection
function send(obj) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "blob";
  ws.onopen = () => {
    status("Connected"); lastViewSent = ""; viewChanged(); startVideo();
    send({ t: "visible", v: !document.hidden });      // the PC only sends phone notifications when you're not looking
  };
  ws.onmessage = async (ev) => {
    if (typeof ev.data !== "string") {
      const meta = pendingMeta; pendingMeta = null;
      if (!meta) return;
      try {
        const img = await createImageBitmap(ev.data);
        const layer = { img, x: meta.x, y: meta.y, w: meta.w, h: meta.h, seq: meta.seq };
        if (videoLive) { img.close?.(); return; }     // a picture sent just before video took over
        if (meta.fw !== fw || meta.fh !== fh) { fw = meta.fw; fh = meta.fh; fit(); }
        if (meta.kind === "base") { if (!base?.video) base?.img.close?.(); base = layer; if (fitted) detail = null; }
        else { detail?.img.close?.(); detail = layer; }
        draw();
      } finally {
        send({ t: "ack", seq: meta.seq });
      }
      return;
    }
    const msg = JSON.parse(ev.data);
    if (msg.t === "frame") pendingMeta = msg;
    else if (msg.t === "status") onStatus(msg);
    else if (msg.t === "fm") onFm(msg);
    else if (msg.t === "rtc-answer") {
      if (pc) pc.setRemoteDescription({ type: msg.type, sdp: msg.sdp }).catch((e) => videoFailed("Video: " + e.name));
    } else if (msg.t === "rtc-error") videoFailed("Video unavailable on the PC (" + msg.msg + ")");
    else if (msg.t === "denied") {
      denied = true;
      if (msg.pair) showPair(); else status(msg.msg, true, true);
    }
  };
  ws.onclose = () => {
    stopVideo(false);
    if (denied) return;
    status("Disconnected, reconnecting…", true, true);
    setTimeout(connect, 2000);
  };
}

// ------------------------------------------------------------------ video (Phase 2: WebRTC, H.264 from the PC's GPU)
// The PC answers our offer with one video track of the FM27 window. Each decoded frame becomes the base picture,
// so zoom, the minimap, the loupe and the Mouse cursor work exactly as with the JPEG pictures. If video doesn't
// come up (old browser, network), it falls back to JPEG pictures.
const VIDEO_TIMEOUT_MS = 8000;
// The Video button steps through Off → Low → Medium → High → Off (5 / 10 / 16 Mbit/s; off = JPEG pictures).
const VIDEO_STEPS = ["off", "low", "normal", "high"];
const VIDEO_LABELS = { off: "Video", low: "Low", normal: "Medium", high: "High" };
let videoQuality = "normal";
try {
  const q = localStorage.getItem("fm27remote.videoq");
  videoQuality = VIDEO_STEPS.includes(q) ? q : localStorage.getItem("fm27remote.video") === "0" ? "off" : "normal";
} catch { /* storage blocked */ }
let videoWanted = videoQuality !== "off";
let pc = null, videoEl = null, videoLive = false, videoTimer = 0;

function videoSupported() { return typeof RTCPeerConnection === "function"; }

async function startVideo() {
  stopVideo(false);
  if (!videoWanted || !videoSupported() || !ws || ws.readyState !== 1) return;
  videoEl = document.createElement("video");
  videoEl.muted = true; videoEl.playsInline = true; videoEl.autoplay = true;
  videoEl.setAttribute("playsinline", "");
  const conn = pc = new RTCPeerConnection({ iceServers: [] });
  conn.addTransceiver("video", { direction: "recvonly" });
  conn.ontrack = (e) => {
    if (conn !== pc) return;
    videoEl.srcObject = e.streams[0] || new MediaStream([e.track]);
    videoEl.play().catch(() => {});
    watchFrames(videoEl);
  };
  conn.onconnectionstatechange = () => {
    if (conn !== pc) return;
    if (conn.connectionState === "failed") videoFailed("Video connection failed");
  };
  try {
    await conn.setLocalDescription(await conn.createOffer());
    await iceDone(conn, 1500);
    if (conn !== pc) return;
    send({ t: "rtc-offer", sdp: conn.localDescription.sdp, type: conn.localDescription.type, quality: videoQuality });
  } catch (e) {
    videoFailed("Video unavailable: " + e.name);
    return;
  }
  videoTimer = setTimeout(() => { if (!videoLive) videoFailed("Video didn't start"); }, VIDEO_TIMEOUT_MS);
}

function iceDone(conn, ms) {           // all local candidates in the offer (the PC doesn't take them one by one)
  if (conn.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((res) => {
    const t = setTimeout(res, ms);
    conn.addEventListener("icegatheringstatechange", () => {
      if (conn.iceGatheringState === "complete") { clearTimeout(t); res(); }
    });
  });
}

function watchFrames(v) {
  const onFrame = () => {
    if (v !== videoEl) return;
    if (v.videoWidth) {
      if (!videoLive) { videoLive = true; clearTimeout(videoTimer); updateVideoButton(); status("Video on"); }
      if (v.videoWidth !== fw || v.videoHeight !== fh) { fw = v.videoWidth; fh = v.videoHeight; fit(); }
      base = { img: v, x: 0, y: 0, w: fw, h: fh, seq: 0, video: true };
      detail = null;
      draw();
    }
    if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(onFrame);
    else requestAnimationFrame(onFrame);
  };
  if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(onFrame); else requestAnimationFrame(onFrame);
}

function stopVideo(tellPc = true) {
  clearTimeout(videoTimer);
  const conn = pc;
  pc = null;
  if (conn) { try { conn.close(); } catch { /* already closed */ } if (tellPc) send({ t: "rtc-stop" }); }
  if (videoEl) { videoEl.srcObject = null; videoEl = null; }
  if (base?.video) base = null;
  videoLive = false;
  updateVideoButton();
  if (tellPc) viewChanged();          // JPEG pictures resume
}

function videoFailed(why) {
  if (!pc) return;
  stopVideo(true);
  status(why + ": using pictures instead", true);
}

function setVideoQuality(q) {
  videoQuality = q;
  videoWanted = q !== "off";
  try { localStorage.setItem("fm27remote.videoq", q); } catch { /* storage blocked */ }
  if (videoWanted) {                                 // a new quality means a new connection to that encoder
    status(`Video: ${VIDEO_LABELS[q].toLowerCase()} quality…`);
    startVideo();
  } else { stopVideo(true); status("Video off: pictures instead"); }
  updateVideoButton();
}
function nextVideoQuality() {
  return VIDEO_STEPS[(VIDEO_STEPS.indexOf(videoQuality) + 1) % VIDEO_STEPS.length];
}

function updateVideoButton() {
  const b = $("b-video");
  if (!b) return;
  b.hidden = !videoSupported();
  b.classList.toggle("on", videoWanted);
  b.title = `Video: ${videoWanted ? VIDEO_LABELS[videoQuality].toLowerCase() + " quality" : "off (pictures)"}. `
          + `Tap for ${VIDEO_LABELS[nextVideoQuality()].replace("Video", "off").toLowerCase()}.`;
  b.querySelector("span").textContent = videoWanted ? VIDEO_LABELS[videoQuality] + (!videoLive && pc ? "…" : "") : "Video";
}

function onStatus(s) {
  if (/[#&]pair=/.test(location.hash)) history.replaceState(null, "", location.pathname);   // already paired here
  if ("https" in s) httpsUrl = s.https;
  if ("analyst" in s) setAnalystLink(s.analyst);
  if (s.w && s.h && (s.w !== fw || s.h !== fh)) { fw = s.w; fh = s.h; fit(); }
  if (s.msg) status(s.msg, true);
  else if (!s.fm) status("FM27 isn't running on the PC", true, true);
  else if (s.paused) status("Control is paused on the PC (Ctrl+Alt+End)", true, true);
}

// ------------------------------------------------------------------ input helpers
function fmPoint(sx, sy) {
  const p = toFm(sx, sy);
  return { x: Math.round(Math.min(Math.max(p.x, 0), fw - 1)), y: Math.round(Math.min(Math.max(p.y, 0), fh - 1)) };
}
function stagePoint(e) {
  const r = stage.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}
function click(sx, sy) {
  const p = fmPoint(sx, sy);
  send({ t: "click", x: p.x, y: p.y, button: modes.right ? "right" : "left" });
  if (modes.right) setMode("right", false);
  flash(sx, sy);
}
function flash(sx, sy) {      // a small ring where the click landed
  const d = document.createElement("div");
  d.style.cssText = `position:absolute;left:${sx - 14}px;top:${sy - 14}px;width:28px;height:28px;border-radius:50%;` +
    "border:2px solid #3d7cf5;pointer-events:none;transition:transform .35s,opacity .35s";
  stage.appendChild(d);
  requestAnimationFrame(() => { d.style.transform = "scale(1.8)"; d.style.opacity = "0"; });
  setTimeout(() => d.remove(), 400);
}

// ------------------------------------------------------------------ gestures
const pointers = new Map();
let gesture = null;          // {kind: "single"|"pinch", ...}
let lastTap = null, tapTimer = 0;

cv.addEventListener("pointerdown", (e) => {
  try { cv.setPointerCapture(e.pointerId); } catch { /* synthetic or already-ended pointer */ }
  const p = stagePoint(e);
  pointers.set(e.pointerId, p);
  if (pointers.size === 1 && mouseMode) {
    mouseDown(p);
  } else if (pointers.size === 1) {
    gesture = { kind: "single", start: p, last: p, path: [p], t0: performance.now(), moved: false, wheelAcc: 0,
                pressed: false, loupe: false, startScale: scale, startTx: tx, startTy: ty };
    if (modes.drag) {          // like a real mouse: the button goes down the moment the finger touches
      gesture.pressed = true;
      send({ t: "press", ...fmPoint(p.x, p.y) });
    }
    gesture.hold = setTimeout(() => {
      if (gesture && gesture.kind === "single" && !gesture.moved && !modes.drag && !modes.scroll) {
        gesture.loupe = true; showLoupe(gesture.last);
      }
    }, HOLD_MS);
  } else if (pointers.size === 2) {
    if (gesture?.kind === "single") {
      clearTimeout(gesture.hold); hideLoupe();
      if (gesture.pressed) {
        const q = gesture.mouse ? cursorPt() : fmPoint(gesture.last.x, gesture.last.y);
        send({ t: "release", ...q }); cursorDown = false;
      }
    }
    const [a, b] = [...pointers.values()];
    gesture = { kind: "pinch", d0: Math.hypot(a.x - b.x, a.y - b.y) || 1, c0: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
                s0: scale, tx0: tx, ty0: ty };
  }
});

cv.addEventListener("pointermove", (e) => {
  if (!pointers.has(e.pointerId)) return;
  const p = stagePoint(e);
  pointers.set(e.pointerId, p);
  if (!gesture) return;
  if (gesture.kind === "pinch" && pointers.size >= 2) {
    const [a, b] = [...pointers.values()];
    const d = Math.hypot(a.x - b.x, a.y - b.y), c = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const fx = (gesture.c0.x - gesture.tx0) / gesture.s0, fy = (gesture.c0.y - gesture.ty0) / gesture.s0;
    const s0 = fitScale();
    scale = Math.min(Math.max(gesture.s0 * d / gesture.d0, s0), s0 * MAX_ZOOM);
    tx = c.x - fx * scale; ty = c.y - fy * scale;
    clampView(); viewChanged();
    return;
  }
  if (gesture.kind !== "single") return;
  if (gesture.path.length < 600) gesture.path.push(p);
  if (gesture.mouse) { mouseMove(p); return; }
  const dx = p.x - gesture.start.x, dy = p.y - gesture.start.y;
  if (!gesture.moved && Math.hypot(dx, dy) > TAP_SLOP) {
    gesture.moved = true;
    if (!gesture.loupe) clearTimeout(gesture.hold);
  }
  const step = { x: p.x - gesture.last.x, y: p.y - gesture.last.y };
  gesture.last = p;
  if (gesture.loupe) { showLoupe(p); return; }
  if (!gesture.moved) return;
  if (gesture.pressed) {
    throttledDrag(p);
  } else if (modes.scroll) {
    gesture.wheelAcc += step.y;
    while (Math.abs(gesture.wheelAcc) >= WHEEL_STEP) {
      const n = gesture.wheelAcc > 0 ? 1 : -1;      // finger down = content down = wheel up
      gesture.wheelAcc -= n * WHEEL_STEP;
      send({ t: "wheel", ...fmPoint(gesture.start.x, gesture.start.y), n });
    }
  } else {
    tx += step.x; ty += step.y; clampView(); viewChanged();      // pan
  }
});

let dragTimer = 0, dragNext = null;
function throttledDrag(p) {
  dragNext = p;
  if (dragTimer) return;
  dragTimer = setTimeout(() => { dragTimer = 0; if (dragNext) send({ t: "drag", ...fmPoint(dragNext.x, dragNext.y) }); }, 33);
}

function endPointer(e) {
  if (!pointers.has(e.pointerId)) return;
  pointers.delete(e.pointerId);
  if (!gesture) return;
  if (gesture.kind === "pinch") {
    if (pointers.size === 0) gesture = null;
    return;
  }
  const g = gesture; gesture = null;
  clearTimeout(g.hold);
  if (e.type !== "pointercancel" && circleGesture(g)) return;
  if (g.mouse) { mouseUp(g, e.type === "pointercancel"); return; }
  if (e.type === "pointercancel") { hideLoupe(); if (g.pressed) send({ t: "release", ...fmPoint(g.last.x, g.last.y) }); return; }
  if (g.loupe) { hideLoupe(); click(g.last.x, g.last.y); return; }
  if (g.pressed) {           // a drop, or (no movement) a plain click
    clearTimeout(dragTimer); dragTimer = 0; dragNext = null;
    const end = g.moved ? g.last : g.start;
    send({ t: "release", ...fmPoint(end.x, end.y) });
    return;
  }
  if (g.moved) return;
  const now = performance.now(), p = g.start;
  if (lastTap && now - lastTap.t < DOUBLE_MS && Math.hypot(p.x - lastTap.x, p.y - lastTap.y) < 30 && !modes.right) {
    clearTimeout(tapTimer); lastTap = null;            // double-tap: zoom instead of clicking
    if (fitted) zoomAt(p.x, p.y, fitScale() * DOUBLE_ZOOM); else fit();
    return;
  }
  lastTap = { x: p.x, y: p.y, t: now };
  tapTimer = setTimeout(() => { lastTap = null; click(p.x, p.y); }, modes.right ? 0 : DOUBLE_MS);
}
cv.addEventListener("pointerup", endPointer);

// A full circle drawn with one finger: anticlockwise goes Back, clockwise goes Forward (the mouse's side buttons).
// Needs most of a turn (300 degrees or more), a roughly even radius and a circle big enough not to be a wobble.
function circleTurn(path) {
  if (path.length < 10) return null;
  let cx = 0, cy = 0;
  for (const q of path) { cx += q.x; cy += q.y; }
  cx /= path.length; cy /= path.length;
  const radii = path.map((q) => Math.hypot(q.x - cx, q.y - cy));
  const r = radii.reduce((a, b) => a + b, 0) / radii.length;
  if (r < 30) return null;
  const spread = Math.sqrt(radii.reduce((a, b) => a + (b - r) ** 2, 0) / radii.length) / r;
  if (spread > 0.35) return null;
  let turn = 0, prev = Math.atan2(path[0].y - cy, path[0].x - cx);
  for (const q of path) {
    if (Math.hypot(q.x - cx, q.y - cy) < r * 0.3) continue;      // too close to the middle to trust the angle
    const a = Math.atan2(q.y - cy, q.x - cx);
    let d = a - prev;
    if (d > Math.PI) d -= 2 * Math.PI; else if (d < -Math.PI) d += 2 * Math.PI;
    turn += d; prev = a;
  }
  if (Math.abs(turn) < Math.PI * 5 / 3) return null;
  return { dir: turn > 0 ? "forward" : "back", x: cx, y: cy };        // screen y points down: positive = clockwise
}
function circleGesture(g) {
  if (!g.moved || g.loupe || g.pressed || modes.scroll) return false;
  const c = circleTurn(g.path);
  if (!c) return false;
  let at;
  if (g.mouse) {
    at = cursorPt();
  } else {
    tx = g.startTx; ty = g.startTy; clampView(); viewChanged();       // undo the panning the circle did
    at = fmPoint(c.x, c.y);
  }
  send({ t: "nav", dir: c.dir, ...at });
  navigator.vibrate?.(20);
  navToast(c.dir === "back" ? "← Back" : "Forward →");
  return true;
}
function navToast(text) {
  const d = document.createElement("div");
  d.className = "navtoast"; d.textContent = text;
  stage.appendChild(d);
  setTimeout(() => d.classList.add("gone"), 450);
  setTimeout(() => d.remove(), 800);
}
cv.addEventListener("pointercancel", endPointer);

// ------------------------------------------------------------------ Mouse mode
function cursorPt() {
  if (!Number.isFinite(cursor.x) || !Number.isFinite(cursor.y)) { cursor.x = fw / 2; cursor.y = fh / 2; }
  return { x: Math.round(cursor.x), y: Math.round(cursor.y) };
}

function mouseDown(p) {
  gesture = { kind: "single", mouse: true, start: p, last: p, path: [p], moved: false, pressed: false, wheelAcc: 0 };
  if (modes.drag) {                      // Drag on: the button goes down at the cursor straight away
    gesture.pressed = cursorDown = true;
    send({ t: "press", ...cursorPt() }); draw();
    return;
  }
  gesture.hold = setTimeout(() => {      // press and hold, then slide: drag with the button held
    if (gesture?.mouse && !gesture.moved && !modes.scroll) {
      gesture.pressed = cursorDown = true;
      send({ t: "press", ...cursorPt() });
      navigator.vibrate?.(15);
      draw();
    }
  }, HOLD_MS);
}

function mouseMove(p) {
  const g = gesture;
  let step = { x: p.x - g.last.x, y: p.y - g.last.y };
  if (!g.moved && Math.hypot(p.x - g.start.x, p.y - g.start.y) > TAP_SLOP) {
    g.moved = true;
    if (!g.pressed) clearTimeout(g.hold);
    step = { x: p.x - g.start.x, y: p.y - g.start.y };   // count the movement inside the tap threshold too
  } else if (!g.moved) {
    return;                              // still could be a tap: don't move the cursor yet
  }
  g.last = p;
  if (modes.scroll && !g.pressed) {      // Scroll on: the finger turns the wheel at the cursor
    g.wheelAcc += step.y;
    while (Math.abs(g.wheelAcc) >= WHEEL_STEP) {
      const n = g.wheelAcc > 0 ? 1 : -1;
      g.wheelAcc -= n * WHEEL_STEP;
      send({ t: "wheel", ...cursorPt(), n });
    }
    return;
  }
  cursorPt();                            // repairs a cursor that never got a real position
  cursor.x = Math.min(Math.max(cursor.x + step.x / scale * MOUSE_SPEED, 0), fw - 1);
  cursor.y = Math.min(Math.max(cursor.y + step.y / scale * MOUSE_SPEED, 0), fh - 1);
  keepCursorInView();
  throttledCursor(g.pressed ? "drag" : "move");
  draw();
}

function mouseUp(g, cancelled) {
  clearTimeout(cursorTimer); cursorTimer = 0;
  if (g.pressed) {
    send({ t: "release", ...cursorPt() });
    cursorDown = false; draw();
    return;
  }
  if (cancelled || g.moved) return;
  send({ t: "click", ...cursorPt(), button: modes.right ? "right" : "left" });      // tap = click at the cursor
  if (modes.right) setMode("right", false);
  flash(cursor.x * scale + tx, cursor.y * scale + ty);
}

function keepCursorInView() {            // zoomed in: the picture follows the cursor near the edges
  if (fitted) return;
  const m = 40, sx = cursor.x * scale + tx, sy = cursor.y * scale + ty;
  if (sx < m) tx += m - sx; else if (sx > cw - m) tx -= sx - (cw - m);
  if (sy < m) ty += m - sy; else if (sy > ch - m) ty -= sy - (ch - m);
  clampView(); viewChanged();
}

let cursorTimer = 0, cursorKind = "move";
function throttledCursor(kind) {
  cursorKind = kind;
  if (cursorTimer) return;
  cursorTimer = setTimeout(() => { cursorTimer = 0; send({ t: cursorKind, ...cursorPt() }); }, 33);
}

function setMouseMode(on) {
  mouseMode = on;
  try { localStorage.setItem("fm27remote.mouse", on ? "1" : "0"); } catch { /* storage blocked */ }
  const b = $("b-mode");
  setIcon(b, on ? "mouse" : "touch");
  b.querySelector("span").textContent = on ? "Mouse" : "Touch";
  b.classList.toggle("on", on);
  if (on) {                              // start the cursor in the middle of what's on screen
    const r = visibleRegion();         // (opening in Mouse mode, the screen may not be laid out yet: use the middle)
    const ok = Number.isFinite(r.x + r.y + r.w + r.h) && r.w > 0 && r.h > 0;
    cursor.x = ok ? r.x + r.w / 2 : fw / 2; cursor.y = ok ? r.y + r.h / 2 : fh / 2;
  }
  status(on ? "Mouse: slide to move the cursor, tap to click, hold then slide to drag" : "Touch: tap where you want to click");
  draw();
}

// wheel and ctrl+wheel when testing on a PC browser
cv.addEventListener("wheel", (e) => {
  e.preventDefault();
  const p = stagePoint(e);
  if (e.ctrlKey) { zoomAt(p.x, p.y, scale * Math.exp(-e.deltaY / 300)); return; }
  send({ t: "wheel", ...fmPoint(p.x, p.y), n: e.deltaY > 0 ? -1 : 1 });
}, { passive: false });

// ------------------------------------------------------------------ loupe
function showLoupe(p) {
  const size = 150, mag = 2, r = window.devicePixelRatio || 1;
  loupe.hidden = false;
  if (loupe.width !== size * r) { loupe.width = loupe.height = size * r; }
  const lx = Math.min(Math.max(p.x - size / 2, 4), cw - size - 4);
  const ly = p.y - size - 40 > 4 ? p.y - size - 40 : p.y + 40;
  loupe.style.left = lx + "px"; loupe.style.top = ly + "px";
  const src = size / mag * r;
  lctx.setTransform(1, 0, 0, 1, 0, 0);
  lctx.fillStyle = "#000"; lctx.fillRect(0, 0, loupe.width, loupe.height);
  lctx.drawImage(cv, p.x * r - src / 2, p.y * r - src / 2, src, src, 0, 0, loupe.width, loupe.height);
  const m = loupe.width / 2;
  lctx.strokeStyle = "#3d7cf5"; lctx.lineWidth = 2 * r;
  lctx.beginPath(); lctx.moveTo(m - 12 * r, m); lctx.lineTo(m + 12 * r, m); lctx.moveTo(m, m - 12 * r); lctx.lineTo(m, m + 12 * r); lctx.stroke();
}
function hideLoupe() { loupe.hidden = true; }

// ------------------------------------------------------------------ minimap
// It sits in a corner (bottom right by default, remembered per phone):
//   tap it, or touch and slide slowly          jump the view there
//   flick it towards another corner            it moves to that corner
//   Mouse mode: the cursor comes near it       it hops out of the way
const MINI_W = 132, MINI_MARGIN = 10, MINI_TOP = 36;   // top corners sit below the status / zoom labels
const FLICK_MS = 350, FLICK_PX = 28, NAV_AFTER_MS = 170;
let miniCorner = "br";
try { miniCorner = /^[tb][lr]$/.test(localStorage.getItem("fm27remote.minimap")) ? localStorage.getItem("fm27remote.minimap") : "br"; } catch { /* storage blocked */ }

function miniRect(corner) {
  const h = Math.round(MINI_W * fh / fw);
  const x = corner[1] === "l" ? MINI_MARGIN : cw - MINI_W - MINI_MARGIN;
  const y = corner[0] === "t" ? MINI_TOP : ch - h - MINI_MARGIN;
  return { x, y, w: MINI_W, h };
}
function placeMinimap() {
  const r = miniRect(miniCorner);
  mini.style.left = r.x + "px"; mini.style.top = r.y + "px";
}
function moveMinimap(corner) {
  if (corner === miniCorner) return;
  miniCorner = corner;
  try { localStorage.setItem("fm27remote.minimap", corner); } catch { /* storage blocked */ }
  placeMinimap();
}
function dodgeCursor() {                 // Mouse mode: never let the minimap cover the cursor
  if (mini.hidden) return;
  const sx = cursor.x * scale + tx, sy = cursor.y * scale + ty, pad = 28;
  const near = (c) => { const r = miniRect(c); return sx > r.x - pad && sx < r.x + r.w + pad && sy > r.y - pad && sy < r.y + r.h + pad; };
  if (!near(miniCorner)) return;
  const flipH = miniCorner[0] + (miniCorner[1] === "l" ? "r" : "l");
  const flipV = (miniCorner[0] === "t" ? "b" : "t") + miniCorner[1];
  const diag = flipV[0] + flipH[1];
  moveMinimap([flipH, flipV, diag].find((c) => !near(c)) || flipH);
}

function miniJump(e) {
  const r = mini.getBoundingClientRect();
  centreOn((e.clientX - r.left) / r.width * fw, (e.clientY - r.top) / r.height * fh);
}
let miniTouch = null;
mini.addEventListener("pointerdown", (e) => {
  try { mini.setPointerCapture(e.pointerId); } catch { /* ignore */ }
  miniTouch = { id: e.pointerId, x: e.clientX, y: e.clientY, t: performance.now(), nav: false };
  e.stopPropagation();
});
mini.addEventListener("pointermove", (e) => {
  const m = miniTouch;
  if (!m || m.id !== e.pointerId) return;
  if (!m.nav && performance.now() - m.t > NAV_AFTER_MS) m.nav = true;   // slow: it's navigation, not a flick
  if (m.nav) miniJump(e);
});
mini.addEventListener("pointerup", (e) => {
  const m = miniTouch; miniTouch = null;
  if (!m || m.id !== e.pointerId || m.nav) return;
  const dx = e.clientX - m.x, dy = e.clientY - m.y;
  if (Math.hypot(dx, dy) > FLICK_PX && performance.now() - m.t < FLICK_MS) {
    const row = dy > FLICK_PX / 2 ? "b" : dy < -FLICK_PX / 2 ? "t" : miniCorner[0];
    const col = dx > FLICK_PX / 2 ? "r" : dx < -FLICK_PX / 2 ? "l" : miniCorner[1];
    moveMinimap(row + col);
  } else {
    miniJump(e);                         // a tap
  }
});
mini.addEventListener("pointercancel", () => { miniTouch = null; });

// ------------------------------------------------------------------ icons
// Drawn as inline SVG: symbol characters (⏵ ☷ ▦ …) are missing or turn into emoji on many phones.
const ICONS = {
  continue: '<path d="M5 6l6 6-6 6M12 6l6 6-6 6"/>',
  home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
  squad: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.4"/><path d="M16 14.1a5 5 0 0 1 6 4.9"/>',
  tactics: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/><circle cx="12" cy="12" r="3"/>',
  news: '<rect x="3" y="5" width="14" height="15" rx="1.5"/><path d="M17 9h3v9a2 2 0 0 1-2 2h-1M6.5 9h7M6.5 12.5h7M6.5 16h4.5"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  training: '<path d="M6 8v8M18 8v8M3 10v4M21 10v4M6 12h12"/>',
  transfers: '<path d="M4 8h14l-3-3M20 16H6l3 3"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  touch: '<path d="M9 12V5.5a1.8 1.8 0 0 1 3.6 0V11"/><path d="M12.6 10.5a1.8 1.8 0 0 1 3.6 0V12"/><path d="M16.2 11.5a1.8 1.8 0 0 1 3.6 0V15a7 7 0 0 1-7 7h-.6a6.5 6.5 0 0 1-5.4-2.9L4 15.3a1.8 1.8 0 0 1 2.9-2.1L9 15"/>',
  mouse: '<path d="M6 3l12.5 7.5-5.6 1.4L10.5 18z" fill="currentColor" stroke-linejoin="round"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7.5 14h9"/>',
  right: '<rect x="6" y="3" width="12" height="18" rx="6"/><path d="M12 3v7h6" /><path d="M12 3.2a6 6 0 0 1 6 5.8V10h-6z" fill="currentColor"/>',
  drag: '<path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>',
  scroll: '<path d="M12 4v16M8 8l4-4 4 4M8 16l4 4 4-4"/>',
  back: '<path d="M10 6l-6 6 6 6M4 12h16"/>',
  picks: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M8.5 10l1.5 1.5 3-3M8.5 16l1.5 1.5 3-3"/>',
  install: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3h16v-3"/>',
  analyst: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  belloff: '<path d="M6 16V11a6 6 0 0 1 9.5-4.9M18 11v5l1.5 2H8"/><path d="M10 20a2 2 0 0 0 4 0M3 3l18 18"/>',
  save: '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>',
  fullscreen: '<path d="M4 9V4h5M4 4l6 6M20 9V4h-5M20 4l-6 6M4 15v5h5M4 20l6-6M20 15v5h-5M20 20l-6-6"/>',
  exitfull: '<path d="M10 4v6H4M4 4l6 6M14 4v6h6M20 4l-6 6M10 20v-6H4M4 20l6-6M14 20v-6h6M20 20l-6-6"/>',
};
function iconSvg(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  svg.innerHTML = ICONS[name] || "";
  return svg;
}
function setIcon(button, name) {
  button.querySelector("svg.icon, .icon-text")?.remove();
  button.prepend(iconSvg(name));
}
for (const b of document.querySelectorAll("button[data-icon]")) setIcon(b, b.dataset.icon);

// ------------------------------------------------------------------ FM27 shortcuts
// Each sends one real key press to FM27. The row comes from the PC (data/remote_shortcuts.json, or the defaults
// in remote/server.py): key is a-z, 0-9, f1-f12, space, enter, escape …
const DEFAULT_SHORTCUTS = [
  { label: "Continue", key: "space", icon: "continue", primary: true },
  { label: "Portal", key: "1", icon: "home" },
  { label: "Squad", key: "2", icon: "squad" },
  { label: "Tactics", key: "3", icon: "tactics" },
  { label: "News", key: "n", icon: "news" },
  { label: "Save", key: "ctrl+s", icon: "save" },
];
const KEY_ICONS = { space: "continue", "1": "home", "2": "squad", "3": "tactics", n: "news", "ctrl+s": "save" };
function renderShortcuts(list) {
  const row = $("shortcuts");
  row.replaceChildren();
  for (const s of list) {
    const b = document.createElement("button");
    b.title = `${s.label} (${s.key === "space" ? "Space" : s.key.toUpperCase()})`;
    if (s.primary) b.className = "primary";
    // A drawn icon by name, else the usual one for that key (older configs sent glyphs like "⌂").
    const icon = ICONS[s.icon] ? s.icon : KEY_ICONS[s.key];
    if (icon) b.append(iconSvg(icon));
    else {                                   // no drawn icon by that name: show the text (or the key) instead
      const t = document.createElement("b");
      t.className = "icon-text";
      t.textContent = (s.icon || (s.key === "space" ? "␣" : s.key.toUpperCase())).slice(0, 3);
      b.append(t);
    }
    const span = document.createElement("span");
    span.textContent = s.label;
    b.append(span);
    b.onclick = () => send({ t: "key", k: s.key });
    row.append(b);
  }
  row.append(barButton("App", "picks", () => openPicks(), "The analyst app: next match, squad and fixtures"),
);
  markBusy();
}

function barButton(label, icon, onclick, title = label, primary = false) {
  const b = document.createElement("button");
  b.title = title;
  if (primary) b.className = "primary";
  b.append(iconSvg(icon));
  const span = document.createElement("span");
  span.textContent = label;
  b.append(span);
  b.onclick = onclick;
  return b;
}

let shortcutList = DEFAULT_SHORTCUTS;

// ------------------------------------------------------------------ App panel (Phases 3-4: the analyst's data)
// Native screens drawn from the FM27 analyst on the PC, easier to read on a phone than FM27's own tables:
//   Next match: who to swap in and out, who to rest, condition alerts.   Squad: the first team.   Fixtures.
// Read-only, apart from "Update", which asks the analyst to capture FM27 now.
const picksEl = $("picks");
let teamTab = "next", squadSort = "pos", openPlayer = null, squadData = null;
try { teamTab = localStorage.getItem("fm27remote.team") || "next"; } catch { /* storage blocked */ }
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const pct = (v) => (v == null ? "–" : Math.round(v) + "%");
const fmtDate = (d) => {
  if (!d) return "";
  const [y, m, dd] = d.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, dd)).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
};
const fmtMoney = (v) => v == null ? "–" : v >= 1e6 ? `£${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `£${Math.round(v / 1e3)}K` : `£${v}`;
const JADED = 300;                                   // the analyst's "jaded" line (FM: needs a rest)
function playerMeta(p) {
  const bits = [p.position, "cond " + pct(p.condition), "sharp " + pct(p.sharpness)];
  if (p.form) bits.push("form " + Number(p.form).toFixed(2));
  const tags = [...(p.unfit || []).map((t) => `<span class="tag bad">${esc(t)}</span>`),
                ...(p.caution || []).map((t) => `<span class="tag">${esc(t)}</span>`),
                ...(p.injury ? [`<span class="tag bad">${esc(p.injury)}</span>`] : [])];
  return `<div class="meta">${esc(bits.filter(Boolean).join(" · "))}</div>${tags.join("")}`;
}
function matchLine(n) {
  return n ? `${esc(n.opponent)} (${esc(n.venue)}) · ${esc(fmtDate(n.date))} ${esc(n.kickoff || "")} · ${esc(n.competition)}`
           : "No upcoming match in the analyst's data";
}

// ---- Next match
function renderNext(d) {
  const parts = [`<p class="headline">${matchLine(d.next)}</p>`, "<h3>Suggested changes</h3>"];
  parts.push(d.swaps.length ? "<ul>" + d.swaps.map((s) => `<li class="swap">
      <div class="out"><div class="name">${esc(s.out?.name)}</div>${s.out ? playerMeta(s.out) : ""}</div>
      <div class="arrow">→</div>
      <div class="in"><div class="name">${esc(s.in?.name)}</div>${s.in ? playerMeta(s.in) : ""}</div></li>`).join("") + "</ul>"
    : '<p class="empty">No changes suggested.</p>');
  if (d.rest.length) {
    parts.push("<h3>Rest</h3><ul>" + d.rest.map((p) => `<li><div class="name">${esc(p.name)}</div>${playerMeta(p)}</li>`).join("") + "</ul>");
  }
  if (d.alerts.length) {
    parts.push("<h3>Alerts</h3><ul>" + d.alerts.map((a) =>
      `<li><span class="name">${esc(a.name)}</span> <span class="meta">${esc(a.kind)} · ${esc(a.detail)}</span></li>`).join("") + "</ul>");
  }
  if (d.upcoming?.length) {
    parts.push("<h3>Coming up</h3><ul>" + d.upcoming.map((f) =>
      `<li><span class="name">${esc(f.opponent)} (${esc(f.venue)})</span> <span class="meta">${esc(fmtDate(f.date))} · ${esc(f.competition)}</span></li>`).join("") + "</ul>");
  }
  return parts.join("");
}

// ---- Squad: one row per player, grouped by position (or sorted by condition / form); tap a row for more
function bar(v, kind) {
  const n = v == null ? 0 : Math.max(0, Math.min(100, v));
  const level = n >= 90 ? "ok" : n >= 75 ? "mid" : "low";
  return `<span class="bar ${kind} ${level}"><i style="width:${n}%"></i></span>`;
}
function formDots(ratings) {
  return `<span class="dots">${(ratings || []).slice(-5).map((r) =>
    `<i class="${r >= 7.2 ? "good" : r >= 6.7 ? "ok" : "poor"}"></i>`).join("")}</span>`;
}
function playerRow(p) {
  const tags = [p.injury ? `<span class="tag bad">${esc(p.injury)}</span>` : "",
                p.jadedness >= JADED ? '<span class="tag">needs a rest</span>' : "",
                p.loan ? '<span class="tag info">on loan</span>' : ""].join("");
  const more = openPlayer === p.unique_id ? `<div class="more">
      <span>Avg rating <b>${p.avg_rating == null ? "–" : Number(p.avg_rating).toFixed(2)}</b> in ${p.apps || 0}</span>
      <span>Last 5 <b>${(p.form || []).slice(-5).map((r) => Number(r).toFixed(1)).join(" ") || "–"}</b></span>
      <span>Form <b>${esc(p.form_label || "–")}</b></span>
      <span>Contract to <b>${esc(p.contract_expires ? fmtDate(p.contract_expires) + " " + p.contract_expires.slice(0, 4) : "–")}</b></span>
      <span>Value <b>${fmtMoney(p.value)}</b></span><span>Wage <b>${fmtMoney(p.wage_per_week)}/wk</b></span></div>` : "";
  return `<li class="player${openPlayer === p.unique_id ? " open" : ""}" data-id="${p.unique_id}">
    <div class="row1"><span class="name">${esc(p.name)}</span><span class="pos">${esc(p.positions.join(", "))}${p.age ? " · " + p.age : ""}</span></div>
    <div class="row2">${bar(p.condition, "cond")}<span class="num">${pct(p.condition)}</span>
      ${bar(p.sharpness, "sharp")}<span class="num">${pct(p.sharpness)}</span>${formDots(p.form)}</div>
    ${tags ? `<div class="tags">${tags}</div>` : ""}${more}</li>`;
}
function renderSquad(d) {
  const sorts = [["pos", "Position"], ["cond", "Condition"], ["form", "Form"]];
  const parts = [`<div class="chips">${sorts.map(([k, l]) =>
    `<button type="button" data-sort="${k}" class="${squadSort === k ? "on" : ""}">${l}</button>`).join("")}</div>`,
    '<p class="legend"><span class="bar cond ok"><i style="width:100%"></i></span> condition &nbsp;'
    + '<span class="bar sharp ok"><i style="width:100%"></i></span> sharpness &nbsp; dots: last 5 ratings</p>'];
  const ps = [...d.players];
  const avg = (p) => p.form?.length ? p.form.slice(-5).reduce((a, b) => a + b, 0) / p.form.slice(-5).length : 0;
  if (squadSort === "cond") ps.sort((a, b) => (a.condition ?? 0) - (b.condition ?? 0));
  if (squadSort === "form") ps.sort((a, b) => avg(b) - avg(a));
  if (squadSort === "pos") {
    for (const g of ["Goalkeepers", "Defenders", "Midfielders", "Attackers", "Other"]) {
      const list = ps.filter((p) => p.group === g);
      if (list.length) parts.push(`<h3>${g}</h3><ul>${list.map(playerRow).join("")}</ul>`);
    }
  } else parts.push(`<ul>${ps.map(playerRow).join("")}</ul>`);
  return parts.join("");
}

// ---- Fixtures
function crestImg(id) {           // the opponent's crest, if the analyst has a logo pack (the image removes itself if not)
  return id ? `<img class="crest" src="/api/crest/${Number(id)}" alt="" loading="lazy" onerror="this.remove()">` : "";
}
function fixtureRow(f) {
  const res = f.result ? `<span class="res ${esc(f.result)}">${esc(f.result)}</span>`
    : `<span class="res soon">${crestImg(f.opponent_id)}</span>`;
  return `<li class="fixture">${res}<div class="what"><div class="name">${f.result ? crestImg(f.opponent_id) : ""}${esc(f.opponent)} (${esc(f.venue)})</div>
    <div class="meta">${esc(fmtDate(f.date))}${f.kickoff && !f.result ? " " + esc(f.kickoff) : ""} · ${esc(f.competition)}</div></div>
    ${f.score ? `<b class="score">${esc(f.score)}</b>` : ""}</li>`;
}
function renderFixtures(d) {
  return ((d.upcoming.length ? `<h3>Coming up</h3><ul>${d.upcoming.map(fixtureRow).join("")}</ul>` : "")
    + (d.results.length ? `<h3>Results</h3><ul>${d.results.map(fixtureRow).join("")}</ul>` : ""))
    || '<p class="empty">No fixtures in the analyst\'s data.</p>';
}

const TEAM_TABS = {
  next: { url: "/api/analyst", render: renderNext },
  squad: { url: "/api/analyst/squad", render: (d) => { squadData = d; return renderSquad(d); } },
  fixtures: { url: "/api/analyst/fixtures", render: renderFixtures },
};
// "Ask the coach" only shows when the analyst's AI coach is set up (its Settings › AI coach)
async function checkCoach() {
  try {
    const r = await fetch("/api/coach", { cache: "no-store" });
    if (r.ok) { const d = await r.json(); coachReady = { ready: !!d.ready, label: d.label }; }
    else coachReady = { ready: false, label: "" };
  } catch { /* offline: keep what we knew */ }
  $("picks-coach").hidden = teamTab === "coach" || !coachReady?.ready;
  return !!coachReady?.ready;
}
async function loadPicks() {
  if (teamTab === "coach") {
    if (await checkCoach()) { showCoach(); return; }
    teamTab = "next";                                  // the coach was turned off since: back to the lists
  }
  $("coach-form").hidden = true; $("picks-coach").hidden = !coachReady?.ready;
  checkCoach();
  const tab = TEAM_TABS[teamTab] ? teamTab : (teamTab = "next"), body = $("picks-body");
  for (const b of document.querySelectorAll("#picks-tabs button")) b.classList.toggle("on", b.dataset.tab === tab);
  body.innerHTML = '<p class="empty">Loading…</p>';
  try {
    const r = await fetch(TEAM_TABS[tab].url, { cache: "no-store" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Error ${r.status}`);
    if (tab !== teamTab) return;                       // switched tab while loading
    $("picks-asof").textContent = d.as_of
      ? `Analyst data from ${fmtDate(d.as_of)}. Tap Update for fresh data after playing on.` : "";
    body.innerHTML = TEAM_TABS[tab].render(d);
  } catch (e) {
    $("picks-asof").textContent = "";
    body.innerHTML = `<p class="empty">${esc(e.message)}</p>`;
  }
}
$("picks-tabs").onclick = (e) => {
  const tab = e.target.closest("button")?.dataset.tab;
  if (!tab || tab === teamTab) return;
  teamTab = tab;
  try { localStorage.setItem("fm27remote.team", tab); } catch { /* storage blocked */ }
  picksEl.scrollTop = 0;
  loadPicks();
};
$("picks-body").onclick = (e) => {
  if (teamTab === "coach") {
    const q = e.target.closest("[data-q]");
    if (q) askCoach(q.dataset.q);
    if (e.target.closest("#coach-new") && !coachBusy) { coachMsgs = []; setCoachConv(null); renderCoach(); }
    return;
  }
  if (!squadData || teamTab !== "squad") return;
  const chip = e.target.closest("[data-sort]");
  const row = e.target.closest("li.player");
  if (chip) squadSort = chip.dataset.sort;
  else if (row) openPlayer = openPlayer === Number(row.dataset.id) ? null : Number(row.dataset.id);
  else return;
  $("picks-body").innerHTML = renderSquad(squadData);
};
function openPicks() {                               // the App button opens the panel, or closes it like ✕
  if (!picksEl.hidden) { picksEl.hidden = true; return; }
  picksEl.hidden = false; loadPicks();
}
$("picks-close").onclick = () => { picksEl.hidden = true; };
$("picks-update").onclick = async () => {
  const b = $("picks-update");
  b.disabled = true; b.textContent = "Capturing…";
  try {
    const r = await fetch("/api/analyst/capture", { method: "POST", headers: { "X-FM-Remote": "1" } });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Error ${r.status}`);
    for (let i = 0; i < 90; i++) {                       // wait for the capture to finish (usually well under a minute)
      await new Promise((res) => setTimeout(res, 1500));
      const s = await fetch("/api/analyst/capture", { cache: "no-store" }).then((x) => x.json()).catch(() => ({}));
      if (!s.running) break;
      b.textContent = `Capturing… ${Math.round(s.elapsed || 0)}s`;
    }
    await loadPicks();
  } catch (e) {
    status(e.message, true);
  } finally {
    b.disabled = false; b.textContent = "Update";
  }
};

// ---- AI coach: the analyst's chat, in the App panel. The analyst holds the provider, the keys and the saved
// conversations (the same ones its own chat lists); the phone sends questions and shows the streamed answers.
const COACH_KEY = "fm27remote.coach";
const COACH_QUESTIONS = ["Who should I rest for the next match?", "Pick my strongest fit XI for the next match.",
  "Who's on form and should stay in the matchday squad?", "Who's really tired and needs a rest?"];
let coachMsgs = [], coachConv = null, coachBusy = false, coachReady = null, coachLoaded = false;
try { coachConv = localStorage.getItem(COACH_KEY); } catch { /* storage blocked */ }
function setCoachConv(id) {
  coachConv = id;
  try { id ? localStorage.setItem(COACH_KEY, id) : localStorage.removeItem(COACH_KEY); } catch { /* storage blocked */ }
}
function coachMd(src) {            // small, safe markdown: escape first, then bold/italic/code, lists, tables, paragraphs
  const inline = (t) => t.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
  let html = "", list = null, table = [];
  const endList = () => { if (list) { html += `</${list}>`; list = null; } };
  const endTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim())));
    html += `<div class="mdt"><table><tr>${rows[0].map((c) => `<th>${c}</th>`).join("")}</tr>`
      + rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</table></div>";
    table = [];
  };
  for (const raw of esc(src).split("\n")) {
    const l = raw.trimEnd();
    let m;
    if (/^\s*\|.*\|\s*$/.test(l)) { endList(); table.push(l.trim()); continue; }
    endTable();
    if ((m = l.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { endList(); html += "<ul>"; list = "ul"; } html += `<li>${inline(m[1])}</li>`; continue; }
    if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { endList(); html += "<ol>"; list = "ol"; } html += `<li>${inline(m[1])}</li>`; continue; }
    endList();
    if ((m = l.match(/^#{1,4}\s+(.*)/))) html += `<h4>${inline(m[1])}</h4>`;
    else if (l.trim()) html += `<p>${inline(l)}</p>`;
  }
  endList(); endTable();
  return html;
}
function renderCoach() {
  if (teamTab !== "coach") return;
  const body = $("picks-body");
  const top = `<div class="coachtop"><span class="pill${coachReady?.ready ? "" : " down"}">${esc(coachReady?.label || "AI coach")}</span>
    <button type="button" id="coach-new"${coachMsgs.length && !coachBusy ? "" : " hidden"}>New chat</button></div>`;
  if (coachReady && !coachReady.ready) {
    body.innerHTML = top + '<p class="empty">The AI coach is not set up yet. Choose a provider in the analyst on your PC, under Settings › AI coach.</p>';
    return;
  }
  const chips = (n) => `<div class="qchips">${COACH_QUESTIONS.slice(0, n).map((q) =>
    `<button type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>`;
  body.innerHTML = top + (coachMsgs.length ? `<div class="chat">${coachMsgs.map((m) => m.role === "user"
      ? `<div class="msg user">${esc(m.content)}</div>`
      : `<div class="msg bot${m.error ? " err" : ""}">${m.status && !m.content ? `<span class="typing">🔎 ${esc(m.status)}…</span>` : ""}${coachMd(m.content)
        || (m.status ? "" : '<span class="typing">…</span>')}${m.tools?.length ? `<div class="msgmeta">🔎 ${esc(m.tools.join(" · "))}</div>` : ""}</div>`).join("")}</div>`
      + (coachBusy ? "" : chips(2))
    : `<p class="empty">Ask about your squad. The coach uses what the analyst captured from FM27.</p>${chips(4)}`);
  picksEl.scrollTop = picksEl.scrollHeight;
}
async function showCoach() {
  for (const b of document.querySelectorAll("#picks-tabs button")) b.classList.remove("on");
  $("picks-asof").textContent = "";
  $("picks-coach").hidden = true; $("coach-form").hidden = false;
  if (!coachLoaded) $("picks-body").innerHTML = '<p class="empty">Loading…</p>';
  else renderCoach();
  try {
    const q = !coachLoaded && coachConv ? `?conversation=${encodeURIComponent(coachConv)}` : "";
    const r = await fetch("/api/coach" + q, { cache: "no-store" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Error ${r.status}`);
    coachReady = d;
    if (q) { if (d.conversation) coachMsgs = d.conversation.messages; else setCoachConv(null); }
    coachLoaded = true;
    renderCoach();
  } catch (e) {
    if (teamTab === "coach") $("picks-body").innerHTML = `<p class="empty">${esc(e.message)}</p>`;
  }
}
async function askCoach(text) {
  text = (text || "").trim();
  if (!text || coachBusy) return;
  coachBusy = true; $("coach-send").disabled = true;
  coachMsgs.push({ role: "user", content: text });
  const reply = { role: "assistant", content: "" };
  coachMsgs.push(reply);
  renderCoach();
  try {
    const r = await fetch("/api/coach", { method: "POST",
      headers: { "X-FM-Remote": "1", "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: coachConv,
        messages: coachMsgs.filter((m) => !m.error && m !== reply).map(({ role, content }) => ({ role, content })) }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Error ${r.status}`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const ev = buf.slice(0, i); buf = buf.slice(i + 2);
        const data = ev.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("");
        if (!data) continue;
        const e = JSON.parse(data);
        if (e.conversation) setCoachConv(e.conversation);
        if (e.delta) { reply.content += e.delta; reply.status = null; renderCoach(); }
        if (e.tool) { reply.status = e.tool; (reply.tools ||= []).push(e.tool); renderCoach(); }
        if (e.error) { reply.content = e.error + "\n\nCheck **Settings › AI coach** in the analyst."; reply.error = true; }
      }
    }
    if (!reply.content) { reply.content = "No answer came back. Try again."; reply.error = true; }
  } catch (e) {
    reply.content = `Couldn't reach the coach: ${e.message}`; reply.error = true;
  }
  reply.status = null; coachBusy = false; $("coach-send").disabled = false;
  renderCoach();
}
$("picks-coach").onclick = () => {
  teamTab = "coach";
  try { localStorage.setItem("fm27remote.team", "coach"); } catch { /* storage blocked */ }
  showCoach();
};
$("coach-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("coach-input").value; $("coach-input").value = ""; askCoach(t);
});
$("coach-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("coach-form").requestSubmit(); }
});
// the tool bars make way for the phone keyboard while typing a question, as they do for the FM27 keyboard
$("coach-input").addEventListener("focus", () => document.body.classList.add("typing"));
$("coach-input").addEventListener("blur", () => document.body.classList.remove("typing"));

// ------------------------------------------------------------------ "FM27 needs you" (Phase 3)
// The PC watches FM27's top-right button (remote/fmstate.py): "»" = waiting for you, anything else = busy (processing
// days, preparing a match). When it goes back to waiting after a few seconds of busy, the phone chimes, buzzes and
// shows a banner with that button, so you can put the phone down after pressing Continue.
const alertEl = $("fm-alert"), baseTitle = document.title;
let fmState = null, alertsOn = true, audio = null, alertTimer = 0;
try { alertsOn = localStorage.getItem("fm27remote.alerts") !== "0"; } catch { /* storage blocked */ }
function unlockAudio() {                          // browsers only allow sound once you've tapped the page
  if (!audio) {
    try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch { return; }
  }
  if (audio.state === "suspended") audio.resume().catch(() => {});
}
addEventListener("pointerdown", () => {
  unlockAudio();
  if (alertEl.hidden) document.title = baseTitle;
}, { capture: true, passive: true });
function chime() {
  if (!audio || audio.state !== "running") return;
  const t = audio.currentTime;
  for (const [freq, at] of [[880, 0], [1320, 0.16]]) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = freq;
    g.gain.setValueAtTime(0.0001, t + at);
    g.gain.exponentialRampToValueAtTime(0.25, t + at + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + at + 0.35);
    o.connect(g).connect(audio.destination);
    o.start(t + at); o.stop(t + at + 0.4);
  }
}
function hideAlert() { alertEl.hidden = true; document.title = baseTitle; clearTimeout(alertTimer); }
function showAlert(img) {
  const im = $("fm-alert-img");
  im.hidden = !img;
  if (img) im.src = "data:image/png;base64," + img;
  alertEl.hidden = false;
  document.title = "● FM27 needs you";              // stays in the tab title until you tap the page
  clearTimeout(alertTimer);
  alertTimer = setTimeout(() => { alertEl.hidden = true; }, 8000);
  chime();
  navigator.vibrate?.([150, 80, 150]);              // Android; iPhones can't vibrate from a web page
}
alertEl.onclick = hideAlert;
function markBusy() {
  document.querySelector("#shortcuts .primary")?.classList.toggle("busy", fmState === "busy");
}
function onFm(msg) {
  fmState = msg.state;
  markBusy();
  if (msg.state === "busy") hideAlert();
  else if (msg.alert && alertsOn) showAlert(msg.img);
}
const alertsBtn = $("b-alerts");
function syncAlertsButton() {
  setIcon(alertsBtn, alertsOn ? "bell" : "belloff");
  alertsBtn.classList.toggle("off", !alertsOn);
  alertsBtn.classList.toggle("ask", alertsOn && typeof pushPending === "function" && pushPending());
}
syncAlertsButton();
alertsBtn.onclick = async () => {
  if (alertsOn && pushPending()) {                   // on, but phone notifications not allowed yet: ask now
    const why = await enablePush(true);
    status(why || "Phone notifications on: a test one is on its way", !!why);
    syncAlertsButton();
    return;
  }
  alertsOn = !alertsOn;
  try { localStorage.setItem("fm27remote.alerts", alertsOn ? "1" : "0"); } catch { /* storage blocked */ }
  syncAlertsButton();
  if (alertsOn) {
    unlockAudio();
    setTimeout(chime, 50);
    navigator.vibrate?.(80);
    status("Alerts on: a chime and buzz when FM27 stops and needs you");
    const why = await enablePush(true);
    if (why) status(why, true);
  } else {
    status("Alerts off");
    disablePush();
  }
};

// ---- phone notifications (Web Push), so "FM27 needs you" arrives with the page closed or the phone locked.
// Needs the https://….ts.net address (Tailscale); on an iPhone also the Home Screen app (iOS 16.4+).
let httpsUrl = null;
document.addEventListener("visibilitychange", () => send({ t: "visible", v: !document.hidden }));
const isIos = /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = matchMedia("(display-mode: standalone), (display-mode: fullscreen)").matches || navigator.standalone;
function b64urlBytes(s) {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}
async function pushPost(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "X-FM-Remote": "1", "Content-Type": "application/json" },
                                body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Error ${r.status}`);
  return d;
}
// Returns "" when notifications are on, or why they can't be (shown to you when you turn Alerts on).
async function enablePush(test = false) {
  if (!window.isSecureContext) {
    return httpsUrl ? `Phone notifications need the HTTPS address: open ${httpsUrl} (Tailscale on)`
                    : "Phone notifications need HTTPS over Tailscale, which isn't set up on the PC";
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return isIos && !standalone ? "On iPhone, add this page to the Home Screen and turn Alerts on there for notifications"
                                : "This browser can't show phone notifications";
  }
  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    if (Notification.permission !== "granted" && (await Notification.requestPermission()) !== "granted") {
      return "Notifications are blocked for this page (allow them in the browser's site settings)";
    }
    const { key } = await (await fetch("/api/push/key", { cache: "no-store" })).json();
    let sub = await reg.pushManager.getSubscription();
    const same = sub && sub.options?.applicationServerKey &&
      btoa(String.fromCharCode(...new Uint8Array(sub.options.applicationServerKey))) === btoa(String.fromCharCode(...b64urlBytes(key)));
    if (sub && !same) { await sub.unsubscribe(); sub = null; }   // the PC's key changed
    sub ||= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64urlBytes(key) });
    await pushPost("/api/push/subscribe", { subscription: sub.toJSON(), test });
    return "";
  } catch (e) {
    return "Couldn't turn on phone notifications: " + e.message;
  }
}
async function disablePush() {
  try {
    const reg = window.isSecureContext && await navigator.serviceWorker?.getRegistration("/");
    const sub = reg && await reg.pushManager.getSubscription();
    if (sub) { await pushPost("/api/push/unsubscribe", { endpoint: sub.endpoint }); await sub.unsubscribe(); }
  } catch { /* nothing to undo */ }
}
// Phone notifications are possible here but not allowed yet: the first tap on the bell asks (browsers only allow
// the question from a tap).
function pushPending() {
  return window.isSecureContext && "PushManager" in window && window.Notification?.permission === "default";
}
// Keep the PC's copy of this phone's subscription current (quietly, without asking for permission again).
if (alertsOn && window.isSecureContext && window.Notification?.permission === "granted") enablePush(false);
if (alertsOn && pushPending()) {
  alertsBtn.classList.add("ask");
  setTimeout(() => status("Tap Alerts (the bell) to allow phone notifications"), 2500);
}

// The rows scroll when their buttons don't fit: fade the edge that has more, so it's clear there's more to swipe to.
function markOverflow(row) {
  const vertical = getComputedStyle(row).flexDirection === "column";
  const [pos, size, view] = vertical ? [row.scrollTop, row.scrollHeight, row.clientHeight]
                                     : [row.scrollLeft, row.scrollWidth, row.clientWidth];
  row.classList.toggle("more-start", pos > 2);
  row.classList.toggle("more-end", pos + view < size - 2);
}
for (const row of [$("shortcuts"), $("bar")]) {
  row.addEventListener("scroll", () => markOverflow(row), { passive: true });
  new ResizeObserver(() => markOverflow(row)).observe(row);
  new MutationObserver(() => markOverflow(row)).observe(row, { childList: true, subtree: true, attributes: true,
                                                               attributeFilter: ["hidden"] });
}

renderShortcuts(DEFAULT_SHORTCUTS);
fetch("/api/shortcuts").then((r) => r.ok ? r.json() : null)
  .then((d) => {
    if (!d?.shortcuts?.length) return;
    shortcutList = d.shortcuts;
    renderShortcuts(shortcutList);
  }).catch(() => {});

// ------------------------------------------------------------------ toolbar
function setMode(name, on) {
  modes[name] = on;
  $("b-" + name).classList.toggle("on", on);
  if (on) for (const other of ["drag", "scroll"]) if (other !== name && name !== "right") { modes[other] = false; $("b-" + other).classList.remove("on"); }
}
$("b-right").onclick = () => setMode("right", !modes.right);
$("b-drag").onclick = () => { setMode("drag", !modes.drag); if (modes.drag) status("Drag: one finger moves things with the button held"); };
$("b-scroll").onclick = () => { setMode("scroll", !modes.scroll); if (modes.scroll) status("Scroll: one finger turns the mouse wheel"); };
$("b-esc").onclick = () => send({ t: "key", k: "escape" });
$("b-fit").onclick = () => fit();
$("b-video").onclick = () => setVideoQuality(nextVideoQuality());
updateVideoButton();

// ---- full screen ----
// Installed (Add to Home Screen) it already opens full screen from the manifest. In an Android browser tab the
// Fullscreen API hides the address bar; iPhone Safari has no Fullscreen API for pages, so the button stays hidden there.
const fullBtn = $("b-full");
const installed = matchMedia("(display-mode: fullscreen), (display-mode: standalone)").matches || navigator.standalone;
const canFull = !installed && document.fullscreenEnabled && document.documentElement.requestFullscreen;
function syncFull() {
  const on = !!document.fullscreenElement;
  setIcon(fullBtn, on ? "exitfull" : "fullscreen");
  fullBtn.querySelector("span").textContent = on ? "Exit" : "Full";
}
if (canFull) {
  fullBtn.hidden = false;
  syncFull();
  document.addEventListener("fullscreenchange", syncFull);
  // Full screen sticks: once turned on, the first tap after opening remote play again (or after Android drops full
  // screen, e.g. when switching apps) goes straight back to it. Browsers only allow it from a tap, not on load.
  const FULL_KEY = "fm27remote.full";
  const wantFull = (v) => { try { if (v === undefined) return localStorage.getItem(FULL_KEY) === "1";
    localStorage.setItem(FULL_KEY, v ? "1" : "0"); } catch { /* storage blocked */ } return false; };
  const goFull = () => document.documentElement.requestFullscreen({ navigationUI: "hide" });
  fullBtn.onclick = () => {
    if (document.fullscreenElement) { wantFull(false); document.exitFullscreen().catch(() => {}); }
    else goFull().then(() => wantFull(true))
      .catch((e) => status(`This browser won't go full screen (${e.name}). Add it to the Home Screen instead.`, true));
  };
  document.addEventListener("pointerup", (e) => {
    if (!document.fullscreenElement && wantFull() && !e.target.closest?.("#b-full")) goFull().catch(() => {});
  }, true);
}
// Install (Android, on the https address): an installed remote play opens with no browser bar at all.
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("b-install").hidden = false;
  markOverflow($("bar"));
});
$("b-install").onclick = async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  const { outcome } = await installPrompt.userChoice.catch(() => ({}));
  if (outcome === "accepted") { $("b-install").hidden = true; status("Installed: open FM27 Remote from your home screen"); }
  installPrompt = null;
};
window.addEventListener("appinstalled", () => { $("b-install").hidden = true; });
$("b-mode").onclick = () => setMouseMode(!mouseMode);
$("b-keys").onclick = () => { kbd.value = ""; kbd.focus(); if (document.activeElement === kbd) setTyping(true); };

// While the phone keyboard is up the bars are hidden: there's no room for them, and on Android the shrunken page
// would otherwise flip to the landscape layout. "Hide keyboard" (or the phone's own back/close) brings them back.
const kbdDone = $("kbd-done");
let kbdFullH = 0, kbdOpened = false;
function setTyping(on) {
  document.body.classList.toggle("typing", on);
  kbdDone.hidden = !on;
  kbdFullH = on ? (visualViewport?.height || innerHeight) : 0;
  kbdOpened = false;
}
kbd.addEventListener("focus", () => { if (!document.body.classList.contains("typing")) setTyping(true); });
kbd.addEventListener("blur", () => setTyping(false));
kbdDone.onclick = () => { kbd.blur(); setTyping(false); };
// Android's back button closes the keyboard without blurring the input: notice the viewport growing back
visualViewport?.addEventListener("resize", () => {
  if (document.activeElement !== kbd || !kbdFullH) return;
  const h = visualViewport.height;
  if (h < kbdFullH * 0.8) kbdOpened = true;
  else if (kbdOpened && h > kbdFullH * 0.9) kbd.blur();
});

// phone keyboards mostly report text through beforeinput, not keydown
kbd.addEventListener("beforeinput", (e) => {
  e.preventDefault();
  if (e.inputType === "insertText" && e.data) send({ t: "text", s: e.data });
  else if (e.inputType === "insertLineBreak") send({ t: "key", k: "enter" });
  else if (e.inputType.startsWith("deleteContentBackward")) send({ t: "key", k: "backspace" });
});
kbd.addEventListener("keydown", (e) => {
  const map = { Enter: "enter", Escape: "escape", Backspace: "backspace", Tab: "tab", ArrowLeft: "left",
                ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
  if (map[e.key]) { e.preventDefault(); send({ t: "key", k: map[e.key] }); }
});

// ------------------------------------------------------------------ back to the analyst
// The Analyst button (tool bar, and the App panel) opens the analyst's phone app. Its address comes from the PC
// (the phone app's public address), or from the link the analyst opened us with, or its port on this same host.
const ANALYST_KEY = "fm27remote.analyst";
function safeUrl(u) {
  try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.origin : null; } catch { return null; }
}
function setAnalystLink(a) {
  let url = a?.url ? safeUrl(a.url) : null;
  if (!url) { try { url = safeUrl(localStorage.getItem(ANALYST_KEY) || ""); } catch { /* storage blocked */ } }
  if (!url && a?.port) url = `http://${location.hostname}:${a.port}`;
  for (const el of [$("b-analyst"), $("picks-analyst")]) el.hidden = !url;
  $("picks-analyst").href = url || "#";
  $("b-analyst").onclick = url ? () => { location.href = url; } : null;
  markOverflow($("bar"));
}
(function rememberAnalyst() {                       // the analyst's "Pair this phone" link says where it is
  const back = /[#&]back=([^&]+)/.exec(location.hash);
  const url = back && safeUrl(decodeURIComponent(back[1]));
  if (url) { try { localStorage.setItem(ANALYST_KEY, url); } catch { /* storage blocked */ } }
  setAnalystLink(null);
})();

// ------------------------------------------------------------------ pairing
function showPair() {
  statusEl.classList.add("hide");
  document.body.classList.add("pairing");                          // no tool bars until paired
  $("pair").hidden = false;
  const fromQr = /[#&]pair=([A-Za-z0-9]{8})/.exec(location.hash);    // the analyst's QR code carries the code
  const name = /[#&]name=([^&]+)/.exec(location.hash);              // the analyst's phone app also names the phone
  if (fromQr) {
    $("pair-code").value = fromQr[1].toUpperCase().replace(/^(.{4})/, "$1-");
    if (name) $("pair-name").value = decodeURIComponent(name[1]).slice(0, 40);
    history.replaceState(null, "", location.pathname);              // the code works once: don't keep it around
  }
  $("pair-name").value ||= /iPhone/.test(navigator.userAgent) ? "iPhone"
    : /Android/.test(navigator.userAgent) ? "Android phone" : "";
  if (fromQr && name) $("pair").requestSubmit();                   // from the analyst's Pair button: nothing to type
}
$("pair").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("pair-msg");
  msg.textContent = "";
  try {
    const r = await fetch("/api/pair", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-FM-Remote": "1" },
      body: JSON.stringify({ code: $("pair-code").value, name: $("pair-name").value }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { msg.textContent = body.detail || `Pairing failed (${r.status})`; return; }
    $("pair").hidden = true;
    document.body.classList.remove("pairing");
    denied = false;
    status(`Paired as ${body.name}`);
    connect();
  } catch {
    msg.textContent = "Couldn't reach the PC.";
  }
});

// ------------------------------------------------------------------ start
new ResizeObserver(resize).observe(stage);
document.addEventListener("gesturestart", (e) => e.preventDefault());     // iOS: no page zoom
resize();
if (mouseMode) setMouseMode(true);      // remembered from last time on this phone
connect();
