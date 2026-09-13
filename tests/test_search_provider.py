"""Settings → Web search: which engine answers is the user's choice.

Before this, the engine was inferred from whether a SearXNG address happened
to be filled in, and a SearXNG that failed silently sent the query to
DuckDuckGo instead: the exact engine somebody running their own instance is
trying not to use.
"""

from __future__ import annotations

import pytest

from memorymap.search import websearch


@pytest.fixture(autouse=True)
def _no_cached_results():
    websearch.clear_cache()
    yield
    websearch.clear_cache()


def _stub(monkeypatch, *, searxng=None, duckduckgo=None):
    """Replace one or both engines. A stub that isn't set raises, so a test
    that reaches the wrong engine fails loudly rather than passing quietly."""

    def unexpected(name):
        def call(*args, **kwargs):
            raise AssertionError(f"{name} should not have been asked")

        return call

    monkeypatch.setattr(
        websearch, "_search_searxng", searxng or unexpected("SearXNG")
    )
    monkeypatch.setattr(
        websearch, "_search_duckduckgo", duckduckgo or unexpected("DuckDuckGo")
    )


def _rows(engine):
    return lambda *a, **k: [
        {"title": "t", "url": "https://e.test/", "snippet": "", "domain": "e.test", "engine": engine}
    ]


# --- the choice itself ------------------------------------------------------


def test_unknown_provider_names_fall_back_to_the_default():
    """preferences.json is a file the user is invited to edit by hand."""
    assert websearch.normalise_provider("nonsense") == "auto"
    assert websearch.normalise_provider(None) == "auto"
    assert websearch.normalise_provider("SearXNG") == "searxng"  # case-insensitive


def test_duckduckgo_only_ignores_a_configured_searxng(monkeypatch):
    _stub(monkeypatch, duckduckgo=_rows("duckduckgo"))
    results = websearch.search_web(
        "q", searxng_url="http://localhost:8888", provider="duckduckgo"
    )
    assert results[0]["engine"] == "duckduckgo"


def test_searxng_only_never_falls_back(monkeypatch):
    """The whole point of picking it: a failure is reported, not routed to the
    engine the user was avoiding."""

    def dead(*args, **kwargs):
        raise websearch.WebSearchError("instance is down")

    _stub(monkeypatch, searxng=dead)
    with pytest.raises(websearch.WebSearchError, match="instance is down"):
        websearch.search_web("q", searxng_url="http://localhost:8888", provider="searxng")


def test_searxng_only_with_no_address_says_so(monkeypatch):
    _stub(monkeypatch)
    with pytest.raises(websearch.WebSearchError, match="no SearXNG address"):
        websearch.search_web("q", provider="searxng")


def test_auto_still_falls_back(monkeypatch):
    """The old behaviour is kept, and is still the default, it is just no
    longer the only behaviour."""

    def dead(*args, **kwargs):
        raise websearch.WebSearchError("instance is down")

    _stub(monkeypatch, searxng=dead, duckduckgo=_rows("duckduckgo"))
    results = websearch.search_web(
        "q", searxng_url="http://localhost:8888", provider="auto"
    )
    assert results[0]["engine"] == "duckduckgo"


def test_the_cache_is_keyed_by_provider(monkeypatch):
    """Switching engine must not hand back the previous engine's results."""
    _stub(monkeypatch, searxng=_rows("searxng"), duckduckgo=_rows("duckduckgo"))
    first = websearch.search_web("same", searxng_url="http://localhost:8888", provider="searxng")
    second = websearch.search_web("same", searxng_url="http://localhost:8888", provider="duckduckgo")
    assert first[0]["engine"] == "searxng"
    assert second[0]["engine"] == "duckduckgo"


# --- the settings screen behind it -----------------------------------------


def test_the_provider_list_is_served_rather_than_duplicated(client):
    """The frontend builds its radio buttons from this, so it cannot offer an
    engine the API would reject."""
    body = client.get("/websearch/providers").json()
    assert {p["id"] for p in body["providers"]} == set(websearch.PROVIDERS)
    assert body["selected"] == "auto"
    assert all(p["label"] and p["detail"] for p in body["providers"])


def test_the_choice_round_trips_through_preferences(client):
    saved = client.put("/preferences", json={"search_provider": "duckduckgo"})
    assert saved.status_code == 200
    assert saved.json()["search_provider"] == "duckduckgo"
    assert client.get("/websearch/providers").json()["selected"] == "duckduckgo"


def test_an_unknown_provider_is_rejected_at_the_door(client):
    """Rather than normalised away, which would silently ignore the request."""
    response = client.put("/preferences", json={"search_provider": "bing"})
    assert response.status_code == 422


def test_the_search_route_uses_the_chosen_engine(client, monkeypatch):
    seen = {}

    def fake(query, limit=5, searxng_url=None, provider="auto"):
        seen["provider"] = provider
        return []

    monkeypatch.setattr(websearch, "search_web", fake)
    client.put("/preferences", json={"web_search_enabled": True, "search_provider": "duckduckgo"})
    body = client.get("/websearch?q=anything").json()
    assert seen["provider"] == "duckduckgo"
    assert body["requested_provider"] == "duckduckgo"


def test_the_agent_tool_uses_the_same_choice(session, app_state, monkeypatch):
    """Two readers of one setting is how the tool ended up ignoring it."""
    from memorymap.ai import tools

    seen = {}

    def fake(query, limit=5, searxng_url=None, provider="auto"):
        seen["provider"] = provider
        return []

    monkeypatch.setattr(websearch, "search_web", fake)
    config = app_state
    config.set_preference("web_search_enabled", True)
    config.set_preference("search_provider", "duckduckgo")
    tools.execute_tool(session, "web_search", {"query": "anything"})
    assert seen["provider"] == "duckduckgo"


# --- the tool itself is gated the same way the endpoint is ---------------------


def test_websearch_tool_hidden_until_opted_in(client):
    from memorymap.ai import tools

    names = [t["function"]["name"] for t in tools.ollama_tools()]
    assert "web_search" not in names

    client.put("/preferences", json={"web_search_enabled": True})
    names = [t["function"]["name"] for t in tools.ollama_tools()]
    assert "web_search" in names


def test_websearch_tool_refuses_when_disabled(client, session):
    from memorymap.ai import tools

    # web_search is gated off until the online opt-in, routed through the
    # shared tool_enabled check → "turned off" message.
    result = tools.execute_tool(session, "web_search", {"query": "x"})
    assert "error" in result and "turned off" in result["error"]
