// Service worker mínimo de VideoLabs: permite instalar la app (PWA). No guarda nada en caché
// para que siempre se vea la versión actual y los videos privados nunca queden almacenados.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
