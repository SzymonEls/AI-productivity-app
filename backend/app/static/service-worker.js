/**
 * Offline support for the client.
 *
 * The version this replaces was network-first for everything, and its precache
 * never worked: PRECACHE_URLS named /pwa-icon-192.png and /pwa-icon-512.png,
 * which no route serves, and cache.addAll is atomic - so every install rejected
 * and the catch swallowed it. Offline worked only by accident, on whatever
 * ordinary navigation had left behind.
 *
 * The strategies below follow what each thing actually is:
 *
 *   assets/*   cache-first. Vite puts a content hash in the name, so a given
 *              URL never changes; fetching it twice is waste.
 *   the shell  network-first. It is the one file that names the current assets,
 *              so a stale copy pins the application to an old build.
 *   /api/*     network-only. The data is in IndexedDB; a cached answer would be
 *              a second, staler copy of something the client already has.
 */

const VERSION = "v3";
const SHELL_CACHE = `shell-${VERSION}`;
const ASSET_CACHE = `assets-${VERSION}`;

const SHELL_URLS = ["/", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches
            .open(SHELL_CACHE)
            // Individually, not addAll: one missing file must not throw away
            // the whole precache, which is the bug this file used to have.
            .then((cache) => Promise.all(
                SHELL_URLS.map((url) => cache.add(url).catch(() => undefined))
            ))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        Promise.all([
            caches.keys().then((names) => Promise.all(
                names
                    .filter((name) => !name.endsWith(VERSION))
                    .map((name) => caches.delete(name))
            )),
            self.clients.claim(),
        ])
    );
});

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) {
        return;
    }

    // The client holds the data. Anything the network cannot answer here is
    // answered from IndexedDB by the page itself.
    if (url.pathname.startsWith("/api/")) {
        return;
    }

    if (url.pathname.startsWith("/static/client/assets/")) {
        event.respondWith(cacheFirst(request));
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(networkFirst(request));
    }
});

async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) {
        return cached;
    }

    const response = await fetch(request);
    if (response.ok) {
        const cache = await caches.open(ASSET_CACHE);
        cache.put(request, response.clone());
    }
    return response;
}

async function networkFirst(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(SHELL_CACHE);
            cache.put("/", response.clone());
        }
        return response;
    } catch (error) {
        // Offline. The shell loads, reads IndexedDB and carries on; the sync
        // button is what says the network is missing.
        const cached = await caches.match("/", { cacheName: SHELL_CACHE });
        if (cached) {
            return cached;
        }
        throw error;
    }
}
