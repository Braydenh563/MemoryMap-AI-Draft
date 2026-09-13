"""Agentic tools: the registry, the tool-calling agent loop over the
streaming chat endpoint, the destructive-call confirm flow, skills
preferences, and hallucinated-write recovery."""

from __future__ import annotations

import json

from memorymap.ai import tools
from memorymap.core.database import Reminder


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def _stream_events(client, question, **body):
    with client.stream(
        "POST", "/chat/stream", json={"question": question, **body}
    ) as response:
        assert response.status_code == 200
        return [json.loads(line) for line in response.iter_lines() if line]


# --- the registry ---------------------------------------------------------------


# Tools that reach the internet. They stay hidden until the user opts in
# (Wave F), so the registry is always larger than what's offered.
ONLINE_TOOLS = {"web_search", "read_url"}


def test_registry_shapes_are_valid_for_ollama(app_state):
    offered = tools.ollama_tools()
    # Expressed as the rule rather than a count, so adding an online tool
    # doesn't fail this test for the wrong reason.
    assert {t["function"]["name"] for t in offered} == set(tools.TOOLS) - ONLINE_TOOLS
    for item in offered:
        assert item["type"] == "function"
        fn = item["function"]
        assert fn["name"] in tools.TOOLS
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_destructive_tools_are_flagged():
    assert tools.TOOLS["delete_note"].destructive
    assert tools.TOOLS["delete_tag"].destructive
    # Everything else must be safe to auto-run.
    safe = {n for n, s in tools.TOOLS.items() if not s.destructive}
    assert "create_note" in safe and "search_notes" in safe


def test_execute_search_and_count(ai_client, session):
    _save(ai_client, "buy milk and eggs", category="Shopping")
    _save(ai_client, "a funny scarecrow joke", category="Jokes")

    found = tools.execute_tool(session, "search_notes", {"query": "groceries milk"})
    assert found["found"] >= 1
    assert any("milk" in n["content"] for n in found["notes"])

    counted = tools.execute_tool(session, "count_notes", {})
    assert counted["total"] == 2
    assert counted["by_category"] == {"Shopping": 1, "Jokes": 1}

    one = tools.execute_tool(session, "count_notes", {"category": "Jokes"})
    assert one["count"] == 1


def test_get_current_time_tool(session):
    result = tools.execute_tool(session, "get_current_time", {})
    assert "iso" in result and "human" in result
    # A parseable ISO timestamp.
    from datetime import datetime

    datetime.fromisoformat(result["iso"])


def test_summarize_notes_tool(ai_client, session):
    _save(ai_client, "buy milk and eggs", category="Shopping")
    _save(ai_client, "a funny scarecrow joke", category="Jokes")

    everything = tools.execute_tool(session, "summarize_notes", {})
    assert everything["count"] == 2
    assert len(everything["notes"]) == 2

    just_jokes = tools.execute_tool(session, "summarize_notes", {"category": "Jokes"})
    assert just_jokes["count"] == 1
    assert "Jokes" in just_jokes["period"]


def test_execute_create_edit_tag_pin_link(ai_client, session):
    created = tools.execute_tool(
        session, "create_note", {"content": "call the dentist", "category": "Tasks"}
    )
    assert created["category"] == "Tasks"
    note_id = created["id"]

    tagged = tools.execute_tool(
        session, "tag_note", {"note_id": note_id, "add": ["health", "phone"]}
    )
    assert set(tagged["tags"]) == {"health", "phone"}

    untagged = tools.execute_tool(
        session, "tag_note", {"note_id": note_id, "remove": ["phone"]}
    )
    assert untagged["tags"] == ["health"]

    pinned = tools.execute_tool(session, "pin_note", {"note_id": note_id})
    assert pinned["pinned"] is True

    other = tools.execute_tool(session, "create_note", {"content": "book a checkup"})
    linked = tools.execute_tool(
        session, "link_notes", {"note_id": note_id, "other_note_id": other["id"]}
    )
    assert linked["linked"] == [note_id, other["id"]]

    edited = tools.execute_tool(
        session, "edit_note", {"note_id": note_id, "category": "Health"}
    )
    assert edited["category"] == "Health"

    # Tool actions land in the audit log with the ai_tool action.
    audit = ai_client.get("/audit?limit=100").json()
    assert any(row["action"] == "ai_tool" for row in audit)


def test_execute_reminder_tools(ai_client, session):
    created = tools.execute_tool(
        session,
        "set_reminder",
        {"text": "water the plants", "due_at": "2030-01-02T09:00"},
    )
    assert created["id"]

    listed = tools.execute_tool(session, "list_reminders", {})
    assert [r["text"] for r in listed["reminders"]] == ["water the plants"]

    done = tools.execute_tool(
        session, "complete_reminder", {"reminder_id": created["id"]}
    )
    assert done["done"] is True
    assert session.get(Reminder, created["id"]).done is True


def test_execute_bad_arguments_return_error_not_crash(ai_client, session):
    result = tools.execute_tool(session, "edit_note", {"note_id": 999})
    assert "error" in result
    result = tools.execute_tool(
        session, "set_reminder", {"text": "x", "due_at": "not-a-date"}
    )
    assert "error" in result
    assert tools.execute_tool(session, "no_such_tool", {}) == {
        "error": "Unknown tool 'no_such_tool'"
    }


def test_an_unexpected_exception_is_a_tool_error_not_a_crash(ai_client, session, monkeypatch):
    """A handler can raise something that isn't a ToolError/KeyError/
    TypeError/ValueError: a SQLAlchemy error, a filesystem error, a plain
    bug. That used to propagate straight through execute_tool: agent.py's
    tool loop has no try/except of its own, so one such call killed the
    whole SSE stream mid-turn with no rollback and nothing the model or the
    user ever saw. It must come back as an ordinary tool error instead."""
    import dataclasses

    def boom(session, args):
        raise RuntimeError("the database exploded")

    broken = dataclasses.replace(tools.TOOLS["count_notes"], handler=boom)
    monkeypatch.setitem(tools.TOOLS, "count_notes", broken)
    result = tools.execute_tool(session, "count_notes", {})
    assert "error" in result
    assert "count_notes" in result["error"]


# --- the agent loop over the streaming endpoint -----------------------------------


def test_agent_runs_tool_then_answers(ai_client, fake_ollama):
    fake_ollama.tool_script = [
        [{"name": "create_note", "arguments": {"content": "buy milk", "category": "Shopping"}}]
    ]
    fake_ollama.librarian_reply = "Done: I saved that to Shopping."

    events = _stream_events(ai_client, "save a note to buy milk")

    tool_events = [e for e in events if e["type"] == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["ok"] is True
    assert "Created note" in tool_events[0]["label"]
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert answer == "Done: I saved that to Shopping."
    assert events[-1]["type"] == "done"

    # The note really exists now.
    entries = ai_client.get("/entries").json()
    assert any(e["content"] == "buy milk" for e in entries)


def test_agent_feeds_tool_results_back_to_model(ai_client, fake_ollama):
    _save(ai_client, "buy milk", category="Shopping")
    fake_ollama.tool_script = [[{"name": "count_notes", "arguments": {}}]]

    _stream_events(ai_client, "how many notes do I have?")

    # Round 2 must contain a tool message with the count result.
    final_round = fake_ollama.tool_rounds[-1]
    tool_messages = [m for m in final_round if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0]["content"])["total"] == 1


def test_agent_destructive_call_waits_for_confirmation(ai_client, fake_ollama):
    saved = _save(ai_client, "delete me please", category="Junk")
    fake_ollama.tool_script = [
        [{"name": "delete_note", "arguments": {"note_id": saved["id"]}}]
    ]

    events = _stream_events(ai_client, "delete that junk note")

    confirms = [e for e in events if e["type"] == "confirm"]
    assert len(confirms) == 1
    assert confirms[0]["name"] == "delete_note"
    assert str(saved["id"]) in confirms[0]["label"]
    # Nothing was deleted: the tool never ran.
    assert not [e for e in events if e["type"] == "tool"]
    entries = ai_client.get("/entries").json()
    assert any(e["id"] == saved["id"] for e in entries)


def test_confirmed_tool_executes_via_endpoint(ai_client):
    saved = _save(ai_client, "delete me please", category="Junk")

    response = ai_client.post(
        "/chat/tools/execute",
        json={"name": "delete_note", "arguments": {"note_id": saved["id"]}},
    )
    assert response.status_code == 200
    assert "recycle bin" in response.json()["label"]

    # Soft-deleted: gone from the list, present in the bin.
    assert all(e["id"] != saved["id"] for e in ai_client.get("/entries").json())
    binned = ai_client.get("/entries?deleted=true").json()
    assert any(e["id"] == saved["id"] for e in binned)


def test_execute_endpoint_rejects_unknown_and_bad_calls(ai_client):
    assert (
        ai_client.post("/chat/tools/execute", json={"name": "nope"}).status_code == 404
    )
    response = ai_client.post(
        "/chat/tools/execute",
        json={"name": "delete_note", "arguments": {"note_id": 12345}},
    )
    assert response.status_code == 400


def test_model_without_tool_support_falls_back_to_plain_chat(ai_client, fake_ollama):
    fake_ollama.supports_tools = False
    _save(ai_client, "a funny scarecrow joke")

    events = _stream_events(ai_client, "any funny jokes?")
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    # The normal streamed librarian answered instead of the agent.
    assert answer == fake_ollama.librarian_reply
    assert events[-1]["type"] == "done"


def test_use_tools_false_skips_the_agent(ai_client, fake_ollama):
    _save(ai_client, "a funny scarecrow joke")
    events = _stream_events(ai_client, "any funny jokes?", use_tools=False)
    assert not fake_ollama.tool_rounds  # chat_tools was never called
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert answer == fake_ollama.librarian_reply


def test_agent_works_on_an_empty_notebook(ai_client, fake_ollama):
    fake_ollama.tool_script = [
        [{"name": "create_note", "arguments": {"content": "first ever note"}}]
    ]
    events = _stream_events(ai_client, "save my first note")
    assert [e for e in events if e["type"] == "tool"]
    assert any(e["content"] == "first ever note" for e in ai_client.get("/entries").json())


def test_agent_round_limit_is_bounded(ai_client, fake_ollama):
    # A model that calls tools forever must be cut off politely.
    fake_ollama.tool_script = [
        [{"name": "count_notes", "arguments": {}}] for _ in range(50)
    ]
    events = _stream_events(ai_client, "loop forever")
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    assert "stopped" in answer.lower()
    assert events[-1]["type"] == "done"


# --- skills preferences -----------------------------------------------------------


def test_skills_preference_roundtrip(client):
    body = {"skills": [{"name": "Weekly review", "prompt": "Summarise my week."}]}
    updated = client.put("/preferences", json=body).json()
    # Stored normalised (§21): a prompt-only skill still round-trips, it just
    # comes back with the empty steps/tools/inputs a skill now has.
    saved = updated["skills"][0]
    assert saved["name"] == "Weekly review"
    assert saved["prompt"] == "Summarise my week."
    assert saved["steps"] == [] and saved["tools"] == []
    assert client.get("/preferences").json()["skills"] == updated["skills"]


def test_tools_enabled_preference_roundtrip(client):
    assert client.get("/preferences").json()["tools_enabled"] is True
    updated = client.put("/preferences", json={"tools_enabled": False}).json()
    assert updated["tools_enabled"] is False


# --- Wave O: hallucinated-write recovery + honesty safety net -----------------------


def test_extract_text_tool_calls_from_wrapper():
    from memorymap.ai.ollama_client import extract_text_tool_calls

    content = (
        'Sure! <tool_call>{"name": "create_note", "arguments": '
        '{"content": "buy milk"}}</tool_call> done.'
    )
    calls, cleaned = extract_text_tool_calls(content, {"create_note", "delete_note"})
    assert calls == [{"name": "create_note", "arguments": {"content": "buy milk"}}]
    assert "<tool_call>" not in cleaned


def test_extract_text_tool_calls_ignores_unknown_tool():
    from memorymap.ai.ollama_client import extract_text_tool_calls

    calls, _ = extract_text_tool_calls('{"name": "not_a_tool"}', {"create_note"})
    assert calls == []


def test_extract_text_tool_calls_bare_json_with_nested_arguments():
    # A bare (untagged) call whose arguments are themselves an object with a
    # list inside: an entirely ordinary shape, not an edge case, and the one
    # the old `\{[^{}]*"name"[^{}]*\}` regex could never match: `[^{}]*`
    # cannot cross a brace at all, so any nested `{` in `arguments` broke the
    # match outright and the whole call was silently dropped. Reported live
    # as "the ai didn't actually call any tools".
    from memorymap.ai.ollama_client import extract_text_tool_calls

    content = (
        'On it: {"name": "create_note", "arguments": '
        '{"content": "buy milk", "tags": ["errand", "home"]}} there you go.'
    )
    calls, cleaned = extract_text_tool_calls(content, {"create_note"})
    assert calls == [
        {"name": "create_note", "arguments": {"content": "buy milk", "tags": ["errand", "home"]}}
    ]
    assert '"name"' not in cleaned


def test_extract_text_tool_calls_multiple_in_one_wrapper():
    # Two calls inside one <tool_call>...</tool_call> pair: both should
    # come back, not just whichever the parser happened to find first.
    from memorymap.ai.ollama_client import extract_text_tool_calls

    content = (
        '<tool_call>{"name": "create_note", "arguments": {"content": "a"}}'
        '{"name": "create_note", "arguments": {"content": "b"}}</tool_call>'
    )
    calls, cleaned = extract_text_tool_calls(content, {"create_note"})
    assert calls == [
        {"name": "create_note", "arguments": {"content": "a"}},
        {"name": "create_note", "arguments": {"content": "b"}},
    ]
    assert "<tool_call>" not in cleaned


def test_agent_recovers_text_emitted_tool_call(ai_client, fake_ollama):
    # The model "narrates" a create as text instead of a structured call, 
    # the client recovers it, so the note is really made (Wave O).
    fake_ollama.text_tool_reply = (
        '<tool_call>{"name": "create_note", "arguments": '
        '{"content": "recovered note"}}</tool_call>'
    )
    _stream_events(ai_client, "save a note that says recovered note")
    entries = ai_client.get("/entries").json()
    assert any(e["content"] == "recovered note" for e in entries)


def test_agent_warns_on_hallucinated_write(ai_client, fake_ollama):
    # No tool call at all, but the model claims it created a note → the
    # safety net appends an honest warning (Wave O).
    #
    # The wording changed in §35B: the warning now names *which* claim was
    # unsupported, because a turn that claims five things and did one needs to
    # say which four did not happen. The property under test is unchanged, 
    # the user is told, in the answer, that nothing was saved.
    fake_ollama.librarian_reply = "I created a new note titled “Jokes”. Enjoy!"
    events = _stream_events(ai_client, "add a note of jokes")
    answer = "".join(e["delta"] for e in events if e["type"] == "answer")
    # Was `assert "" in answer`. The warning glyph went away with the rest of
    # the colour emoji: this is prose appended to the model's own answer, and
    # a bitmap emoji in it renders at the OS's whim and cannot follow the
    # theme. What the test is actually for is that the user is TOLD, so it
    # pins the words rather than the decoration.
    assert "Heads up" in answer
    assert "saved a note" in answer
    assert "didn't actually run the tool" in answer


# --- per-tool enable/disable toggles ---------------------------------------------


def test_tool_catalog_lists_tools(client):
    catalog = client.get("/chat/tools").json()
    names = {t["name"] for t in catalog}
    assert {"create_note", "delete_note", "set_reminder"} <= names
    delete = next(t for t in catalog if t["name"] == "delete_note")
    assert delete["destructive"] is True


def test_disabled_tool_is_hidden_and_refused(ai_client):
    from memorymap.ai import tools

    # Disable create_note via the preference.
    ai_client.put("/preferences", json={"disabled_tools": ["create_note"]})
    offered = [t["function"]["name"] for t in tools.ollama_tools()]
    assert "create_note" not in offered

    # And the execute endpoint refuses it too.
    from memorymap.core import deps

    session = deps.get_db().session()
    try:
        result = tools.execute_tool(session, "create_note", {"content": "x"})
        assert "error" in result and "turned off" in result["error"]
    finally:
        session.close()


def test_disabled_tools_preference_roundtrips(client):
    body = client.put("/preferences", json={"disabled_tools": ["delete_tag"]}).json()
    assert body["disabled_tools"] == ["delete_tag"]
    assert client.get("/preferences").json()["disabled_tools"] == ["delete_tag"]


# --- registry classification: what counts as a read, a write, or a duplicate ---


def test_find_similar_notes_is_a_read_not_a_write():
    """It was added to WRITE_TOOLS. A read listed there counts as work for the
    "you claimed you saved it" checker, labels search-only skills as acting,
    and, the expensive one, trips the write branch in `run_agent`, which
    clears the read-dedup ledger and re-opens every answered read."""
    assert "find_similar_notes" not in tools.WRITE_TOOLS


def test_there_is_only_one_skill_writing_tool():
    """`generate_skill` wrote raw AI-authored dicts straight into preferences,
    skipping `save_skill`'s schema check, its built-in-name guard, its
    validation of every declared tool name, and MAX_SKILLS. It also called a
    `config.save_preference` method that does not exist, so it could only ever
    have raised."""
    assert "generate_skill" not in tools.TOOLS
    assert "save_skill" in tools.TOOLS


def test_listing_reminders_hands_the_model_a_page_not_the_table(session):
    """Everything a tool returns is spent from the model's context window.

    `_list_reminders` read the whole table; its sibling `list_documents` has
    paged since it was written. A notebook with three hundred reminders would
    have filled the window with reminders and left no room to reason about
    them. The `done` filter moved into SQL at the same time, because
    filtering a page after limiting it is how "show me ten" quietly returns
    two.
    """
    from datetime import datetime, timedelta, timezone

    from memorymap.ai import tools
    from memorymap.core.database import Reminder

    now = datetime.now(timezone.utc)
    for i in range(60):
        session.add(
            Reminder(text=f"reminder {i}", due_at=now + timedelta(hours=i), done=i % 2 == 0)
        )
    session.commit()

    page = tools.execute_tool(session, "list_reminders", {})
    assert len(page["reminders"]) < 30, "the whole table went to the model"
    assert page["total"] == 30, page["total"]
    assert all(not r["done"] for r in page["reminders"]), "a done reminder reached the model"

    second = tools.execute_tool(session, "list_reminders", {"offset": len(page["reminders"])})
    first_ids = {r["id"] for r in page["reminders"]}
    assert first_ids.isdisjoint({r["id"] for r in second["reminders"]}), "offset returned the same page"

    withdone = tools.execute_tool(session, "list_reminders", {"include_done": True})
    assert withdone["total"] == 60, withdone["total"]
