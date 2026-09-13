"""The user's clock: stored in UTC everywhere, but reasoned about (and
displayed) in whichever zone they set, not the server's.

(The reminder-list-specific case of this, a naive DateTime column losing its
offset on the way back from disk, has its own reported-bug writeup in
test_reminder_times.py/test_reminders_api.py; this file covers the
preference itself and the other places the same guarantee has to hold:
entry timestamps and the agent's prompt.)
"""

from __future__ import annotations


def test_entry_timestamps_are_marked_as_utc_too(client):
    """The same column type backs every table, so the guarantee is app-wide."""
    from datetime import datetime

    client.post("/entries", json={"content": "a note"})
    entry = client.get("/entries").json()[0]
    value = entry["created_at"]
    assert value.endswith("Z") or "+" in value[10:], value
    assert datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None


def test_timezone_preference_drives_the_users_clock(client):
    """"In ten minutes" has to mean ten minutes on the USER's clock.

    Storage stays UTC, a notebook must survive its owner changing timezone , 
    but anything the AI reasons about in time is resolved against the zone the
    browser reported, because the server may be running in UTC while the person
    is in Brisbane.
    """
    from memorymap.core import deps
    from memorymap.core.config import user_now

    assert client.put("/preferences", json={"timezone": "Australia/Brisbane"}).status_code == 200
    assert client.get("/preferences").json()["timezone"] == "Australia/Brisbane"

    now = user_now(deps.get_config())
    assert now.utcoffset().total_seconds() == 10 * 3600  # AEST, no DST


def test_an_unknown_timezone_is_refused(client):
    """A bad zone name would otherwise sit in preferences failing silently."""
    assert client.put("/preferences", json={"timezone": "Middle/Earth"}).status_code == 422


def test_no_timezone_falls_back_to_the_server_clock(client):
    """The ordinary case, app and browser on one machine, must need no setup."""
    from memorymap.core import deps
    from memorymap.core.config import user_now

    assert client.get("/preferences").json()["timezone"] == ""
    assert user_now(deps.get_config()).tzinfo is not None


def test_the_agent_is_told_the_users_local_time(client):
    """The prompt line that "remind me in 10 minutes" is computed from."""
    from memorymap.ai import agent

    client.put("/preferences", json={"timezone": "Australia/Brisbane"})
    messages = agent.build_agent_messages("remind me in 10 minutes", [])
    system = messages[0]["content"]
    assert "The current date and time is" in system
    assert "+10:00" in system


def test_agent_prompt_includes_current_time_and_reminder_hint():
    """The other half of the same line: it also has to point at the tool
    that acts on it, or the model knows the time and not what to do with it."""
    from memorymap.ai import agent

    messages = agent.build_agent_messages("remind me to fold washing in 10 minutes", [])
    system = messages[0]["content"]
    assert "current date and time is" in system
    assert "set_reminder" in system
