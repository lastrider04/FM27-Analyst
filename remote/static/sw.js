// FM27 Remote service worker: shows phone notifications ("FM27 needs you") pushed by the PC, even with the page
// closed. Nothing is cached; the page always loads fresh from the PC.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { /* not JSON */ }
  e.waitUntil(self.registration.showNotification(d.title || "FM27 needs you", {
    body: d.body || "FM27 has stopped and is waiting for you.",
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    tag: d.tag || "fm27-needs-you",          // a newer one replaces the old one instead of piling up
    renotify: true,
    vibrate: [150, 80, 150],
  }));
});

// Tapping the notification brings the remote page back (or opens it).
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) if ("focus" in w) return w.focus();
    return self.clients.openWindow("/");
  })());
});
