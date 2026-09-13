"""Web search: the opt-in DuckDuckGo/SearXNG lookup, page reader, and
SearXNG process admin (install/start/stop/reinstall).

Split out of `routes_settings.py`'s "web search" section
(ROADMAP.md §0/§4): self-contained apart from the app-wide `router`
pattern every route module follows.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from memorymap.core import deps
from memorymap.core.deps import get_session
from memorymap.entry import manager
from memorymap.search import websearch

router = APIRouter(tags=["settings"])

def _require_web_search() -> str:
    """403 while the preference is off so nothing can quietly go online.
    Returns the configured SearXNG URL ('' = use DuckDuckGo)."""
    config = deps.get_config()
    if not config.get_preference("web_search_enabled", False):
        raise HTTPException(
            status_code=403,
            detail="Web search is turned off. Enable it in Settings → Web search "
            "(this is the one feature that goes online).",
        )
    return str(config.get_preference("searxng_url", "") or "")


@router.get("/websearch/providers")
def web_search_providers() -> dict:
    """The engine choices, for the selector in Settings → Web search.

    Served rather than duplicated in the frontend so the list can't drift from
    what `search_web` will actually accept.
    """
    searxng_url, provider = websearch.settings_from(deps.get_config())
    return {
        "selected": provider,
        "searxng_url": searxng_url,
        "providers": [
            {"id": key, **value} for key, value in websearch.PROVIDERS.items()
        ],
    }


@router.get("/websearch")
def web_search(
    q: str,
    limit: int = Query(default=5, ge=1, le=20),
    session: Session = Depends(get_session),
) -> dict:
    """Opt-in web lookup through whichever engine the user chose."""
    _require_web_search()
    searxng, provider = websearch.settings_from(deps.get_config())
    try:
        results = websearch.search_web(
            q,
            # Matches this route's own `le=20` bound. Used to clamp to 10
            # regardless of what was asked for: both providers already fetch
            # one page and slice it (rows[:limit] / _parse_results(body,
            # limit)), so nothing about asking for up to 20 costs a second
            # request: the frontend's "show more" reveals the rest of what
            # was already fetched, not a second search.
            limit=max(1, min(limit, 20)),
            searxng_url=searxng or None,
            provider=provider,
        )
    except websearch.WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    manager.log_action(session, "web_searched", "chat", detail=q[:120])
    session.commit()
    # Which engine actually answered, not which one was asked for, under
    # "auto" those differ, and the difference is the interesting part. Resolved
    # even when nothing came back: "no results" is exactly when you want to
    # know who found nothing, and it is the case the panel used to go quiet.
    answered = results[0]["engine"] if results else ("searxng" if searxng else "duckduckgo")
    return {
        "query": q,
        "results": results,
        "provider": answered,
        "answered_by": websearch.answered_by(answered),
        "requested_provider": provider,
    }


@router.post("/websearch/detect-searxng")
def detect_searxng(url: str = "", session: Session = Depends(get_session)) -> dict:
    """Test a SearXNG URL, or scan the usual local ports for one.

    Saves the working URL to preferences so the user never has to know how the
    connection is wired up, if they have an instance running, this finds it.
    """
    from memorymap.search import websearch

    config = deps.get_config()
    if url:
        found = url.rstrip("/") if websearch.probe_searxng(url) else None
    else:
        found = websearch.discover_searxng()

    if not found:
        return {
            "found": False,
            "detail": "No SearXNG found. Start one (see the setup note) and try again.",
        }
    config.set_preference("searxng_url", found)
    websearch.clear_cache()  # results from the old provider are stale now
    manager.log_action(session, "edited", "preferences", detail=f"searxng_url={found}")
    session.commit()
    return {"found": True, "url": found}


@router.get("/websearch/searxng/status")
def searxng_status() -> dict:
    """Is a MemoryMap-managed SearXNG installed, running, and answering?"""
    from memorymap.search import searxng_manager

    data_dir = deps.get_config().data_dir
    return {
        **searxng_manager.status(data_dir),
        # What the instance itself last said. Its output used to go to
        # DEVNULL, which is why a failed start could only ever be guessed at.
        "output": searxng_manager.recent_output(data_dir),
    }


@router.post("/websearch/searxng/start")
def searxng_start(session: Session = Depends(get_session)) -> dict:
    """Run SearXNG for the user and switch web search over to it."""
    from memorymap.search import searxng_manager, websearch

    config = deps.get_config()
    try:
        # When nothing is installed yet, this kicks off a background install
        # that ends by starting SearXNG itself, the callback points web
        # search at it the moment it answers, with no second Start press.
        result = searxng_manager.start(
            config.data_dir,
            on_ready=lambda url: (
                config.set_preference("searxng_url", url),
                websearch.clear_cache(),
            ),
        )
    except searxng_manager.SearxngError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    config.set_preference("searxng_url", result["url"])
    websearch.clear_cache()
    manager.log_action(session, "edited", "preferences", detail="searxng started")
    session.commit()
    return {"running": True, **result}


@router.post("/websearch/searxng/reinstall")
def searxng_reinstall(session: Session = Depends(get_session)) -> dict:
    """Throw the SearXNG install away and build a fresh one.

    A part-finished install looks installed and dies on start, which reads as
    "it just doesn't work" with nothing to act on, and the only fix was to go
    and delete folders by hand.
    """
    from memorymap.search import searxng_manager

    config = deps.get_config()
    try:
        # The rebuilt SearXNG starts itself when the install lands; the
        # callback points web search back at it, so reinstall is one press.
        result = searxng_manager.reinstall_source(
            config.data_dir,
            on_ready=lambda url: (
                config.set_preference("searxng_url", url),
                websearch.clear_cache(),
            ),
        )
    except searxng_manager.SearxngError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    config.set_preference("searxng_url", "")  # nothing to point at until it's back
    websearch.clear_cache()
    manager.log_action(session, "edited", "preferences", detail="searxng reinstalled")
    session.commit()
    return result


@router.post("/websearch/searxng/stop")
def searxng_stop(session: Session = Depends(get_session)) -> dict:
    """Stop the managed instance and fall back to DuckDuckGo."""
    from memorymap.search import searxng_manager, websearch

    config = deps.get_config()
    try:
        result = searxng_manager.stop(config.data_dir)
    except searxng_manager.SearxngError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Point search back at DuckDuckGo so nothing tries the dead instance.
    config.set_preference("searxng_url", "")
    websearch.clear_cache()
    manager.log_action(session, "edited", "preferences", detail="searxng stopped")
    session.commit()
    return {"running": False, **result}


@router.get("/websearch/read")
def web_read(url: str, session: Session = Depends(get_session)) -> dict:
    """Fetch a page as plain readable text.

    Deliberately not an embedded browser: the page is stripped to text on the
    server, so no third-party script, tracker, or iframe ever runs in the app.
    """
    from memorymap.search import websearch

    _require_web_search()

    # A cheap shape check for a clean 400; the security check that matters is
    # in fetch_readable, which re-runs it on every redirect hop.
    #
    # There is deliberately NO host allowlist here. One was added briefly and
    # it only permitted the search engines themselves, but the reader exists
    # to open the *results*, which live on whatever site published them, so it
    # rejected every real page with "URL host is not allowed".
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only http(s) URLs are allowed")

    try:
        page = websearch.fetch_readable(url)
    except websearch.WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    manager.log_action(session, "web_read", "chat", detail=url[:120])
    session.commit()
    return page

