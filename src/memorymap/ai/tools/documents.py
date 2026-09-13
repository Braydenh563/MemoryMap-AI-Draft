"""AI tool handlers for the Documents tab: list/get/create/delete.

Split out of `ai/tools.py`'s "documents, past chats, and skills" section
(ROADMAP.md §0/§4): this is the documents quarter of it; whiteboard and
skills/chat-history handlers live in their own modules alongside it.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.entry import manager

from ._common import (
    DEFAULT_LIST_LIMIT,
    DOCUMENT_CHARS,
    PREVIEW_CHARS,
    ToolError,
    _clip,
    _keyword_context,
    _limit_arg,
)

def _list_documents(session: Session, args: dict) -> dict:
    from memorymap.core.database import LIKE_ESCAPE, Document, like_escape

    limit = _limit_arg(args, default=DEFAULT_LIST_LIMIT)
    offset = max(0, int(args.get("offset") or 0))
    term = str(args.get("query") or "").strip()
    # One list of filters, applied to both the page and the count, so the
    # total can never describe a different set than the rows.
    filters = []
    if term:
        like = f"%{like_escape(term)}%"
        filters.append(
            Document.title.ilike(like, escape=LIKE_ESCAPE)
            | Document.content.ilike(like, escape=LIKE_ESCAPE)
        )
    total = session.scalar(select(func.count(Document.id)).where(*filters)) or 0
    rows = list(
        session.scalars(
            select(Document)
            .where(*filters)
            .order_by(Document.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return {
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "words": len(d.content.split()),
                "updated_at": d.updated_at.isoformat(),
                #: **Around the match, not the start of the document.**
                #: Reported directly: "if the ai is searching for something,
                #: might keywords be flagged in certain pages... then it can
                #: use a tool or smth simpler to get the full text from
                #: those areas." This used to be `_clip(d.content,
                #: PREVIEW_CHARS)` regardless of `term`, so a search that
                #: correctly found a 40-page document because the word
                #: appeared on page 30 showed the model page one, which very
                #: likely does not mention it at all. `_keyword_context`
                #: falls back to the same head-of-document clip when there
                #: is no term (the plain "list everything" case), so this is
                #: strictly an improvement, never a behaviour change for a
                #: bare list.
                "preview": _keyword_context(d.content, term, length=PREVIEW_CHARS),
            }
            for d in rows
        ],
        "returned": len(rows),
        "total_matching": total,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "how_to_read_more": (
            "Previews only. Call get_document with an id to read one in full."
        ),
        "label": f"ph:books Listed documents{f' matching “{_clip(term, 30)}”' if term else ''}",
    }


def _get_document(session: Session, args: dict) -> dict:
    from memorymap.core.database import Document
    from memorymap.core import deps

    document = session.get(Document, int(args["document_id"]))
    if document is None:
        raise ToolError(f"No document with id {args.get('document_id')}")
    text = document.content

    query = args.get("query")
    clipped = None
    used_snippets = False
    if query:
        # A long document blows out the model's context; when the agent
        # already knows what it's looking for, rank paragraph chunks by
        # similarity to the query and hand back only the best few instead
        # of a plain head-of-document truncation.
        from memorymap.ai.embeddings import cosine_similarity

        embeddings = deps.get_embeddings()
        chunks = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 20]
        if chunks:
            q_vec = embeddings.embed_text(query)
            if q_vec is not None:
                chunk_vecs = [embeddings.embed_text(c) for c in chunks]
                scored = [
                    (cosine_similarity(q_vec, cv), c)
                    for cv, c in zip(chunk_vecs, chunks)
                    if cv is not None
                ]
                if scored:
                    scored.sort(key=lambda x: x[0], reverse=True)
                    best_chunks = [c for _, c in scored[:3]]
                    clipped = "\n\n...\n\n".join(best_chunks)
                    used_snippets = True
    used_keyword_fallback = False
    if clipped is None and query and query.strip().lower() in text.lower():
        #: **The "or something simpler" this was asked for, by name.** The
        #: embedding path above needs a working embedding backend
        #: (`deps.get_embeddings()`), and CLAUDE.md is explicit that this
        #: project runs without one on purpose, no torch, no
        #: sentence-transformers: so `q_vec` is `None` there on every
        #: install that followed that instruction, and this used to fall
        #: straight through to a plain head-of-document clip: exactly the
        #: "keyword found the document, the returned text does not contain
        #: it" gap reported directly. A literal substring search around the
        #: query costs nothing extra to try before giving up to the
        #: head-clip, and it is the one path this tool has that works with
        #: no model and no embeddings at all.
        clipped = _keyword_context(text, query, radius=900, max_hits=4, length=DOCUMENT_CHARS)
        used_keyword_fallback = True
    if clipped is None:
        clipped = _clip(text, DOCUMENT_CHARS)

    return {
        "id": document.id,
        "title": document.title,
        "content": clipped,
        "truncated": len(clipped) < len(text),
        "words": len(text.split()),
        "label": f"ph:file-text Read the document “{_clip(document.title, 40)}”"
        + (
            " (extracted snippets for query)"
            if used_snippets
            else " (text around your search term)"
            if used_keyword_fallback
            else ""
        ),
    }


#: A document the agent writes. Generous next to a note's cap because a
#: document is long-form by definition, but still a cap, since the content
#: comes back through the model's own output and an unbounded one would mean a
#: single tool call could fill the window on the next round.
MAX_NEW_DOCUMENT_CHARS = 20_000


def _create_document(session: Session, args: dict) -> dict:
    """Write a long-form document.

    The asymmetry this closes: there was `list_documents` and `get_document`
    and no way to make one, so a model asked to "write this up properly" could
    read every document the user had and then had nowhere to put the result.
    Reported directly, "the agent can't create a document either" (§35J) , 
    and it was a gap nobody noticed rather than a deliberate limit, because
    §5's document work was built UI-first.

    Deliberately a separate tool from `create_note` rather than a flag on it.
    A note is a captured thought and a document is something you sat down to
    write; the database keeps them apart precisely so half-written documents
    do not turn up in search results and in the graph, and one tool covering
    both would hand the model the decision that separation exists to make.
    """
    from memorymap.core.database import Document

    title = str(args.get("title") or "").strip()[:200]
    content = str(args.get("content") or "")
    if not title:
        raise ToolError("A document needs a title.")
    if not content.strip():
        # A titled empty document is the shape of a model that called the tool
        # to announce its intention. Refusing is what makes it write first.
        raise ToolError(
            "A document needs its text in `content`, write the document, then "
            "save it in one call."
        )
    if len(content) > MAX_NEW_DOCUMENT_CHARS:
        raise ToolError(
            f"That document is too long to save in one call "
            f"({len(content):,} characters, limit {MAX_NEW_DOCUMENT_CHARS:,})."
        )
    document = Document(title=title, content=content)
    session.add(document)
    session.flush()
    manager.log_action(session, "created", "document", document.id, title[:80])
    session.commit()
    return {
        "id": document.id,
        "title": document.title,
        "words": len(content.split()),
        "label": f"ph:file-text Created the document “{_clip(title, 40)}”",
        # Same contract every other write follows, so the run summary can offer
        # an Undo beside it rather than listing a change nobody can take back.
        "undo": {"tool": "delete_document", "arguments": {"document_id": document.id}},
    }


def _delete_document(session: Session, args: dict) -> dict:
    """Remove a document. Destructive, so the user confirms it first.

    Exists mainly so `create_document` has an inverse: §21 lists "links and
    reminders have no inverse tool" as a real cost, and shipping a new write
    without one would be adding to that list rather than working it down.
    """
    from memorymap.core.database import Document

    document = session.get(Document, int(args.get("document_id") or 0))
    if document is None:
        raise ToolError(f"No document with id {args.get('document_id')}")
    title = document.title
    session.delete(document)
    manager.log_action(session, "deleted", "document", None, title[:80])
    session.commit()
    return {"title": title, "label": f"ph:trash Deleted the document “{_clip(title, 40)}”"}


