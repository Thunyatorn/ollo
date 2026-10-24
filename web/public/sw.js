// Minimal service worker so the app is installable. Live data always comes from Spacetime, so nothing is cached.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
