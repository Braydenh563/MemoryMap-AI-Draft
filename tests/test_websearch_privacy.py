"""Web search is the one feature that leaves the machine, so what it sends
matters as much as what it returns.

Asked for directly: make it as untraceable as possible. None of this is a
guarantee, a header is a request, not a control, but a request that
identifies the exact application, or that carries the click id a marketing
campaign put in the link, is traceable by construction.
"""

from __future__ import annotations

import ipaddress

import pytest

from memorymap.search import websearch


# --- what we send ------------------------------------------------------------------


def test_the_user_agent_does_not_announce_this_app():
    """It used to be "MemoryMapAI/0.1 (personal notebook)", a near-unique
    fingerprint linking every site visited back to one piece of software."""
    agent = websearch.PRIVACY_HEADERS["User-Agent"]
    for giveaway in ["MemoryMap", "memorymap", "notebook"]:
        assert giveaway not in agent
    assert agent.startswith("Mozilla/5.0")


def test_every_request_carries_the_same_privacy_headers():
    headers = websearch.PRIVACY_HEADERS
    assert headers["DNT"] == "1"
    assert headers["Sec-GPC"] == "1"
    # Where you came from is nobody's business.
    assert headers["Referer"] == ""
    # A specific locale narrows you down; a generic one doesn't.
    assert headers["Accept-Language"] == "en-US,en;q=0.9"


def test_searxng_probe_keeps_the_privacy_headers_and_pins_the_host():
    """The probe overrides Host to pin the address, it must not lose the rest."""
    target = websearch._searxng_target("http://127.0.0.1:8888")
    assert target is not None
    url, headers = target
    assert headers["User-Agent"] == websearch.PRIVACY_HEADERS["User-Agent"]
    assert headers["DNT"] == "1"
    assert headers["Host"] == "127.0.0.1:8888"
    # The URL requests is given is the checked address, not the name.
    assert url == "http://127.0.0.1:8888/search"


def test_a_searxng_address_that_is_not_local_is_refused():
    """The one rule that makes the SearXNG path safe: it can only reach you."""
    assert websearch._searxng_target("http://93.184.216.34:8888") is None
    assert websearch._searxng_target("ftp://127.0.0.1:8888") is None
    # Credentials make an address read as one host and resolve as another.
    assert websearch._searxng_target("http://127.0.0.1@93.184.216.34/") is None


def test_a_nonsense_searxng_port_is_refused_rather_than_raising():
    """A bad preference must come back as "no", not as a 500 from Settings."""
    assert websearch._searxng_target("http://127.0.0.1:99999") is None
    assert websearch._searxng_target("http://127.0.0.1:notaport") is None


# --- what we strip out of links ------------------------------------------------------


def test_tracking_parameters_are_removed():
    cleaned = websearch.strip_tracking(
        "https://example.com/article?utm_source=news&utm_campaign=spring&id=7&fbclid=xyz"
    )
    assert "utm_source" not in cleaned
    assert "utm_campaign" not in cleaned
    assert "fbclid" not in cleaned
    # The parameters the page actually needs survive.
    assert "id=7" in cleaned


def test_a_url_with_nothing_to_strip_comes_back_byte_for_byte():
    """Rewriting a URL that needed no change risks breaking it for nothing."""
    for url in [
        "https://example.com/article?id=7&page=2",
        "https://example.com/plain",
        "https://example.com/",
    ]:
        assert websearch.strip_tracking(url) == url


def test_stripping_never_throws_on_junk():
    for value in ["", "not a url", "http://", "://///"]:
        assert isinstance(websearch.strip_tracking(value), str)


def test_a_link_that_is_only_tracking_still_resolves():
    cleaned = websearch.strip_tracking("https://example.com/page?utm_source=x")
    assert cleaned.startswith("https://example.com/page")
    assert "utm_source" not in cleaned


def test_duckduckgo_redirect_wrappers_are_unwrapped_and_cleaned():
    """DDG wraps every result; the real URL underneath still carries whatever
    campaign tags the destination site put in it."""
    wrapped = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%3Futm_source%3Dddg%26id%3D3"
    real = websearch._real_url(wrapped)
    assert real.startswith("https://example.com/a")
    assert "utm_source" not in real
    assert "id=3" in real


def test_results_parsed_from_a_page_come_back_without_tracking():
    """End to end through the parser, since that's the path results take."""
    page = """
      <a class="result__a" href="https://example.com/x?utm_medium=cpc&amp;q=1">A title</a>
      <a class="result__snippet">A snippet</a>
    """
    results = websearch._parse_results(page, limit=5)
    assert results, "the parser found nothing to check"
    assert "utm_medium" not in results[0]["url"]
    assert "q=1" in results[0]["url"]


# --- how the page is handed back -----------------------------------------------------


def test_headings_keep_their_depth():
    """Flattening h1..h6 into one "heading" threw away the page's outline,
    which is what tells you where you are in a long article."""
    page = """
      <article>
        <h1>The title</h1>
        <p>Opening paragraph with enough words to survive the junk filter.</p>
        <h2>A section</h2>
        <p>More prose here, again long enough to count as content.</p>
        <h3>A subsection</h3>
        <p>Yet more prose, so the block survives.</p>
      </article>
    """
    blocks = websearch._readable_blocks(page)
    headings = [b for b in blocks if b["type"] == "heading"]
    assert [h["level"] for h in headings] == [1, 2, 3]
    assert [h["text"] for h in headings] == ["The title", "A section", "A subsection"]
    # Non-headings don't carry a level.
    assert all("level" not in b for b in blocks if b["type"] != "heading")


# --- what we connect to --------------------------------------------------------------
# Headers and link-stripping cover what a site learns about you. These cover a
# different risk: being made to fetch something on your own machine.


def test_a_search_session_starts_with_an_empty_cookie_jar():
    """Cookies are the other half of correlation, they link one query to the
    next regardless of how careful the headers are."""
    session = websearch._private_session()
    try:
        assert len(session.cookies) == 0
        assert session.headers["User-Agent"] == websearch.USER_AGENT
        # trust_env must stay on: it is how someone's own proxy (Tor, a VPN)
        # and the system CA bundle reach requests at all. Disabling it would
        # look like a privacy win and be the opposite.
        assert session.trust_env is True
    finally:
        session.close()


def test_pin_url_swaps_in_the_checked_address_and_keeps_the_host():
    """The connection has to go to the address that passed the check.

    Resolving once for the check and again for the connection leaves a window
    where a hostile nameserver answers the two differently (DNS rebinding).
    """
    pinned, host = websearch._pin_url(
        "https://example.com/page", ipaddress.ip_address("93.184.216.34")
    )
    assert pinned == "https://93.184.216.34:443/page"
    assert host == "example.com"


def test_pin_url_brackets_ipv6_and_keeps_an_explicit_port():
    pinned, host = websearch._pin_url(
        "http://example.com:8080/p",
        ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946"),
    )
    assert pinned.startswith("http://[2606:2800:220:1:248:1893:25c8:1946]:8080/")
    assert host == "example.com:8080"


def test_assert_external_hands_back_the_addresses_it_validated(monkeypatch):
    monkeypatch.setattr(
        websearch,
        "_host_addresses",
        lambda host: [ipaddress.ip_address("93.184.216.34")],
    )
    assert websearch._assert_external("https://example.com/") == [
        ipaddress.ip_address("93.184.216.34")
    ]


def test_assert_external_still_refuses_local_addresses(monkeypatch):
    monkeypatch.setattr(
        websearch, "_host_addresses", lambda host: [ipaddress.ip_address("127.0.0.1")]
    )
    with pytest.raises(websearch.WebSearchError, match="local address"):
        websearch._assert_external("http://sneaky.example/")


# --- reading a page for the model ------------------------------------------------------


def test_read_url_is_hidden_until_web_search_is_enabled(app_state):
    """It reaches the internet, so it lives behind the same opt-in as search."""
    from memorymap.ai import tools

    assert tools.tool_enabled("read_url") is False
    assert "read_url" not in {t["function"]["name"] for t in tools.ollama_tools()}


def test_read_url_returns_the_page_text(app_state, session, monkeypatch):
    """The tool behind "Ask about this". Without it the model is handed a URL
    it cannot open, and answers from the address alone."""
    from memorymap.ai import tools
    from memorymap.core import deps

    deps.get_config().set_preference("web_search_enabled", True)
    monkeypatch.setattr(
        websearch,
        "fetch_readable",
        lambda url: {
            "url": url,
            "domain": "example.com",
            "title": "A post",
            "text": "The readable body of the page.",
            "blocks": [],
        },
    )
    result = tools.execute_tool(session, "read_url", {"url": "https://example.com/a"})
    assert result["title"] == "A post"
    assert result["text"] == "The readable body of the page."
    assert result["truncated"] is False
    # Compared whole rather than as a substring: `"example.com" in label` also
    # passes for "example.com.evil.test", which is the shape of check this
    # codebase must never learn by habit.
    assert result["domain"] == "example.com"
    assert result["label"] == "ph:book-open Read example.com"


def test_read_url_says_when_it_only_read_part_of_a_page(app_state, session, monkeypatch):
    """A truncated page reported as whole is how a model confidently answers
    from an article it only saw the top of."""
    from memorymap.ai import tools
    from memorymap.core import deps

    deps.get_config().set_preference("web_search_enabled", True)
    long_page = "x" * (tools.READ_URL_MAX_CHARS + 500)
    monkeypatch.setattr(
        websearch,
        "fetch_readable",
        lambda url: {
            "url": url, "domain": "example.com", "title": "Long",
            "text": long_page, "blocks": [],
        },
    )
    result = tools.execute_tool(session, "read_url", {"url": "https://example.com/a"})
    assert len(result["text"]) == tools.READ_URL_MAX_CHARS
    assert result["truncated"] is True
    assert result["note"]


def test_read_url_reports_a_refused_address_to_the_model(app_state, session, monkeypatch):
    from memorymap.ai import tools
    from memorymap.core import deps

    deps.get_config().set_preference("web_search_enabled", True)

    def boom(url):
        raise websearch.WebSearchError("That link points at a local address")

    monkeypatch.setattr(websearch, "fetch_readable", boom)
    result = tools.execute_tool(session, "read_url", {"url": "http://127.0.0.1/"})
    # An error comes back as data the model can act on, never as a crash.
    assert "local address" in result["error"]


# --- the same guard, one layer up: probing/searching a configured SearXNG -----
#
# (test_a_searxng_address_that_is_not_local_is_refused above covers the lower-
# level `_searxng_target` helper; these cover `probe_searxng`/`_search_searxng`,
# which call it.)


def test_searxng_probe_rejects_a_public_address(monkeypatch):
    """SearXNG is self-hosted, so a public URL is refused rather than probed."""

    def boom(*args, **kwargs):  # pragma: no cover: must never be reached
        raise AssertionError("the guard should have stopped this request")

    monkeypatch.setattr(websearch.requests, "get", boom)
    assert websearch.probe_searxng("https://searx.example.com") is False
    assert websearch.probe_searxng("not-a-url") is False


def test_searxng_search_rejects_a_public_address():
    with pytest.raises(websearch.WebSearchError, match="this machine or your own network"):
        websearch._search_searxng("anything", 5, "https://searx.example.com")


def test_searxng_probe_still_allows_localhost(monkeypatch):
    """The guard must not break the instance the app itself starts."""

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"results": []}

    monkeypatch.setattr(websearch.requests, "get", lambda *a, **k: FakeResponse())
    assert websearch.probe_searxng("http://localhost:8888") is True
