"""The /chat endpoint end-to-end over HTTP (with the AI faked so it runs
offline: the real-model run happens manually with Ollama installed): the
dad-joke "done when" test, suggestions, and follow-up conversation memory."""

from __future__ import annotations

from memorymap.ai import librarian


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_dad_joke_loop(ai_client):
    joke = _save(ai_client, "Why did the scarecrow win an award? Outstanding in his field!")
    shopping = _save(ai_client, "buy milk, eggs and bread")
    race = _save(ai_client, "Came 2nd in the 100m sprint at the athletics carnival")

    # The janitor filed the three notes into three different categories.
    assert joke["category"] == "Dad Jokes"
    assert shopping["category"] == "Shopping"
    assert race["category"] == "Sport Results"
    assert joke["ai_confidence"] > 0

    response = ai_client.post("/chat", json={"question": "What jokes have I saved?"})
    assert response.status_code == 200
    body = response.json()

    # Both halves of the answer: conversational + raw rows.
    assert body["ai_response"] == "Here's what I found in your notebook!"
    assert body["search_mode"] == "semantic"
    contents = [row["content"] for row in body["raw_results"]]
    assert joke["content"] in contents
    assert shopping["content"] not in contents  # only joke-topic rows come back


def test_semantic_match_carries_its_score(ai_client):
    """A semantic hit's `match_info` should name a real similarity score, not
    just "semantic" with nothing behind it, the whole point of the badge is
    to say *how* confident the match was."""
    joke = _save(ai_client, "Why did the scarecrow win an award? Outstanding in his field!")
    _save(ai_client, "buy milk, eggs and bread")

    body = ai_client.post("/chat", json={"question": "What jokes have I saved?"}).json()
    assert body["search_mode"] == "semantic"

    info = body["match_info"][str(joke["id"])]
    assert info["type"] == "semantic"
    assert 0 < info["score"] <= 1


def test_a_second_note_on_the_same_topic_is_still_filed_by_the_model(
    ai_client, fake_ollama
):
    """This asserted the opposite - that a centroid match skipped the model.

    That was the filing order until it was reversed: the embedding shortcut
    ran first and was so rarely declined that in an established notebook the
    model was almost never asked, so notes were filed by what they *resemble*
    rather than by where they belong. Reported as notes landing in the wrong
    category and needing fixing by hand.

    What the test protects now is the outcome rather than the shortcut: the
    second joke still lands in "Dad Jokes", and the model is what decided it.
    The saving this test was originally written to prove is covered instead
    by test_ai_core.py's no-model case, which is the situation the embedding
    paths actually exist for.
    """
    _save(ai_client, "Why did the scarecrow win an award? Outstanding in his field!")
    calls_before = len(fake_ollama.chat_calls)

    second = _save(ai_client, "another funny pun about cheese")

    assert second["category"] == "Dad Jokes"
    assert len(fake_ollama.chat_calls) == calls_before + 1


def test_chat_with_ollama_down_still_returns_raw_results(ai_client, fake_ollama):
    _save(ai_client, "Why did the scarecrow win an award? Outstanding in his field!")

    fake_ollama.running = False  # kill the chat model, keep embeddings
    response = ai_client.post("/chat", json={"question": "any jokes?"})
    body = response.json()

    assert body["ai_response"] == librarian.OFFLINE_MESSAGE
    assert len(body["raw_results"]) == 1  # raw results survive an AI outage


def test_capture_works_with_zero_ai(client):
    saved = _save(client, "note taken while everything AI is off")
    assert saved["category"] == "Uncategorised"
    assert saved["ai_confidence"] == 0

    response = client.post("/chat", json={"question": "everything AI"})
    body = response.json()
    assert body["search_mode"] == "keyword"  # no embeddings → keyword fallback
    assert len(body["raw_results"]) == 1
    assert body["ai_response"] == librarian.OFFLINE_MESSAGE


# --- chat suggestions ----------------------------------------------------------


def _starters():
    from memorymap.api.routes_chat import STARTER_SUGGESTIONS

    return STARTER_SUGGESTIONS


def test_suggestions_starters_for_empty_notebook(client):
    assert client.get("/chat/suggestions").json() == _starters()


def test_suggestions_are_content_aware(client):
    # Guided mode files these under real categories, skipping the AI.
    _save(client, "a joke", category="Jokes")
    _save(client, "another joke", category="Jokes")
    _save(client, "milk", category="Shopping")

    picks = client.get("/chat/suggestions").json()
    assert any("jokes" in p.lower() for p in picks)  # most-populated first
    assert any("shopping" in p.lower() for p in picks)
    assert len(picks) <= 5
    assert len(picks) == len(set(picks))  # no duplicates


def _asked(session, question):
    """One question in the Ask box's history, the row `/chat/recent` reads."""
    from memorymap.api.routes_chat import ASK_SURFACE
    from memorymap.core.database import AuditLog

    session.add(AuditLog(action="queried", entity_type=ASK_SURFACE, detail=question))
    session.commit()


def test_suggestions_drop_what_ask_again_already_offers(client, session):
    """INBOX 120: "the try asking and ask again suggestions are nearly
    identical". The history row wins a duplicate, and the generated row fills
    the gap with its next candidate rather than coming back one chip short."""
    _save(client, "a joke", category="Jokes")
    _save(client, "another joke", category="Jokes")
    _save(client, "milk", category="Shopping")
    _save(client, "a run", category="Fitness")

    before = client.get("/chat/suggestions").json()
    assert "What have I saved about jokes?" in before

    _asked(session, "What have I saved about jokes?")
    after = client.get("/chat/suggestions").json()

    assert "What have I saved about jokes?" not in after
    assert "What have I saved about jokes?" in client.get("/chat/recent").json()
    # Same length, one new candidate promoted into the gap.
    assert len(after) == len(before)
    assert set(after) - set(before) == {"What have I saved about fitness?"}


def test_suggestions_ignore_case_and_spacing_of_what_was_asked(client, session):
    _save(client, "a joke", category="Jokes")
    _save(client, "milk", category="Shopping")
    _asked(session, "  what have i saved about   JOKES?  ")

    assert "What have I saved about jokes?" not in client.get("/chat/suggestions").json()


def test_suggestions_ignore_uncategorised(client):
    _save(client, "a stray thought")  # lands in Uncategorised (no AI)
    # Only the generic starters, since there's no real category.
    assert client.get("/chat/suggestions").json() == _starters()


# --- follow-up conversation memory ----------------------------------------------


def test_build_messages_replays_history():
    notes = [{"content": "the cheese joke", "category": "Jokes"}]
    history = [{"question": "what jokes?", "answer": "You have a cheese joke."}]
    messages = librarian.build_messages("tell me more", notes, history=history)

    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "what jokes?"
    assert messages[2]["content"] == "You have a cheese joke."
    assert "tell me more" in messages[-1]["content"]


def test_build_messages_clips_history_length():
    long_answer = "x" * 5000
    history = [{"question": f"q{i}", "answer": long_answer} for i in range(10)]
    messages = librarian.build_messages("now", [{"content": "n", "category": "c"}], history=history)

    # At most MAX_HISTORY_TURNS pairs survive, and each answer is clipped, 
    # old ones hard, the most recent one generously, because "save that as a
    # note" refers to it and a stump of it is what used to get saved.
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == librarian.MAX_HISTORY_TURNS
    assert all(
        len(m["content"]) <= librarian.MAX_HISTORY_ANSWER_CHARS
        for m in assistant_msgs[:-1]
    )
    assert len(assistant_msgs[-1]["content"]) <= librarian.LAST_ANSWER_CHARS


def test_an_attached_documents_content_actually_reaches_the_model(ai_client, fake_ollama):
    """The composer has sent `document_ids` since the staging UI shipped, 
    the field didn't exist on ChatRequest and routes_chat.py never read it,
    so an attached document showed as a chip on the message and the model
    never saw a word of it. Worse than not offering the feature: it looked
    like it worked."""
    document = ai_client.post(
        "/documents", json={"title": "Q3 plan", "content": "Ship the thing by October."}
    ).json()

    ai_client.post(
        "/chat",
        json={"question": "what does this say?", "document_ids": [document["id"]]},
    )
    sent = fake_ollama.chat_calls[-1]
    assert any("Ship the thing by October." in m["content"] for m in sent)
    assert any("Q3 plan" in m["content"] for m in sent)


def test_an_attached_library_files_text_reaches_the_model(ai_client, fake_ollama):
    """Asked for directly: "I want to be able to attach not just existing notes
    to a chat for context, but also already uploaded files, documents, and
    images." A Library file is an Attachment row -- not a Document and not an
    Entry -- so it needed a field of its own, and its text is extracted at
    request time by the same core.docview the file viewer uses."""
    entry = ai_client.post("/entries", json={"content": "holds the file"}).json()
    updated = ai_client.post(
        f"/entries/{entry['id']}/files",
        files={"file": ("plan.md", b"# Roadmap\n\nShip the reader in March.", "text/markdown")},
    ).json()
    attachment = updated["attachments"][0]

    ai_client.post(
        "/chat",
        json={"question": "what does the file say?", "file_ids": [attachment["id"]]},
    )
    sent = fake_ollama.chat_calls[-1]
    assert any("Ship the reader in March." in m["content"] for m in sent)
    assert any("plan.md" in m["content"] for m in sent)


def test_an_unreadable_attached_file_still_reaches_the_model_by_name(ai_client, fake_ollama):
    """A file whose text cannot be extracted must not reach the model as
    silence: the chip is in the transcript either way, and a chip that
    corresponds to nothing at all is the exact failure document_ids shipped
    once already. Its name is a real clue on its own."""
    entry = ai_client.post("/entries", json={"content": "holds the file"}).json()
    updated = ai_client.post(
        f"/entries/{entry['id']}/files",
        files={"file": ("scan.pdf", b"not really a pdf", "application/pdf")},
    ).json()
    attachment = updated["attachments"][0]

    ai_client.post("/chat", json={"question": "what is it?", "file_ids": [attachment["id"]]})
    sent = fake_ollama.chat_calls[-1]
    assert any("scan.pdf" in m["content"] for m in sent)


def test_chat_endpoint_threads_history_to_model(ai_client, fake_ollama):
    _save(ai_client, "a funny scarecrow joke")
    ai_client.post(
        "/chat",
        json={
            "question": "any more jokes?",
            "history": [{"question": "any jokes?", "answer": "Yes, a scarecrow one."}],
        },
    )
    # The fake records the exact messages it was asked to answer.
    sent = fake_ollama.chat_calls[-1]
    assert any(m["content"] == "any jokes?" for m in sent)
    assert any(m["content"] == "Yes, a scarecrow one." for m in sent)
