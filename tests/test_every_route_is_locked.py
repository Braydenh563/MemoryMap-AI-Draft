"""Every route answers 401 to a stranger, and this test walks them all.

The gate is per router: `app.include_router(..., dependencies=locked)` in
`api/app.py`. That works, and it is invisible when it is missing. A new router
added without `dependencies=locked` reads exactly like one with it, ships
open, and nothing in the suite notices, because each feature's own tests send
a token. WORLD_CLASS_PLAN section 10, F9, which is why this walks
`app.routes` rather than naming endpoints: a route that does not exist yet is
the one this is for.

The allowlist below is the whole security decision, in one place and with a
reason per line. Anything not in it must refuse an unauthenticated caller.

**A route missing from the app is not the failure this catches.** The test
sends nonsense path parameters on purpose (`1` for an int, `x` for the rest):
a locked route refuses before it ever looks at them, which is the property
being asserted. A route that answers 404 or 422 to this request looked at the
request first, and that is the finding.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from memorymap.api import routes_auth

#: Paths that must stay reachable without a token, each for a stated reason.
#: A path is matched exactly; a prefix entry ends in `/`.
OPEN = {
    # The unlock itself, and the "is a password set?" question the lock screen
    # asks before it can draw the right mode.
    "/auth/status",
    "/auth/unlock",
    "/auth/setup",
    "/auth/lock",
    # Liveness, deliberately: the launcher polls it before the vault exists.
    "/health",
    # The browser's own crash reports, which have to reach the log *before*
    # unlock, because that is when the failure they describe happens
    # (`routes_settings.open_router`).
    "/logs/client",
    # The page itself and its assets. Serving the lock screen to someone who
    # has not unlocked is the point of a lock screen.
    "/",
    "/favicon.svg",
    "/manifest.webmanifest",
    "/sw.js",
}

#: Prefixes, for the same reason, where the path carries a file name.
OPEN_PREFIXES = ("/static/", "/css/", "/js/", "/assets/", "/icons/", "/fonts/")

#: Methods that are never asserted: HEAD and OPTIONS are handled by Starlette
#: itself (CORS preflight must answer without a token or no browser can make
#: the real request).
SKIP_METHODS = {"HEAD", "OPTIONS", "TRACE"}


def _fill(path: str) -> str:
    """A path with its parameters filled in with values a locked route never
    reads. `{entry_id:int}` style converters are handled too."""
    out = []
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            out.append("1" if ("int" in name or name.endswith("_id") or name == "id") else "x")
        else:
            out.append(part)
    return "/".join(out)


def _routes(app):
    """Every (method, path) the app serves, included routers walked through.

    `app.routes` is not the list it looks like: this FastAPI keeps an included
    router as one lazy `_IncludedRouter` entry holding the real router, so a
    plain `isinstance(route, APIRoute)` filter over `app.routes` sees three
    routes out of two hundred and passes with the whole API unchecked. That is
    the shape of bug this file exists to catch, so it is worth the recursion.
    """
    seen = set()

    def walk(routes, prefix=""):
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                context = getattr(route, "include_context", None)
                yield from walk(inner.routes, prefix + getattr(context, "prefix", ""))
                continue
            if not isinstance(route, APIRoute):
                continue
            for method in sorted(set(route.methods or []) - SKIP_METHODS):
                pair = (method, prefix + route.path)
                if pair not in seen:
                    seen.add(pair)
                    yield pair

    yield from walk(app.routes)


@pytest.fixture()
def locked_client(app_state):
    """A notebook with a password set and nobody unlocked."""
    from memorymap.api.app import create_app

    client = TestClient(create_app())
    made = client.post("/auth/setup", json={"password": "correct horse battery"})
    assert made.status_code in (200, 201), made.text
    routes_auth._active_tokens.clear()  # the setup call hands back a token
    return client


def test_every_route_refuses_a_caller_with_no_token(locked_client):
    app = locked_client.app
    open_now = []
    for method, path in _routes(app):
        if path in OPEN or path.startswith(OPEN_PREFIXES):
            continue
        response = locked_client.request(method, _fill(path))
        if response.status_code != 401:
            open_now.append(f"{method} {path} -> {response.status_code}")
    assert not open_now, (
        "these routes answered an unauthenticated caller with something other "
        "than 401, so they are either open or they validate the request before "
        "they check who is asking: " + "; ".join(open_now)
    )


def test_the_allowlist_names_only_routes_that_exist(locked_client):
    """An allowlist entry for a route that has been renamed or removed is a
    hole waiting for the name to be reused."""
    paths = {path for _method, path in _routes(locked_client.app)}
    # `/` and the static files are served by mounts rather than API routes, so
    # they are checked by reaching them rather than by name.
    named = {entry for entry in OPEN if entry.startswith("/auth") or entry in {"/health", "/logs/client"}}
    missing = sorted(entry for entry in named if entry not in paths)
    assert not missing, f"allowlisted but no longer routed: {missing}"


def test_the_lock_screen_itself_is_still_served(locked_client):
    """The other half of the same decision: if `/` were locked, a locked
    notebook would answer its owner with JSON instead of a way back in."""
    page = locked_client.get("/")
    assert page.status_code == 200
    assert "lock-password" in page.text
