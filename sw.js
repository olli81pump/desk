const CACHE = "strategy-desk-v43";
const PRECACHE = ["./", "./index.html", "./desk.css?v=43", "./app.js?v=43", "./manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // never cache live data, state, or API
  if (/state\.json|live\.json|\/live(\/|$)|\/chart/.test(url.pathname + url.search)) {
    event.respondWith((async () => {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 10000);
      try {
        return await fetch(req, { cache: "no-store", signal: ctrl.signal });
      } finally {
        clearTimeout(t);
      }
    })());
    return;
  }
  if (url.origin !== location.origin) return;
  event.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req).then((res) => {
        if (res && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
