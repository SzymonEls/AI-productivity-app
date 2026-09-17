const VERSION = "pwa-network-first-v3";
const SHELL_CACHE = `${VERSION}-shell`;
const RUNTIME_CACHE = `${VERSION}-runtime`;
const START_URL = "/";
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

const NAVIGATION_TIMEOUT_MS = 2500;

// Races a fetch against a timeout so a server that's down but not actively
// refusing connections (e.g. hung, or silently dropping packets) doesn't
// leave the browser waiting indefinitely before falling back to the cache.
function fetchWithTimeout(request, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("navigation-timeout")), timeoutMs);
    fetch(request).then(
      (response) => {
        clearTimeout(timer);
        resolve(response);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

// Navigations: network-first. Online the page is always fresh; the cache is
// only an offline safety net, so you never see a stale dashboard. Redirects
// (e.g. an expired session sending you to /login) are passed through untouched
// and are never cached under START_URL, so they can't poison the start entry.
async function handleNavigation(event) {
  const request = event.request;

  try {
    const preloadedResponse = await event.preloadResponse;
    const response = preloadedResponse || await fetchWithTimeout(request, NAVIGATION_TIMEOUT_MS);

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
      return markAsServedOffline(cachedResponse);
    }

    return new Response(
      "<!doctype html><meta charset=\"utf-8\"><title>Offline</title>" +
        "<script>window.__appOffline = true;</script>" +
        "<body style=\"font-family:system-ui,sans-serif;padding:2rem;text-align:center\">" +
        "<h1>You're offline</h1><p>Reconnect and try again.</p>",
      {
        status: 503,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      }
    );
  }
}

// Stamps a flag into the served-from-cache page so it can light up the
// offline indicator immediately on load, instead of the page having to make
// its own request to find out the network already failed.
async function markAsServedOffline(response) {
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("text/html")) {
    return response;
  }

  const html = await response.text();
  const flaggedHtml = /<head[^>]*>/i.test(html)
    ? html.replace(/<head([^>]*)>/i, "<head$1><script>window.__appOffline = true;</script>")
    : `<script>window.__appOffline = true;</script>${html}`;

  return new Response(flaggedHtml, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
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

// ---------------------------------------------------------------------------
// Quick capture from the notification shade.
//
// The "Add to inbox" shortcut in the app icon's menu opens /inbox/capture,
// whose only job is to raise the notification below and get out of the way. The
// reply is handled here rather than in that page, and that is the whole point:
// a service worker is woken for notificationclick whether or not a window is
// open, so dictating a thought never actually launches the app - you stay in
// whatever you were doing, pull down the shade, tap Add, talk, send.
//
// The session cookie rides along on credentials: "include", so this needs no
// token of its own. A signed-out phone gets a JSON 401 back (the endpoint is
// asked with X-Requested-With, so Flask-Login answers rather than redirecting)
// and the message is put back in the shade.
// ---------------------------------------------------------------------------

const INBOX_ENDPOINT = "/inbox";
const INBOX_TAG = "inbox-capture";
const INBOX_TITLE = "Add to inbox";

// One shape for every state of the notification, so the reply field survives
// whatever the last attempt did. renotify stays off and the sound is silenced:
// this is a box you reach for, not something that should interrupt anyone.
function inboxNotification(body, sticky) {
  return {
    body,
    tag: INBOX_TAG,
    silent: true,
    requireInteraction: Boolean(sticky),
    icon: "/static/icons/pwa-icon-192.png",
    badge: "/static/icons/pwa-icon-192.png",
    data: { kind: INBOX_TAG },
    actions: [
      {
        action: "inbox",
        type: "text",
        title: "Add",
        placeholder: "A thought to file later…",
      },
    ],
  };
}

self.addEventListener("notificationclick", (event) => {
  const notification = event.notification;
  const isInbox = notification.data && notification.data.kind === INBOX_TAG;

  if (isInbox && event.action === "inbox") {
    notification.close();
    event.waitUntil(saveThought((event.reply || "").trim()));
    return;
  }

  // The body of the notification, or a device with no inline reply: open the
  // app instead, where the same thing can be typed beside "Today".
  notification.close();
  event.waitUntil(focusApp());
});

async function saveThought(text) {
  if (!text) {
    return self.registration.showNotification(
      INBOX_TITLE,
      inboxNotification("Nothing was written. Reply to add a thought.")
    );
  }

  try {
    const response = await fetch(INBOX_ENDPOINT, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ body: text }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || "The thought was not saved.");
    }

    return self.registration.showNotification(
      INBOX_TITLE,
      inboxNotification("Added. Reply again to add another.")
    );
  } catch (error) {
    // The text is quoted back rather than dropped, because the reply field
    // cannot be pre-filled and this is all that is left of it. Sticky, so it
    // survives until it has been dealt with.
    const reason = error && error.message ? error.message : "The thought was not saved.";
    return self.registration.showNotification(
      "Not added to the inbox",
      inboxNotification(`${reason}\n\nStill unsaved: “${text}”`, true)
    );
  }
}

async function focusApp() {
  const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  const own = windows.find((client) => client.url && client.url.startsWith(self.location.origin));
  if (own) {
    return own.focus();
  }
  return self.clients.openWindow(START_URL);
}
