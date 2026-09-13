"""Keeping a growing pile of chats usable (roadmap §2).

The conversation list was flat, ordered by recency, searchable only by
title, and an answer could not be corrected. Each of those is fine with
five chats and useless with two hundred.
"""

from __future__ import annotations


def _chat(client, question, answer, **extra):
    response = client.post(
        "/conversations", json={"question": question, "answer": answer, **extra}
    )
    assert response.status_code == 201
    return response.json()


def _turn(client, conversation_id, question, answer, **extra):
    response = client.post(
        f"/conversations/{conversation_id}/turns",
        json={"question": question, "answer": answer, **extra},
    )
    assert response.status_code == 200
    return response.json()


# --- finding a chat again --------------------------------------------------------


def test_search_matches_what_was_said_not_just_the_title(client):
    """You remember what you asked about; you rarely remember the title."""
    kept = _chat(client, "how do I proof sourdough?", "Leave it somewhere warm.")
    client.put(f"/conversations/{kept['id']}", json={"title": "Tuesday"})
    _chat(client, "what's my bike tyre pressure?", "Around 90 psi.")

    by_body = client.get("/conversations", params={"q": "sourdough"}).json()
    assert [c["id"] for c in by_body] == [kept["id"]]

    by_title = client.get("/conversations", params={"q": "Tuesday"}).json()
    assert [c["id"] for c in by_title] == [kept["id"]]

    # An answer's text counts too, it's part of what was said.
    by_answer = client.get("/conversations", params={"q": "90 psi"}).json()
    assert len(by_answer) == 1


def test_an_empty_search_returns_everything(client):
    _chat(client, "one", "a")
    _chat(client, "two", "b")
    assert len(client.get("/conversations", params={"q": ""}).json()) == 2
    assert len(client.get("/conversations").json()) == 2


def test_search_finds_nothing_rather_than_everything(client):
    _chat(client, "sourdough", "warm")
    assert client.get("/conversations", params={"q": "helicopters"}).json() == []


# --- pinning ---------------------------------------------------------------------


def test_pinned_chats_sort_above_more_recent_ones(client):
    old = _chat(client, "the one I keep coming back to", "…")
    _chat(client, "a throwaway question", "…")
    _chat(client, "another throwaway", "…")

    # Unpinned, the old chat is last.
    assert client.get("/conversations").json()[-1]["id"] == old["id"]

    client.put(f"/conversations/{old['id']}/pin", json={"pinned": True})
    listed = client.get("/conversations").json()
    assert listed[0]["id"] == old["id"]
    assert listed[0]["pinned"] is True

    client.put(f"/conversations/{old['id']}/pin", json={"pinned": False})
    assert client.get("/conversations").json()[-1]["id"] == old["id"]


def test_pinning_does_not_count_as_using_the_chat(client):
    """Bumping updated_at would reshuffle the list you just organised."""
    first = _chat(client, "first", "…")
    _chat(client, "second", "…")
    before = client.get(f"/conversations/{first['id']}").json()["updated_at"]

    client.put(f"/conversations/{first['id']}/pin", json={"pinned": True})
    after = client.get(f"/conversations/{first['id']}").json()["updated_at"]
    assert after == before


# --- what a conversation costs ----------------------------------------------------


def test_a_conversation_totals_its_tokens(client):
    """Per-message counts can't answer "should I start a new chat?"."""
    chat = _chat(client, "q1", "a1", tokens=120)
    assert chat["tokens"] == 120

    _turn(client, chat["id"], "q2", "a2", tokens=200)
    assert client.get(f"/conversations/{chat['id']}").json()["tokens"] == 320


def test_turns_without_token_counts_are_not_an_error(client):
    """Older saved chats have none, and a model may not report them."""
    chat = _chat(client, "q", "a")
    assert chat["tokens"] == 0
    _turn(client, chat["id"], "q2", "a2", tokens=50)
    assert client.get("/conversations").json()[0]["tokens"] == 50


def test_the_list_previews_the_first_question(client):
    chat = _chat(client, "how do I proof sourdough?", "Leave it somewhere warm.")
    client.put(f"/conversations/{chat['id']}", json={"title": "Tuesday"})
    listed = client.get("/conversations").json()[0]
    assert listed["preview"].startswith("how do I proof sourdough")


# --- correcting an answer ---------------------------------------------------------


def test_an_answer_can_be_edited_in_place(client):
    chat = _chat(client, "what's the wifi password?", "I think it's 'guest'.")
    _turn(client, chat["id"], "and the printer?", "No idea.")

    response = client.put(
        f"/conversations/{chat['id']}/turns/0/answer",
        json={"content": "It's 'sunflower-42'."},
    )
    assert response.status_code == 200

    messages = client.get(f"/conversations/{chat['id']}").json()["messages"]
    assert messages[1]["content"] == "It's 'sunflower-42'."
    # Marked, so the transcript never passes your words off as the model's.
    assert messages[1]["edited"] is True
    # Everything else is untouched.
    assert messages[0]["content"] == "what's the wifi password?"
    assert messages[3]["content"] == "No idea."


def test_editing_an_answer_also_updates_the_step_timeline(client):
    """The edit has to land in `steps`, because `steps` is what gets rendered.

    Reopening a chat replays the saved timeline; `content` only feeds the copy
    button. Updating one without the other made a correction disappear as soon
    as the chat was reopened, with the model's original wording back in place.
    """
    chat = client.post(
        "/conversations",
        json={
            "question": "what's the wifi password?",
            "answer": "I think it's 'guest'.",
            "steps": [
                {"kind": "thinking", "text": "Checking the notes."},
                {"kind": "tool", "label": "search_notes", "ok": True},
                {"kind": "answer", "text": "I think it's 'guest'."},
            ],
        },
    ).json()

    client.put(
        f"/conversations/{chat['id']}/turns/0/answer",
        json={"content": "It's 'sunflower-42'."},
    )

    steps = client.get(f"/conversations/{chat['id']}").json()["messages"][1]["steps"]
    assert [s["kind"] for s in steps] == ["thinking", "tool", "answer"]
    assert steps[-1]["text"] == "It's 'sunflower-42'."
    # What the model actually did is not the user's to rewrite.
    assert steps[0]["text"] == "Checking the notes."
    assert steps[1]["label"] == "search_notes"


def test_editing_collapses_several_prose_steps_into_the_correction(client):
    """Two prose blocks must not both become the edited text."""
    chat = client.post(
        "/conversations",
        json={
            "question": "q",
            "answer": "part one\n\npart two",
            "steps": [
                {"kind": "answer", "text": "part one"},
                {"kind": "tool", "label": "read_url", "ok": True},
                {"kind": "answer", "text": "part two"},
            ],
        },
    ).json()

    client.put(
        f"/conversations/{chat['id']}/turns/0/answer", json={"content": "my version"}
    )

    steps = client.get(f"/conversations/{chat['id']}").json()["messages"][1]["steps"]
    assert [s["kind"] for s in steps] == ["answer", "tool"]
    assert steps[0]["text"] == "my version"


def test_editing_a_tool_only_turn_gains_an_answer_step(client):
    """A turn that only ran tools still has to show the prose it was given."""
    chat = client.post(
        "/conversations",
        json={
            "question": "file that away",
            "answer": "",
            "steps": [{"kind": "tool", "label": "create_note", "ok": True}],
        },
    ).json()

    client.put(
        f"/conversations/{chat['id']}/turns/0/answer", json={"content": "Filed it."}
    )

    steps = client.get(f"/conversations/{chat['id']}").json()["messages"][1]["steps"]
    assert steps[-1] == {"kind": "answer", "text": "Filed it."}


def test_editing_a_turn_that_does_not_exist_is_a_404(client):
    chat = _chat(client, "q", "a")
    assert (
        client.put(
            f"/conversations/{chat['id']}/turns/7/answer", json={"content": "x"}
        ).status_code
        == 404
    )


def test_an_existing_database_gains_pinning_without_a_reset(tmp_path):
    """The auto-migrator has to cover the new column, or upgrading loses chats."""
    import json

    from sqlalchemy import select

    from memorymap.core.database import Conversation, DatabaseManager

    db_path = tmp_path / "existing.db"
    old = DatabaseManager(db_path).session()
    old.add(
        Conversation(
            title="from before pinning existed",
            messages=json.dumps([{"role": "user", "content": "hi"}]),
        )
    )
    old.commit()
    old.close()

    upgraded = DatabaseManager(db_path).session()
    surviving = upgraded.scalars(select(Conversation)).all()
    assert [c.title for c in surviving] == ["from before pinning existed"]
    assert all(c.pinned is False for c in surviving)  # backfilled, not null
    upgraded.close()


def test_search_does_not_match_the_json_keys_of_the_transcript(client):
    """Messages are stored as JSON, so a naive LIKE over that column also
    searches its own keys: "tent" is a substring of "content", which matched
    every conversation ever saved. What was *said* is the only thing anyone
    means by searching a chat."""
    wanted = _chat(client, "which tent did we settle on?", "The two-person one.")
    _chat(client, "what's for dinner?", "Pasta.")

    for key_fragment in ["tent", "role", "assistan", "think"]:
        hits = client.get("/conversations", params={"q": key_fragment}).json()
        assert all(c["id"] == wanted["id"] for c in hits), (
            f"'{key_fragment}' matched a chat that never mentions it"
        )

    assert [c["id"] for c in client.get("/conversations", params={"q": "tent"}).json()] == [
        wanted["id"]
    ]
