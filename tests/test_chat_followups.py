"""The "what to ask next" chips have to survive leaving the chat (§ chat).

Reported directly:

    "also suggested repsponse continuation prompts in chat doesnt persist and
     disappears once I switch chat sessions or quit the app."

They disappeared because nothing stored them. `offerFollowups` fires a second
model call *after* the turn is already saved, deliberately, so it can never
delay the answer: appended the chips to a live DOM node, and that node was
the whole of their existence.
"""

from __future__ import annotations

from pathlib import Path


def _turn(client, question="q", answer="a"):
    return client.post("/conversations", json={"question": question, "answer": answer}).json()


def test_followups_are_remembered_against_the_turn(client):
    conversation = _turn(client)
    saved = client.put(
        f"/conversations/{conversation['id']}/turns/0/followups",
        json={"followups": ["Why did that happen?", "Show me the notes"]},
    ).json()
    assert saved["saved"] is True

    messages = client.get(f"/conversations/{conversation['id']}").json()["messages"]
    assert messages[1]["followups"] == ["Why did that happen?", "Show me the notes"]


def test_they_hang_off_the_answer_not_the_question(client):
    """Index `n` addresses turn `n`, the same way every other per-turn endpoint
    here does: and the chips belong under the answer they follow from."""
    conversation = _turn(client)
    client.post(
        f"/conversations/{conversation['id']}/turns",
        json={"question": "second", "answer": "second answer"},
    )
    client.put(
        f"/conversations/{conversation['id']}/turns/1/followups",
        json={"followups": ["and then?"]},
    )
    messages = client.get(f"/conversations/{conversation['id']}").json()["messages"]
    assert "followups" not in messages[1]
    assert messages[3]["followups"] == ["and then?"]
    assert messages[2]["role"] == "user"


def test_an_empty_list_clears_them(client):
    conversation = _turn(client)
    client.put(
        f"/conversations/{conversation['id']}/turns/0/followups",
        json={"followups": ["something"]},
    )
    client.put(f"/conversations/{conversation['id']}/turns/0/followups", json={"followups": []})
    assert "followups" not in client.get(f"/conversations/{conversation['id']}").json()[
        "messages"
    ][1]


def test_a_turn_that_is_gone_is_a_no_op_not_an_error(client):
    """The suggestions arrive after the turn is saved and can land after the
    reader has deleted it. Moving on is allowed."""
    conversation = _turn(client)
    response = client.put(
        f"/conversations/{conversation['id']}/turns/9/followups",
        json={"followups": ["late"]},
    )
    assert response.status_code == 200
    assert response.json()["saved"] is False


def test_saving_them_does_not_reshuffle_the_chat_list(client):
    """`updated_at` orders the sidebar. A suggestion the user has not read is
    not activity, and bumping it would move the chat under them seconds after
    they stopped reading."""
    conversation = _turn(client)
    before = client.get(f"/conversations/{conversation['id']}").json()["updated_at"]
    client.put(
        f"/conversations/{conversation['id']}/turns/0/followups",
        json={"followups": ["a", "b"]},
    )
    assert client.get(f"/conversations/{conversation['id']}").json()["updated_at"] == before


def test_the_list_is_bounded(client):
    """One row of buttons under an answer. A body with two hundred of them is
    a bug or an attack, not a longer list of good questions."""
    conversation = _turn(client)
    response = client.put(
        f"/conversations/{conversation['id']}/turns/0/followups",
        json={"followups": [f"q{i}" for i in range(30)]},
    )
    assert response.status_code == 422


# --- the frontend half ----------------------------------------------------------


def test_one_renderer_serves_the_live_path_and_the_reopen():
    """Two renderers would be two chances for a restored chip to look unlike a
    fresh one."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "function renderFollowups(" in source
    assert source.count("renderFollowups(") >= 3  # the definition plus both callers
    assert "if (message.followups) {" in source


def test_saving_them_never_puts_an_error_on_screen():
    """Bookkeeping behind a suggestion. A failed save must not show an error
    over an answer that is fine, the same rule the request itself follows."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    block = source.split("async function saveFollowups(")[1].split("\n}")[0]
    assert "silent: true" in block
    assert ".catch(() => {})" in block


# --- the live timer -------------------------------------------------------------


def test_the_chat_timer_starts_with_the_turn_and_stops_with_it():
    """Asked for directly: "can there be an active timer on responses in chatg
    messages as well??", the *live* one; the finished time was already in the
    metadata line."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "function startChatTimer()" in source and "function stopChatTimer()" in source
    assert "startChatTimer();" in source
    # Stopped where the controller is cleared, which is the one place every
    # ending, answered, errored, stopped, passes through.
    tail = source.split("if (chatController === controller) {")[1][:200]
    assert "stopChatTimer();" in tail


def test_the_timer_ticks_on_a_clock_not_on_stream_events():
    """The seconds have to keep moving while the model is thinking and sending
    nothing, which is exactly the stretch that makes someone wonder if it has
    hung."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    block = source.split("function startChatTimer()")[1].split("\nfunction stopChatTimer")[0]
    assert "setInterval(paintChatTimer, 1000)" in block


def test_switching_chats_mid_stream_hides_the_timer():
    """It belongs to the composer, which has just been handed to a different
    conversation: leaving it ticking would time this chat's turn against the
    next chat's empty box."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    block = source.split("function releaseChatComposer(")[1].split("\n}")[0]
    assert 'chat-elapsed' in block


# --- reported after the first version shipped --------------------------------
#
# Three separate complaints about the same corner of a chat bubble, all lints:
# nothing in this suite can see a rendered page.


def test_the_action_row_does_not_reserve_space_when_hidden():
    """"the suggested responses appear after the popup buttons which leaves a
    gap visually when not hovering over the chat bubble", `opacity: 0` hides a
    row while keeping every pixel of its layout, so a finished answer had a 2rem
    band of nothing above its "Next:" chips. Out of flow entirely: `display:
    none` until hover would close the gap and make the chips jump 2rem the
    moment the pointer entered the bubble."""
    css = Path("frontend/css/02-chat-graph.css").read_text(encoding="utf-8")
    block = css.split(".msg-actions {")[1].split("}")[0]
    assert "position: absolute" in block
    # And unclickable while invisible, or an unhovered bubble swallows clicks.
    assert "pointer-events: none" in block


def test_the_live_timer_is_mounted_in_the_bubble_and_removed_with_it():
    """"the time of response stays below the chat input bar and doesnt
    disappear, I want the timer to appear on the chat bubble while it is
    responding until the response is finished." Both halves are the same
    mistake: the counter lived in the composer, which is not where the answer
    is written and is not unmounted when the answer ends."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "function mountChatTimer(bubble)" in source
    assert "mountChatTimer(bubble);" in source
    stop = source.split("function stopChatTimer()")[1].split("\n}")[0]
    assert "chatTimerBox?.remove()" in stop
    assert "chatTimerBox = null" in stop


def test_only_the_last_answer_keeps_its_followup_chips():
    """Chips under an older answer invite forking the thread backwards: the
    click sends that question as a new message at the end, three exchanges
    away from the suggestion. Deleting the newest turn brings the previous
    turn's saved chips back, which is why they are stashed on the bubble
    rather than discarded."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "function refreshFollowupVisibility()" in source
    render = source.split("function renderFollowups(bubble, picks)")[1].split("\n}")[0]
    assert "bubble.dataset.followups" in render
    assert "refreshFollowupVisibility()" in render
    # Brought back when the turn above becomes the last one again.
    delete = source.split("async function deleteChatTurn(")[1].split("\n}")[0]
    assert "refreshFollowupVisibility()" in delete
