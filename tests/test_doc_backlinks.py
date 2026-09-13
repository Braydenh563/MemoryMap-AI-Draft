"""Backlinks with context, and unlinked mentions (DOCUMENTS_PLAN Phase 4.1).

The panel this feeds used to list the *titles* of the notes that link here.
Two things make that knowledge rather than a lookup, and both are measured
here rather than in a browser, because both are string work:

- the sentence around the link, with the hit's own offsets inside it, so the
  browser marks the occurrence that matched and not the first one that looks
  like it;
- the mentions that are not links yet, which is the half a title list cannot
  express at all.

The offsets are the part worth a test of its own: they are also what the
"Link" action writes over, so an off-by-one here is a sentence of somebody's
note replaced with a wiki link.
"""

from __future__ import annotations


def _document(client, title, content=""):
    response = client.post("/documents", json={"title": title, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


def _note(client, content):
    response = client.post("/entries", json={"content": content})
    assert response.status_code in (200, 201), response.text
    return response.json()


def _backlinks(client, document_id):
    response = client.get(f"/documents/{document_id}/backlinks")
    assert response.status_code == 200, response.text
    return response.json()


def _marked(row):
    """The text the browser would mark, read back out of the row's offsets."""
    return row["context"][row["hit_start"] : row["hit_end"]]


def test_a_linked_mention_arrives_with_the_sentence_it_sits_in(client):
    target = _document(client, "Design system notes")
    _document(
        client,
        "Weekly review",
        "Monday was quiet. I finally read [[Design system notes]] end to end. "
        "Tuesday was not.",
    )
    body = _backlinks(client, target["id"])
    assert len(body["links"]) == 1
    row = body["links"][0]
    assert row["kind"] == "document"
    assert row["title"] == "Weekly review"
    assert row["context"] == "I finally read [[Design system notes]] end to end."
    assert _marked(row) == "[[Design system notes]]"
    assert body["mentions"] == []


def test_a_note_that_links_here_is_a_backlink_too(client):
    target = _document(client, "Roadmap")
    _note(client, "# Standup\n\nAgreed the order in [[Roadmap]] is right.")
    body = _backlinks(client, target["id"])
    assert [row["kind"] for row in body["links"]] == ["note"]
    assert body["links"][0]["title"] == "Standup"
    assert body["links"][0]["context"] == "Agreed the order in [[Roadmap]] is right."


def test_an_unlinked_mention_is_found_and_kept_apart_from_the_links(client):
    target = _document(client, "Design system notes")
    _note(client, "The design system notes say to use one radius everywhere.")
    body = _backlinks(client, target["id"])
    assert body["links"] == []
    assert len(body["mentions"]) == 1
    row = body["mentions"][0]
    assert _marked(row) == "design system notes", "the hit is the text as written"
    assert row["kind"] == "note"


def test_a_source_that_already_links_is_not_also_an_unlinked_mention(client):
    """The second list means "not connected yet". A source in both lists says
    the opposite of what each list is for."""
    target = _document(client, "Design system notes")
    _note(
        client,
        "See [[Design system notes]]. The design system notes are the source of truth.",
    )
    body = _backlinks(client, target["id"])
    assert len(body["links"]) == 1
    assert body["mentions"] == []


def test_a_mention_inside_a_wider_wiki_link_is_not_a_mention(client):
    """No lookaround can see this one: `[[Roadmap for 2027]]` contains the
    title but is a link to something else."""
    target = _document(client, "Roadmap")
    _note(client, "Filed under [[Roadmap for 2027]] for now.")
    body = _backlinks(client, target["id"])
    assert body["links"] == []
    assert body["mentions"] == []


def test_a_longer_word_that_merely_starts_with_the_title_is_not_a_mention(client):
    target = _document(client, "Roadmap")
    _note(client, "The roadmaps are all out of date.")
    assert _backlinks(client, target["id"])["mentions"] == []


def test_a_short_title_is_never_hunted_as_an_unlinked_mention(client):
    """"AI" would match a third of a notebook. A real `[[AI]]` still resolves:
    the guard is on one half of the panel, not on both."""
    target = _document(client, "AI")
    _note(client, "Everything about AI is moving fast.")
    _note(client, "Filed under [[AI]] today.")
    body = _backlinks(client, target["id"])
    assert body["mentions"] == []
    assert len(body["links"]) == 1


def test_the_offsets_point_into_the_source_so_a_link_action_can_rewrite_it(client):
    target = _document(client, "Design system notes")
    text = "Read the design system notes when you get a moment."
    note = _note(client, text)
    row = _backlinks(client, target["id"])["mentions"][0]
    assert text[row["start"] : row["end"]] == "design system notes"
    rewritten = text[: row["start"]] + "[[Design system notes]]" + text[row["end"] :]
    updated = client.put(f"/entries/{note['id']}", json={"content": rewritten})
    assert updated.status_code == 200, updated.text
    body = _backlinks(client, target["id"])
    assert body["mentions"] == []
    assert len(body["links"]) == 1


def test_a_hit_at_the_very_start_of_a_paragraph_keeps_its_own_marker(client):
    """The left edge is tidied of `#` and `- `, but never past the hit: a
    mention that *is* the heading would otherwise lose itself with the hash."""
    target = _document(client, "Roadmap")
    _document(client, "Plans", "# Roadmap thoughts\n\nNothing yet.")
    row = _backlinks(client, target["id"])["mentions"][0]
    assert row["context"] == "Roadmap thoughts"
    assert _marked(row) == "Roadmap"


def test_a_bullet_loses_its_bullet_and_keeps_its_sentence(client):
    target = _document(client, "Roadmap")
    _document(client, "Plans", "Things to do:\n\n- ask about the roadmap first\n")
    row = _backlinks(client, target["id"])["mentions"][0]
    assert row["context"] == "ask about the roadmap first"
    assert _marked(row) == "roadmap"


def test_a_long_paragraph_is_cut_with_an_ellipsis_at_both_ends(client):
    target = _document(client, "Roadmap")
    filler = "word " * 80
    _document(client, "Long", f"{filler}the roadmap matters {filler}")
    row = _backlinks(client, target["id"])["mentions"][0]
    assert row["context"].startswith("…")
    assert row["context"].endswith("…")
    assert _marked(row) == "roadmap"
    assert len(row["context"]) < 400


def test_a_sentence_that_ends_on_its_own_gets_no_ellipsis(client):
    target = _document(client, "Roadmap")
    _document(client, "Short", "One sentence. The roadmap is here. Another sentence.")
    row = _backlinks(client, target["id"])["mentions"][0]
    assert row["context"] == "The roadmap is here."


def test_many_hits_in_one_source_are_capped(client):
    target = _document(client, "Roadmap")
    _document(client, "Repetitive", "\n".join(f"The roadmap again, line {n}." for n in range(9)))
    rows = _backlinks(client, target["id"])["mentions"]
    assert len(rows) == 3, "a source that says one thing nine times has said one thing"


def test_the_document_never_backlinks_to_itself(client):
    target = _document(client, "Roadmap", "The roadmap explains itself, see [[Roadmap]].")
    body = _backlinks(client, target["id"])
    assert body["links"] == []
    assert body["mentions"] == []


def test_a_private_note_is_never_a_backlink(client, session):
    """Set on the row rather than through the vault route: a private note is
    encrypted at rest, so its text would fail the LIKE anyway. The filter is
    asserted so that stays true by decision and not by side effect."""
    from memorymap.core.database import Entry

    target = _document(client, "Roadmap")
    note = _note(client, "The roadmap is secret.")
    assert len(_backlinks(client, target["id"])["mentions"]) == 1
    row = session.get(Entry, note["id"])
    row.is_private = True
    session.commit()
    assert _backlinks(client, target["id"])["mentions"] == []


def test_an_archived_document_does_not_haunt_the_panel(client):
    target = _document(client, "Roadmap")
    ghost = _document(client, "Old plan", "The roadmap used to say otherwise.")
    assert len(_backlinks(client, target["id"])["mentions"]) == 1
    archived = client.put(f"/documents/{ghost['id']}/archive")
    assert archived.status_code == 200, archived.text
    assert _backlinks(client, target["id"])["mentions"] == []


def test_an_untitled_document_answers_empty_rather_than_failing(client):
    target = client.post("/documents", json={"title": "   ", "content": ""}).json()
    body = _backlinks(client, target["id"])
    assert body["links"] == [] and body["mentions"] == []


def test_a_missing_document_is_a_404(client):
    assert client.get("/documents/999999/backlinks").status_code == 404
