import re

from fastapi import APIRouter, Depends, HTTPException

from memorymap.api.schemas import SpaceResponse, SpaceCreate, SpaceUpdate
from memorymap.core import deps
from memorymap.core.database import Category, Entry, Space, workspace_scoped_models
from memorymap.core.deps import get_session, impersonate_workspace
from sqlalchemy.orm import Session

router = APIRouter(tags=["Spaces"])

# "all" is the frontend's "show every space" sentinel and "default" is the
# fallback delete_space reassigns orphaned rows to, a user-created space
# with either id would break both, so neither can ever be created or deleted.
RESERVED_SPACE_IDS = {"all", "default"}

# Phosphor icon names only. The frontend does `class="ph " + icon` with no
# escaping, so an unvalidated icon is a CSS class injection into the page.
_ICON_RE = re.compile(r"^ph-[a-z0-9-]{1,40}$")

_MAX_NAME_LEN = 60


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:49] or "space"


def _generate_space_id(name: str, session: Session) -> str:
    """Server-generated id: slugify(name), de-duplicated with a numeric
    suffix. Chosen over validating a client-supplied id because the
    reserved-sentinel and charset rules a client id would need are exactly
    the rules a generated-and-deduped slug satisfies for free."""
    base = _slugify(name)
    existing = {row[0] for row in session.query(Space.id).all()}
    candidate = base
    n = 2
    while candidate in RESERVED_SPACE_IDS or candidate in existing:
        suffix = f"-{n}"
        candidate = f"{base[: 49 - len(suffix)]}{suffix}"
        n += 1
    return candidate


def _validate_icon(icon: str) -> str:
    if not _ICON_RE.match(icon):
        raise HTTPException(400, "icon must match ^ph-[a-z0-9-]{1,40}$")
    return icon


def _validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(400, "name must not be empty")
    if len(name) > _MAX_NAME_LEN:
        raise HTTPException(400, f"name must be at most {_MAX_NAME_LEN} characters")
    return name


@router.get("/spaces", response_model=list[SpaceResponse])
def get_spaces(session: Session = Depends(get_session)):
    return session.query(Space).all()


@router.post("/spaces", response_model=SpaceResponse)
def create_space(space_in: SpaceCreate, session: Session = Depends(get_session)):
    # space_in.id is intentionally never read, see SpaceCreate.id's docstring.
    name = _validate_name(space_in.name)
    icon = _validate_icon(space_in.icon)
    space_id = _generate_space_id(name, session)
    space = Space(id=space_id, name=name, icon=icon)
    session.add(space)
    session.commit()
    session.refresh(space)
    return space


@router.put("/spaces/{space_id}", response_model=SpaceResponse)
def update_space(space_id: str, space_in: SpaceUpdate, session: Session = Depends(get_session)):
    space = deps.get_or_404(session, Space, space_id, "Space not found")
    # Only fields the caller actually sent are applied, so an omitted field
    # doesn't get overwritten with None (SpaceUpdate's fields are optional).
    provided = space_in.model_dump(exclude_unset=True)
    if "name" in provided:
        space.name = _validate_name(provided["name"])
    if "icon" in provided:
        space.icon = _validate_icon(provided["icon"])
    if "hidden_from_all" in provided:
        # "default" is where a deleted space's notes land, so hiding it would
        # quietly empty the everything-view of anything that ever fell back
        # to it: refused for the same reason it cannot be deleted.
        if space.id == "default" and provided["hidden_from_all"]:
            raise HTTPException(
                status_code=400,
                detail="The default space cannot be hidden from All spaces.",
            )
        space.hidden_from_all = bool(provided["hidden_from_all"])
    session.commit()
    session.refresh(space)
    return space


@router.delete("/spaces/{space_id}", response_model=SpaceResponse)
def delete_space(space_id: str, session: Session = Depends(get_session)):
    if space_id in RESERVED_SPACE_IDS:
        raise HTTPException(400, "Cannot delete default spaces")
    space = deps.get_or_404(session, Space, space_id, "Space not found")

    # Capture the response body before deleting: reading attributes off an
    # instance after session.delete()+commit() raises ObjectDeletedError,
    # since SQLAlchemy expires it and then finds no row to refresh from.
    response = SpaceResponse.model_validate(space)

    # **Deleting a space deletes what was in it.** Asked for directly: "make
    # sure that if a specific space is deleted too, that all the content
    # including notes files and images etc originating in that specific
    # space get deleted with it as well." This used to *reassign* every row
    # to "default", which is the opposite of what the word means, the notes
    # did not go away, they turned up in another space.
    #
    # impersonate_workspace(..., "all") disables the session's ambient
    # workspace filter for this block: a request carrying X-Workspace-ID for
    # some *other* space would otherwise AND that id into every DELETE, so
    # deleting "personal" while browsing "work" would remove nothing.
    #
    # Dependents before their parents, because the foreign keys are real
    # (a document delete once failed outright on its revisions). Files on
    # disk are unlinked after the commit: a row that is gone and a file that
    # is still there is recoverable; the reverse is not.
    from pathlib import Path

    from memorymap.core.database import (
        AskTurn, Attachment, Bookmark, Conversation, Document, DocumentAiEdit,
        DocumentBookmark, DocumentLink, DocumentRevision, EmbeddingRecord,
        EntityMention, EntryBookmark, EntryDate, EntryLink, EntryRevision, MediaUpload,
        PageRead, Reminder, WhiteboardNode, WhiteboardObject, WhiteboardSketch,
    )

    config = deps.get_config()
    to_unlink: list[Path] = []
    with impersonate_workspace(session, "all"):
        def rows(model):
            return session.query(model).filter_by(workspace_id=space_id)

        attachment_ids = [a.id for a in rows(Attachment).all()]
        to_unlink += [config.uploads_dir / a.stored_name for a in rows(Attachment).all()]
        upload_ids = [u.id for u in rows(MediaUpload).all()]
        to_unlink += [config.data_dir / "media" / u.filename for u in rows(MediaUpload).all()]
        document_ids = [d.id for d in rows(Document).all()]
        entry_ids = [e.id for e in rows(Entry).all()]
        bookmark_ids = [b.id for b in rows(Bookmark).all()]

        # The unscoped side tables: no workspace column of their own, only a
        # foreign key into a row that is about to go. Each is the table a
        # plain DELETE of its parent tripped over (real FKs, enforced).
        def purge(model, column, ids):
            if ids:
                session.query(model).filter(column.in_(ids)).delete(synchronize_session=False)

        for model, column in (
            (EntityMention, EntityMention.entry_id),
            (EmbeddingRecord, EmbeddingRecord.entry_id),
            (EntryRevision, EntryRevision.entry_id),
            (EntryDate, EntryDate.entry_id),
            (EntryBookmark, EntryBookmark.entry_id),
            (DocumentLink, DocumentLink.entry_id),
        ):
            purge(model, column, entry_ids)
        for model, column in (
            (DocumentBookmark, DocumentBookmark.document_id),
            (DocumentLink, DocumentLink.document_id),
            (DocumentAiEdit, DocumentAiEdit.document_id),
        ):
            purge(model, column, document_ids)
        purge(EntryBookmark, EntryBookmark.bookmark_id, bookmark_ids)
        purge(DocumentBookmark, DocumentBookmark.bookmark_id, bookmark_ids)

        # A note in *another* space can point at one of this space's
        # categories (the reason the old reassign code merged categories by
        # name). Those notes are not ours to delete; they just lose the
        # pointer, the same as if the category had been deleted on its own.
        category_ids = [c.id for c in rows(Category).all()]
        if category_ids:
            session.query(Entry).filter(Entry.category_id.in_(category_ids)).update(
                {"category_id": None}, synchronize_session=False
            )

        if attachment_ids:
            session.query(PageRead).filter(
                PageRead.kind == "attachment", PageRead.source_id.in_(attachment_ids)
            ).delete(synchronize_session=False)
        if upload_ids:
            session.query(PageRead).filter(
                PageRead.kind == "media", PageRead.source_id.in_(upload_ids)
            ).delete(synchronize_session=False)
        if document_ids:
            session.query(DocumentRevision).filter(
                DocumentRevision.document_id.in_(document_ids)
            ).delete(synchronize_session=False)

        for model in (
            EntryLink, Attachment, AskTurn, Conversation, Reminder, Bookmark,
            WhiteboardSketch, WhiteboardObject, WhiteboardNode, Document,
            Entry, Category, MediaUpload,
        ):
            rows(model).delete(synchronize_session=False)

        # Anything with WorkspaceMixin that the ordered list above does not
        # name: a model added later must not survive its space.
        for model in workspace_scoped_models():
            rows(model).delete(synchronize_session=False)

    session.delete(space)
    session.commit()
    for path in to_unlink:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # the row is gone; a stray file is the recoverable failure
    return response
