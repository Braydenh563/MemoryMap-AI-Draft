"""Preferences, plus the manual-override/linking/audit/export routes that
don't have a larger domain file of their own.

(Auth flow moved to test_account.py, recycle-bin tests to
test_recycle_bin.py: same domain as their other coverage.)"""

from __future__ import annotations

import csv
import io
import sys

from memorymap.core import deps


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


# --- manual overrides -----------------------------------------------------------


def test_edit_entry_content_category_tags(client):
    entry = _save(client, "a note the AI got wrong")
    response = client.put(
        f"/entries/{entry['id']}",
        json={"content": "corrected note", "category": "Jokes", "tags": ["fixed"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "corrected note"
    assert body["category"] == "Jokes"  # created on the fly
    assert body["tags"] == ["fixed"]


def test_guided_entry_skips_janitor(ai_client, fake_ollama):
    calls_before = len(fake_ollama.chat_calls)
    entry = _save(ai_client, "definitely a recipe", category="Recipes")
    assert entry["category"] == "Recipes"
    assert entry["filed_by"] == "user"
    assert entry["ai_confidence"] == 100
    assert len(fake_ollama.chat_calls) == calls_before  # AI never consulted


# --- linking ---------------------------------------------------------------------


def test_link_and_unlink_entries(client):
    first = _save(client, "the joke about cheese")
    second = _save(client, "heard at Dave's party")

    linked = client.post(f"/entries/{first['id']}/links", json={"target_id": second["id"]})
    assert linked.status_code == 200
    links = linked.json()["links"]
    assert len(links) == 1 and links[0]["entry_id"] == second["id"]

    # Both directions see it; duplicates (either way) are rejected.
    assert client.get(f"/entries/{second['id']}").json()["links"][0]["entry_id"] == first["id"]
    dup = client.post(f"/entries/{second['id']}/links", json={"target_id": first["id"]})
    assert dup.status_code == 400
    assert (
        client.post(f"/entries/{first['id']}/links", json={"target_id": first["id"]}).status_code
        == 400
    )

    unlinked = client.delete(f"/entries/{first['id']}/links/{links[0]['link_id']}")
    assert unlinked.json()["links"] == []


# --- audit, export, preferences ---------------------------------------------------


def test_audit_viewer_lists_actions(client):
    entry = _save(client, "watch me get logged")
    client.delete(f"/entries/{entry['id']}")
    actions = [row["action"] for row in client.get("/audit").json()]
    assert "created" in actions and "deleted" in actions
    # Newest first.
    assert actions[0] == "deleted"


def test_clearing_the_audit_log_only_removes_the_named_entity_type(client):
    """The AI Skills sidebar's own "Clear" button: asked for directly. Scoped
    to one entity_type at a time on purpose: this must never be a way to
    wipe the whole audit trail (note edits/deletes are real accountability
    history), only the one filtered slice the caller names."""
    entry = _save(client, "an ordinary note")
    client.delete(f"/entries/{entry['id']}")
    before = client.get("/audit").json()
    assert any(row["entity_type"] == "entry" for row in before)

    response = client.delete("/audit?entity_type=skill")
    assert response.status_code == 200
    assert response.json() == {"deleted": 0}

    # Nothing about the entry's own audit trail was touched.
    after = [row["action"] for row in client.get("/audit").json()]
    assert "created" in after and "deleted" in after


def test_clearing_the_audit_log_requires_an_entity_type(client):
    response = client.delete("/audit")
    assert response.status_code == 422


def test_export_json_includes_binned_entries(client):
    keep = _save(client, "keeper", tags=["a"])
    binned = _save(client, "binned")
    client.delete(f"/entries/{binned['id']}")

    body = client.get("/export/json").json()
    by_id = {e["id"]: e for e in body["entries"]}
    assert by_id[keep["id"]]["is_deleted"] is False
    assert by_id[binned["id"]]["is_deleted"] is True
    assert by_id[keep["id"]]["tags"] == ["a"]


def test_export_csv_parses(client):
    _save(client, 'tricky "quoted, csv" content')
    response = client.get("/export/csv")
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:3] == ["id", "content", "category"]
    assert rows[1][1] == 'tricky "quoted, csv" content'


def test_preferences_roundtrip(client):
    assert client.get("/preferences").json()["recycle_bin_days"] == 30
    updated = client.put(
        "/preferences", json={"recycle_bin_days": 7, "communication_style": "concise"}
    ).json()
    assert updated["recycle_bin_days"] == 7
    assert updated["communication_style"] == "concise"
    # Persisted for real.
    assert deps.get_config().get_preference("recycle_bin_days") == 7


def test_display_name_preference_roundtrip(client):
    assert client.get("/preferences").json()["display_name"] == ""
    updated = client.put("/preferences", json={"display_name": "Brayden"}).json()
    assert updated["display_name"] == "Brayden"
    assert deps.get_config().get_preference("display_name") == "Brayden"
    # An empty string clears it (not excluded like None).
    assert client.put("/preferences", json={"display_name": ""}).json()["display_name"] == ""
    # Over-long names are rejected.
    assert client.put("/preferences", json={"display_name": "x" * 61}).status_code == 422


def test_preferences_validated(client):
    assert client.put("/preferences", json={"recycle_bin_days": 0}).status_code == 422
    assert (
        client.put("/preferences", json={"communication_style": "sarcastic"}).status_code
        == 422
    )


# --- console mode (Dev view / User view) -------------------------------------------


def test_show_console_on_startup_defaults_to_dev_view(client):
    """A fresh install starts on "Dev view" (console visible): asked for
    directly, reversing an earlier default in this same app. "User view"
    is the one a person opts into, via the first-run prompt or Settings."""
    assert client.get("/preferences").json()["show_console_on_startup"] is True


def test_console_mode_route_saves_the_preference_even_off_the_desktop_app(client):
    """Not running as the desktop app (no MEMORYMAP_DESKTOP=1, which the
    test client never sets), still saves the preference for next launch,
    just doesn't try to restart anything live."""
    body = client.post(
        "/system/console-mode", json={"show_console_on_startup": False}
    ).json()
    assert body == {"show_console_on_startup": False, "restarting": False}
    assert deps.get_config().get_preference("show_console_on_startup") is False


def test_console_mode_route_does_not_restart_when_nothing_actually_changed(
    client, monkeypatch
):
    """Picking the option that already matches the current mode, the
    common case for the first-run intro prompt, since Dev view is already
    the default it's asking about: must not trigger a restart. A route
    that always restarts on any POST would bounce the app the user just
    opened for confirming a choice they hadn't changed."""
    # Imported (and, transitively, uvicorn along with it, memorymap.__main__
    # does `import uvicorn` at module level) BEFORE sys.platform is patched
    # below: this is the same module the route imports lazily, and if THIS
    # is the first time anything in the whole test session imports it, doing
    # so while sys.platform lies about being "win32" makes uvicorn.server's
    # own module-level `signal.SIGBREAK` reference: real on Windows, absent
    # on Linux: blow up at import time, taking every test after this one
    # down with a confusing unrelated-looking collection error.
    import memorymap.__main__  # noqa: F401

    monkeypatch.setenv("MEMORYMAP_DESKTOP", "1")
    monkeypatch.setattr(sys, "platform", "win32")
    restarted = []
    monkeypatch.setattr(
        "memorymap.__main__.restart_in_console_mode",
        lambda hidden: restarted.append(hidden),
    )

    # Preference already defaults to True, asking for True again is a no-op.
    body = client.post(
        "/system/console-mode", json={"show_console_on_startup": True}
    ).json()
    assert body["restarting"] is False
    assert restarted == []

    # Actually changing it does restart.
    body = client.post(
        "/system/console-mode", json={"show_console_on_startup": False}
    ).json()
    assert body["restarting"] is True
    assert restarted == [True]  # hidden=True, since show_console_on_startup is now False


def test_restart_route_is_a_no_op_off_the_desktop_app(client):
    """ROADMAP item C's "second caller", not tied to any preference
    changing. Same platform gate as /system/console-mode: nothing to
    restart into off the desktop app, so it says so rather than pretending."""
    body = client.post("/system/restart").json()
    assert body == {"restarting": False}


def test_restart_route_restarts_on_the_desktop_app(client, monkeypatch):
    """The mechanism is the same one console-mode switching already uses, 
    this call just doesn't change what it's restarting into."""
    import memorymap.__main__  # noqa: F401  # see the console-mode test above

    monkeypatch.setenv("MEMORYMAP_DESKTOP", "1")
    monkeypatch.setattr(sys, "platform", "win32")
    restarted = []
    monkeypatch.setattr(
        "memorymap.__main__.restart_in_console_mode",
        lambda hidden: restarted.append(hidden),
    )

    body = client.post("/system/restart").json()
    assert body == {"restarting": True}
    # hidden=False because show_console_on_startup defaults to True and this
    # restart doesn't touch it: restart_in_console_mode's own `hidden`
    # param is "hide the console," the inverse of "show it."
    assert restarted == [False]


def test_autonomous_and_battery_preferences_round_trip_through_get(client):
    """`get_preferences()` is a hand-built dict, and eight keys, every
    Autonomous Background Workers toggle, the battery mode switch, and smart
    model routing: were settable and correctly *honoured* (`autonomous.py`
    and `model_manager.py` both read them straight from storage) but never
    once echoed back here. Every Settings checkbox bound to one of them
    showed unchecked again the moment the page reloaded, regardless of what
    had actually been saved and was actually in effect."""
    client.put(
        "/preferences",
        json={
            "autonomous_tasks_enabled": True,
            "auto_tag_enabled": False,
            "auto_link_enabled": False,
            "auto_dedupe_enabled": False,
            "auto_stale_review_enabled": True,
            "autonomous_tasks_interval_hours": 2,
            "autonomous_tasks_model": "phi3.5",
            "battery_efficient_mode": True,
            "smart_model_routing_enabled": False,
        },
    )
    fresh = client.get("/preferences").json()
    assert fresh["autonomous_tasks_enabled"] is True
    assert fresh["auto_tag_enabled"] is False
    assert fresh["auto_link_enabled"] is False
    assert fresh["auto_dedupe_enabled"] is False
    assert fresh["auto_stale_review_enabled"] is True
    assert fresh["autonomous_tasks_interval_hours"] == 2
    assert fresh["autonomous_tasks_model"] == "phi3.5"
    assert fresh["battery_efficient_mode"] is True
    assert fresh["smart_model_routing_enabled"] is False


def test_auto_stale_review_preference_was_silently_dropped_before_this_fix(client):
    """The checkbox (#pref-auto-stale-review) called setPreference exactly
    like its tag/link/dedupe siblings, but PreferencesBody never declared
    this field: so the PUT below returned 200 while quietly discarding the
    value, and `config.get_preference("auto_stale_review_enabled")`, which
    `autonomous.py`'s optimisation pass actually reads, stayed False no
    matter what the checkbox showed. Asserting the config layer directly
    (not just the GET echo, which the round-trip test above already covers)
    is what would have caught the original bug: the field simply never
    reached `body.model_dump()` to be saved at all."""
    from memorymap.core import deps

    assert deps.get_config().get_preference("auto_stale_review_enabled", False) is False
    client.put("/preferences", json={"auto_stale_review_enabled": True})
    assert deps.get_config().get_preference("auto_stale_review_enabled") is True


def test_session_idle_ttl_minutes_round_trips_through_get(client):
    """Was settable and honoured (routes_auth.py's idle-timeout checks all
    read it) but never echoed back, Settings -> Account showed its HTML
    default on every reload no matter what had actually been saved."""
    assert client.get("/preferences").json()["session_idle_ttl_minutes"] == 720
    client.put("/preferences", json={"session_idle_ttl_minutes": 30})
    assert client.get("/preferences").json()["session_idle_ttl_minutes"] == 30


def test_response_mode_was_silently_dropped_before_this_fix(client):
    """setResponseMode (app.js) PUTs response_mode on every pick in the
    Quick/Normal/Detailed dropdown, but PreferencesBody never declared the
    field: same shape as auto_stale_review_enabled above. The dropdown
    itself updates its own <select> client-side regardless of whether the
    save actually worked, so this was invisible until the next reload
    silently reverted to the default."""
    from memorymap.ai import presets
    from memorymap.core import deps

    assert deps.get_config().get_preference("response_mode", presets.DEFAULT_MODE) == "normal"
    client.put("/preferences", json={"response_mode": "detailed"})
    assert deps.get_config().get_preference("response_mode") == "detailed"
    # And the echo, and the route the frontend actually reads the active
    # mode from (loadResponseModes -> GET /chat/modes -> _resolve_mode).
    assert client.get("/preferences").json()["response_mode"] == "detailed"
    assert client.get("/chat/modes").json()["active"] == "detailed"


def test_response_mode_rejects_an_unknown_value(client):
    response = client.put("/preferences", json={"response_mode": "extremely-verbose"})
    assert response.status_code == 422


def test_notification_mute_preference_round_trips_through_get(client):
    assert client.get("/preferences").json()["notifications_muted_except_reminders"] is False
    client.put("/preferences", json={"notifications_muted_except_reminders": True})
    assert client.get("/preferences").json()["notifications_muted_except_reminders"] is True


def test_saving_an_autonomous_preference_wakes_the_scheduler(client, monkeypatch):
    """Battery mode, the on/off toggle and the interval used to only be read
    once per scheduled tick, up to six hours away, so switching one off
    (or back on) silently did nothing until then. Saving one now has to wake
    the loop so the change is read on the very next tick."""
    from memorymap.ai import autonomous

    woken = []
    monkeypatch.setattr(autonomous, "wake", lambda: woken.append(True))

    client.put("/preferences", json={"battery_efficient_mode": True})
    assert woken == [True]

    woken.clear()
    client.put("/preferences", json={"display_name": "unrelated change"})
    assert woken == []
