"""The /websearch endpoint itself: opt-in gate, DuckDuckGo parsing, the
SearXNG hand-off and fallback, result caching, and detecting an instance
already running.

(Which provider preference wins is test_search_provider.py's job; explaining
*why* a search came back empty is test_websearch_diagnosis.py's; this file
is the happy-path plumbing underneath both.)
"""

from __future__ import annotations

from memorymap.search import websearch

FAKE_DDG_PAGE = """
<div class="result">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fbrisbane&amp;rut=abc">Brisbane &amp; weather</a>
  <a class="result__snippet" href="#">It is <b>sunny</b> today.</a>
</div>
"""


def test_websearch_disabled_by_default(client):
    response = client.get("/websearch?q=anything")
    assert response.status_code == 403
    assert "Settings" in response.json()["detail"]


def test_websearch_enabled_returns_parsed_results(client, monkeypatch):
    client.put("/preferences", json={"web_search_enabled": True})
    monkeypatch.setattr(
        websearch,
        "search_web",
        lambda q, limit=5, searxng_url=None, provider="auto": websearch._parse_results(
            FAKE_DDG_PAGE, limit
        ),
    )
    body = client.get("/websearch?q=brisbane weather").json()
    assert body["results"] == [
        {
            "title": "Brisbane & weather",
            "url": "https://example.com/brisbane",
            "snippet": "It is sunny today.",
            "domain": "example.com",
            "engine": "duckduckgo",
        }
    ]
    assert body["provider"] == "duckduckgo"


def test_websearch_passes_through_up_to_the_route_s_own_cap(client, monkeypatch):
    """Used to silently clamp to 10 regardless of what was asked for, so the
    frontend's "show more" (up to 20, one request) had nothing extra to
    reveal. Both providers already fetch one page and slice it, so nothing
    stops asking for the route's full `le=20` bound in one call."""
    client.put("/preferences", json={"web_search_enabled": True})
    seen_limits = []

    def fake_search_web(q, limit=5, searxng_url=None, provider="auto"):
        seen_limits.append(limit)
        return []

    monkeypatch.setattr(websearch, "search_web", fake_search_web)
    client.get("/websearch?q=brisbane&limit=20")
    assert seen_limits == [20]


def test_ddg_parser_has_a_backup_pattern():
    """If the primary result markup disappears, the looser pattern still works."""
    websearch.clear_cache()
    changed_markup = """
    <div class="results">
      <a href="/l/?uddg=https%3A%2F%2Fexample.org%2Fdocs" class="result-link">Docs</a>
      <td class="result-snippet">Some helpful text.</td>
    </div>
    """
    parsed = websearch._parse_results(changed_markup, 5)
    assert parsed[0]["url"] == "https://example.org/docs"
    assert parsed[0]["snippet"] == "Some helpful text."


def test_searxng_is_used_when_configured(client, monkeypatch):
    websearch.clear_cache()
    client.put(
        "/preferences",
        json={"web_search_enabled": True, "searxng_url": "http://localhost:8888"},
    )

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Self-hosted result",
                        "url": "https://example.net/page",
                        "content": "From my own instance.",
                    }
                ]
            }

    captured = {}

    # Searches now go through a throwaway private session (no cookie jar, no
    # identifying User-Agent) and use POST so the query stays out of the
    # request line, so the fake stands in for the session rather than for
    # requests.get.
    class FakeSession:
        def post(self, url, data=None, headers=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers or {}
            return FakeResponse()

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(websearch, "_private_session", FakeSession)
    body = client.get("/websearch?q=hello").json()
    # The request goes to the address the guard checked, not to the name, 
    # re-resolving between the check and the connection is the rebinding hole
    # the reader path already closed. `localhost` can be 127.0.0.1 or ::1
    # depending on the machine, so assert the shape rather than one of them.
    import ipaddress
    from urllib.parse import urlparse

    pinned = urlparse(captured["url"])
    assert pinned.path == "/search"
    assert pinned.port == 8888
    assert ipaddress.ip_address(pinned.hostname).is_loopback
    # …and TLS/vhost routing still sees the name the user configured.
    assert captured["headers"]["Host"] == "localhost:8888"
    assert captured["data"]["format"] == "json"
    assert captured["closed"] is True  # the session must not be kept around
    assert body["provider"] == "searxng"
    assert body["results"][0]["domain"] == "example.net"
    assert body["results"][0]["engine"] == "searxng"


def test_searxng_failure_falls_back_to_duckduckgo(client, monkeypatch):
    websearch.clear_cache()
    client.put(
        "/preferences",
        json={"web_search_enabled": True, "searxng_url": "http://localhost:8888"},
    )

    class DeadSession:
        def post(self, *args, **kwargs):
            raise websearch.requests.RequestException("instance is down")

        def close(self):
            pass

    monkeypatch.setattr(websearch, "_private_session", DeadSession)
    monkeypatch.setattr(
        websearch, "_search_duckduckgo", lambda q, limit: websearch._parse_results(FAKE_DDG_PAGE, limit)
    )
    body = client.get("/websearch?q=anything").json()
    # SearXNG failing must not break search, DuckDuckGo answers instead.
    assert body["results"][0]["engine"] == "duckduckgo"


def test_websearch_results_are_cached_briefly(monkeypatch):
    websearch.clear_cache()
    calls = []

    def counted(query, limit):
        calls.append(query)
        return websearch._parse_results(FAKE_DDG_PAGE, limit)

    monkeypatch.setattr(websearch, "_search_duckduckgo", counted)
    websearch.search_web("same query")
    websearch.search_web("same query")
    assert len(calls) == 1  # second one served from cache
    websearch.clear_cache()


# --- detecting an instance already running --------------------------------------


def test_searxng_detection_saves_the_url(client, monkeypatch):
    client.put("/preferences", json={"web_search_enabled": True})
    monkeypatch.setattr(
        websearch, "discover_searxng", lambda: "http://localhost:8888"
    )
    body = client.post("/websearch/detect-searxng").json()
    assert body == {"found": True, "url": "http://localhost:8888"}
    assert client.get("/preferences").json()["searxng_url"] == "http://localhost:8888"


def test_searxng_detection_reports_when_absent(client, monkeypatch):
    client.put("/preferences", json={"web_search_enabled": True})
    monkeypatch.setattr(websearch, "discover_searxng", lambda: None)
    body = client.post("/websearch/detect-searxng").json()
    assert body["found"] is False
    assert "No SearXNG" in body["detail"]
