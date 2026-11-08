// FM27 Analyst theme: dark / light / follow Windows, coloured by the club (or a colour of the user's choosing).
// Loaded in <head> so the last theme applies before the page paints; app.js calls fmApplyTheme() with the
// server's appearance setting ({mode, accent}) once /api/status answers.
(function () {
  const hex = (h) => { const m = /^#?([0-9a-f]{6})$/i.exec(h || ""); return m ? parseInt(m[1], 16) : null; };
  const rgb = (h) => { const v = hex(h); return v === null ? [200, 16, 46] : [v >> 16, (v >> 8) & 255, v & 255]; };
  const toHex = (c) => "#" + c.map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, t) => { const x = rgb(a), y = rgb(b); return toHex(x.map((v, i) => v + (y[i] - v) * t)); };
  const lum = (h) => {     // relative luminance (WCAG)
    const [r, g, b] = rgb(h).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ink = (h) => (lum(h) > 0.4 ? "#111318" : "#ffffff");   // text that reads on top of a colour
  let current = null;

  window.fmApplyTheme = function (t) {
    t = Object.assign({ mode: "dark", accent: "#c8102e" }, t || {});
    current = t;
    const root = document.documentElement;
    const dark = t.mode === "system" ? matchMedia("(prefers-color-scheme: dark)").matches : t.mode !== "light";
    root.dataset.theme = dark ? "dark" : "light";
    let a = (t.accent || "#c8102e").toLowerCase();
    // keep the club colour visible: near-black kits lighten a little on dark, near-white kits deepen on light
    if (dark && lum(a) < 0.03) a = mix(a, "#ffffff", 0.3);
    if (!dark && lum(a) > 0.6) a = mix(a, "#000000", 0.45);
    const deep = mix(a, "#000000", 0.42);
    const head = mix(a, "#000000", 0.18);
    const s = root.style;
    s.setProperty("--accent", a);
    s.setProperty("--accent-deep", deep);
    s.setProperty("--accent-ink", ink(a));
    s.setProperty("--head-ink", ink(head));
    s.setProperty("--head-a", head);
    s.setProperty("--head-b", deep);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = deep;
    try { localStorage.setItem("fmTheme", JSON.stringify(t)); } catch { /* private mode */ }
    window.dispatchEvent(new CustomEvent("fmtheme", { detail: { dark, accent: a } }));
  };

  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (current && current.mode === "system") window.fmApplyTheme(current);
  });
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("fmTheme") || "null"); } catch { /* none yet */ }
  window.fmApplyTheme(saved);
})();
