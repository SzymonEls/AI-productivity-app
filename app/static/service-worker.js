const VERSION = "pwa-network-first-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const RUNTIME_CACHE = `${VERSION}-runtime`;
const START_URL = "/projects/dashboard?view=timeline";
const PRECACHE_URLS = [
  START_URL,
  "/manifest.webmanifest",
  "/static/css/styles.css",
  "/pwa-icon-192.png",
  "/pwa-icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    Promise.all([
      caches.keys().then((cacheNames) => Promise.all(
        cacheNames
          .filter((cacheName) => !cacheName.startsWith(VERSION))
          .map((cacheName) => caches.delete(cacheName))
      )),
      self.registration.navigationPreload
        ? self.registration.navigationPreload.enable()
        : Promise.resolve(),
      self.clients.claim(),
    ])
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(handleNavigation(event));
    return;
  }

  const url = new URL(request.url);
  const isStaticAsset =
    url.origin === self.location.origin &&
    (url.pathname.startsWith("/static/") ||
      url.pathname.startsWith("/pwa-icon-") ||
      url.pathname === "/manifest.webmanifest");
  const isBootstrapAsset =
    url.origin === "https://cdn.jsdelivr.net" &&
    url.pathname.includes("/npm/bootstrap@");

  if (isStaticAsset || isBootstrapAsset) {
    event.respondWith(networkFirstAsset(request));
  }
});

// Navigations: network-first. Online the page is always fresh; the cache is
// only an offline safety net, so you never see a stale dashboard. Redirects
// (e.g. an expired session sending you to /login) are passed through untouched
// and are never cached under START_URL, so they can't poison the start entry.
async function handleNavigation(event) {
  const request = event.request;

  try {
    const preloadedResponse = await event.preloadResponse;
    const response = preloadedResponse || await fetch(request);

    // Cache only clean, non-redirected success pages as the offline fallback.
    // This keeps login redirects and error pages out of the shell cache.
    if (response && response.ok && !response.redirected) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
      const requestUrl = new URL(request.url);
      if (`${requestUrl.pathname}${requestUrl.search}` === START_URL) {
        cache.put(START_URL, response.clone());
      }
    }

    return response;
  } catch (error) {
    // Network failed (offline / no signal yet): serve whatever we cached so the
    // app still opens instead of showing a blank screen or needing a second tap.
    const cachedResponse =
      (await caches.match(request)) ||
      (await caches.match(START_URL)) ||
      (await caches.match("/"));

    if (cachedResponse) {
      return cachedResponse;
    }

    return new Response(
      "<!doctype html><meta charset=\"utf-8\"><title>Offline</title>" +
        "<body style=\"font-family:system-ui,sans-serif;padding:2rem;text-align:center\">" +
        "<h1>You're offline</h1><p>Reconnect and try again.</p>",
      {
        status: 503,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      }
    );
  }
}

// Static assets: network-first as well, so a new deploy is picked up on the
// next load without cache-busting query strings or filename hashes. The cache
// is only consulted when the network is unavailable.
async function networkFirstAsset(request) {
  const cache = await caches.open(RUNTIME_CACHE);

  try {
    const response = await fetch(request);
    if (response && (response.ok || response.type === "opaque")) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cachedResponse = await cache.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    throw error;
  }
}
