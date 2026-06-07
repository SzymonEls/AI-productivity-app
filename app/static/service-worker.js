const VERSION = "pwa-fast-start-v3";
const APP_CACHE = `${VERSION}-app`;
const STATIC_CACHE = `${VERSION}-static`;
const NAVIGATION_TIMEOUT_MS = 500;
const START_URL = "/projects/dashboard?view=timeline";
const APP_SHELL_URLS = [
  START_URL,
  "/manifest.webmanifest",
  "/static/css/styles.css",
  "/pwa-icon-192.png",
  "/pwa-icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(APP_CACHE)
      .then((cache) => cache.addAll(APP_SHELL_URLS))
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
    const networkResponsePromise = getNavigationResponse(event);
    event.waitUntil(networkResponsePromise.catch(() => undefined));
    event.respondWith(handleNavigation(event, networkResponsePromise));
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
    event.respondWith(staleWhileRevalidate(request));
  }
});

async function handleNavigation(event, networkResponsePromise) {
  const request = event.request;
  const cachedResponse =
    await caches.match(request) ||
    await caches.match(START_URL) ||
    await caches.match("/");

  if (cachedResponse) {
    const timeoutPromise = new Promise((resolve) => {
      setTimeout(() => resolve(cachedResponse), NAVIGATION_TIMEOUT_MS);
    });

    return Promise.race([
      networkResponsePromise.catch(() => cachedResponse),
      timeoutPromise,
    ]);
  }

  return networkResponsePromise;
}

async function getNavigationResponse(event) {
  const preloadedResponse = await event.preloadResponse;
  const response = preloadedResponse || await fetch(event.request);

  if (response && response.ok) {
    const cache = await caches.open(APP_CACHE);
    cache.put(event.request, response.clone());
    const requestUrl = new URL(event.request.url);
    if (`${requestUrl.pathname}${requestUrl.search}` === START_URL) {
      cache.put(START_URL, response.clone());
    }
  }

  return response;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cachedResponse = await cache.match(request);
  const networkResponsePromise = fetch(request)
    .then((response) => {
      if (response && (response.ok || response.type === "opaque")) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cachedResponse);

  return cachedResponse || networkResponsePromise;
}
