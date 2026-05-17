/* Aixtraball Intern – Service Worker */

var CACHE_NAME = 'intern-v3';
var OFFLINE_URL = '/static/intern/offline.html';

var PRECACHE_URLS = [
  '/intern/',
  '/static/intern/css/intern.css',
  '/static/intern/js/intern-app.js',
  OFFLINE_URL,
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(PRECACHE_URLS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE_NAME; })
            .map(function (k) { return caches.delete(k); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  var url = new URL(req.url);

  // Only handle same-origin requests
  if (url.origin !== location.origin) return;

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then(function (cached) {
        if (cached) return cached;
        return fetch(req).then(function (resp) {
          if (resp.ok) {
            var clone = resp.clone();
            caches.open(CACHE_NAME).then(function (c) { c.put(req, clone); });
          }
          return resp;
        });
      })
    );
    return;
  }

  // /intern/* pages: network-first with offline fallback
  if (url.pathname.startsWith('/intern/')) {
    event.respondWith(
      Promise.race([
        fetch(req),
        new Promise(function (_, reject) {
          setTimeout(function () { reject(new Error('timeout')); }, 5000);
        }),
      ])
      .then(function (resp) {
        if (resp.ok) {
          var clone = resp.clone();
          caches.open(CACHE_NAME).then(function (c) { c.put(req, clone); });
        }
        return resp;
      })
      .catch(function () {
        return caches.match(req).then(function (cached) {
          return cached || caches.match(OFFLINE_URL);
        });
      })
    );
  }
});
