// 牛牛盯盘系统 - Service Worker (PWA + 钉钉代理)
const CACHE = 'niuniu-v2';
const SHELL = [
  '/',
  '/-crypto-dash/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
];

// Install: cache app shell
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL).catch(() => {}))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch handler
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // === DingTalk proxy via Service Worker (bypasses CORS) ===
  if (url.pathname.endsWith('/proxy/dingtalk')) {
    e.respondWith((async () => {
      try {
        const payload = await e.request.json();
        const targetUrl = payload.url;
        const body = payload.body || '{}';
        const resp = await fetch(targetUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
        });
        const data = await resp.text();
        return new Response(data, {
          status: resp.status,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        });
      } catch (err) {
        return new Response(JSON.stringify({ errmsg: err.message, errcode: -1 }), {
          status: 502,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        });
      }
    })());
    return;
  }

  // OPTIONS for proxy
  if (e.request.method === 'OPTIONS' && url.pathname.endsWith('/proxy/dingtalk')) {
    e.respondWith(new Response(null, {
      status: 200,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      },
    }));
    return;
  }

  // Binance API — network only
  if (url.hostname === 'api.binance.com') {
    return;
  }

  // CDN scripts — cache then network
  if (url.hostname === 'unpkg.com') {
    e.respondWith(
      caches.match(e.request).then((cached) => {
        const fetchPromise = fetch(e.request).then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((cache) => cache.put(e.request, clone));
          }
          return res;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    );
    return;
  }

  // App shell — network first, cache fallback
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then((cache) => cache.put(e.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
