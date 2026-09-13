"""`list_documents`/`get_document`: the search preview and the plain
(no-embeddings) full read actually contain the search term, not just the
document's opening paragraph.

Reported directly: "if the ai is searching for something, might keywords be
flagged in certain pages of a file document in the actual document and/or
extracted text, then it can use a tool or smth simpler to get the full text
from those areas??" `list_documents` already found the right document (a
plain SQL `ILIKE` over the whole body), the preview it handed back was
always the document's first `PREVIEW_CHARS` characters regardless of where
the match was, and `get_document`'s own `query` argument only ranked
paragraphs when a working embedding backend was present, which CLAUDE.md
says this project runs without on purpose (no torch, no
sentence-transformers). Without one, a query used to fall straight through
to the same head-of-document clip as no query at all.
"""

from __future__ import annotations

from memorymap.ai import tools
from memorymap.ai.tools._common import DOCUMENT_CHARS, PREVIEW_CHARS
from memorymap.core import deps
from memorymap.core.database import Document


class _NoEmbeddings:
    """Stands in for `deps.get_embeddings()` on an install with no working
    backend: exactly the case CLAUDE.md says this project runs in by
    default (no torch, no sentence-transformers). The suite's own fixture
    backend (`tests/fakes.py`) is real enough to rank paragraphs, which
    would take the *better* path (`used_snippets=True`) rather than the one
    these two tests exist to pin, so it is swapped out deliberately, once,
    for the tests that need the fallback specifically."""

    def embed_text(self, text: str):  # noqa: ANN001, D102
        return None


def _doc(session, title="Untitled", content=""):
    row = Document(title=title, content=content)
    session.add(row)
    session.commit()
    return row


def test_the_tools_are_registered():
    assert "list_documents" in tools.TOOLS
    assert "get_document" in tools.TOOLS


def test_list_documents_preview_contains_the_matched_term(session):
    filler = "padding " * 100  # comfortably past PREVIEW_CHARS
    assert len(filler) > PREVIEW_CHARS
    _doc(session, "Meeting notes", f"{filler}the launch date is March 3rd{filler}")
    found = tools.TOOLS["list_documents"].handler(session, {"query": "launch date"})
    assert found["returned"] == 1
    assert "launch date is March 3rd" in found["documents"][0]["preview"]


def test_list_documents_with_no_query_keeps_the_head_of_document_preview(session):
    """Additive, not a replacement for the plain "list everything" case."""
    _doc(session, "Short one", "Hello, this is the start of a document.")
    found = tools.TOOLS["list_documents"].handler(session, {})
    assert found["documents"][0]["preview"] == "Hello, this is the start of a document."


def test_get_document_with_a_query_falls_back_to_the_matched_passage(session, monkeypatch):
    """The case CLAUDE.md describes as the project's default (no embedding
    backend): `q_vec` comes back `None`, and before this fix that meant a
    plain head-of-document clip with no regard for where, or whether, the
    term actually appeared."""
    monkeypatch.setattr(deps, "get_embeddings", _NoEmbeddings)
    filler = "the quick brown fox jumps over the lazy dog. " * 300
    assert len(filler) > DOCUMENT_CHARS
    doc = _doc(session, "Long report", f"{filler}THE BUDGET IS $4,471{filler}")
    read = tools.TOOLS["get_document"].handler(
        session, {"document_id": doc.id, "query": "budget"}
    )
    assert "THE BUDGET IS $4,471" in read["content"]
    assert "search term" in read["label"]


def test_get_document_with_a_query_that_does_not_appear_keeps_the_old_behaviour(session, monkeypatch):
    """A query for a word that is not in the document must not pretend it
    found something: falls back to the plain head-of-document clip, same
    as if no query had been given at all."""
    monkeypatch.setattr(deps, "get_embeddings", _NoEmbeddings)
    doc = _doc(session, "Doc", "Nothing relevant is written here at all.")
    read = tools.TOOLS["get_document"].handler(
        session, {"document_id": doc.id, "query": "xylophone"}
    )
    assert read["content"] == "Nothing relevant is written here at all."
    assert "search term" not in read["label"]


def test_get_document_with_no_query_is_unchanged(session):
    doc = _doc(session, "Doc", "Plain content, no query given.")
    read = tools.TOOLS["get_document"].handler(session, {"document_id": doc.id})
    assert read["content"] == "Plain content, no query given."
