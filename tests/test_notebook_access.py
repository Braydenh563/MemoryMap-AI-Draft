"""The AI reaching the notebook (roadmap §1).

Before this, the model only ever saw the five similarity hits retrieval
handed it: it couldn't count, couldn't work through a category, and couldn't
be pointed at one note. These tests cover the tools that fixed that, and,
more importantly, the two things that make them safe to hand to a model:

  1. a context budget, so a large notebook can't flood a small window;
  2. private notes staying out of every single one of them.
"""

from __future__ import annotations

import json

import pytest

from memorymap.ai import agent, tools
from memorymap.core import vault


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


# --- reading one note -----------------------------------------------------------


def test_get_note_returns_the_whole_note_where_a_list_gave_a_preview(ai_client, session):
    long_note = "recipe: " + ("chop the onions very finely. " * 40)
    saved = _save(ai_client, long_note, category="Recipes")

    listed = tools.execute_tool(session, "list_notes", {})
    preview = listed["notes"][0]
    assert preview["truncated"] is True
    assert len(preview["content"]) <= tools.PREVIEW_CHARS + 1
    assert listed["previews_only"] is True

    full = tools.execute_tool(session, "get_note", {"note_id": saved["id"]})
    assert full["content"] == long_note
    assert full["truncated"] is False


def test_get_note_on_a_missing_note_is_an_error_not_a_crash(ai_client, session):
    result = tools.execute_tool(session, "get_note", {"note_id": 9999})
    assert "error" in result and "9999" in result["error"]


# --- walking the notebook -------------------------------------------------------


def test_list_notes_pages_rather_than_truncating_silently(ai_client, session):
    for i in range(12):
        _save(ai_client, f"note number {i}", category="Log")

    first = tools.execute_tool(session, "list_notes", {"limit": 5})
    assert first["returned"] == 5
    assert first["total_matching"] == 12
    assert first["has_more"] is True
    assert first["next_offset"] == 5
    # The model must be *told* it's looking at a page, or it will answer
    # "you have 5 notes" from a truncated view.
    assert "12" in first["note_to_model"]

    second = tools.execute_tool(
        session, "list_notes", {"limit": 5, "offset": first["next_offset"]}
    )
    assert second["returned"] == 5
    assert second["offset"] == 5

    last = tools.execute_tool(session, "list_notes", {"limit": 5, "offset": 10})
    assert last["returned"] == 2
    assert last["has_more"] is False
    assert "next_offset" not in last

    seen = [n["id"] for page in (first, second, last) for n in page["notes"]]
    assert len(set(seen)) == 12  # every note exactly once across the pages


def test_list_notes_limit_is_clamped_to_the_budget(ai_client, session):
    for i in range(40):
        _save(ai_client, f"note {i}")

    greedy = tools.execute_tool(session, "list_notes", {"limit": 500})
    assert greedy["returned"] == tools.MAX_LIST_LIMIT
    assert greedy["has_more"] is True


def test_list_notes_filters_by_category_and_tag(ai_client, session):
    _save(ai_client, "sourdough starter", category="Recipes", tags=["bread"])
    _save(ai_client, "focaccia", category="Recipes", tags=["bread", "italian"])
    _save(ai_client, "call the dentist", category="Errands")

    recipes = tools.execute_tool(session, "list_notes", {"category": "Recipes"})
    assert recipes["total_matching"] == 2
    assert all(n["category"] == "Recipes" for n in recipes["notes"])

    # Case shouldn't matter: a model won't reliably match the user's casing.
    lowered = tools.execute_tool(session, "list_notes", {"category": "recipes"})
    assert lowered["total_matching"] == 2

    italian = tools.execute_tool(session, "list_notes", {"tag": "italian"})
    assert [n["content"] for n in italian["notes"]] == ["focaccia"]


def test_an_unknown_category_returns_nothing_rather_than_everything(ai_client, session):
    _save(ai_client, "a note", category="Recipes")
    empty = tools.execute_tool(session, "list_notes", {"category": "Nonexistent"})
    assert empty["returned"] == 0
    assert empty["total_matching"] == 0


def test_a_tag_filter_does_not_match_a_longer_tag(ai_client, session):
    """Tags are stored as one delimited string, so the SQL filter over-matches
    ("work" hits "homework"). The exact check has to happen after it."""
    _save(ai_client, "maths sheet", tags=["homework"])
    _save(ai_client, "quarterly report", tags=["work"])

    work = tools.execute_tool(session, "list_notes", {"tag": "work"})
    assert [n["content"] for n in work["notes"]] == ["quarterly report"]
    assert work["total_matching"] == 1


def test_since_accepts_days_or_an_iso_date(ai_client, session):
    _save(ai_client, "written today")

    assert tools.execute_tool(session, "list_notes", {"since": 7})["total_matching"] == 1
    assert tools.execute_tool(session, "list_notes", {"since": "1"})["total_matching"] == 1
    assert (
        tools.execute_tool(session, "list_notes", {"since": "2020-01-01"})[
            "total_matching"
        ]
        == 1
    )
    # Unparseable means "no time filter", not an error: a wider answer beats
    # a burnt round.
    assert (
        tools.execute_tool(session, "list_notes", {"since": "recently"})[
            "total_matching"
        ]
        == 1
    )


# --- counting and listing what exists -------------------------------------------


def test_count_notes_by_tag_and_category(ai_client, session):
    _save(ai_client, "one", category="Work", tags=["urgent"])
    _save(ai_client, "two", category="Work", tags=["urgent"])
    _save(ai_client, "three", category="Home", tags=["urgent"])
    _save(ai_client, "four", category="Work")

    assert tools.execute_tool(session, "count_notes", {})["total"] == 4
    assert tools.execute_tool(session, "count_notes", {"tag": "urgent"})["count"] == 3
    both = tools.execute_tool(session, "count_notes", {"tag": "urgent", "category": "Work"})
    assert both["count"] == 2
    # No note content in a count, that's the point of it being cheap.
    assert "notes" not in both


def test_list_tags_reports_counts_most_used_first(ai_client, session):
    _save(ai_client, "a", tags=["common", "rare"])
    _save(ai_client, "b", tags=["common"])
    _save(ai_client, "c", tags=["common"])

    listed = tools.execute_tool(session, "list_tags", {})
    assert listed["tags"][0] == {"name": "common", "notes": 3}
    assert {"name": "rare", "notes": 1} in listed["tags"]


def test_list_categories_reports_a_total(ai_client, session):
    _save(ai_client, "a", category="Work")
    _save(ai_client, "b", category="Home")

    listed = tools.execute_tool(session, "list_categories", {})
    assert listed["total_notes"] == 2
    assert {"name": "Work", "notes": 1} in listed["categories"]


def test_notebook_overview_combines_categories_tags_and_total(ai_client, session):
    # Reported live: a skill wanting "the shape of the notebook" spent three
    # separate tool calls (count_notes, list_categories, list_tags) to get
    # what this single call now returns.
    _save(ai_client, "a", category="Work", tags=["urgent"])
    _save(ai_client, "b", category="Home", tags=["urgent", "chores"])

    overview = tools.execute_tool(session, "notebook_overview", {})
    assert overview["total_notes"] == 2
    assert {"name": "Work", "notes": 1} in overview["categories"]
    assert {"name": "Home", "notes": 1} in overview["categories"]
    assert {"name": "urgent", "notes": 2} in overview["tags"]
    assert {"name": "chores", "notes": 1} in overview["tags"]


def test_the_new_tools_are_offered_to_the_model(app_state):
    offered = {t["function"]["name"] for t in tools.ollama_tools()}
    assert {"get_note", "list_notes", "count_notes", "list_tags"} <= offered


# --- the non-negotiable: private notes stay out ---------------------------------


@pytest.fixture()
def unlocked_vault(session):
    vault.close()
    vault.create(session, "test-passphrase")
    session.commit()
    yield
    vault.close()


def _make_private(client, content):
    entry = client.post("/entries", json={"content": content}).json()
    assert client.post(f"/entries/{entry['id']}/privacy", json={"private": True}).status_code == 200
    return entry


def test_no_reading_tool_can_see_a_private_note(ai_client, session, unlocked_vault):
    """One test over every read path, deliberately: the risk isn't that a
    handler is wrong today, it's that the next one added forgets the rule."""
    # The query deliberately shares no words with the secret, so finding it in
    # a result can only mean the note leaked, not that the query echoed.
    secret = "submarine plans: codeword ELDERFLOWER opens the safe"
    private = _make_private(ai_client, secret)
    _save(ai_client, "an ordinary public note", category="Open")

    for name, args in [
        ("list_notes", {}),
        ("search_notes", {"query": "tell me about submarines"}),
        ("summarize_notes", {}),
    ]:
        result = tools.execute_tool(session, name, args)
        blob = json.dumps(result)
        assert "ELDERFLOWER" not in blob, f"{name} leaked a private note"
        assert private["id"] not in [n["id"] for n in result["notes"]], name

    # Counts must not include it either, "you have 2 notes" is itself a leak
    # about a note the AI is not allowed to know exists.
    assert tools.execute_tool(session, "count_notes", {})["total"] == 1
    assert tools.execute_tool(session, "list_categories", {})["total_notes"] == 1


def test_get_note_refuses_a_private_note_by_id(ai_client, session, unlocked_vault):
    """Guessing an id must not be a way around it."""
    private = _make_private(ai_client, "codeword ELDERFLOWER")

    result = tools.execute_tool(session, "get_note", {"note_id": private["id"]})
    assert "error" in result
    assert "private" in result["error"].lower()
    assert "ELDERFLOWER" not in json.dumps(result)


def test_write_tools_refuse_private_notes_too(ai_client, session, unlocked_vault):
    """Editing one would round-trip its text through the model."""
    private = _make_private(ai_client, "codeword ELDERFLOWER")

    for name, args in [
        ("edit_note", {"note_id": private["id"], "content": "overwritten"}),
        ("tag_note", {"note_id": private["id"], "add": ["snooped"]}),
        ("pin_note", {"note_id": private["id"]}),
    ]:
        result = tools.execute_tool(session, name, args)
        assert "error" in result and "private" in result["error"].lower(), name


def test_restore_note_refuses_a_deleted_private_note(ai_client, session, unlocked_vault):
    """A private note soft-deleted from the UI must stay unreadable through
    restore too: `restore_note` has to reach a *deleted* note where
    `_require_note` normally refuses one, so it cannot just call
    `_require_note` unmodified. It still has to refuse a *private* one, same
    as every other write tool, or restoring becomes a way to read a private
    note's content back through `_note_summary`."""
    private = _make_private(ai_client, "codeword ELDERFLOWER")
    deleted = ai_client.delete(f"/entries/{private['id']}")
    assert deleted.status_code == 200

    result = tools.execute_tool(session, "restore_note", {"note_id": private["id"]})
    assert "error" in result and "private" in result["error"].lower()
    assert "ELDERFLOWER" not in json.dumps(result)

    # And it must actually still be deleted, refusing to read it should not
    # have restored it as a side effect.
    from memorymap.entry import manager as entry_manager

    entry = entry_manager.get_entry(session, private["id"])
    assert entry.is_deleted is True


def test_a_private_notes_tags_are_not_listed(ai_client, session, unlocked_vault):
    """A tag is a description of the note; listing it leaks what it's about."""
    entry = ai_client.post(
        "/entries", json={"content": "x", "tags": ["elderflower-safe-combination"]}
    ).json()
    ai_client.post(f"/entries/{entry['id']}/privacy", json={"private": True})

    listed = tools.execute_tool(session, "list_tags", {})
    assert all(t["name"] != "elderflower-safe-combination" for t in listed["tags"])


# --- the turn-level context budget ----------------------------------------------


def test_the_agent_stops_adding_tool_results_once_the_budget_is_spent(
    ai_client, session, fake_ollama, monkeypatch
):
    """A model that keeps paging must run out of budget, not out of window.

    The budget is squeezed to something tiny so one page of results crosses
    it; what's under test is the stop rule, not the size of the number.
    """
    monkeypatch.setattr(agent, "TOOL_RESULT_BUDGET_CHARS", 200)
    for i in range(30):
        _save(ai_client, f"note number {i} with enough text to cost something")

    fake_ollama.tool_script = [
        [{"name": "list_notes", "arguments": {"limit": 25}}],
        [{"name": "list_notes", "arguments": {"limit": 25, "offset": 25}}],
    ]
    fake_ollama.librarian_reply = "Here's a partial summary."

    events = list(
        agent.run_agent(
            session,
            "go through all my notes",
            [],
            model_manager=__import__(
                "memorymap.core.deps", fromlist=["deps"]
            ).get_model_manager(),
            ollama=fake_ollama,
        )
    )
    # The agent streams, so the answer arrives as one or more "answer" deltas
    # followed by the round's "stats", it is no longer the single last event.
    # What matters is that the turn ends by answering rather than looping.
    assert "answer" in [e["type"] for e in events]
    assert [e["type"] for e in events if e["type"] in ("answer", "tool")][-1] == "answer"

    # The second call's result was replaced by the notice, and the tool list
    # was withdrawn so the model has to answer.
    tool_messages = [
        m
        for round_messages in fake_ollama.tool_rounds
        for m in round_messages
        if m.get("role") == "tool"
    ]
    assert any("context_budget_reached" in m["content"] for m in tool_messages)


def test_a_normal_turn_is_not_affected_by_the_budget(ai_client, session, fake_ollama):
    """The budget must be invisible in ordinary use, or it's just a bug."""
    _save(ai_client, "buy milk", category="Shopping")
    fake_ollama.tool_script = [[{"name": "count_notes", "arguments": {}}]]
    fake_ollama.librarian_reply = "You have one note."

    from memorymap.core import deps

    events = list(
        agent.run_agent(
            session,
            "how many notes do I have?",
            [],
            model_manager=deps.get_model_manager(),
            ollama=fake_ollama,
        )
    )
    tool_events = [e for e in events if e["type"] == "tool"]
    assert tool_events and tool_events[0]["ok"] is True
    # Joined, because streaming splits the answer across deltas.
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert answer == "You have one note."
