"""The page reader: HTML → structured blocks, and the SSRF guards on
`/websearch/read` (CodeQL findings: a search result must not be able to
make the app fetch its own network)."""

from __future__ import annotations


def test_reader_strips_scripts_and_markup():
    from memorymap.search import websearch

    page = """
    <html><head><title>A Page</title></head>
    <body><script>alert('x')</script><style>p{color:red}</style>
    <h1>Heading</h1><p>First para.</p><p>Second para.</p></body></html>
    """
    text = websearch._readable_text(page)
    assert "alert" not in text and "color:red" not in text
    assert "Heading" in text and "First para." in text
    assert websearch._page_title(page) == "A Page"


def test_reader_returns_structured_blocks():
    """Headings, paragraphs and list items come back separately so the reader
    can lay a page out instead of dumping one wall of text."""
    from memorymap.search import websearch

    page = """
    <html><head><title>Doc</title></head><body>
      <nav>Home Login Subscribe</nav>
      <article>
        <h2>Getting started</h2>
        <p>First paragraph of the article.</p>
        <ul><li>Point one</li><li>Point two</li></ul>
        <p>Closing thoughts.</p>
      </article>
      <footer>Cookie notice</footer>
    </body></html>
    """
    blocks = websearch._readable_blocks(page)
    kinds = [b["type"] for b in blocks]
    texts = [b["text"] for b in blocks]
    assert "heading" in kinds and "li" in kinds
    assert "Getting started" in texts
    assert "Point one" in texts
    # Nav and footer furniture is dropped.
    assert not any("Login" in t or "Cookie" in t for t in texts)


def test_reader_endpoint_requires_opt_in_and_http(client):
    assert client.get("/websearch/read?url=https://example.com").status_code == 403
    client.put("/preferences", json={"web_search_enabled": True})
    # Not a fetchable URL at all, so it's rejected as a bad request rather than
    # attempted and reported as a bad gateway.
    assert client.get("/websearch/read?url=file:///etc/passwd").status_code == 400


def test_reader_opens_an_ordinary_result_page(client, monkeypatch):
    """The reader's whole job is opening results, which live on any site.

    Guards this against the host allowlist that briefly shipped and rejected
    every real page, since the engines it allowed are never where results are.
    """
    from memorymap.search import websearch

    monkeypatch.setattr(
        websearch,
        "fetch_readable",
        lambda url: {"title": "A post", "url": url, "blocks": [], "text": "hello"},
    )
    client.put("/preferences", json={"web_search_enabled": True})
    response = client.get("/websearch/read?url=https://en.wikipedia.org/wiki/Cat")
    assert response.status_code == 200
    assert response.json()["title"] == "A post"


# --- outbound-request guards (CodeQL SSRF findings) ---------------------------


def test_reader_refuses_a_link_that_points_at_this_machine(client, monkeypatch):
    """A search result must not be able to make the app fetch localhost."""
    from memorymap.search import websearch

    def boom(*args, **kwargs):  # pragma: no cover: must never be reached
        raise AssertionError("the guard should have stopped this request")

    monkeypatch.setattr(websearch.requests, "get", boom)
    client.put("/preferences", json={"web_search_enabled": True})
    response = client.get("/websearch/read?url=http://127.0.0.1:8080/admin")
    assert response.status_code == 502
    assert "local address" in response.json()["detail"]


def test_reader_refuses_a_url_carrying_credentials(client, monkeypatch):
    """"http://ok.example@evil.example/" reads as one host and resolves to another."""
    from memorymap.search import websearch

    def boom(*args, **kwargs):  # pragma: no cover: must never be reached
        raise AssertionError("the guard should have stopped this request")

    monkeypatch.setattr(websearch.requests, "get", boom)
    client.put("/preferences", json={"web_search_enabled": True})
    response = client.get("/websearch/read?url=http://example.com@127.0.0.1/")
    assert response.status_code == 502


def test_reader_refuses_a_redirect_into_the_local_network(client, monkeypatch):
    """A public page must not be able to 302 the app onto localhost."""
    from memorymap.search import websearch

    seen = []

    class FakeResponse:
        def __init__(self, url):
            self.is_redirect = True
            self.is_permanent_redirect = False
            self.headers = {"location": "http://127.0.0.1:11434/api/tags"}
            self.url = url

        def close(self):
            pass

    class FakeSession:
        def get(self, url, **kwargs):
            seen.append((url, kwargs.get("headers", {}).get("Host")))
            return FakeResponse(url)

        def mount(self, prefix, adapter):
            pass

        def close(self):
            pass

    monkeypatch.setattr(websearch, "_private_session", FakeSession)
    client.put("/preferences", json={"web_search_enabled": True})
    response = client.get("/websearch/read?url=https://example.com/post")
    assert response.status_code == 502
    assert "local address" in response.json()["detail"]
    # One hop was fetched and the redirect target never was. The fetched URL
    # carries the resolved IP rather than the hostname, each hop connects to
    # the address that passed the check, so a nameserver can't answer the
    # check and the connection differently (DNS rebinding).
    assert len(seen) == 1
    fetched_url, host_header = seen[0]
    assert host_header == "example.com"
    assert "example.com" not in fetched_url
