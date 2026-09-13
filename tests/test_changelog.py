"""CHANGELOG.md, readable inside the app (roadmap §36E).

Asked for: "a way to view application changelogs by accessing the changelog.md
file or smth". Serving the file is the whole point, the alternative is a
second in-app list that says roughly the same things and drifts from the real
one within a release.

Small, and it makes the app feel maintained rather than static: the version
number was already in Settings → About with nothing behind it.
"""

from __future__ import annotations


def test_the_changelog_is_served(client):
    body = client.get("/changelog").json()
    assert body["markdown"].startswith("# Changelog")


def test_it_is_the_real_file_not_a_copy(client):
    """If this ever diverges, someone has started maintaining a second list, 
    which is exactly what serving the file exists to prevent."""
    from pathlib import Path

    on_disk = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    assert client.get("/changelog").json()["markdown"] == on_disk


def test_a_missing_file_is_not_an_error(client, monkeypatch):
    """A packaged build may not ship it. Missing release notes are not worth a
    500: the About panel hides the control instead."""
    import memorymap.api.app as app_module

    real_read = type(app_module.Path("x")).read_text

    def explode(self, *args, **kwargs):
        if self.name == "CHANGELOG.md":
            raise OSError("not packaged")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(type(app_module.Path("x")), "read_text", explode)
    response = client.get("/changelog")
    assert response.status_code == 200
    assert response.json()["markdown"] == ""
