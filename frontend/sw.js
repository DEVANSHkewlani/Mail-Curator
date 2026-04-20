/**
 * sw.js — Service Worker for The Curator Mail PWA
 *
 * Strategy:
 *   - On install: pre-cache all static shell assets (HTML, JS)
 *   - On fetch: serve shell from cache, fall through to network for API calls
 *   - API calls (/smtp, /send, /attachments, /campaigns) are always network-only
 */

const CACHE_NAME = 'curator-mail-v5';

const SHELL_ASSETS = [
  '/',
  '/login.html',
  '/signup.html',
  '/compose.html',
  '/contacts.html',
  '/attachments.html',
  '/send.html',
  '/app.js?v=5',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

// API path prefixes that must never be served from cache
const API_PREFIXES = [
  '/smtp',
  '/auth',
  '/send',
  '/attachments',
  '/campaigns',
  '/contacts',
  '/send-history',
];

// ─── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

// ─── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME)
          .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ─── Fetch ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Always use network for API routes
  const isApi = API_PREFIXES.some(p => url.pathname.startsWith(p));
  if (isApi) return; // let browser handle it normally

  // For navigation requests (HTML pages): network-first, fall back to cache
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(request, clone));
          return res;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // For static assets: cache-first
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached;
      return fetch(request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(c => c.put(request, clone));
        return res;
      });
    })
  );
});
