/* vinted-bot's service worker: one job. When the dashboard is opened (from the Dock, the
 * taskbar or a bookmark) while vinted-bot isn't running, the browser has nothing to show
 * but its own error. This keeps one page that says what happened and how to start it.
 * Nothing else is cached: finds must never be shown stale. Browsers only run it on
 * https or on this computer (localhost), not on a phone over the home network. */
const CACHE = "vinted-bot-offline-1";
const OFFLINE = "/offline";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.add(new Request(OFFLINE, { cache: "reload" })))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
