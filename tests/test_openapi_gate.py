"""The API schema is behind the unlock, and the CDN doc pages are gone.

MODERNISATION_AUDIT.md D5: `/openapi.json`, every route, parameter and model
name: was served to anyone who could reach the port, before the unlock; the
one security finding in that audit not already handled. `/docs` and `/redoc`
load their scripts from a CDN this offline app's CSP refuses, so they never
rendered and are not mounted at all now.
"""

from __future__ import annotations


def _setup(client, password="first-pass"):
    token = client.post("/auth/setup", json={"password": password}).json()["token"]
    return {"X-Auth-Token": token}


def test_the_schema_needs_the_unlock(client):
    _setup(client)
    assert client.get("/openapi.json").status_code == 401


def test_the_schema_is_served_once_unlocked(client):
    headers = _setup(client)
    response = client.get("/openapi.json", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["info"]["title"] == "MemoryMap AI"
    assert "/entries" in body["paths"]
    # The gate itself is not in the document it gates.
    assert "/openapi.json" not in body["paths"]


def test_the_cdn_doc_pages_are_not_mounted(client):
    headers = _setup(client)
    for path in ("/docs", "/redoc"):
        assert client.get(path, headers=headers).status_code == 404, path
