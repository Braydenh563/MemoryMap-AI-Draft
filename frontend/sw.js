// Service worker: **network-only, and deliberately so.**
//
// Asked for directly: *"if the backend is closed the ui should fail to load
// or connect on browsers until started back up again."*
//
// This file used to precache the app shell (`/`, app.js, the eight CSS
// files, the icon font, d3, p5) so MemoryMap would "open instantly and still
// open while the local server is briefly down". That second half is the
// problem. MemoryMap is not a web app that degrades gracefully offline, it
// is a front end for a local server that holds every note, every file and
// every model call. With the server down, the shell still painted: tabs,
// toolbars, empty lists, a capture box you could type into. It looked like a
// working app with an empty notebook, which is the most alarming thing it
// could possibly show someone whose notes are all on that machine.
//
// So the shell is not cached any more, and this worker now does exactly one
// useful thing: it gets out of the way, and it **deletes the caches earlier
// versions left behind**. That second part is why the file still exists
// rather than being removed outright, a worker that is simply deleted is
// not fetched again, so every browser that already installed v10 would keep
// serving that stale shell forever, including the stale `app.js` that this
// project's own CLAUDE.md records as having cost two sessions of debugging.
// A worker that installs, claims its clients and clears the old caches is
// the only reliable way to retire one.
//
// Nothing replaces the offline behaviour, on purpose. When the server is
// down the browser shows its own "can't connect" page, which is true, and
// `boot-guard.js` covers the case where the page loads but a script does
// not.

const RETIRED_CACHE_PREFIX = "memorymap-shell-";

self.addEventListener("install", () => {
  // Nothing to precache. `skipWaiting` so a browser still running the old
  // caching worker replaces it on this load rather than the next one.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(RETIRED_CACHE_PREFIX))
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// No `fetch` handler at all. A service worker without one is transparent, 
// every request goes to the network exactly as if this worker were not
// installed, which is precisely the behaviour asked for. An empty handler
// that called `fetch(event.request)` would be the same thing with an extra
// round trip through the worker thread, and a handler is the place a future
// change would quietly re-introduce caching.
