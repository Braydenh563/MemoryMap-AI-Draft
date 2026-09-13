"""[[wiki links]]: build a web of notes without AI, a dialog, or the mouse."""

from __future__ import annotations

from memorymap.entry import manager


def _make(client, content):
    return client.post("/entries", json={"content": content}).json()


def test_parsing_finds_names_once_each():
    found = manager.wiki_link_targets("see [[bread]] and [[Kayaking]] and [[bread]]")
    assert found == ["bread", "Kayaking"]


def test_parsing_ignores_empty_brackets():
    assert manager.wiki_link_targets("[[]] and [[   ]]") == []
    assert manager.wiki_link_targets("no links at all") == []


def test_a_wiki_link_creates_a_real_link(client):
    target = _make(client, "bread proving times vary")
    source = _make(client, "reminder: check [[bread proving]] before baking")

    linked = client.get(f"/entries/{source['id']}").json()["links"]
    assert [link["entry_id"] for link in linked] == [target["id"]]


def test_the_link_is_visible_from_both_ends(client):
    target = _make(client, "kayaking trip in March")
    source = _make(client, "pack the roof rack for [[kayaking]]")

    from_target = client.get(f"/entries/{target['id']}").json()["links"]
    assert [link["entry_id"] for link in from_target] == [source["id"]]


def test_an_exact_match_wins_over_a_longer_note(client):
    exact = _make(client, "bread")
    _make(client, "bread proving times vary")
    source = _make(client, "see [[bread]]")

    linked = client.get(f"/entries/{source['id']}").json()["links"]
    assert [link["entry_id"] for link in linked] == [exact["id"]]


def test_a_link_to_nothing_does_not_break_the_save(client):
    """You often write the link before the note it points at."""
    response = client.post("/entries", json={"content": "todo: write [[the thing]] up"})
    assert response.status_code == 201
    assert response.json()["links"] == []


def test_a_note_cannot_link_to_itself(client):
    source = _make(client, "recursion is when [[recursion]] happens")
    assert client.get(f"/entries/{source['id']}").json()["links"] == []


def test_editing_a_note_resolves_new_links(client):
    target = _make(client, "sourdough starter care")
    source = _make(client, "a plain note")
    client.put(f"/entries/{source['id']}", json={"content": "now mentions [[sourdough]]"})

    linked = client.get(f"/entries/{source['id']}").json()["links"]
    assert [link["entry_id"] for link in linked] == [target["id"]]


def test_private_notes_are_not_link_targets(client, session):
    """A link would reveal that a private note exists, and what it's called."""
    from memorymap.core import vault

    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()

    secret = _make(client, "secret plans for the party")
    client.post(f"/entries/{secret['id']}/privacy", json={"private": True})

    source = _make(client, "see [[secret plans]]")
    assert client.get(f"/entries/{source['id']}").json()["links"] == []
    vault.close()


def test_binned_notes_are_not_link_targets(client):
    target = _make(client, "an old note about pears")
    client.delete(f"/entries/{target['id']}")
    source = _make(client, "see [[an old note]]")
    assert client.get(f"/entries/{source['id']}").json()["links"] == []


def test_nested_brackets_resolve_to_the_inner_name():
    """Documents the parser's behaviour, which the UI is built to avoid hitting.

    A name can't contain brackets, so "[[outer [[inner]] text]]" matches the
    inner one. That's why the autocomplete strips brackets out of a note's text
    before inserting it as a link name, otherwise picking a note that itself
    contains a link would silently point somewhere else entirely.
    """
    assert manager.wiki_link_targets("[[outer [[inner]] text]]") == ["inner"]


def test_a_name_is_capped_so_a_whole_note_cannot_become_one():
    long_name = "x" * 200
    assert manager.wiki_link_targets(f"[[{long_name}]]") == []


def test_link_previews_do_not_show_the_bracket_syntax(client):
    """The [[ ]] is scaffolding; a link chip reading "[[bread]]" is just noise."""
    _make(client, "bread proving times vary")
    source = _make(client, "check [[bread proving]] before baking")

    preview = client.get(f"/entries/{source['id']}").json()["links"][0]["preview"]
    assert "[[" not in preview and "]]" not in preview
