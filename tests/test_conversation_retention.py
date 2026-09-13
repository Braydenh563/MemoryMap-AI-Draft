"""Chat history retention: the one collection in the app that grew forever.

Notes have had a recycle bin with a configurable auto-purge for a long time;
saved chats had no cap, no warning and nothing that would ever notice. These
tests pin the three decisions that make the feature safe rather than merely
present: it is off unless asked for, pinning protects a chat at any age, and
age is measured from the last time the thread was touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from memorymap.ai import autonomous
from memorymap.core import deps
from memorymap.core.database import Conversation


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


@pytest.fixture
def chats(app_state):
    """Four chats: ancient, ancient-but-pinned, recent, and ancient-but-touched."""
    db = deps.get_db()
    with db.session() as session:
        session.info["workspace_id"] = "all"
        session.add_all(
            [
                Conversation(title="ancient", messages="[]", created_at=_ago(400), updated_at=_ago(400)),
                Conversation(title="pinned", messages="[]", pinned=True, created_at=_ago(400), updated_at=_ago(400)),
                Conversation(title="recent", messages="[]", created_at=_ago(2), updated_at=_ago(2)),
                Conversation(title="revived", messages="[]", created_at=_ago(400), updated_at=_ago(1)),
            ]
        )
        session.commit()
    return db


def _titles(db) -> set[str]:
    with db.session() as session:
        session.info["workspace_id"] = "all"
        return {c.title for c in session.scalars(select(Conversation))}


def test_nothing_is_deleted_by_default(chats):
    """Off unless asked for. Deleting somebody's history because a background
    job decided it was old is exactly the behaviour a local-first notebook
    must not have."""
    assert autonomous.purge_old_conversations() == 0
    assert _titles(chats) == {"ancient", "pinned", "recent", "revived"}


def test_zero_days_means_keep_everything(chats):
    deps.get_config().set_preference("conversation_retention_days", 0)
    assert autonomous.purge_old_conversations() == 0
    assert len(_titles(chats)) == 4


def test_old_chats_go_once_a_retention_period_is_set(chats):
    deps.get_config().set_preference("conversation_retention_days", 30)
    assert autonomous.purge_old_conversations() == 1
    assert "ancient" not in _titles(chats)


def test_a_pinned_chat_survives_at_any_age(chats):
    """Pinning is the existing way to say "this one matters"; a retention rule
    that could delete it would make pinning useless."""
    deps.get_config().set_preference("conversation_retention_days", 1)
    autonomous.purge_old_conversations()
    assert "pinned" in _titles(chats)


def test_age_is_measured_from_the_last_message_not_the_first(chats):
    """A long-running thread added to yesterday is not an old conversation,
    however long ago it started."""
    deps.get_config().set_preference("conversation_retention_days", 30)
    autonomous.purge_old_conversations()
    assert "revived" in _titles(chats)
    assert "recent" in _titles(chats)


def test_the_purge_covers_every_space_not_just_the_active_one(app_state):
    """Maintenance runs over the database, not over a view of it. Without an
    explicit "all", the session's own workspace filter would scope the purge to
    whichever space happened to be active and let the others grow forever."""
    db = deps.get_db()
    with db.session() as session:
        session.info["workspace_id"] = "all"
        session.add_all(
            [
                Conversation(title="in-work", messages="[]", workspace_id="work",
                             created_at=_ago(400), updated_at=_ago(400)),
                Conversation(title="in-personal", messages="[]", workspace_id="personal",
                             created_at=_ago(400), updated_at=_ago(400)),
            ]
        )
        session.commit()
    deps.get_config().set_preference("conversation_retention_days", 30)
    assert autonomous.purge_old_conversations() == 2
    assert _titles(db) == set()


def test_the_preference_round_trips_through_the_api(client):
    """Item 4a in the roadmap was a preference that saved correctly and was
    honoured correctly and never came back from GET /preferences. Pinned here
    so this one cannot repeat it."""
    assert client.get("/preferences").json()["conversation_retention_days"] == 0
    client.put("/preferences", json={"conversation_retention_days": 90})
    assert client.get("/preferences").json()["conversation_retention_days"] == 90
