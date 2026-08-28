/*
 * Service worker.
 *
 * Two jobs: make the app installable (Chrome will not offer a real home-screen
 * install without a service worker that handles fetch), and later receive push
 * notifications when a trainee calls.
 *
 * Deliberately no caching. A stale call app is worse than a slow one - if the
 * network is down the call cannot happen anyway, and serving an old bundle
 * against a changed API is a bug waiting to happen.
 */

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
  // Pass through to the network. Present because installability requires it.
});

/* ------------------------------------------------------------------ push */

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = {};
  }

  const title = data.title || "إتقان";
  const body = data.body || "متدرب ينتظر";

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "icons/icon-192.png",
      badge: "icons/icon-192.png",
      tag: "itqan-incoming-call",   // a second ring replaces the first
      renotify: true,
      requireInteraction: true,     // stays until answered or dismissed
      vibrate: [200, 100, 200, 100, 200],
      data: { url: data.url || "/coach.html" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/coach.html";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true })
      .then((windows) => {
        // Focus the coach app if it is already open rather than stacking tabs.
        for (const w of windows) {
          if (w.url.includes("coach") && "focus" in w) return w.focus();
        }
        return self.clients.openWindow(target);
      })
  );
});
