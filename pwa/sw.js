// Service worker tối giản: luôn lấy bản mới từ mạng, mất mạng thì dùng bản đã lưu lần trước.
const CACHE = "avanta-v2";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
  .then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/cap-nhat") ||
      u.pathname.startsWith("/api/auth") || u.pathname.startsWith("/dang-nhap")) return;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && !r.redirected) { const c = r.clone(); caches.open(CACHE).then(cache => cache.put(e.request, c)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true })));
});
