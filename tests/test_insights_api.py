"""The /insights router: stats, on-this-day, greeting, tag cloud, heatmap,
and the dashboard layout preference.

(The digest's own content logic, what makes a week worth summarising, has
its own file, test_digest_structure.py; the HTTP/streaming half of the
digest endpoint lives there too, next to that logic.)
"""

from __future__ import annotations

from datetime import timedelta

from memorymap.api import routes_insights
from memorymap.core import deps
from memorymap.core.database import Entry, utcnow


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


# --- stats + on this day -------------------------------------------------------


def test_stats_counts_and_activity(client):
    _save(client, "one", category="Alpha")
    _save(client, "two", category="Alpha")
    _save(client, "three", category="Beta")

    body = client.get("/insights/stats").json()
    assert body["total_entries"] == 3
    assert body["categories"][0] == {"name": "Alpha", "count": 2}
    assert len(body["per_day"]) == body["days"]
    assert body["per_day"][-1] == 3  # all created today


def test_on_this_day_resurfaces_old_notes(client):
    _save(client, "fresh note")  # today → excluded (too recent)
    session = deps.get_db().session()
    try:
        old = Entry(content="a year ago today", tags="[]")
        old.created_at = utcnow() - timedelta(days=365)
        session.add(old)
        session.commit()
    finally:
        session.close()

    matches = client.get("/insights/on-this-day").json()
    assert [m["content"] for m in matches] == ["a year ago today"]


def test_on_this_day_excludes_private_notes(client):
    """Every other view filters `is_private` before a note reaches the
    caller; this one didn't, and read `entry.content` straight off the
    column, ciphertext, for a private note, instead of through
    `readable_content`."""
    session = deps.get_db().session()
    try:
        old = Entry(content="a year ago today", tags="[]", is_private=True)
        old.created_at = utcnow() - timedelta(days=365)
        session.add(old)
        session.commit()
    finally:
        session.close()

    assert client.get("/insights/on-this-day").json() == []


# --- greeting --------------------------------------------------------------------


def test_greeting_uses_ai_when_available(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "Rise and shine"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["greeting"] == "Rise and shine"
    assert body["source"] == "ai"
    assert body["punctuation"] == "."


def test_greeting_keeps_its_terminal_mark_separate(ai_client, fake_ollama):
    """The mark is returned apart from the phrase so a name can slot in
    before it: "Rise and shine, Sam!" rather than "Rise and shine!, Sam"."""
    fake_ollama.librarian_reply = "Rise and shine!"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["greeting"] == "Rise and shine"
    assert body["punctuation"] == "!"


def test_greeting_is_sentence_cased(ai_client, fake_ollama):
    """Local models often answer in lowercase; the banner is a sentence."""
    fake_ollama.librarian_reply = "good morning"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["greeting"] == "Good morning"


def test_greeting_keeps_interior_capitals(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "welcome back to Brisbane"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["greeting"] == "Welcome back to Brisbane"


def test_greeting_weaves_in_the_saved_name(ai_client, fake_ollama, monkeypatch):
    """With a display name set, the model is asked to use it, and when it
    does, the response says so, so the frontend won't append it again."""
    # Name use is deliberately probabilistic; pin it so the test is stable.
    monkeypatch.setattr(routes_insights, "NAME_USE_CHANCE", 1.0)
    ai_client.put("/preferences", json={"display_name": "Brayden"})
    fake_ollama.librarian_reply = "Morning, Brayden!"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["greeting"] == "Morning, Brayden"
    assert body["punctuation"] == "!"
    assert body["append_name"] is False  # model handled it; don't add it twice
    # The name reached the prompt from preferences, not from the client.
    assert "Brayden" in fake_ollama.chat_calls[-1][0]["content"]


def test_greeting_normalises_the_name_casing(ai_client, fake_ollama):
    ai_client.put("/preferences", json={"display_name": "Brayden"})
    fake_ollama.librarian_reply = "welcome back, brayden"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["greeting"] == "Welcome back, Brayden"  # saved spelling wins
    assert body["append_name"] is False


def test_greeting_flags_when_the_model_ignores_the_name(ai_client, fake_ollama, monkeypatch):
    """The model dropping the name must not lose it, append_name stays
    true so the frontend appends it as before."""
    monkeypatch.setattr(routes_insights, "NAME_USE_CHANCE", 1.0)
    ai_client.put("/preferences", json={"display_name": "Brayden"})
    fake_ollama.librarian_reply = "Good morning"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["append_name"] is True  # model dropped it, so we add it
    assert body["greeting"] == "Good morning"


def test_greeting_without_a_name_is_unchanged(ai_client, fake_ollama):
    fake_ollama.librarian_reply = "Good morning"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert body["append_name"] is False  # no name saved, nothing to add


def test_greeting_sometimes_skips_the_name(ai_client, fake_ollama, monkeypatch):
    """Not every greeting uses the name, when we skip it, the frontend must
    not bolt it on, or the variety is lost."""
    monkeypatch.setattr(routes_insights, "NAME_USE_CHANCE", 0.0)
    ai_client.put("/preferences", json={"display_name": "Brayden"})
    fake_ollama.librarian_reply = "Late night?"
    body = ai_client.get("/insights/greeting?block=night").json()
    assert body["greeting"] == "Late night"
    assert body["punctuation"] == "?"
    assert body["append_name"] is False
    assert "Brayden" not in fake_ollama.chat_calls[-1][0]["content"]


def test_greeting_uses_the_active_persona(ai_client, fake_ollama):
    ai_client.put(
        "/preferences",
        json={
            "personas": [{"name": "Pirate", "prompt": "You are a pirate captain."}],
            "active_persona": "Pirate",
        },
    )
    fake_ollama.librarian_reply = "Ahoy there"
    ai_client.get("/insights/greeting?block=morning")
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "pirate captain" in system.lower()


def test_greeting_prefers_dashboard_persona_over_active_persona(ai_client, fake_ollama):
    """Asked for directly: the dashboard greeting should be settable to a
    different persona than whichever one Chat/search has active, not forced
    to match it."""
    ai_client.put(
        "/preferences",
        json={
            "personas": [
                {"name": "Pirate", "prompt": "You are a pirate captain."},
                {"name": "Coach", "prompt": "You are an encouraging coach."},
            ],
            "active_persona": "Pirate",
            "dashboard_persona": "Coach",
        },
    )
    fake_ollama.librarian_reply = "You've got this"
    ai_client.get("/insights/greeting?block=morning")
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "encouraging coach" in system.lower()
    assert "pirate" not in system.lower()


def test_greeting_falls_back_to_active_persona_when_unset(ai_client, fake_ollama):
    """No dashboard_persona override → same behaviour as before this existed:
    the greeting follows active_persona."""
    ai_client.put(
        "/preferences",
        json={
            "personas": [{"name": "Pirate", "prompt": "You are a pirate captain."}],
            "active_persona": "Pirate",
        },
    )
    fake_ollama.librarian_reply = "Ahoy there"
    ai_client.get("/insights/greeting?block=morning")
    system = fake_ollama.chat_calls[-1][0]["content"]
    assert "pirate captain" in system.lower()


def test_greeting_falls_back_when_ai_is_down(ai_client, fake_ollama):
    fake_ollama.running = False
    body = ai_client.get("/insights/greeting?block=evening").json()
    assert body["source"] == "fallback"
    assert body["greeting"] in [
        "Good evening",
        "Evening",
        "Winding down",
    ]


def test_greeting_rejects_a_rambling_model_reply(ai_client, fake_ollama):
    # Too long / multi-sentence → the handwritten fallback wins.
    fake_ollama.librarian_reply = (
        "Certainly! Here is a lovely greeting for you to use today: "
        "Good morning and welcome back to your wonderful notebook."
    )
    body = ai_client.get("/insights/greeting?block=night").json()
    assert body["source"] == "fallback"
    assert body["greeting"] in ["Still up", "Working late", "Burning the midnight oil"]


def test_greeting_strips_quotes_and_trailing_punctuation(ai_client, fake_ollama):
    fake_ollama.librarian_reply = '"Welcome back!"'
    body = ai_client.get("/insights/greeting?block=morning").json()
    # Quotes gone, phrase clean, and the "!" preserved for the sentence end.
    assert body == {
        "greeting": "Welcome back",
        "punctuation": "!",
        "append_name": False,
        "source": "ai",
    }


def test_greeting_never_contains_a_name(ai_client, fake_ollama):
    # The endpoint returns a phrase only, the frontend adds the display name,
    # so a stored name must not leak into the API response.
    ai_client.put("/preferences", json={"display_name": "Brayden"})
    fake_ollama.librarian_reply = "Good morning"
    body = ai_client.get("/insights/greeting?block=morning").json()
    assert "Brayden" not in body["greeting"]


# --- tag cloud + heatmap ---------------------------------------------------------


def test_heatmap_counts_recent_notes(client):
    _save(client, "first note")
    _save(client, "second note")
    body = client.get("/insights/heatmap").json()
    assert body["days"] == len(body["counts"]) == 371
    assert body["total"] == 2
    # Today is the last bucket.
    assert body["counts"][-1] == 2
    assert body["busiest"] == 2


def test_tag_cloud_weights_by_frequency(client):
    _save(client, "note one", tags=["work", "ideas"])
    _save(client, "note two", tags=["work"])
    cloud = client.get("/insights/tag-cloud").json()
    assert cloud[0] == {"tag": "work", "count": 2}
    assert {"tag": "ideas", "count": 1} in cloud


def test_all_tags_is_not_rescanned_for_an_unchanged_notebook(client, monkeypatch, session):
    """Was a full non-deleted-entry scan + per-row json.loads, paid again on
    every Library tab open, every tag_cloud call, and every /tags call. Same
    fingerprint-cache pattern as routes_graph.py's pagerank: this pins that
    a second call within the same notebook version doesn't redo the scan."""
    from memorymap.entry import manager

    _save(client, "note one", tags=["work"])

    calls: list[int] = []
    original_scalars = session.scalars

    def counting_scalars(stmt, *a, **k):
        calls.append(1)
        return original_scalars(stmt, *a, **k)

    monkeypatch.setattr(session, "scalars", counting_scalars)
    manager.all_tags(session)
    first_call_count = len(calls)
    manager.all_tags(session)
    assert len(calls) == first_call_count, "all_tags rescanned an unchanged notebook"

    # ...and a new tag invalidates it, because a stale count is worse than a
    # slow one.
    _save(client, "note two", tags=["ideas"])
    manager.all_tags(session)
    assert len(calls) > first_call_count
    manager.reset_tag_cache()


def test_all_tags_cache_is_scoped_to_the_notebook_it_was_built_from(app_state, session):
    """The cache is process-global; restoring a backup must not be served
    the previous notebook's tag counts."""
    from memorymap.entry import manager

    fingerprint = manager._tag_fingerprint(session)
    assert str(app_state.data_dir) in fingerprint
    manager.reset_tag_cache()


# --- dashboard layout preference --------------------------------------------------


def test_dashboard_layout_roundtrip(client):
    layout = {"order": ["stats", "pinned"], "hidden": ["digest"]}
    updated = client.put("/preferences", json={"dashboard_layout": layout}).json()
    saved = updated["dashboard_layout"]
    assert saved["order"] == layout["order"]
    assert saved["hidden"] == layout["hidden"]
    # Both width encodings default to empty and round-trip.
    assert saved["wide"] == []
    assert saved["sizes"] == {}


def test_dashboard_layout_wide_widgets_persist(client):
    layout = {"order": ["stats"], "hidden": [], "wide": ["digest", "art"]}
    updated = client.put("/preferences", json={"dashboard_layout": layout}).json()
    assert updated["dashboard_layout"]["wide"] == ["digest", "art"]


def test_dashboard_layout_persists_legacy_widget_sizes(client):
    """Layouts saved before the switch to `wide` still round-trip."""
    layout = {"order": ["stats"], "hidden": [], "sizes": {"stats": "wide"}}
    updated = client.put("/preferences", json={"dashboard_layout": layout}).json()
    assert updated["dashboard_layout"]["sizes"] == {"stats": "wide"}
