"""Before and after for Brief 11's retrieval engine, on this sandbox.

Builds a 5,000-entry notebook in a throwaway data directory and times the two
paths against each other: what search did before this engine existed
(`search_manager.keyword_search` for words, `semantic_search` for meaning,
both entries-only) and what it does now (`engine.search`, `engine.related`).

Run: PYTHONPATH=src .venv/bin/python scratchpad/search/measure_engine.py
Numbers belong in the report as measured here, never as promises.
"""
from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ENTRIES = 5000


def timed(label, call, runs=7):
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        result = call()
        samples.append((time.perf_counter() - started) * 1000)
        size = len(result) if hasattr(result, "__len__") else 0
    median = statistics.median(samples)
    print(f"{label:<52} {median:7.1f} ms  (best {min(samples):6.1f}, worst {max(samples):6.1f}, hits {size})")
    return median


def main() -> None:
    from memorymap.core import deps

    with tempfile.TemporaryDirectory() as tmp:
        deps.reset_app_state()
        deps.init_app_state(data_dir=Path(tmp) / "data")
        from tests.fakes import FakeEmbeddingService

        fake = FakeEmbeddingService(available=True)
        deps.override_ai(embeddings=fake)

        from memorymap.ai.embeddings import vector_to_bytes
        from memorymap.core.database import EmbeddingRecord
        from memorymap.entry import manager
        from memorymap.search import engine, search_manager

        session = deps.get_db().session()
        built = time.perf_counter()
        for i in range(ENTRIES):
            manager.create_entry(
                session,
                f"note {i} about topic{i % 50} and thing{i % 7}",
                tags=[f"t{i % 9}"],
            )
        session.commit()
        print(f"fixture: {ENTRIES} entries in {time.perf_counter() - built:.1f}s")

        # A vector per note, so the "before" similarity path has something to
        # scan and the "after" matrix has something to hold. The fake backend
        # is 4-dimensional; a real one is 384, so the scan below is a
        # *generous* reading of the old path, not a pessimistic one.
        for entry in session.query(manager.Entry).all():
            vector = fake.embed_text(entry.content)
            session.add(
                EmbeddingRecord(
                    entry_id=entry.id,
                    embedding=vector_to_bytes(vector),
                    dim=int(vector.shape[0]),
                    model_version=fake.backend_id(),
                )
            )
        session.commit()
        print(f"index: {engine.index_counts(session)}")

        print("\nbefore (the paths this replaces)")
        timed("keyword_search, entries only", lambda: search_manager.keyword_search(session, "topic7 thing3", limit=20))
        timed("semantic_search, scans every vector", lambda: search_manager.semantic_search(session, "topic7 thing3", fake, limit=10))
        first = session.query(manager.Entry).first()
        timed("related, the old route body (semantic_search)", lambda: search_manager.semantic_search(session, first.content, fake, limit=4))

        print("\nafter (the engine)")
        engine.warm_vectors(session)
        timed("engine.search, keyword only", lambda: engine.search(session, "topic7 thing3", ctx=None, hybrid=False))
        timed("engine.search, hybrid", lambda: engine.search(session, "topic7 thing3", ctx=None))
        timed("engine.search, hybrid with an open note", lambda: engine.search(session, "topic7 thing3", ctx={"entry_id": first.id}))
        timed("engine.search, every kind, one word", lambda: engine.search(session, "topic7", ctx=None))
        timed("engine.related, from the matrix", lambda: engine.related(session, first.id, k=10))
        warm = time.perf_counter()
        engine._matrix = None
        engine.warm_vectors(session)
        print(f"{'matrix build (once per process)':<52} {(time.perf_counter() - warm) * 1000:7.1f} ms")
        session.close()
        deps.reset_app_state()


if __name__ == "__main__":
    main()
