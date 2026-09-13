"""The memory stream: standing preferences the model saves about itself, or
the user writes by hand, and replays into its own future system prompts.

Split out of test_antigravity_regressions.py (§40/§41): grouped here rather
than left as scattered bug-regression tests because this is now a real,
readable feature: save, list, edit, deactivate, forget, and the budget that
keeps it from growing without bound.
"""

from __future__ import annotations

from memorymap.ai import agent, memory, tools
from memorymap.core.database import UserPreference


# --- the memory stream -----------------------------------------------------------


def test_an_accepted_preference_reaches_the_next_turns_persona(session):
    tools.execute_tool(
        session, "save_user_preference", {"preference": "Always answer in British English"}
    )
    row = session.query(UserPreference).one()
    row.proposed, row.active = False, True
    session.commit()

    persona = memory.persona_with_memory(session, "You are a librarian.")
    assert "British English" in persona


def test_the_memory_stream_cannot_grow_past_its_budget(session):
    """It was appended to the system prompt unbounded, on every round of every
    turn: slipping straight past `PROSE_BUDGET_CHARS`, the guard that exists
    to stop exactly this."""
    for i in range(60):
        session.add(UserPreference(content=f"preference number {i} " + "x" * 120))
    session.commit()

    persona = memory.persona_with_memory(session, "P.")
    assert len(persona) <= len("P.") + agent.MEMORY_STREAM_BUDGET_CHARS + 80


def test_an_over_long_preference_is_refused(session):
    result = tools.execute_tool(
        session, "save_user_preference", {"preference": "x" * 5_000}
    )
    assert "error" in result


def test_the_same_preference_is_not_saved_twice(session):
    for _ in range(2):
        tools.execute_tool(session, "save_user_preference", {"preference": "Be brief"})
    assert session.query(UserPreference).count() == 1


def test_losing_the_memory_stream_never_costs_the_turn(monkeypatch):
    """`run_agent` is also driven with stand-in sessions, and a notebook that
    predates the table has no `user_preferences` at all. A missing memory
    stream must degrade to "no preferences", not to a broken turn, this
    exact line took out 7 agent tests with an AttributeError."""

    class NotReallyASession:
        pass

    persona = memory.persona_with_memory(NotReallyASession(), "Just the persona.")
    assert persona == "Just the persona."


# --- the memory stream, made visible (§39B / §40 open item 1) --------------------


def test_the_saved_preferences_can_be_listed(ai_client, session):
    """The feature shipped write-only: the model could save standing
    instructions into its own future system prompts and the user had no way to
    see them. A rule you cannot read is indistinguishable from the assistant
    behaving oddly."""
    ai_client.post("/memory", json={"content": "Be concise"})

    body = ai_client.get("/memory").json()
    assert [p["content"] for p in body["preferences"]] == ["Be concise"]
    assert body["preferences"][0]["active"] is True
    assert body["preferences"][0]["proposed"] is False
    assert body["budget_chars"] == agent.MEMORY_STREAM_BUDGET_CHARS


def test_a_preference_can_be_switched_off_without_deleting_it(ai_client, session):
    """"Stop doing this for now" and "you should never have saved that" are
    different intentions. `active` already existed and nothing ever set it."""
    ai_client.post("/memory", json={"content": "Use bullet points"})
    pref = ai_client.get("/memory").json()["preferences"][0]

    turned_off = ai_client.patch(f"/memory/{pref['id']}", json={"active": False})
    assert turned_off.status_code == 200

    session.expire_all()
    assert "bullet points" not in memory.persona_with_memory(session, "P.")
    # Still listed, so it can be turned back on.
    assert ai_client.get("/memory").json()["preferences"][0]["active"] is False


def test_a_preference_can_be_edited(ai_client, session):
    ai_client.post("/memory", json={"content": "Answer in French"})
    pref = ai_client.get("/memory").json()["preferences"][0]

    edited = ai_client.patch(f"/memory/{pref['id']}", json={"content": "Answer in German"})
    assert edited.status_code == 200
    session.expire_all()
    assert "German" in memory.persona_with_memory(session, "P.")


def test_a_forgotten_preference_stops_reaching_the_model(ai_client, session):
    ai_client.post("/memory", json={"content": "Never use emoji"})
    pref = ai_client.get("/memory").json()["preferences"][0]

    forgotten = ai_client.delete(f"/memory/{pref['id']}")
    assert forgotten.status_code == 200
    session.expire_all()
    assert "emoji" not in memory.persona_with_memory(session, "P.")
    assert ai_client.get("/memory").json()["preferences"] == []


def test_editing_a_preference_that_is_gone_is_a_404(ai_client):
    patch_response = ai_client.patch("/memory/999", json={"active": False})
    assert patch_response.status_code == 404

    delete_response = ai_client.delete("/memory/999")
    assert delete_response.status_code == 404


def test_a_preference_cannot_be_edited_into_nothing(ai_client, session):
    ai_client.post("/memory", json={"content": "Something"})
    pref = ai_client.get("/memory").json()["preferences"][0]
    blanked = ai_client.patch(f"/memory/{pref['id']}", json={"content": "   "})
    assert blanked.status_code == 422


# --- reported directly, after the audit (§41) ------------------------------------


def test_a_preference_can_be_added_by_hand(ai_client):
    """`save_user_preference` is the model's door in. "I already know what I
    want it to always do" needed one too, and was the first thing asked for
    once the list became visible."""
    made = ai_client.post("/memory", json={"content": "Never use emoji"})
    assert made.status_code == 201
    assert made.json()["content"] == "Never use emoji"
    assert [p["content"] for p in ai_client.get("/memory").json()["preferences"]] == [
        "Never use emoji"
    ]


def test_adding_the_same_preference_twice_is_refused(ai_client):
    ai_client.post("/memory", json={"content": "Be brief"})
    again = ai_client.post("/memory", json={"content": "  be BRIEF "})
    assert again.status_code == 409


def test_an_empty_preference_is_refused(ai_client):
    empty = ai_client.post("/memory", json={"content": "   "})
    assert empty.status_code == 422


def test_a_hand_written_preference_is_capped_like_the_tools(ai_client):
    from memorymap.ai.tools import MAX_ACTIVE_PREFERENCES

    for i in range(MAX_ACTIVE_PREFERENCES):
        saved = ai_client.post("/memory", json={"content": f"rule {i}"})
        assert saved.status_code == 201
    # The cap exists because every active preference is replayed into the
    # system prompt on every round, true whoever typed it.
    over_the_cap = ai_client.post("/memory", json={"content": "one too many"})
    assert over_the_cap.status_code == 409


# --- ask before remembering (§39B, reported directly) ----------------------------
#
# "can the ai pick up things and suggest the user adds it as a preference in
# that section with an accept or deny or similar popup??", and the question is
# the right one because of what the tool used to do. `save_user_preference`
# wrote a standing instruction into every future system prompt with no
# confirmation and no notice, so one over-read sentence gave the model a
# permanent rule its user never agreed to and would keep obeying for weeks.


def test_the_tool_proposes_rather_than_saving(session):
    result = tools.execute_tool(
        session, "save_user_preference", {"preference": "Always use bullet points"}
    )
    row = session.query(UserPreference).one()
    assert row.proposed is True
    assert row.active is False
    # Nothing is in force until the user answers.
    assert "bullet points" not in memory.persona_with_memory(session, "P.")
    # And the model is told so, so it doesn't announce a saved preference.
    assert "NOT in force" in result["message"]
    assert result["proposal"] == {"id": row.id, "content": "Always use bullet points"}


def test_accepting_a_proposal_puts_it_in_the_prompt(ai_client, session):
    tools.execute_tool(session, "save_user_preference", {"preference": "Answer in Welsh"})
    pref = ai_client.get("/memory").json()["preferences"][0]
    assert pref["proposed"] is True

    answered = ai_client.post(f"/memory/{pref['id']}/answer", json={"accept": True})
    assert answered.status_code == 200
    assert answered.json()["proposed"] is False
    assert answered.json()["active"] is True

    session.expire_all()
    assert "Welsh" in memory.persona_with_memory(session, "P.")


def test_declining_a_proposal_keeps_the_row_switched_off(ai_client, session):
    """Deliberately not a delete. The tool's duplicate check reads *every*
    preference, so the kept "no" is the only thing stopping the model
    proposing the same rule again an hour later."""
    tools.execute_tool(session, "save_user_preference", {"preference": "Answer in Welsh"})
    pref = ai_client.get("/memory").json()["preferences"][0]

    declined = ai_client.post(f"/memory/{pref['id']}/answer", json={"accept": False})
    assert declined.status_code == 200
    assert declined.json() == {**declined.json(), "proposed": False, "active": False}

    session.expire_all()
    assert "Welsh" not in memory.persona_with_memory(session, "P.")
    # Still listed, so it reads as an ordinary switched-off preference.
    assert len(ai_client.get("/memory").json()["preferences"]) == 1

    again = tools.execute_tool(
        session, "save_user_preference", {"preference": "Answer in Welsh"}
    )
    assert session.query(UserPreference).count() == 1, again


def test_answering_the_same_proposal_twice_is_a_no_op(ai_client, session):
    """Two windows, two clicks, one of them second."""
    tools.execute_tool(session, "save_user_preference", {"preference": "Be brief"})
    pref = ai_client.get("/memory").json()["preferences"][0]

    ai_client.post(f"/memory/{pref['id']}/answer", json={"accept": True})
    second = ai_client.post(f"/memory/{pref['id']}/answer", json={"accept": False})
    assert second.status_code == 200
    # The first answer stands, a stale card can't switch off a live rule.
    assert second.json()["active"] is True


def test_answering_a_proposal_that_is_gone_is_a_404(ai_client):
    assert ai_client.post("/memory/999/answer", json={"accept": True}).status_code == 404


def test_a_proposal_does_not_count_against_the_active_cap(ai_client, session):
    """The cap exists because active preferences are replayed into the system
    prompt. A pending question is not in the prompt, so it must not be able to
    lock the list: otherwise a chatty model could fill the cap with questions
    and block the user from saving anything by hand."""
    from memorymap.ai.tools import MAX_ACTIVE_PREFERENCES

    for i in range(MAX_ACTIVE_PREFERENCES):
        tools.execute_tool(session, "save_user_preference", {"preference": f"rule {i}"})
    assert ai_client.post("/memory", json={"content": "by hand"}).status_code == 201


def test_the_chat_is_where_a_proposal_is_answered():
    """A lint: nothing here can see a rendered page. The card is only useful
    if the tool event carries the id, Settings alone was the write-only
    version of this feature with an extra step."""
    from pathlib import Path

    agent_src = Path("src/memorymap/ai/agent.py").read_text(encoding="utf-8")
    assert 'event["proposal"] = result["proposal"]' in agent_src

    app_js = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "renderMemoryProposal" in app_js
    assert "/answer`" in app_js
    assert "memory-proposal" in app_js
