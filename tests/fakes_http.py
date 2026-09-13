"""A fake HTTP transport for the OpenAI-compatible provider (§6).

Split from `conftest.py` on a real distinction: **fixtures are discovered,
helpers are imported.** `capture_post` and `openai_client` are fixtures and
live in conftest, where pytest finds them by name with no import. `FakeResponse`
and `sse` are ordinary callables, so a test module has to import them, and
importing them from another *test* module (which is what this file replaces)
re-binds every name that import brings along, which is how `client` from
`test_providers` came to shadow conftest's own `client` fixture and silently
decide which HTTP client three files' tests were handed.
"""

from __future__ import annotations

import json


class FakeResponse:
    """Just enough `requests.Response` for the provider paths under test."""

    def __init__(self, *, lines=None, payload=None, status=200, text=""):
        self._lines = lines or []
        self._payload = payload
        self.status_code = status
        self.text = text

    @property
    def ok(self):
        """`requests.Response.ok`, real responses have it, so this must too.

        Added when a provider path started using it and this double did not
        model it, which surfaced as an AttributeError in a test rather than as
        the behaviour under test.
        """
        return self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload

    def iter_lines(self):
        for line in self._lines:
            yield line.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sse(*objects) -> list[str]:
    """The wire format: `data: {...}` lines, then the `[DONE]` sentinel."""
    return [f"data: {json.dumps(o)}" for o in objects] + ["data: [DONE]"]
