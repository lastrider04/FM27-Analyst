// FM27 Remote: a game controller connected to the phone or tablet (Bluetooth or USB: Xbox, PlayStation, Switch Pro,
// MFi …) plays FM27 like a mouse and keyboard.
//
//   left stick     moves the cursor (Mouse mode turns on by itself); a light push is slow, a full push is fast
//   right stick    scrolls at the cursor, up/down and left/right (in the App panel it scrolls the panel)
//   buttons        each does one thing from the tool bar or the shortcut row: change them under "Pad"
//                  (A clicks, held it drags; B is FM27's Back; Menu is Continue; the d-pad sends the arrow keys …)
//
// Loaded after remote.js and uses its globals (send, cursor, setMouseMode, shortcutList …). The button choices and
// the cursor speed are kept on this phone (localStorage). The browser only shows a controller to the page after one
// of its buttons is pressed, and some browsers only on the https address.
"use strict";

(() => {
  if (typeof navigator.getGamepads !== "function") return;     // no Gamepad API here (e.g. Chrome on plain http)

  const PAD_KEY = "fm27remote.pad";
  // the browser's "standard" layout: index → name (Xbox / PlayStation)
  const BUTTONS = [
    [0, "A / ✕"], [1, "B / ○"], [2, "X / □"], [3, "Y / △"], [4, "LB / L1"], [5, "RB / R1"], [6, "LT / L2"],
    [7, "RT / R2"], [8, "View / Share"], [9, "Menu / Options"], [10, "Left stick press"], [11, "Right stick press"],
    [12, "D-pad up"], [13, "D-pad down"], [14, "D-pad left"], [15, "D-pad right"],
  ];
  const DEFAULT_MAP = {
    0: "click", 1: "back", 2: "rightclick", 3: "escape", 4: "key:2", 5: "key:3", 6: "zoomout", 7: "zoomin",
    8: "app", 9: "key:space", 10: "fit", 11: "none", 12: "key:up", 13: "key:down", 14: "key:left", 15: "key:right",
  };
  const BASE_ACTIONS = [
    ["none", "Nothing"], ["click", "Click (hold to drag)"], ["rightclick", "Right click"], ["back", "Back"],
    ["forward", "Forward"], ["escape", "Esc"], ["key:enter", "Enter"], ["key:up", "Arrow up"],
    ["key:down", "Arrow down"], ["key:left", "Arrow left"], ["key:right", "Arrow right"], ["key:tab", "Tab"],
    ["key:pageup", "Page up"], ["key:pagedown", "Page down"], ["zoomin", "Zoom in"], ["zoomout", "Zoom out"],
    ["fit", "Fit"], ["app", "App panel"], ["mode", "Touch / Mouse"], ["video", "Video"],
  ];
  const REPEAT = new Set(["key:up", "key:down", "key:left", "key:right", "key:tab", "key:pageup", "key:pagedown"]);
  const REPEAT_DELAY = 380, REPEAT_EVERY = 110;
  const DEAD = 0.16;                 // stick dead zone (worn sticks rest a little off centre)
  const CURSOR_PER_S = 0.85;         // a full push crosses this much of the picture's width a second (× speed)
  const NOTCHES_PER_S = 14;          // a full push on the right stick: wheel notches a second
  const ZOOM_PER_S = 1.6;            // a full trigger: zoom by e^this a second
  const PRESSED = 0.5;               // an analogue trigger counts as pressed past this

  let cfg = load();
  function load() {
    try {
      const c = JSON.parse(localStorage.getItem(PAD_KEY) || "{}");
      return { map: { ...DEFAULT_MAP, ...(c.map || {}) }, speed: Number(c.speed) > 0 ? Number(c.speed) : 1 };
    } catch { return { map: { ...DEFAULT_MAP }, speed: 1 }; }
  }
  function save() {
    try { localStorage.setItem(PAD_KEY, JSON.stringify(cfg)); } catch { /* storage blocked */ }
  }

  // every action a button can have: the tool bar's, then the shortcut row's (from the PC)
  function actions() {
    const list = BASE_ACTIONS.slice();
    const known = new Set(list.map((a) => a[0]));
    const at = list.findIndex((a) => a[0] === "key:enter");
    const rows = (shortcutList || []).filter((s) => !known.has("key:" + s.key))
      .map((s) => ["key:" + s.key, `${s.label} (shortcut)`]);
    list.splice(at, 0, ...rows);
    for (const a of rows) known.add(a[0]);
    for (const v of Object.values(cfg.map)) if (!known.has(v) && v.startsWith("key:")) { list.push([v, v.slice(4).toUpperCase()]); known.add(v); }
    return list;
  }
  const label = (id) => (actions().find((a) => a[0] === id) || [id, id])[1];

  // ------------------------------------------------------------------ button actions
  const held = new Map();            // button index → {action, t, next} while it's down
  function down(i, now) {
    const a = cfg.map[i] || "none";
    held.set(i, { action: a, t: now, next: now + REPEAT_DELAY });
    if (padPanel && !padPanel.hidden) { highlight(i); return; }        // the Pad panel: find the button's row
    if (!picksEl.hidden && (a === "back" || a === "escape")) { picksEl.hidden = true; return; }   // B closes the panel
    if (!picksEl.hidden && a !== "app") return;                         // the App panel is a phone screen, not FM27
    run(a, true);
  }
  function up(i) {
    const h = held.get(i);
    held.delete(i);
    if (h?.action === "click" && cursorDown) { send({ t: "release", ...cursorPt() }); cursorDown = false; draw(); }
  }
  function ensureMouse() { if (!mouseMode) setMouseMode(true); }
  function run(a, first) {
    if (a === "none") return;
    if (a.startsWith("key:")) { send({ t: "key", k: a.slice(4) }); return; }
    switch (a) {
      case "click":                  // the button goes down now and up when you let go: hold and move to drag
        ensureMouse();
        if (first) { cursorDown = true; send({ t: "press", ...cursorPt() }); flash(cursor.x * scale + tx, cursor.y * scale + ty); draw(); }
        break;
      case "rightclick":
        ensureMouse(); send({ t: "click", ...cursorPt(), button: "right" }); flash(cursor.x * scale + tx, cursor.y * scale + ty); break;
      case "back": case "forward":
        send({ t: "nav", dir: a, ...cursorPt() }); navToast(a === "back" ? "Back" : "Forward"); break;
      case "escape": send({ t: "key", k: "escape" }); break;
      case "fit": fit(); break;
      case "app": openPicks(); break;
      case "mode": setMouseMode(!mouseMode); break;
      case "video": setVideoQuality(nextVideoQuality()); break;
      // zoomin / zoomout are held: see tick()
    }
  }

  // ------------------------------------------------------------------ the loop (only while a controller is there)
  let running = false, last = 0, wheelY = 0, wheelX = 0, prev = [];
  function pad() {
    const all = [...navigator.getGamepads()].filter(Boolean);
    return all.find((g) => g.mapping === "standard") || all[0] || null;
  }
  function stick(x, y) {             // dead zone, then a curve: small pushes are precise, full pushes are fast
    const m = Math.hypot(x, y);
    if (m < DEAD) return { x: 0, y: 0 };
    const k = Math.min(1, (m - DEAD) / (1 - DEAD)) ** 2 / m;
    return { x: x * k, y: y * k };
  }
  function tick(now) {
    const g = pad();
    if (!g || document.hidden) { running = false; releaseAll(); return; }
    const dt = Math.min(0.05, (now - (last || now)) / 1000);
    last = now;

    const pressed = g.buttons.map((b) => b && (b.pressed || b.value > PRESSED));
    for (let i = 0; i < pressed.length; i++) {
      if (pressed[i] && !prev[i]) down(i, now);
      else if (!pressed[i] && prev[i]) up(i);
    }
    prev = pressed;

    const blocked = (padPanel && !padPanel.hidden) || !picksEl.hidden;
    for (const [i, h] of held) {
      if (blocked) break;
      if (REPEAT.has(h.action) && now >= h.next) { run(h.action, false); h.next = now + REPEAT_EVERY; }
      if (h.action === "zoomin" || h.action === "zoomout") {
        const v = g.buttons[i]?.value || 1, k = Math.exp((h.action === "zoomin" ? 1 : -1) * ZOOM_PER_S * v * dt);
        ensureMouse();
        zoomAt(cursor.x * scale + tx, cursor.y * scale + ty, scale * k); draw();
      }
    }

    const L = stick(g.axes[0] || 0, g.axes[1] || 0), R = stick(g.axes[2] || 0, g.axes[3] || 0);
    if (!picksEl.hidden) {                       // the App panel: the right stick (or the left) scrolls it
      const s = R.y || L.y;
      if (s) picksEl.scrollTop += s * 900 * dt;
    } else if (!blocked) {
      if (L.x || L.y) {
        ensureMouse();
        const px = cw * CURSOR_PER_S * cfg.speed * dt / scale;      // FM pixels, the same speed on screen at any zoom
        cursorPt();
        cursor.x = Math.min(Math.max(cursor.x + L.x * px, 0), fw - 1);
        cursor.y = Math.min(Math.max(cursor.y + L.y * px, 0), fh - 1);
        keepCursorInView(); dodgeCursor();
        throttledCursor(cursorDown ? "drag" : "move");
        draw();
      }
      wheelY += -R.y * NOTCHES_PER_S * dt;       // stick up = scroll up = wheel forward
      wheelX += R.x * NOTCHES_PER_S * dt;
      if (!R.y) wheelY = 0;
      if (!R.x) wheelX = 0;
      while (Math.abs(wheelY) >= 1) { const n = Math.sign(wheelY); wheelY -= n; send({ t: "wheel", ...cursorPt(), n }); }
      while (Math.abs(wheelX) >= 1) { const n = Math.sign(wheelX); wheelX -= n; send({ t: "hwheel", ...cursorPt(), n }); }
    }
    requestAnimationFrame(tick);
  }
  function releaseAll() {
    for (const i of [...held.keys()]) up(i);
    prev = [];
  }
  function start() {
    if (running || !pad()) return;
    running = true; last = 0;
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------------ Pad button and panel
  ICONS.gamepad = '<path d="M7 7h10a4.5 4.5 0 0 1 4.4 5.4l-.9 4.4a2.4 2.4 0 0 1-4.1 1.2L14 15.5h-4L7.6 18a2.4 2.4 0 0 1-4.1-1.2l-.9-4.4A4.5 4.5 0 0 1 7 7z"/><path d="M7.5 10v3M6 11.5h3"/><circle cx="15.5" cy="10.5" r=".6" fill="currentColor"/><circle cx="17.5" cy="12.5" r=".6" fill="currentColor"/>';
  const padBtn = barButton("Pad", "gamepad", () => openPad(), "Game controller: choose what each button does");
  padBtn.id = "b-pad";
  padBtn.hidden = true;
  $("bar").insertBefore(padBtn, $("b-fit"));

  let padPanel = null;
  function buildPanel() {
    padPanel = document.createElement("aside");
    padPanel.id = "pad";
    padPanel.hidden = true;
    padPanel.setAttribute("aria-label", "Game controller buttons");
    padPanel.innerHTML = `
      <header><h2>Controller</h2><button type="button" id="pad-reset">Reset</button>
        <button type="button" id="pad-close" aria-label="Close">✕</button></header>
      <p id="pad-name" class="padnote"></p>
      <p class="padnote">Left stick moves the cursor, right stick scrolls. Press a button on the controller to find its
        row, then pick what it does. Kept on this phone.</p>
      <label class="padspeed">Cursor speed <input id="pad-speed" type="range" min="0.4" max="2.2" step="0.1"></label>
      <table id="pad-map"></table>`;
    $("stage").append(padPanel);
    padPanel.querySelector("#pad-close").onclick = () => { padPanel.hidden = true; };
    padPanel.querySelector("#pad-reset").onclick = () => { cfg = { map: { ...DEFAULT_MAP }, speed: 1 }; save(); fillPanel(); };
    const sp = padPanel.querySelector("#pad-speed");
    sp.oninput = () => { cfg.speed = Number(sp.value); save(); };
  }
  function fillPanel() {
    const g = pad();
    padPanel.querySelector("#pad-name").textContent = g
      ? `Connected: ${g.id.replace(/\s*\(.*\)\s*$/, "") || "controller"}${g.mapping === "standard" ? "" : " (unusual layout: buttons may be named differently)"}`
      : "No controller yet: connect one to this phone and press any of its buttons.";
    padPanel.querySelector("#pad-speed").value = cfg.speed;
    const opts = actions();
    const t = padPanel.querySelector("#pad-map");
    t.replaceChildren();
    for (const [i, name] of BUTTONS) {
      const tr = document.createElement("tr");
      tr.dataset.b = i;
      const th = document.createElement("th");
      th.textContent = name;
      const sel = document.createElement("select");
      for (const [id, text] of opts) sel.append(new Option(text, id, false, cfg.map[i] === id));
      sel.onchange = () => { cfg.map[i] = sel.value; save(); };
      const td = document.createElement("td");
      td.append(sel);
      tr.append(th, td);
      t.append(tr);
    }
  }
  function highlight(i) {
    const tr = padPanel.querySelector(`tr[data-b="${i}"]`);
    if (!tr) return;
    for (const x of padPanel.querySelectorAll("tr.hit")) x.classList.remove("hit");
    tr.classList.add("hit");
    tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function openPad() {
    if (!padPanel) buildPanel();
    if (!padPanel.hidden) { padPanel.hidden = true; return; }
    picksEl.hidden = true;
    fillPanel();
    padPanel.hidden = false;
  }

  function connected(e) {
    padBtn.hidden = false;
    markOverflow($("bar"));
    const name = e?.gamepad?.id?.replace(/\s*\(.*\)\s*$/, "") || "Controller";
    status(`${name} connected: left stick moves the cursor, A: ${label(cfg.map[0]).toLowerCase()}. Tap Pad to change buttons`);
    if (padPanel && !padPanel.hidden) fillPanel();
    start();
  }
  window.addEventListener("gamepadconnected", connected);
  window.addEventListener("gamepaddisconnected", () => {
    if (pad()) return;
    releaseAll();
    status("Controller disconnected");
    if (padPanel && !padPanel.hidden) fillPanel();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) start(); });
  if (pad()) connected(null);                  // already connected (and used) before the page loaded
})();
