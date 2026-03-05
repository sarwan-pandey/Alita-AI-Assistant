// Aura Service Worker — Offline cache + push notifications
const CACHE_NAME = "aura-v1";
const STATIC_ASSETS = ["/", "/index.html"];

// Install — cache static assets
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch — network-first with cache fallback
self.addEventListener("fetch", (event) => {
    // Skip non-GET and WebSocket requests
    if (event.request.method !== "GET" || event.request.url.includes("/ws")) return;

    // Don't intercept cross-origin requests (map tiles, external APIs, etc.)
    if (!event.request.url.startsWith(self.location.origin)) return;

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Cache successful responses
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});

// Push notification handler
self.addEventListener("push", (event) => {
    const data = event.data?.json() || { title: "Aura", body: "Hey! I have something for you." };
    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: "/favicon.ico",
            badge: "/favicon.ico",
            vibrate: [100, 50, 100],
        })
    );
});

// Notification click — focus or open app
self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    event.waitUntil(
        self.clients.matchAll({ type: "window" }).then((clients) => {
            if (clients.length > 0) {
                clients[0].focus();
            } else {
                self.clients.openWindow("/");
            }
        })
    );
});
