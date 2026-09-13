"""Two writers wanting the same new category must not lose a note.

`get_or_create_category` is a check-then-insert, and this app genuinely has
several writers: the desktop window, a browser tab, and the night shift's
auto-filing all save notes. Two of them reaching an unseen category in the
same moment both see no row, both insert, and the loser hits `UNIQUE
constraint failed: categories.workspace_id, categories.name`, which surfaces
as a 500 and loses whatever was being saved.

Measured before the fix, with this test's own shape: 5 of 72 saves died.
A count rather than a timing, because the collision is what is being
asserted, not the speed.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from memorymap.core import deps
from memorymap.core.database import Category, Entry

WRITERS = 6
EACH = 12


@pytest.fixture()
def parallel_app(app_state):
    from memorymap.api.app import create_app
    from tests.fakes import FakeEmbeddingService, FakeOllama

    deps.override_ai(
        ollama=FakeOllama(running=False), embeddings=FakeEmbeddingService(available=False)
    )
    return create_app()


def test_concurrent_captures_all_survive(parallel_app):
    codes: list[int] = []
    raised: list[str] = []
    lock = threading.Lock()

    def writer(n: int) -> None:
        client = TestClient(parallel_app)
        for i in range(EACH):
            try:
                reply = client.post("/entries", json={"content": f"writer {n} note {i}"})
                with lock:
                    codes.append(reply.status_code)
            except Exception as exc:  # noqa: BLE001 - the failure being asserted against
                with lock:
                    raised.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(WRITERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not raised, f"a concurrent save raised instead of answering: {raised[:3]}"
    assert codes.count(201) == WRITERS * EACH, (
        f"{WRITERS * EACH - codes.count(201)} of {WRITERS * EACH} saves did not succeed: "
        f"{sorted(set(codes))}"
    )

    # And the category was made once, not once per writer that raced for it.
    with deps.get_db().session() as session:
        session.info["workspace_id"] = "default"
        names = session.scalars(select(Category.name)).all()
        assert len(names) == len(set(names)), f"a duplicate category survived: {names}"
        assert session.scalar(select(func.count()).select_from(Entry)) == WRITERS * EACH


def test_storing_a_vector_twice_replaces_it_rather_than_raising(session):
    """`store_for_entry` is named for a result, not for an insert.

    `embeddings.entry_id` is unique, so a second call for the same note
    raised `UNIQUE constraint failed: embeddings.entry_id` and took whatever
    was saving down with it. Nothing was broken in practice: all four callers
    already delete the old row first, or select only notes that have none.
    That duplicated guard was the bug waiting to happen, because the next
    caller has to know to write it and the method's name says it does not.
    """
    from sqlalchemy import func

    from memorymap.core.database import EmbeddingRecord
    from memorymap.entry import manager
    from tests.fakes import FakeEmbeddingService

    entry = manager.create_entry(session, "a note about gardens", tags=[])
    session.commit()
    service = FakeEmbeddingService(available=True)

    assert service.store_for_entry(session, entry) is True
    assert service.store_for_entry(session, entry) is True
    assert session.scalar(select(func.count()).select_from(EmbeddingRecord)) == 1
