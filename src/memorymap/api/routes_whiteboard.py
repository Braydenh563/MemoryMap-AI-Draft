"""Whiteboard: note cards and freehand sketches placed on a canvas.

A "board" is itself a note (`board_id` points at an entry), so a board is
something you can search, tag and file like anything else in the notebook, 
and `board_id = NULL` is the one unnamed scratch board every notebook starts
with.

Two rules run through all of it, both learned by their absence in the first
version:

- **A node has to point at a note that exists.** Nothing validated `entry_id`,
  so a card could be created for note 9999 and the board would then fail to
  render for good, with no way to remove the card from the UI.
- **A write has to be scoped to the board it claims.** `PUT`/`DELETE` took an
  id and nothing else, so any node on any board could be moved or deleted by
  guessing a number: and `PUT` silently ignored `board_id`, so "move this
  card to that board" quietly did nothing at all.
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from memorymap.core import deps, events
from memorymap.core.database import Entry, WhiteboardNode, WhiteboardObject, WhiteboardSketch
from memorymap.core.deps import get_session
from memorymap.entry.manager import apply_title, extract_title, update_entry

router = APIRouter(prefix="/whiteboard", tags=["whiteboard"])

#: An image object's `data.url`, as an allowlist rather than a prefix check.
#:
#: **A `startswith("/media/")` test is not enough, and the difference is a
#: file-deletion vulnerability.** `delete_object` removes the backing file
#: when an image object goes, and `/media/../../../etc/passwd` passes a
#: prefix check while resolving well outside the media folder, so the
#: delete would unlink an arbitrary path. Matching the exact shape
#: `upload_media` actually produces (a uuid4 hex plus a short suffix) closes
#: it at the door, and `_media_path` below refuses to resolve outside the
#: folder as well, because one check standing between a stored string and
#: `unlink()` is one check too few.
MEDIA_URL_RE = re.compile(r"^/media/[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")

#: A sketch is a path list, not an image. Big enough for a page of scribble,
#: small enough that a runaway client can't fill the disk one PUT at a time.
MAX_SKETCH_CHARS = 400_000

#: A text box's own content. Generous: this is a whiteboard note, not a tweet
#:, but still bounded for the same reason every other free-text field here is.
MAX_OBJECT_TEXT_CHARS = 20_000

#: What a board *is*. A map is a board with tree semantics turned on
#: (MINDMAP_PLAN.md §4, option B), the same rows, the same endpoints, one
#: extra edge per node. "board" is the default, and is what NULL settings
#: mean, so every board that existed before maps did stays exactly what it
#: was.
BOARD_TYPES = {"board", "map"}
DEFAULT_BOARD_TYPE = "board"

#: How a map arranges itself. "free" means "wherever you dragged it", which
#: is the only thing an ordinary whiteboard has ever done; the other three
#: are the standard mindmap arrangements (MINDMAP_PLAN.md §3.1). Stored
#: rather than computed because it is a property of the map, not of the
#: session looking at it, the layout you chose has to be there tomorrow.
BOARD_LAYOUTS = {"free", "tree-right", "tree-down", "radial"}
DEFAULT_BOARD_LAYOUT = "free"

#: A map node that stands for something that lives in the library. The node
#: is a *pointer*: deleting it removes the pointer and never the thing, which
#: is the half of containment that must not be got wrong (MINDMAP_PLAN.md
#: §5.4). `image` is deliberately not in here, an image object owns its file
#: and `delete_object` unlinks it, which is the opposite rule.
MAP_REFERENCE_KINDS = {"note", "document", "file", "link"}

#: A topic is text that exists only in the map. It is the one node kind with
#: nothing behind it, which is why deleting the map deletes it.
MAP_TOPIC_KIND = "topic"

VALID_OBJECT_KINDS = {"image", "text", MAP_TOPIC_KIND} | MAP_REFERENCE_KINDS


#: A card/sketch/object's own persisted group, asked for directly (Ctrl+G).
#: Opaque and client-generated (a `crypto.randomUUID()`), not a foreign key:
#: one group spans three different tables, so there's no single row for it
#: to reference. 40 chars is a UUID with room to spare.
GROUP_ID_MAX_LEN = 40


class WhiteboardNodeBase(BaseModel):
    entry_id: int
    board_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    z: int = 0
    #: Asked for directly ("resizing... cards"). `None` means auto-sized: 
    #: the same ~250×150 CSS default every card used before this existed.
    width: float | None = Field(default=None, ge=20, le=4000)
    height: float | None = Field(default=None, ge=20, le=4000)
    #: Degrees, clockwise, about the card's own centre. Asked for directly
    #: ("rotations"); `None` renders identically to 0.
    rotation: float | None = Field(default=None, ge=-360, le=360)
    group_id: str | None = Field(default=None, max_length=GROUP_ID_MAX_LEN)


class WhiteboardNodeOut(WhiteboardNodeBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class WhiteboardSketchBase(BaseModel):
    data: str = Field(max_length=MAX_SKETCH_CHARS)
    board_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    z: int = 0
    group_id: str | None = Field(default=None, max_length=GROUP_ID_MAX_LEN)


class WhiteboardSketchOut(WhiteboardSketchBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class WhiteboardObjectData(BaseModel):
    """What `data` actually holds, validated by `kind` rather than left as an
    opaque string the way a sketch's own path data is, an image needs a real
    same-origin URL (never an arbitrary one a client could point anywhere),
    and a text box's content has its own length bound."""

    url: str | None = Field(default=None, max_length=300)
    content: str | None = Field(default=None, max_length=MAX_OBJECT_TEXT_CHARS)
    color: str | None = Field(default=None, max_length=20)
    font_size: int | None = Field(default=None, ge=8, le=200)
    #: A text box's own fill/border: asked for directly (the properties
    #: panel). Images have no use for either; left `None` there.
    bg: str | None = Field(default=None, max_length=20)
    border_color: str | None = Field(default=None, max_length=20)
    #: How the text sits in its box, and whether it is shown as rendered
    #: markdown: asked for directly ("text alignment, font size etc", "rendered
    #: md which is togglable in text boxes and sticky notes"). A field the
    #: schema does not name is dropped silently by Pydantic, which is exactly
    #: how the first attempt at this looked like a frontend bug: the toggle
    #: flipped, the PUT succeeded, and the value came back missing.
    align: str | None = Field(default=None, pattern="^(left|center|right)$")
    md: bool | None = None
    #: A map reference node's target: the note / document / file / bookmark id
    #: this node stands for. Only meaningful for `MAP_REFERENCE_KINDS`; a
    #: topic has nothing to point at and leaves it None.
    ref_id: int | None = Field(default=None, ge=1)
    #: A collapsed branch hides its children (Coggle's "tidy on demand"), and
    #: a pinned node keeps the position it was dragged to when the map is
    #: re-laid-out. Both are per-node view state on a node that already
    #: carries a JSON blob, so neither earns a column.
    collapsed: bool | None = None
    pinned: bool | None = None
    #: The node edit strip's four (MINDMAP_PLAN.md §12.1 item 2, Coggle's
    #: text/link/image/icon). Weight and slant are stored here rather than
    #: written into the label as `**markdown**` because §12.0 says so
    #: ("styling is per node ... text size, weight, alignment") and because a
    #: label is already markdown-ish: a bold *marker* would then compose with
    #: whatever inline emphasis the text itself carries, and the two would
    #: fight over the same asterisks. Size and alignment reuse `font_size`
    #: and `align` above, which a text box already stores in exactly the same
    #: units, rather than adding a second way to say the same thing.
    bold: bool | None = None
    italic: bool | None = None
    #: A Phosphor icon name without the `ph-` prefix. The pattern is the
    #: whole guard: this string is written straight into a class attribute on
    #: the node, so anything but the character set Phosphor's own names use
    #: has no business arriving here.
    icon: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9-]+$")
    #: How a topic is drawn (MINDMAP_PLAN.md §12.1 item 3, decided in §12.0).
    #: Four values and not the plan's eight: `None` is the rounded card this
    #: map has always drawn, and `pill`, `rect` and `none` are the three that
    #: can be had from a border-radius and a surface. Parallelogram,
    #: trapezoid, cloud and diamond want a clip-path that cuts into the box
    #: the label sits in, which at node size clips the label.
    shape: str | None = Field(default=None, pattern="^(pill|rect|none)$")
    #: Where a topic points. Held to the three schemes a link on a page may
    #: safely have: `javascript:` and `data:` are the two this rejects by
    #: existing, and the frontend's own `wbMapOpenLink` refuses anything else
    #: again at the click (a stored value predating this validator, or one
    #: written by a tool, is still not a hole).
    link: str | None = Field(default=None, max_length=500)
    #: What the line *into* this node says (MINDMAP_PLAN.md §12.1 items 3 and
    #: 4, "label on the link"). Stored on the child rather than anywhere else
    #: because a tree edge has no row of its own: it is `parent_id`, so the
    #: only thing that can carry its label is one of its two ends, and the
    #: child is the end that has exactly one incoming edge.
    edge_label: str | None = Field(default=None, max_length=80)
    #: And how that line is drawn (§12.1 item 4, the link radial). Stored on
    #: the child for the same reason as its label. `curve` is the default and
    #: is what an unset value means, so a map made before these existed draws
    #: exactly as it did.
    edge_style: str | None = Field(default=None, pattern="^(curve|elbow|straight)$")
    edge_dashed: bool | None = None

    @field_validator("link")
    @classmethod
    def _safe_link_scheme(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        lowered = text.lower()
        if not lowered.startswith(("http://", "https://", "mailto:")):
            raise ValueError("A topic's link must be an http, https or mailto address")
        return text


class WhiteboardObjectBase(BaseModel):
    kind: str
    data: WhiteboardObjectData
    board_id: int | None = None
    x: float = 0.0
    y: float = 0.0
    z: int = 0
    width: float = Field(default=200.0, ge=20, le=4000)
    height: float = Field(default=120.0, ge=20, le=4000)
    rotation: float | None = Field(default=None, ge=-360, le=360)
    group_id: str | None = Field(default=None, max_length=GROUP_ID_MAX_LEN)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in VALID_OBJECT_KINDS:
            raise ValueError(
                f"Unknown object kind {value!r}: expected one of "
                + ", ".join(sorted(VALID_OBJECT_KINDS))
            )
        return value


class WhiteboardObjectOut(BaseModel):
    id: int
    kind: str
    data: WhiteboardObjectData
    board_id: int | None
    x: float
    y: float
    z: int
    width: float
    height: float
    rotation: float | None
    group_id: str | None
    #: A map node's parent, NULL for everything on an ordinary whiteboard.
    parent_id: int | None = None


# --- the event log for a board (WORLD_CLASS_PLAN B1, Brief 7) ---------------
#
# The entry managers record one event per write with whole-field values, which
# is what lets a note replay to its current state and a version be put back.
# A board recorded nothing at all, so the half of B1's own wording that says
# "and `routes_whiteboard.py`'s manager" was not true: a card could be moved,
# a text box rewritten and a branch deleted with no record of who did it or
# what it said before.
#
# **What a board's replayable entity is.** A note is one row and replays to
# one dict. A board is not: it is a note plus every card, sketch and object
# on it. So the entity here is the *item*, one of `whiteboard_node`,
# `whiteboard_sketch` and `whiteboard_object`, each replaying to its own
# current state through the same `events.replay`; the board's own events
# (`board` created, duplicated, its type or layout changed) are on the board.
# A board's whole state is the union of its items' replays, which is the only
# reading that keeps `replay` one function rather than one per surface.
#
# Every write below is wrapped in `@events.writes`, not left to remember a
# call: the decorator is what makes "one write, one event" true by
# construction, so a route that grows a second write inside it folds rather
# than quietly recording twice. The exception is any route that calls an
# entry manager (`rename_board` through `update_entry`): opening a scope
# there would fold the *note's* own edit into the board's event and take it
# out of that note's history, which is a worse loss than the tidier shape is
# worth. Those record beside the manager's event instead, and only for the
# fields the manager does not know about.


# The payload builders themselves live in `core/events.py`, beside
# `entry_state`, because the routes are no longer the only writer of these
# events: the AI's own board tools (`ai/tools/whiteboard.py`) record the same
# ones, `ai/` cannot import `api/` at module level, and two copies of a state
# function is how two writers of one entity come to disagree about what its
# state is. Aliased rather than called through `events.` at every site so the
# twenty-odd uses below read as they did.
_node_state = events.node_state
_sketch_state = events.sketch_state
_object_state = events.object_state

#: What a deleted item replays to; see `events.DELETED`.
_DELETED = events.DELETED


def _object_to_out(obj: WhiteboardObject) -> WhiteboardObjectOut:
    return WhiteboardObjectOut(
        id=obj.id,
        kind=obj.kind,
        data=WhiteboardObjectData(**json.loads(obj.data)),
        board_id=obj.board_id,
        x=obj.x,
        y=obj.y,
        z=obj.z,
        width=obj.width,
        height=obj.height,
        rotation=obj.rotation,
        group_id=obj.group_id,
        parent_id=obj.parent_id,
    )


def _require_object_data(body: WhiteboardObjectBase) -> None:
    if body.kind == "image":
        if not body.data.url or not MEDIA_URL_RE.match(body.data.url):
            raise HTTPException(
                status_code=422, detail="An image object needs a /media/... url"
            )
    elif body.kind in ("text", MAP_TOPIC_KIND) and body.data.content is None:
        raise HTTPException(
            status_code=422, detail=f"A {body.kind} object needs content"
        )
    elif body.kind in MAP_REFERENCE_KINDS and body.data.ref_id is None:
        # A reference node with nothing to reference is the map equivalent of
        # a card pointing at note 9999 (this module's own opening comment): it
        # stores fine, draws as an empty box, and there is no way to tell from
        # the UI what it was ever meant to be.
        raise HTTPException(
            status_code=422,
            detail=f"A {body.kind} node needs a ref_id, the id of the {body.kind} it stands for",
        )


def _media_path(url: str):
    """The file behind a `/media/...` url, or None if it isn't safely inside
    the media folder.

    Second of the two checks (`MEDIA_URL_RE` is the first, on the way in).
    This one is what makes the delete safe even for a row written before
    that pattern existed, or by some future writer that forgets it: resolve
    the path and confirm the media folder is genuinely a parent, rather than
    trusting the string it came from.
    """
    if not MEDIA_URL_RE.match(url):
        return None
    media_dir = (deps.get_config().data_dir / "media").resolve()
    candidate = (media_dir / url.removeprefix("/media/")).resolve()
    return candidate if candidate.is_relative_to(media_dir) else None


class WhiteboardStateOut(BaseModel):
    nodes: list[WhiteboardNodeOut]
    sketches: list[WhiteboardSketchOut]
    objects: list[WhiteboardObjectOut] = []


def _board_filter(model, board_id: int | None):
    """`board_id = N`, or `IS NULL` for the unnamed scratch board.

    `== None` renders as `= NULL` in SQL, which is never true for any row, so
    the default board came back empty however much was on it. SQLAlchemy's
    `is_()` is the difference between a working board and a blank one.
    """
    return model.board_id.is_(None) if board_id is None else model.board_id == board_id


def _forget_links_to(db: Session, board_id: int | None, kind: str, item_id: int) -> int:
    """Delete the link sketches on a board whose either end was the item just
    deleted. Links live as sketch rows whose JSON `data` names their ends
    (`sourceId`/`targetId` plus a `sourceKind`/`targetKind` of "node",
    "object" or "sketch", "node" when absent); the frontend already skips a
    link whose end is gone, so without this a deleted card left an invisible
    orphan row behind forever. One linear pass over the board's sketches: 
    boards are hundreds of rows, not millions. Returns how many went."""
    rows = db.scalars(select(WhiteboardSketch).where(_board_filter(WhiteboardSketch, board_id))).all()
    gone = 0
    for row in rows:
        try:
            data = json.loads(row.data or "{}")
        except (TypeError, ValueError):
            continue
        # A sketch's `data` is whatever was stored in it, and only a link
        # sketch is an object with a `type`. A drawing saved as a bare JSON
        # array (which the API accepts and an import can produce) used to
        # reach `.get` on a list here and raise, turning a card's deletion
        # into a 500 because of an unrelated sketch on the same board.
        if not isinstance(data, dict) or not str(data.get("type", "")).startswith("link-"):
            continue
        ends = (
            (data.get("sourceId"), data.get("sourceKind") or "node"),
            (data.get("targetId"), data.get("targetKind") or "node"),
        )
        if any(end_id == item_id and end_kind == kind for end_id, end_kind in ends):
            db.delete(row)
            gone += 1
    return gone


def _require_entry(session: Session, entry_id: int) -> Entry:
    entry = session.get(Entry, entry_id)
    if entry is None or entry.is_deleted:
        raise HTTPException(status_code=404, detail=f"No note with id {entry_id}")
    return entry


def _require_board(session: Session, board_id: int | None) -> None:
    """A board is a note too, and `board_id` is a real foreign key
    (`PRAGMA foreign_keys=ON`), writing one that doesn't exist doesn't fail
    quietly, it throws `IntegrityError` out of `db.commit()` as a raw 500. A
    board note purged (or hard-deleted) out from under a stale client-side
    `currentBoardId` is exactly how that happens: nothing here re-validates
    the id on write the way `_require_entry` already does for `entry_id`.
    Checked the same permissive way `_board_filter` reads it: `None` always
    means the default scratch board, never "board 0".

    Also where an ordinary note gets permanently remembered as a board the
    first time anything is drawn on it, every node/sketch/object write with
    a real `board_id` already funnels through here, so this is the one
    place that sees "this note just became a board" regardless of which of
    the three it was. See `Entry.is_board`'s own comment for why that has to
    survive the board being emptied again later, not just recognise it now.
    """
    if board_id is None:
        return
    entry = session.get(Entry, board_id)
    if entry is None or entry.is_deleted:
        raise HTTPException(status_code=404, detail=f"No board with id {board_id}")
    if not entry.is_board:
        entry.is_board = True
        session.commit()


@router.get("/", response_model=WhiteboardStateOut)
def get_whiteboard_state(
    board_id: int | None = None, db: Session = Depends(get_session)
) -> WhiteboardStateOut:
    nodes = db.scalars(
        select(WhiteboardNode).where(_board_filter(WhiteboardNode, board_id))
    ).all()
    sketches = db.scalars(
        select(WhiteboardSketch).where(_board_filter(WhiteboardSketch, board_id))
    ).all()
    objects = db.scalars(
        select(WhiteboardObject).where(_board_filter(WhiteboardObject, board_id))
    ).all()
    dropped = _drop_orphan_links(db, sketches, nodes, objects)
    if dropped:
        db.commit()
        sketches = [row for row in sketches if row.id not in dropped]
    return WhiteboardStateOut(
        nodes=list(nodes),
        sketches=list(sketches),
        objects=[_object_to_out(o) for o in objects],
    )


def _drop_orphan_links(db: Session, sketches, nodes, objects) -> set[int]:
    """Delete every link on this board whose named end no longer exists, and
    return the ids that went.

    **An integrity pass, because the delete paths cannot be the only guard.**
    Reported with a screenshot: a node "had a dangling curved edge to nowhere
    (an edge whose other end is a deleted node or a point)". Every *delete*
    route does call `_forget_links_to`, but a link's ends are ids inside a
    JSON blob, not foreign keys, so nothing at the database level enforces
    them, and any path that removes a row without going through those routes
    leaves the link behind. One such path is live and was measured: purging a
    note deletes its `WhiteboardNode` rows in bulk (`entry/manager.py`), and
    the link sketch that pointed at the card survived with an id that resolves
    to nothing.

    Doing it on load rather than on write is deliberate. It is the one moment
    the whole board is already in memory, so the check costs no extra query;
    it catches an orphan whatever created it, including one already sitting in
    a notebook from before this existed; and it cannot be forgotten by the
    next route that deletes something.

    A *free* end (`sourcePoint`/`targetPoint`, a fixed board-space point with
    no item at all) is left alone: that is a real feature, asked for in those
    words, and only an end that names an id which is gone is an orphan.
    """
    node_ids = {row.id for row in nodes}
    object_ids = {row.id for row in objects}
    known = {"node": node_ids, "object": object_ids, "sketch": {row.id for row in sketches}}
    dropped: set[int] = set()
    for row in sketches:
        try:
            data = json.loads(row.data or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or not str(data.get("type", "")).startswith("link-"):
            continue
        ends = (
            (data.get("sourceId"), data.get("sourceKind") or "node"),
            (data.get("targetId"), data.get("targetKind") or "node"),
        )
        for end_id, end_kind in ends:
            if end_id is None:
                continue  # a free point, which is allowed
            if end_id not in known.get(end_kind, set()):
                dropped.add(row.id)
                db.delete(row)
                break
    return dropped


def _board_settings(entry: Entry | None) -> tuple[str, str]:
    """This board's `(type, layout)`, defaulted and validated on the way out.

    Everything here is defensive on purpose, because the column is JSON in a
    text field and this is the only place that reads it: NULL (every board
    that predates maps), a blob that isn't JSON, a blob that is JSON but not
    an object, and a value outside the known set all mean the same thing, 
    an ordinary free-layout whiteboard. A board is a note someone can still
    edit by other means; a bad value here must degrade to the default, never
    to a 500 on the Library's own board list.
    """
    if entry is None:
        return DEFAULT_BOARD_TYPE, DEFAULT_BOARD_LAYOUT
    try:
        parsed = json.loads(entry.board_settings or "{}")
    except (TypeError, ValueError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    board_type = parsed.get("type")
    layout = parsed.get("layout")
    return (
        board_type if board_type in BOARD_TYPES else DEFAULT_BOARD_TYPE,
        layout if layout in BOARD_LAYOUTS else DEFAULT_BOARD_LAYOUT,
    )


def _store_board_settings(
    entry: Entry, board_type: str | None = None, layout: str | None = None
) -> tuple[str, str]:
    """Write `type`/`layout` back, leaving whatever this board already had
    for the one that wasn't given. Returns the pair as it now stands.

    Read-modify-write rather than replace, because a settings blob is a
    family that will keep growing (a default node colour, tidy-on-drop) and
    the failure mode of replacing is silent: changing the layout would clear
    every setting added after this function was written.
    """
    current_type, current_layout = _board_settings(entry)
    resolved_type = board_type or current_type
    resolved_layout = layout or current_layout
    try:
        existing = json.loads(entry.board_settings or "{}")
    except (TypeError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing["type"] = resolved_type
    existing["layout"] = resolved_layout
    entry.board_settings = json.dumps(existing)
    return resolved_type, resolved_layout


class BoardOut(BaseModel):
    #: None is the one unnamed scratch board every notebook starts with.
    id: int | None
    title: str
    node_count: int
    sketch_count: int
    object_count: int = 0
    #: "board" (a free canvas) or "map" (tree semantics). See BOARD_TYPES.
    type: str = DEFAULT_BOARD_TYPE
    layout: str = DEFAULT_BOARD_LAYOUT
    #: A miniature of where things actually sit on this board: up to
    #: Up to `PREVIEW_POINTS` items, `{x, y, kind, label}`, each position
    #: normalised into 0..1 against the board's own bounding box. The
    #: Library's board cards showed an icon, a title and a count, which is
    #: the same three facts for every board anyone has ever drawn (reported
    #: as the Boards & maps sub-tab being "boring" and wanting previews).
    #:
    #: **`kind` and `label` are why this replaced a bare list of points**,
    #: and both came out of looking at the result: reported again as "the
    #: whiteboard preview is poor", and the screenshot showed why. Every card
    #: drew as an identical blank grey rectangle, so three different boards
    #: called "Cloud computing" were indistinguishable: a preview whose only
    #: information is *how many* things there are and roughly where. And a
    #: board holding only sketches previewed as nothing at all, because
    #: sketches were not in the sample; "Default board · 2 sketches" showed
    #: an empty space where its picture should be.
    #:
    #: Normalised here rather than client-side because the client would then
    #: need every item's absolute coordinates to compute the bounds, which is
    #: the whole board: and a list of twenty boards would ship twenty whole
    #: boards to draw twenty thumbnails.
    preview_items: list[dict] = []
    #: A map's parent→child edges as line segments, `{x1, y1, x2, y2}`, in the
    #: same normalised 0..1 space as `preview_items` and sampled with it.
    #:
    #: Empty for an ordinary board, which has no tree to draw. It exists
    #: because a map whose thumbnail is a scatter of dots is indistinguishable
    #: from a board: and structure is the entire difference between the two,
    #: so the one thing the picture has to show is the one thing points alone
    #: cannot.
    preview_edges: list[dict] = []
    #: The board's own width/height, so a thumbnail can be drawn at the shape
    #: the board actually has instead of stretched to whatever box it lands
    #: in. Normalising into 0..1 threw this away: a tall map and a wide board
    #: both came back as the unit square, so every card drew the same
    #: rectangle and a tree that runs left to right looked identical to one
    #: that runs top to bottom.
    #:
    #: Clamped into `PREVIEW_ASPECT_RANGE`. Past that the letterboxed picture
    #: is a sliver a few pixels wide inside a card that is mostly empty, which
    #: says less about the board than a slightly wrong ratio does.
    preview_aspect: float = 1.0


class BoardTypeMixin(BaseModel):
    """`type` and `layout` as a request field, validated once for every
    endpoint that takes them rather than three times slightly differently."""

    type: str | None = None
    layout: str | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str | None) -> str | None:
        if value is not None and value not in BOARD_TYPES:
            raise ValueError(
                f"Unknown board type {value!r}: expected " + " or ".join(sorted(BOARD_TYPES))
            )
        return value

    @field_validator("layout")
    @classmethod
    def _known_layout(cls, value: str | None) -> str | None:
        if value is not None and value not in BOARD_LAYOUTS:
            raise ValueError(
                f"Unknown layout {value!r}: expected one of " + ", ".join(sorted(BOARD_LAYOUTS))
            )
        return value


class BoardCreate(BoardTypeMixin):
    name: str = Field(min_length=1, max_length=100)


#: The most points a board's thumbnail carries. A minimap is a shape, not a
#: census: past a few dozen dots the picture stops distinguishing boards and
#: starts being noise, and the payload grows with every card anyone adds.
PREVIEW_POINTS = 40


def _preview_points(rows: list[tuple[float, float]]) -> list[list[float]]:
    """Normalise raw board coordinates into 0..1 for a thumbnail.

    Evenly sampled rather than truncated: `rows[:40]` of a 300-card board is
    whatever 40 cards were inserted first, which is not the board's shape.
    A stride keeps the sample spread across the whole board.

    A board whose content is a single point, or a perfectly straight row of
    cards, has zero extent on at least one axis, hence the guard, which
    centres that axis instead of dividing by zero.
    """
    if not rows:
        return []
    stride = max(1, len(rows) // PREVIEW_POINTS)
    sampled = rows[::stride][:PREVIEW_POINTS]
    xs = [x for x, _ in sampled]
    ys = [y for _, y in sampled]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max_x - min_x
    span_y = max_y - min_y
    return [
        [
            round((x - min_x) / span_x, 3) if span_x else 0.5,
            round((y - min_y) / span_y, 3) if span_y else 0.5,
        ]
        for x, y in sampled
    ]


#: How much of a card's own text the thumbnail carries. Enough to tell two
#: boards apart at a glance and no more, the label is drawn at a few pixels
#: high, so a longer string is only bytes.
PREVIEW_LABEL_CHARS = 28

#: What a thing is drawn at on the canvas when it has no size of its own,
#: so a thumbnail draws the same picture the board does. These mirror
#: `WB_CARD_DEFAULT_SIZE`, `WB_MAP_NODE_W/H` and the sketch's own box in
#: frontend/whiteboard.js; a card's width and height are nullable columns and
#: a sketch has none at all, so without a figure here every one of them would
#: have to be drawn as a point.
PREVIEW_DEFAULT_SIZES = {
    "card": (250.0, 150.0),
    "sketch": (200.0, 150.0),
    MAP_TOPIC_KIND: (200.0, 56.0),
}
PREVIEW_FALLBACK_SIZE = (200.0, 120.0)


#: The branch colours a map's thumbnail draws, in the order a first-level
#: branch claims them.
#:
#: **This is `d3.schemeTableau10`, copied.** The canvas takes that scale from
#: d3 at runtime (`wbMapColors`, whiteboard.js), and the thumbnail has to
#: agree with the canvas or the same map is two different pictures depending
#: on where you look at it. The server has no d3, and shipping a *branch
#: index* instead would only move the same duplication into app.js, where the
#: preview is drawn and d3 is not guaranteed to have loaded. Copied here, once,
#: with `tests/test_board_preview.py` asserting a preview's colours come from
#: this list.
MAP_BRANCH_PALETTE = [
    "#4e79a7",
    "#f28e2c",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc949",
    "#af7aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ab",
]


def _map_branch_colors(
    parents: dict[int, int | None], own: dict[int, str | None]
) -> dict[int, str]:
    """Every map node's branch colour, by object id: Coggle's rule, which the
    canvas already follows.

    A first-level topic (a *child of a root*, not a root) takes the next
    palette entry, and every descendant inherits it unless it sets its own
    `data.color`. Starting at the roots instead would paint a whole map one
    colour, which is the one thing branch colour exists not to do.

    Iterative rather than recursive: a map imported from a deep OPML file is
    still a tree, but nothing here should be able to turn a 1,000-deep import
    into a `RecursionError` in a *thumbnail*. `seen` also makes a cycle (a
    dangling or corrupt `parent_id`) terminate rather than hang, and any node
    whose parent is missing is treated as a root, which is what every other
    reader of `parent_id` does.
    """
    children: dict[int | None, list[int]] = {}
    for node_id, parent_id in parents.items():
        key = parent_id if parent_id in parents else None
        children.setdefault(key, []).append(node_id)
    colors: dict[int, str] = {}
    seen: set[int] = set()
    branch = 0
    # (id, the colour inherited from above, depth from its root)
    stack: list[tuple[int, str | None, int]] = [
        (node_id, None, 0) for node_id in reversed(children.get(None, []))
    ]
    while stack:
        node_id, inherited, depth = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        colour = own.get(node_id)
        if colour is None and depth == 1:
            # Depth 1 *is* the branch, and it is the only depth that ever
            # takes a new colour: the client decides this by asking whether
            # the colour handed down was null, which is true for exactly one
            # generation, a root's own children.
            colour = MAP_BRANCH_PALETTE[branch % len(MAP_BRANCH_PALETTE)]
            branch += 1
        if colour is None:
            colour = inherited
        if colour:
            colors[node_id] = colour
        for child_id in reversed(children.get(node_id, [])):
            stack.append((child_id, colour, depth + 1))
    return colors


def _preview_size(
    kind: str, width: float | None, height: float | None
) -> tuple[float, float]:
    """How big this thing is on the board, falling back to what the canvas
    would draw it at.

    A card's `width`/`height` are nullable columns and a sketch has neither,
    so "no size stored" is the common case rather than the odd one, and it
    means "the default", not "zero".
    """
    default = PREVIEW_DEFAULT_SIZES.get(kind, PREVIEW_FALLBACK_SIZE)
    w = float(width) if width else default[0]
    h = float(height) if height else default[1]
    return (max(1.0, w), max(1.0, h))


def _preview_items(
    rows: list[tuple[float, float, str, str, str | None, float, float]],
) -> list[dict]:
    """The same normalisation as `_preview_points`, carrying what each item
    *is*, what it says, what colour it is and **how big it is**.

    Sampling happens before normalising and both use one stride, so the
    labels can never end up attached to the wrong positions, which is the
    obvious way to break this while every number still looks plausible.

    `color` is omitted rather than sent as null for the items that have none
    (every card, every sketch, every object on an ordinary board): a
    twenty-board list ships eight hundred of these.

    **`w` and `h` are why a board stopped previewing as identical grey
    blobs** (INBOX 68, the owner twice: "Boards & maps preview looks so bad,
    especially in the dashboard"). Positions alone cannot say that the banner
    across the top of a board is six times the width of the sticky under it,
    so every item was drawn as the same rectangle and the picture was of the
    renderer rather than of the board. They are fractions of the same span
    the positions were normalised into, so the client multiplies them by
    exactly what it multiplies `x` and `y` by, and a span of zero (one item,
    or a straight line of them) leaves them out rather than shipping an
    infinity.
    """
    if not rows:
        return []
    stride = max(1, len(rows) // PREVIEW_POINTS)
    sampled = rows[::stride][:PREVIEW_POINTS]
    points = _preview_points([(x, y) for x, y, _, _, _, _, _ in sampled])
    xs = [x for x, _, _, _, _, _, _ in sampled]
    ys = [y for _, y, _, _, _, _, _ in sampled]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    items = []
    for (nx, ny), (_, _, kind, label, colour, w, h) in zip(points, sampled, strict=True):
        item = {"x": nx, "y": ny, "kind": kind, "label": label}
        if colour:
            item["color"] = colour
        if span_x > 0 and span_y > 0:
            item["w"] = round(w / span_x, 4)
            item["h"] = round(h / span_y, 4)
        items.append(item)
    return items


#: How far a thumbnail's shape is allowed to depart from a square, as
#: width/height. A board 30 times wider than it is tall is a real board, and
#: letterboxed honestly into a Library card it is a two-pixel band of grey:
#: past this the ratio stops being information and starts being an empty card.
PREVIEW_ASPECT_RANGE = (0.5, 3.0)


def _board_preview(
    db: Session, board_id: int | None
) -> tuple[list[dict], list[dict], float]:
    """Everything placed on one board, as a thumbnail: `(items, edges, aspect)`.

    Cards, sketches *and* objects. Cards alone was the first version and it
    is why a sketch-only board previewed as an empty rectangle: the count
    line said "2 sketches" beside a picture of nothing.

    **Edges are computed from the sampled items, not from the board.** The
    sampler drops items on a large board (`PREVIEW_POINTS`), and an edge
    whose other end was dropped would be a line to nowhere, so an edge is
    emitted only when both of its ends survived sampling, and it reuses the
    normalised coordinates the items already got rather than normalising a
    second time against different bounds.

    **`aspect` is the shape the normalisation threw away.** Positions come
    back in 0..1 on both axes, so the client cannot tell a tall map from a
    wide board and drew both stretched into the card's box. It is measured
    over exactly the sampled corner span the items were normalised against,
    not over the board's true extent including each item's own width and
    height: the picture the client letterboxes *is* that span, so a ratio
    measured any other way would be a number that does not match the drawing.
    """
    from memorymap.entry import manager

    def on(model):
        return (
            model.board_id.is_(None) if board_id is None else model.board_id == board_id
        )

    rows: list[tuple[float, float, str, str, str | None, float, float]] = []
    #: Which object each row came from, positionally, `None` for a card or a
    #: sketch, which have no tree. Only map nodes ever claim a parent, so an
    #: ordinary board leaves `parent_of` empty and pays for nothing.
    owners: list[int | None] = []
    parent_of: dict[int, int] = {}
    #: Every object's parent (including the roots, at None) and its own
    #: `data.color`, which is what the branch-colour walk needs. Separate from
    #: `parent_of` because that one carries only real parents and is what the
    #: edges are drawn from.
    tree_parents: dict[int, int | None] = {}
    own_colors: dict[int, str | None] = {}

    for node in db.scalars(select(WhiteboardNode).where(on(WhiteboardNode))):
        entry = db.get(Entry, node.entry_id)
        label = ""
        if entry is not None and not entry.is_private:
            # A card *is* a note, so its own title (or first words) is what
            # is written on it. A private note contributes its position and
            # nothing else: the same rule the Connections block and the
            # Library's file-usage chips follow.
            text = manager.readable_content(entry)
            label = (manager.extract_title(text) or text.strip().split("\n")[0])[
                :PREVIEW_LABEL_CHARS
            ]
        rows.append(
            (
                float(node.x),
                float(node.y),
                "card",
                label,
                None,
                *_preview_size("card", node.width, node.height),
            )
        )
        owners.append(None)

    for sketch in db.scalars(select(WhiteboardSketch).where(on(WhiteboardSketch))):
        rows.append(
            (
                float(sketch.x),
                float(sketch.y),
                "sketch",
                "",
                None,
                *_preview_size("sketch", None, None),
            )
        )
        owners.append(None)

    # Ordered by id so the branch colours fall in the same order the canvas
    # gives them: the client walks the objects in the order `GET /whiteboard`
    # returns them, which is this one.
    objects = list(
        db.scalars(
            select(WhiteboardObject)
            .where(on(WhiteboardObject))
            .order_by(WhiteboardObject.id)
        )
    )
    for obj in objects:
        label = ""
        data = {}
        try:
            parsed = json.loads(obj.data)
            data = parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            data = {}
        if obj.kind == MAP_TOPIC_KIND or obj.kind == "text":
            # A map's thumbnail is mostly topics, and a topic *is* its text,
            # a tree of unlabelled boxes tells two maps apart no better than
            # a scatter of dots did.
            #
            # A whiteboard's text boxes and sticky notes are the same case and
            # were left out of it (INBOX 68: "Boards & maps preview looks so
            # bad"). A board of five text boxes previewed as five blank
            # rectangles, so the one thing written on the board, which is what
            # a person named it after, was the one thing the picture of it did
            # not have. An image object still has no label: what it says is a
            # picture, and a thumbnail of a thumbnail is a different feature.
            label = str(data.get("content") or "")[:PREVIEW_LABEL_CHARS]
        rows.append(
            (
                float(obj.x),
                float(obj.y),
                obj.kind or "object",
                label,
                None,
                *_preview_size(obj.kind or "object", obj.width, obj.height),
            )
        )
        owners.append(obj.id)
        if obj.parent_id is not None:
            parent_of[obj.id] = obj.parent_id
        if obj.kind == MAP_TOPIC_KIND or obj.kind in MAP_REFERENCE_KINDS:
            tree_parents[obj.id] = obj.parent_id
            colour = data.get("color")
            own_colors[obj.id] = colour if isinstance(colour, str) and colour else None

    # **The branch colours, computed here and not in the client.** Every node
    # drew in one grey before this, so a map's thumbnail showed its structure
    # and nothing about which branch was which, while the same map on the
    # canvas is colour-coded by branch. The rule is Coggle's and the canvas
    # already implements it; see `_map_branch_colors`.
    if tree_parents:
        branch_colors = _map_branch_colors(tree_parents, own_colors)
        rows = [
            (
                x,
                y,
                kind,
                label,
                branch_colors.get(owner) if owner is not None else colour,
                w,
                h,
            )
            for (x, y, kind, label, colour, w, h), owner in zip(rows, owners, strict=True)
        ]

    # Sample here rather than inside `_preview_items` so the edges can be
    # drawn against the *same* survivors: passing an already-sampled list
    # back through it is a no-op (its own stride is 1 for anything at or
    # under PREVIEW_POINTS), so nothing about the items changes.
    stride = max(1, len(rows) // PREVIEW_POINTS)
    kept = list(range(len(rows)))[::stride][:PREVIEW_POINTS]
    items = _preview_items([rows[i] for i in kept])

    # The sampled corner span, which is the box the items were normalised
    # into and therefore the box the client draws.
    aspect = 1.0
    if kept:
        xs = [rows[i][0] for i in kept]
        ys = [rows[i][1] for i in kept]
        span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
        if span_x > 0 and span_y > 0:
            low, high = PREVIEW_ASPECT_RANGE
            aspect = round(min(max(span_x / span_y, low), high), 3)
        # A single item, or a straight line of them, has no extent on an axis
        # and keeps the square: the alternative is a divide by zero or a
        # thumbnail whose shape is an artefact of a rounding error.

    edges: list[dict] = []
    if parent_of:
        at = {owners[i]: n for n, i in enumerate(kept) if owners[i] is not None}
        for child_id, parent_id in parent_of.items():
            if child_id in at and parent_id in at:
                child, parent = items[at[child_id]], items[at[parent_id]]
                edge = {
                    "x1": parent["x"],
                    "y1": parent["y"],
                    "x2": child["x"],
                    "y2": child["y"],
                }
                # An edge takes the *child's* colour, which is what the canvas
                # does: a branch is one colour from where it leaves the trunk
                # all the way out, and colouring it by the parent would paint
                # the first hop of every branch the trunk's colour.
                if child.get("color"):
                    edge["color"] = child["color"]
                edges.append(edge)
    return items, edges, aspect


#: How many boards' thumbnails are remembered at once. The Library lists every
#: board in the notebook, so this only has to cover one screenful of cards
#: plus the dashboard's widget; a notebook with more boards than this simply
#: recomputes the ones that fell off the end.
PREVIEW_CACHE_LIMIT = 128

#: `key -> (items, edges, aspect)`, where the key carries a fingerprint of
#: everything the picture is drawn from (see `_preview_fingerprint`), so a
#: stale entry cannot be served: a changed board has a different key, and the
#: old entry ages out rather than being invalidated by hand.
_PREVIEW_CACHE: "OrderedDict[tuple, tuple[list[dict], list[dict], float]]" = OrderedDict()

#: Hits and misses since the process started. Read by
#: `tests/test_board_preview.py`, which is the only way to assert a cache
#: works: the response is identical either way, which is the point of it.
PREVIEW_CACHE_STATS = {"hits": 0, "misses": 0}


def _preview_fingerprint(db: Session, board_id: int | None) -> tuple:
    """Everything a board's thumbnail depends on, as a cheap tuple.

    Three counts and three high-water marks, one per table, plus the same
    pair for the *notes* the board's cards stand for: a card's label is the
    note's title, so renaming a note has to change this key even though
    nothing on the board was touched. Six aggregates over indexed columns
    against a full scan of every row on the board plus one `Entry` fetch per
    card, which is what the miss path costs.

    The database's own identity is in the key as well. The cache is module
    state and the test suite builds a fresh database per test, so two
    databases whose board 1 is empty in the same way would otherwise share an
    entry: harmless today (both previews are empty) and exactly the sort of
    cross-test leak that is diagnosed at three in the morning.
    """
    def on(model):
        return model.board_id.is_(None) if board_id is None else model.board_id == board_id

    stamps: list = []
    for model in (WhiteboardNode, WhiteboardSketch, WhiteboardObject):
        row = db.execute(
            select(func.count(), func.max(model.updated_at)).where(on(model))
        ).one()
        stamps.append((row[0], str(row[1])))
    cards = db.execute(
        select(func.count(), func.max(Entry.updated_at))
        .select_from(WhiteboardNode)
        .join(Entry, Entry.id == WhiteboardNode.entry_id)
        .where(on(WhiteboardNode))
    ).one()
    stamps.append((cards[0], str(cards[1])))
    bind = db.get_bind()
    return (
        str(getattr(bind, "url", bind)),
        db.info.get("workspace_id"),
        board_id,
        tuple(stamps),
    )


def _preview_fields(db: Session, board_id: int | None) -> dict:
    """A board's three preview fields, ready to splat into `BoardOut`, from
    the cache when the board has not moved since it was last drawn.

    **Why this is cached at all**: the Library rebuilds every board's
    thumbnail on every visit, and a thumbnail is a full scan of the board.
    Twenty boards of a few hundred items each is twenty of those, per visit,
    for a picture that changes only when the board does.
    """
    key = _preview_fingerprint(db, board_id)
    cached = _PREVIEW_CACHE.get(key)
    if cached is not None:
        PREVIEW_CACHE_STATS["hits"] += 1
        # Newest last: this is a plain LRU, and a board being looked at now is
        # the one least worth dropping.
        _PREVIEW_CACHE.move_to_end(key)
        items, edges, aspect = cached
    else:
        PREVIEW_CACHE_STATS["misses"] += 1
        items, edges, aspect = _board_preview(db, board_id)
        _PREVIEW_CACHE[key] = (items, edges, aspect)
        while len(_PREVIEW_CACHE) > PREVIEW_CACHE_LIMIT:
            _PREVIEW_CACHE.popitem(last=False)
    # Copied on the way out: the cached lists are shared with every later
    # caller, and a response model that a caller mutated in place would poison
    # every board list after it.
    return {
        "preview_items": [dict(item) for item in items],
        "preview_edges": [dict(edge) for edge in edges],
        "preview_aspect": aspect,
    }


#: A page of boards, and a page of board images. Both lists grow with the
#: notebook rather than with anything the app controls, which is the rule
#: `tests/test_list_endpoints_page.py` enforces. 200 because it is the number
#: every other paged list here already uses, and because a board row carries a
#: preview (up to `PREVIEW_POINTS` points): at 200 that is a response of tens
#: of kilobytes instead of one that grows forever.
BOARDS_PAGE_SIZE = 200
BOARDS_PAGE_SIZE_MAX = 1000


@router.get("/boards", response_model=list[BoardOut])
def list_boards(
    response: Response,
    type: str | None = None,
    limit: int = Query(default=BOARDS_PAGE_SIZE, ge=1, le=BOARDS_PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[BoardOut]:
    """Boards actually in use, not, as the client used to build this list
    itself, every note in the notebook.

    Reported directly: "the different board options confuse me." The cause
    wasn't a bug so much as a design choice nobody had reckoned with yet, a
    board being *just a note* (this file's own opening comment) is right for
    the data model, but the picker took that literally and listed every
    single note as a "board", the vast majority of which had never been used
    as one. A notebook with 50 notes had a 50-item "Switch board" dropdown
    with no way to tell which one, if any, was actually a board someone had
    drawn on. This lists only notes with at least one card or sketch on them,
    plus the always-present default board.

    `?type=map` (or `board`) narrows it to one kind, the Library's Maps
    chip. Filtered in Python rather than in SQL because a board's type lives
    inside a JSON settings blob (`Entry.board_settings`), and because this
    function already materialises every board to build its preview: the list
    is tens of rows long, not thousands. An unknown value returns nothing
    rather than everything: a filter that silently ignores itself reads as
    "you have no maps" only after the user has read every row.

    **Paged.** `limit`, `offset` and an `X-Total-Count` counted over the same
    type filter as the page, so a caller that wants every board asks for the
    next page until it has them all (`apiPagedList` in the frontend). The
    default board is row one of page one and is counted like any other. The
    order is the default board, then entry id ascending, which is the order
    this list already came back in; the tiebreaker matters more here than
    elsewhere, because two boards created in the same second would otherwise
    be free to swap places between two pages and hide one of themselves.

    The page boundary is also where the cost is: `_preview_fields` is a query
    per board, and it now runs for the rows in the page rather than for every
    board in the notebook.
    """
    if type is not None and type not in BOARD_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown board type {type!r}: expected " + " or ".join(sorted(BOARD_TYPES)),
        )
    node_counts = dict(
        db.execute(
            select(WhiteboardNode.board_id, func.count())
            .where(WhiteboardNode.board_id.is_not(None))
            .group_by(WhiteboardNode.board_id)
        ).all()
    )
    sketch_counts = dict(
        db.execute(
            select(WhiteboardSketch.board_id, func.count())
            .where(WhiteboardSketch.board_id.is_not(None))
            .group_by(WhiteboardSketch.board_id)
        ).all()
    )
    object_counts = dict(
        db.execute(
            select(WhiteboardObject.board_id, func.count())
            .where(WhiteboardObject.board_id.is_not(None))
            .group_by(WhiteboardObject.board_id)
        ).all()
    )
    default_nodes = db.scalar(
        select(func.count()).select_from(WhiteboardNode).where(WhiteboardNode.board_id.is_(None))
    )
    default_sketches = db.scalar(
        select(func.count()).select_from(WhiteboardSketch).where(WhiteboardSketch.board_id.is_(None))
    )
    default_objects = db.scalar(
        select(func.count()).select_from(WhiteboardObject).where(WhiteboardObject.board_id.is_(None))
    )
    # The default scratch board has no note behind it, so it has nowhere to
    # store settings and is always an ordinary board, which is why it is
    # excluded by `?type=map` rather than being special-cased into it.
    # The page is decided before any preview is built: `None` stands for the
    # default board, and every other row is an `Entry` that passed the type
    # filter. Building `BoardOut`s first and slicing afterwards would pay for
    # a preview query per board in the notebook to answer a request for
    # twenty of them.
    page_rows: list[Entry | None] = [None] if type in (None, DEFAULT_BOARD_TYPE) else []
    # `is_board` entries are included even at zero counts, see its own
    # comment on the model and on `_require_board` above: a board that is
    # currently empty (just created, or cleared back to empty) is still a
    # board, and used to vanish from this list the moment its count hit
    # zero, which read as the board having deleted itself.
    board_ids = set(node_counts) | set(sketch_counts) | set(object_counts)
    board_ids |= set(
        db.scalars(
            select(Entry.id).where(Entry.is_board.is_(True), Entry.is_deleted.is_(False))
        ).all()
    )
    settings: dict[int, tuple[str, str]] = {}
    if board_ids:
        entries = db.scalars(
            select(Entry)
            .where(Entry.id.in_(board_ids), Entry.is_deleted.is_(False))
            .order_by(Entry.id)
        ).all()
        for entry in entries:
            board_type, layout = _board_settings(entry)
            # The type lives inside a JSON settings blob, so this filter is
            # Python either way (the docstring above says why); doing it here
            # rather than inside the page loop is what makes `total` the size
            # of the selection rather than of the table.
            if type is not None and board_type != type:
                continue
            settings[entry.id] = (board_type, layout)
            page_rows.append(entry)
    response.headers["X-Total-Count"] = str(len(page_rows))
    boards = []
    for entry in page_rows[offset:offset + limit]:
        if entry is None:
            # The default scratch board has no note behind it, so it has
            # nowhere to store settings and is always an ordinary board, which
            # is why it is excluded by `?type=map` rather than special-cased
            # into it.
            boards.append(
                BoardOut(
                    id=None,
                    title="Default board",
                    node_count=default_nodes,
                    sketch_count=default_sketches,
                    object_count=default_objects,
                    **_preview_fields(db, None),
                )
            )
            continue
        board_type, layout = settings[entry.id]
        title = extract_title(entry.content) or entry.content.strip()[:40] or f"Note {entry.id}"
        boards.append(
            BoardOut(
                id=entry.id,
                title=title,
                node_count=node_counts.get(entry.id, 0),
                sketch_count=sketch_counts.get(entry.id, 0),
                object_count=object_counts.get(entry.id, 0),
                type=board_type,
                layout=layout,
                **_preview_fields(db, entry.id),
            )
        )
    return boards


class BoardImageOut(BaseModel):
    id: int
    board_id: int | None
    board_title: str
    url: str


@router.get("/images", response_model=list[BoardImageOut])
def list_images(
    response: Response,
    limit: int = Query(default=BOARDS_PAGE_SIZE, ge=1, le=BOARDS_PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[BoardImageOut]:
    """A page of the image objects across every board, asked for directly
    ("what about uploaded images" in the Library). Whiteboard images already
    have a real row (`WhiteboardObject`, unlike an image pasted into a note's
    own markdown, which has none, see ROADMAP item 20a for that still-open
    gap), so this is a flat query, not new plumbing.

    **Paged**, with `X-Total-Count` over the same selection as the page and
    the row id as the order, which is also the tiebreaker two rows created in
    the same second need to stop them swapping places between pages.

    The one thing worth knowing about the shape below: the "does this row
    actually carry a url" test cannot be a SQL filter, because the url is a
    key inside a JSON blob. So the ids and blobs are read first and filtered
    in Python, and the page is taken from *that* list. Counting every image
    row instead and skipping the empty ones per page would make
    `X-Total-Count` bigger than the number of rows a caller can ever collect,
    and `apiPagedList` walks until it has that many: it would never stop.
    """
    rows = db.execute(
        select(WhiteboardObject.id, WhiteboardObject.board_id, WhiteboardObject.data)
        .where(WhiteboardObject.kind == "image")
        .order_by(WhiteboardObject.id)
    ).all()
    usable = []
    for obj_id, board_id, data in rows:
        try:
            url = json.loads(data).get("url")
        except (TypeError, ValueError):
            url = None
        if url:
            usable.append((obj_id, board_id, url))
    response.headers["X-Total-Count"] = str(len(usable))
    page = usable[offset:offset + limit]
    if not page:
        return []
    board_ids = {board_id for _, board_id, _ in page if board_id is not None}
    titles: dict[int | None, str] = {None: "Default board"}
    if board_ids:
        for entry in db.scalars(select(Entry).where(Entry.id.in_(board_ids), Entry.is_deleted.is_(False))):
            titles[entry.id] = extract_title(entry.content) or entry.content.strip()[:40] or f"Note {entry.id}"
    return [
        BoardImageOut(
            id=obj_id,
            board_id=board_id,
            board_title=titles.get(board_id, f"Note {board_id}"),
            url=url,
        )
        for obj_id, board_id, url in page
    ]


@router.post("/boards", response_model=BoardOut, status_code=201)
@events.writes("board", "created")
def create_board(body: BoardCreate, db: Session = Depends(get_session)) -> BoardOut:
    """A fresh, empty board, a plain note whose whole job is to be one.

    Named directly (`# {name}` as its first line, the same heading convention
    every note's own title already reads), rather than the previous only way
    in: create an ordinary note somewhere else first, then find it again in a
    dropdown that listed the entire notebook.
    """
    name = body.name.strip()
    entry = Entry(content=f"# {name}", is_board=True)
    # Written before the first commit rather than in a second UPDATE after
    # it: a map created as a board and turned into one a moment later is a
    # window in which the Library, the board list and any other reader see it
    # as an ordinary whiteboard.
    board_type, layout = _store_board_settings(entry, body.type, body.layout)
    db.add(entry)
    db.flush()  # so the event can name the board's id
    # This route builds the note itself rather than going through
    # `manager.create_entry`, so without this line a board was the one thing
    # in the app that could appear with nothing anywhere saying it had.
    events.record(
        db,
        "created",
        "board",
        entry.id,
        name[:80],
        payload={"after": {"title": name, "type": board_type, "layout": layout}},
    )
    db.commit()
    db.refresh(entry)
    return BoardOut(
        id=entry.id,
        title=name,
        node_count=0,
        sketch_count=0,
        type=board_type,
        layout=layout,
    )


@router.post("/boards/{board_id}/duplicate", response_model=BoardOut, status_code=201)
@events.writes("board", "created")
def duplicate_board(board_id: int, db: Session = Depends(get_session)) -> BoardOut:
    """Copy a board: every card, sketch and object, at the same positions.

    ROADMAP.md item 8 ("managing concept maps"): creating a map works and so
    do listing and renaming, but duplicating did not exist on either side.
    It is the one that makes a map reusable, a map you have laid out is a
    template for the next one, and without this the only way to reuse a shape
    is to rebuild it card by card.

    **A card is a real note**, which is the app's own premise (see
    `createConceptMap`) and the reason this is not a shallow row copy: the
    duplicate gets *new* notes with the same text, so editing a card on the
    copy cannot rewrite the original's. The alternative: pointing both boards
    at one set of notes, looks identical the moment it is made and diverges
    into data loss the first time someone edits the copy.

    Sketches and objects carry no separate identity, so those rows are copied
    as they are.
    """
    # `_require_board` validates and returns nothing, so the Entry is fetched
    # separately: the title has to come from the board note's own heading,
    # which is where a board's title lives (see `rename_board`).
    _require_board(db, board_id)
    source = deps.get_or_404(db, Entry, board_id, "Board not found")
    title = extract_title(source.content) or "Untitled board"
    copy = Entry(content=f"# {title} (copy)", is_board=True)
    # A copy of a map is a map. Copying the settings blob wholesale (rather
    # than reading the two fields and writing them back) is what keeps that
    # true for every board-level setting added after this line was written.
    copy.board_settings = source.board_settings
    db.add(copy)
    db.flush()  # the new board needs its id before anything can point at it

    nodes = db.scalars(
        select(WhiteboardNode).where(_board_filter(WhiteboardNode, board_id))
    ).all()
    for node in nodes:
        original = db.get(Entry, node.entry_id)
        if original is None:
            continue  # a stale row: skip rather than copy a dangling card
        card = Entry(content=original.content, is_private=original.is_private)
        db.add(card)
        db.flush()
        db.add(
            WhiteboardNode(
                board_id=copy.id,
                entry_id=card.id,
                x=node.x,
                y=node.y,
                z=node.z,
                width=node.width,
                height=node.height,
            )
        )

    for sketch in db.scalars(
        select(WhiteboardSketch).where(_board_filter(WhiteboardSketch, board_id))
    ).all():
        db.add(WhiteboardSketch(board_id=copy.id, data=sketch.data))

    # **The copy's tree has to point at the copy.** A row-by-row copy carries
    # `parent_id` verbatim, which would leave every node in the duplicate
    # parented to the *original's* rows: a map that looks right in the object
    # list and renders as a flat pile of roots, because the tree walk on this
    # board finds no parent of its own on it. So: copy first, then re-wire by
    # the old id → new id map, which needs the new ids and therefore a flush.
    copied_by_source: dict[int, WhiteboardObject] = {}
    sources = db.scalars(
        select(WhiteboardObject).where(_board_filter(WhiteboardObject, board_id))
    ).all()
    for obj in sources:
        clone = WhiteboardObject(
            board_id=copy.id,
            kind=obj.kind,
            data=obj.data,
            x=obj.x,
            y=obj.y,
            z=obj.z,
            width=obj.width,
            height=obj.height,
        )
        db.add(clone)
        copied_by_source[obj.id] = clone
    db.flush()
    for obj in sources:
        if obj.parent_id is not None and obj.parent_id in copied_by_source:
            copied_by_source[obj.id].parent_id = copied_by_source[obj.parent_id].id

    # One event, not one per copied row: a duplicate is one action, and the
    # copy's own items each replay from the state recorded here.
    events.record(
        db,
        "created",
        "board",
        copy.id,
        f"copy of board {board_id}",
        payload={
            "after": {"title": f"{title} (copy)", "copied_from": board_id},
            "cards": len(nodes),
            "objects": len(sources),
        },
    )
    db.commit()
    db.refresh(copy)
    board_type, layout = _board_settings(copy)
    return BoardOut(
        id=copy.id,
        title=f"{title} (copy)",
        node_count=len(nodes),
        sketch_count=0,
        object_count=len(sources),
        type=board_type,
        layout=layout,
        **_preview_fields(db, copy.id),
    )


class BoardRename(BoardTypeMixin):
    #: Optional since maps: `PUT` used to be rename-only and required a
    #: title, so a client changing the *layout* had to resend the name it was
    #: not touching: which is how a rename made in another tab gets silently
    #: overwritten by a stale one. `None` means "leave the title alone".
    title: str | None = Field(default=None, min_length=1, max_length=100)


@router.put("/boards/{board_id}", response_model=BoardOut)
def rename_board(board_id: int, body: BoardRename, db: Session = Depends(get_session)) -> BoardOut:
    """A board's title is its underlying note's own first `#` heading line
    (`list_boards`'s own `extract_title` read, above): so renaming a board
    is the same `apply_title` edit any other note's title goes through, not
    a second stored field. The default scratch board (`board_id=None`) has
    no underlying note to rename; `board_id=0` and negative ids can't
    resolve to a real note either, so both 404 the same way a stale or
    guessed id does.

    Also where a board becomes a map and back (`type`), and where a map's
    `layout` is chosen. Every field is optional and only what was sent is
    applied: the same shape `PATCH` would have, kept as `PUT` because the
    route, the client call and this function's name already existed.
    """
    entry = db.get(Entry, board_id) if board_id > 0 else None
    if entry is None or entry.is_deleted:
        raise HTTPException(status_code=404, detail=f"No board with id {board_id}")
    entry.is_board = True
    if body.type is not None or body.layout is not None:
        before = dict(zip(("type", "layout"), _board_settings(entry)))
        stored = _store_board_settings(entry, body.type, body.layout)
        # **Deliberately not wrapped in `@events.writes`.** A title change
        # here goes through `manager.update_entry`, which records the note's
        # own `edited` event; a write scope on this route would fold that
        # into the board's event and take the edit out of the note's history,
        # which is where a person looks for it and where its replay needs it.
        # So the board's settings, which the manager knows nothing about, get
        # their own event beside the note's rather than instead of it.
        events.record(
            db,
            "edited",
            "board",
            entry.id,
            f"{stored[0]}, {stored[1]}",
            payload={"after": dict(zip(("type", "layout"), stored)), "before": before},
        )
    if body.title is not None:
        title = body.title.strip()
        update_entry(db, entry, content=apply_title(entry.content, title))
    else:
        # `update_entry` commits for us; without a title change nothing else
        # would, and the settings above would be lost on session close.
        db.commit()
        title = extract_title(entry.content) or entry.content.strip()[:40] or f"Note {entry.id}"
    board_type, layout = _board_settings(entry)
    node_count = db.scalar(
        select(func.count()).select_from(WhiteboardNode).where(WhiteboardNode.board_id == board_id)
    )
    sketch_count = db.scalar(
        select(func.count()).select_from(WhiteboardSketch).where(WhiteboardSketch.board_id == board_id)
    )
    object_count = db.scalar(
        select(func.count()).select_from(WhiteboardObject).where(WhiteboardObject.board_id == board_id)
    )
    return BoardOut(
        id=board_id,
        title=title,
        node_count=node_count,
        sketch_count=sketch_count,
        object_count=object_count,
        type=board_type,
        layout=layout,
        **_preview_fields(db, board_id),
    )


@router.post("/nodes", response_model=WhiteboardNodeOut)
@events.writes("whiteboard_node", "placed")
def create_node(
    node_in: WhiteboardNodeBase, db: Session = Depends(get_session)
) -> WhiteboardNode:
    _require_entry(db, node_in.entry_id)
    _require_board(db, node_in.board_id)
    # One card per note per board. Dropping the same note on a board twice is
    # a move, not a duplicate, the alternative is two cards stacked exactly
    # on top of each other, which reads as one card that won't drag properly.
    existing = db.scalar(
        select(WhiteboardNode).where(
            WhiteboardNode.entry_id == node_in.entry_id,
            _board_filter(WhiteboardNode, node_in.board_id),
        )
    )
    node = existing or WhiteboardNode(
        entry_id=node_in.entry_id, board_id=node_in.board_id
    )
    node.x, node.y, node.z = node_in.x, node_in.y, node_in.z
    node.width, node.height, node.group_id = node_in.width, node_in.height, node_in.group_id
    node.rotation = node_in.rotation
    if existing is None:
        db.add(node)
        db.flush()  # so the event can name the card's id
    # "placed" rather than "created": dropping the same note on the same board
    # twice moves the card that is already there (see above), so one verb has
    # to be honest about both, and where the card ended up is the fact worth
    # keeping either way.
    events.record(
        db,
        "placed",
        "whiteboard_node",
        node.id,
        f"note {node.entry_id} on board {node.board_id}",
        payload={"after": _node_state(node), "existing": existing is not None},
    )
    db.commit()
    db.refresh(node)
    return node


@router.put("/nodes/{node_id}", response_model=WhiteboardNodeOut)
@events.writes("whiteboard_node", "edited")
def update_node(
    node_id: int, node_in: WhiteboardNodeBase, db: Session = Depends(get_session)
) -> WhiteboardNode:
    node = deps.get_or_404(db, WhiteboardNode, node_id, "Node not found")
    _require_entry(db, node_in.entry_id)
    _require_board(db, node_in.board_id)
    before = _node_state(node)
    node.entry_id = node_in.entry_id
    # `board_id` was read from the body and then never assigned, so moving a
    # card between boards returned 200 and changed nothing.
    node.board_id = node_in.board_id
    node.x, node.y, node.z = node_in.x, node_in.y, node_in.z
    node.width, node.height, node.group_id = node_in.width, node_in.height, node_in.group_id
    node.rotation = node_in.rotation
    events.record(
        db,
        "edited",
        "whiteboard_node",
        node.id,
        f"card on board {node.board_id}",
        payload={"after": _node_state(node), "before": before},
    )
    db.commit()
    db.refresh(node)
    return node


@router.delete("/nodes/{node_id}")
@events.writes("whiteboard_node", "deleted")
def delete_node(node_id: int, db: Session = Depends(get_session)) -> dict:
    # 404 rather than a cheerful "ok": deleting something that isn't there
    # is how a client finds out its board is stale, and swallowing it left
    # ghost cards on screen until a reload.
    node = deps.get_or_404(db, WhiteboardNode, node_id, "Node not found")
    events.record(
        db,
        "deleted",
        "whiteboard_node",
        node.id,
        f"card off board {node.board_id}",
        payload={"before": _node_state(node), "after": dict(_DELETED)},
    )
    _forget_links_to(db, node.board_id, "node", node.id)
    db.delete(node)
    db.commit()
    return {"status": "ok"}


@router.post("/sketches", response_model=WhiteboardSketchOut)
@events.writes("whiteboard_sketch", "created")
def create_sketch(
    sketch_in: WhiteboardSketchBase, db: Session = Depends(get_session)
) -> WhiteboardSketch:
    _require_board(db, sketch_in.board_id)
    sketch = WhiteboardSketch(**sketch_in.model_dump())
    db.add(sketch)
    db.flush()  # so the event can name the sketch's id
    events.record(
        db,
        "created",
        "whiteboard_sketch",
        sketch.id,
        f"drawing on board {sketch.board_id}",
        payload={"after": _sketch_state(sketch)},
    )
    db.commit()
    db.refresh(sketch)
    return sketch


@router.put("/sketches/{sketch_id}", response_model=WhiteboardSketchOut)
@events.writes("whiteboard_sketch", "edited")
def update_sketch(
    sketch_id: int, sketch_in: WhiteboardSketchBase, db: Session = Depends(get_session)
) -> WhiteboardSketch:
    sketch = deps.get_or_404(db, WhiteboardSketch, sketch_id, "Sketch not found")
    _require_board(db, sketch_in.board_id)
    before = _sketch_state(sketch)
    sketch.data = sketch_in.data
    sketch.board_id = sketch_in.board_id
    sketch.x, sketch.y, sketch.z = sketch_in.x, sketch_in.y, sketch_in.z
    sketch.group_id = sketch_in.group_id
    events.record(
        db,
        "edited",
        "whiteboard_sketch",
        sketch.id,
        f"drawing on board {sketch.board_id}",
        payload={"after": _sketch_state(sketch), "before": before},
    )
    db.commit()
    db.refresh(sketch)
    return sketch


@router.delete("/sketches/{sketch_id}")
@events.writes("whiteboard_sketch", "deleted")
def delete_sketch(sketch_id: int, db: Session = Depends(get_session)) -> dict:
    sketch = deps.get_or_404(db, WhiteboardSketch, sketch_id, "Sketch not found")
    events.record(
        db,
        "deleted",
        "whiteboard_sketch",
        sketch.id,
        f"drawing off board {sketch.board_id}",
        payload={"before": _sketch_state(sketch), "after": dict(_DELETED)},
    )
    _forget_links_to(db, sketch.board_id, "sketch", sketch.id)
    db.delete(sketch)
    db.commit()
    return {"status": "ok"}


# --- objects: images and text boxes, neither tied to a note -----------------
#
# Asked for directly: "images can also be attached by copy and pasting into
# the whiteboard as well though they wouldn't be shown in a note and would
# only be accessible from the library and the whiteboard", and separately,
# "I want the whiteboard to basically be like OneNote and Microsoft
# Whiteboard", which needs a real text box. A card always wraps an existing
# note; a sketch is a path, not a placeable rectangle. Neither fits an image
# or a text box, hence a third kind of thing on the canvas.


@router.post("/objects", response_model=WhiteboardObjectOut, status_code=201)
@events.writes("whiteboard_object", "created")
def create_object(
    body: WhiteboardObjectBase, db: Session = Depends(get_session)
) -> WhiteboardObjectOut:
    _require_board(db, body.board_id)
    _require_object_data(body)
    obj = WhiteboardObject(
        kind=body.kind,
        data=body.data.model_dump_json(exclude_none=True),
        board_id=body.board_id,
        x=body.x,
        y=body.y,
        z=body.z,
        width=body.width,
        height=body.height,
        rotation=body.rotation,
        group_id=body.group_id,
    )
    db.add(obj)
    db.flush()  # so the event can name the object's id
    events.record(
        db,
        "created",
        "whiteboard_object",
        obj.id,
        f"{obj.kind} on board {obj.board_id}",
        payload={"after": _object_state(obj)},
    )
    db.commit()
    db.refresh(obj)
    if obj.kind == "image":
        # Placing an image object on the board is itself the commit, a
        # whiteboard has no separate staging/save step the way a note or
        # chat draft does, so this fires immediately (core/media_process.py's
        # own docstring covers the other three commit points).
        from memorymap.core import media_process

        media_process.process_referenced_uploads(
            db, deps.get_config().data_dir / "media", obj.data
        )
    return _object_to_out(obj)


@router.put("/objects/{object_id}", response_model=WhiteboardObjectOut)
@events.writes("whiteboard_object", "edited")
def update_object(
    object_id: int, body: WhiteboardObjectBase, db: Session = Depends(get_session)
) -> WhiteboardObjectOut:
    obj = deps.get_or_404(db, WhiteboardObject, object_id, "Object not found")
    _require_board(db, body.board_id)
    _require_object_data(body)
    # The kind an object was created as doesn't change: an image resized or
    # moved is still an image; nothing in the UI offers "turn this into a
    # text box", so treating a mismatched kind here as a client bug rather
    # than silently reinterpreting the row is the safer failure.
    if body.kind != obj.kind:
        raise HTTPException(status_code=422, detail="An object's kind can't change")
    before = _object_state(obj)
    obj.data = body.data.model_dump_json(exclude_none=True)
    obj.board_id = body.board_id
    obj.x, obj.y, obj.z = body.x, body.y, body.z
    obj.width, obj.height = body.width, body.height
    obj.rotation = body.rotation
    obj.group_id = body.group_id
    events.record(
        db,
        "edited",
        "whiteboard_object",
        obj.id,
        f"{obj.kind} on board {obj.board_id}",
        payload={"after": _object_state(obj), "before": before},
    )
    db.commit()
    db.refresh(obj)
    return _object_to_out(obj)


@router.delete("/objects/{object_id}")
@events.writes("whiteboard_object", "deleted")
def delete_object(object_id: int, db: Session = Depends(get_session)) -> dict:
    """Delete an object: and, on a map, everything hanging off it.

    **Coggle's rule, chosen deliberately over re-parenting** (MINDMAP_PLAN.md
    §5.4). The alternative, promoting a deleted node's children to its
    parent, reads as the gentler option and is worse: a branch you meant to
    remove reappears as loose children under a node that never had them, and
    there is no single action that puts it back. Deleting the subtree is one
    action, so it can be undone as one, which is why the whole subtree comes
    back in the response, rows and positions included, rather than a count.

    An ordinary object has no children, so this is exactly what it always
    was for a text box or an image.
    """
    obj = deps.get_or_404(db, WhiteboardObject, object_id, "Object not found")
    doomed = _subtree(db, obj)
    deleted = [_object_to_out(row).model_dump() for row in doomed]
    # One event with the id list, the same shape a purge of notes records
    # (`manager.purge_entries`): deleting a branch is one action a person took
    # and has to be undoable as one, so it is one event holding the state of
    # every row that went, not one event per row.
    events.record(
        db,
        "deleted",
        "whiteboard_object",
        obj.id,
        f"{obj.kind} on board {obj.board_id}"
        + (f" with {len(doomed) - 1} under it" if len(doomed) > 1 else ""),
        payload={
            "before": _object_state(obj),
            "after": dict(_DELETED),
            "ids": [row.id for row in doomed],
            "subtree": [_object_state(row) for row in doomed],
        },
    )
    for row in doomed:
        _delete_one_object(db, row)
    db.commit()
    return {"status": "ok", "deleted": deleted}


def _subtree(db: Session, root: WhiteboardObject) -> list[WhiteboardObject]:
    """`root` and every map node under it, deepest last.

    Breadth-first with a seen-set rather than recursion, because `parent_id`
    is a plain integer with no database-level constraint behind it (see the
    column's own comment): a cycle written by a bad client, or by a bug in
    something that has not been written yet, must end this walk rather than
    the process. Scoped to `root`'s own board for the same reason every other
    write here is: a child claiming a parent on another board is not part of
    this tree.
    """
    found = [root]
    seen = {root.id}
    frontier = [root.id]
    while frontier:
        children = db.scalars(
            select(WhiteboardObject).where(
                WhiteboardObject.parent_id.in_(frontier),
                _board_filter(WhiteboardObject, root.board_id),
            )
        ).all()
        frontier = []
        for child in children:
            if child.id in seen:
                continue
            seen.add(child.id)
            found.append(child)
            frontier.append(child.id)
    return found


def _delete_one_object(db: Session, obj: WhiteboardObject) -> None:
    """The per-row half of `delete_object`: forget its links, unlink its file
    if it owned one, remove the row. Does not commit: a subtree is one
    delete, so it is one transaction."""
    _forget_links_to(db, obj.board_id, "object", obj.id)
    if obj.kind == "image":
        # The only thing that ever pointed at this file, best-effort, the
        # same rule `_hard_delete` already follows for an attachment's own
        # file: the row goes either way, a stubborn file must not block it.
        # `_media_path` returns None for anything that isn't provably inside
        # the media folder, so a hand-edited or legacy row cannot turn this
        # into "delete any file on disk".
        try:
            path = _media_path(json.loads(obj.data).get("url", "") or "")
            if path is not None:
                path.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            # `int(obj.id)` rather than anything that came off the request.
            # FastAPI already rejects a non-integer path parameter with a 422
            # before any of this runs, so it cannot carry the newline a forged
            # log line would need, but a path parameter reaching a log record
            # is a flow CodeQL flags on principle (py/log-injection), and the
            # explicit conversion keeps that guarantee true even if the
            # signature is ever loosened to a str.
            logging.getLogger("memorymap.whiteboard").warning(
                "couldn't delete the file for whiteboard image %s (%s); "
                "removing the record anyway",
                int(obj.id),
                type(exc).__name__,
            )
    db.delete(obj)


# --- maps: the same board, with a tree on it --------------------------------
#
# MINDMAP_PLAN.md §4 chose option B, a mindmap is a board with `type: "map"`,
# not a second entity with its own tables. Everything below therefore reads
# and writes the rows that already exist (`WhiteboardObject`, and link
# sketches for cross-branch connections); the only genuinely new endpoints are
# the ones that would otherwise force a client to invent a tree out of a flat
# list, and to invent coordinates for it.


#: How far a map's own tree walks will go before deciding the tree is not
#: one. `parent_id` has no database constraint behind it (see the column's
#: comment), so a cycle is possible in principle; every walk here is
#: iterative and seen-set guarded, and this is the second belt, a map 200
#: levels deep is a bug, not a map.
MAX_MAP_DEPTH = 200

#: Where a node lands when the caller does not say. Mirrored from
#: `ai/tools/whiteboard.py`'s `_DIAGRAM_ROW`/`_DIAGRAM_COL`, which are
#: themselves mirrored from the whiteboard's own `wbArrangeMindMap`, so a
#: node added by the AI, by an import, and by a person's own Tab key all land
#: on the same spacing convention instead of three different ones.
MAP_ROW = 170.0
MAP_COL = 320.0

#: An imported outline's ceiling, in characters and in nodes. An import is
#: the one door in this app that takes a document written somewhere else, so
#: it is the one that needs a size the parser cannot be argued out of.
MAX_IMPORT_CHARS = 400_000
MAX_IMPORT_NODES = 2_000

#: How deep an imported outline may nest. Deeper than any real map, shallow
#: enough that a file of nothing but indentation cannot build a stack.
MAX_IMPORT_DEPTH = 40


def _map_kind_ok(kind: str) -> None:
    if kind != MAP_TOPIC_KIND and kind not in MAP_REFERENCE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown map node kind {kind!r}: expected "
                + ", ".join(sorted({MAP_TOPIC_KIND} | MAP_REFERENCE_KINDS))
            ),
        )


def _require_reference(db: Session, kind: str, ref_id: int | None) -> None:
    """A reference node has to point at something that exists.

    The same rule, and the same reason, as `_require_entry` at the top of
    this file: an unvalidated id is a node that stores fine, draws as an
    empty box, and cannot be identified or removed from the UI afterwards,
    because the thing you would click is the item that isn't there.

    Privacy is deliberately *not* checked here, and that is not an oversight.
    Putting your own private note on your own map is the same act as dropping
    it on a board (`create_node` does not refuse it either), the app is
    behind the lock either way. The refusal that matters is the AI's, and it
    lives where the AI is: `_require_note` in `ai/tools/_common.py`, which
    every map tool in `ai/tools/whiteboard.py` calls before it writes, and
    `read_mindmap`, which will not read a private note's text back out.
    """
    from memorymap.core.database import Attachment, Bookmark, Document

    if ref_id is None:
        raise HTTPException(status_code=422, detail=f"A {kind} node needs a ref_id")
    if kind == "note":
        _require_entry(db, ref_id)
        return
    model, label = {
        "document": (Document, "document"),
        "file": (Attachment, "file"),
        "link": (Bookmark, "bookmark"),
    }[kind]
    if db.get(model, ref_id) is None:
        raise HTTPException(status_code=404, detail=f"No {label} with id {ref_id}")


def _reference_label(db: Session, kind: str, ref_id: int | None, fallback: str) -> str:
    """What a reference node is *called*, resolved from the thing it points
    at rather than copied into the map when the node was made.

    Copied text goes stale the moment the note is renamed, and a map full of
    names that no longer match the notes is worse than one with no names at
    all. A private note contributes the fact of the reference and nothing
    else: the same rule the board preview and the Connections block follow.
    """
    from memorymap.core.database import Attachment, Bookmark, Document
    from memorymap.entry import manager

    if ref_id is None:
        return fallback
    if kind == "note":
        entry = db.get(Entry, ref_id)
        if entry is None or entry.is_deleted:
            return fallback or "(note missing)"
        if entry.is_private:
            return "Private note"
        text = manager.readable_content(entry)
        return manager.extract_title(text) or text.strip().split("\n")[0][:80] or fallback
    if kind == "document":
        document = db.get(Document, ref_id)
        return (document.title if document is not None else "") or fallback
    if kind == "file":
        attachment = db.get(Attachment, ref_id)
        return (attachment.filename if attachment is not None else "") or fallback
    if kind == "link":
        bookmark = db.get(Bookmark, ref_id)
        if bookmark is None:
            return fallback
        return bookmark.title or bookmark.url or fallback
    return fallback


def _reference_facets(db: Session, kind: str, ref_id: int | None) -> dict:
    """What the *notebook* knows about the note behind a node: its category
    and when it was last edited.

    MINDMAP_PLAN.md §5 item 19, and the sentence in it that is the reason
    this is here at all: colouring a map by category or by age is "the thing
    a general mindmapper cannot do", because a general mindmapper has only
    the tree. Resolved on the server for the same reason the label is
    (`_reference_label`): a copy on the client goes stale the moment a note is
    refiled, and the client has no way to know it did.

    Only for `note` nodes. A document, file or link has no filing of its own
    in this notebook, and a private note contributes nothing at all, which is
    the same boundary its title is behind one function above.
    """
    from memorymap.core.database import Category

    if kind != "note" or ref_id is None:
        return {}
    entry = db.get(Entry, ref_id)
    if entry is None or entry.is_deleted or entry.is_private:
        return {}
    category = db.get(Category, entry.category_id) if entry.category_id is not None else None
    return {
        "ref_category": category.name if category is not None else "Unfiled",
        # Naive UTC, as every timestamp in this database is: the client reads
        # it as UTC explicitly rather than letting the browser guess a zone.
        "ref_updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _object_data(obj: WhiteboardObject) -> dict:
    """An object's JSON blob, never raising. A row edited by hand, or written
    by an older version, must not take a whole board's tree down with it."""
    try:
        parsed = json.loads(obj.data or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


#: What the node edit strip and the two radials write on a node, beyond its
#: text and its colour (MINDMAP_PLAN.md §12.1 items 2 to 4). Named in one
#: place because three things have to agree about them: the tree endpoint
#: hands them to the canvas, the two XML exports carry them out, and the two
#: XML imports read them back. The seven that arrived with the strip and the
#: rings were invisible to the exports for exactly as long as this list did
#: not exist, and §12.0 says a feature that cannot round-trip is not built.
#: `color` is not here because a node dict has carried it as a key of its own
#: since long before the strip existed; the exports read both.
MAP_STYLE_FIELDS = (
    "bold",
    "italic",
    "font_size",
    "align",
    "shape",
    "icon",
    "link",
    "edge_label",
    "edge_style",
    "edge_dashed",
)


def _map_node_style(data: dict) -> dict:
    """The style fields a node actually carries, in a fixed order, with the
    unset ones left out: an export writes an attribute only for what somebody
    chose, so a plain map exports as the same file it did before any of this
    existed."""
    style: dict = {}
    for field in MAP_STYLE_FIELDS:
        value = data.get(field)
        if value is None or value is False or value == "":
            continue
        style[field] = value
    return style


def _map_node_dict(db: Session, obj: WhiteboardObject) -> dict:
    """One node, flat: `_build_tree` fills in `children`."""
    data = _object_data(obj)
    content = str(data.get("content") or "")
    raw_ref = data.get("ref_id")
    ref_id = int(raw_ref) if isinstance(raw_ref, int) else None
    text = (
        content
        if obj.kind in (MAP_TOPIC_KIND, "text")
        else _reference_label(db, obj.kind, ref_id, content)
    )
    node = {
        "id": obj.id,
        "kind": obj.kind,
        "text": text,
        "ref_id": ref_id,
        "x": obj.x,
        "y": obj.y,
        "color": data.get("color"),
        "collapsed": bool(data.get("collapsed")),
        "pinned": bool(data.get("pinned")),
        "style": _map_node_style(data),
        "children": [],
    }
    node.update(_reference_facets(db, obj.kind, ref_id))
    return node


def _build_tree(db: Session, objects: list[WhiteboardObject]) -> list[dict]:
    """The board's objects as nested roots.

    **A node whose parent is not on this board is a root**, and that is the
    reason this is not a two-line recursion down from `parent_id IS NULL`.
    `parent_id` is a plain integer (see the column's comment), so a pointer
    can go stale: and a walk that starts only from NULL silently drops every
    node under a broken pointer. The board still holds them; the map just
    stops showing them, which is the worst way to lose something.
    """
    nodes = {obj.id: _map_node_dict(db, obj) for obj in objects}
    roots: list[dict] = []
    for obj in objects:
        parent = nodes.get(obj.parent_id) if obj.parent_id is not None else None
        if parent is None:
            roots.append(nodes[obj.id])
        else:
            parent["children"].append(nodes[obj.id])

    # A ring (a → b → a) leaves both nodes attached to each other and neither
    # in `roots`, so the outline would simply not mention them. They are
    # still on the board, so the lowest id of each unreachable ring is
    # re-rooted and the rest follows it, rather than pretending the rows are
    # not there.
    reachable: set[int] = set()

    def claim(start: dict) -> None:
        frontier = [start]
        while frontier:
            node = frontier.pop()
            if node["id"] in reachable:
                continue
            reachable.add(node["id"])
            frontier.extend(node["children"])

    for root in list(roots):
        claim(root)
    for obj in objects:
        if obj.id not in reachable:
            roots.append(nodes[obj.id])
            claim(nodes[obj.id])
    return roots


def _map_objects(db: Session, board_id: int | None) -> list[WhiteboardObject]:
    """Every object on a board, oldest first, creation order, which is the
    order a person built the map in and the only one an outline can be read
    in without surprises. Position decides where a node is *drawn*; it does
    not decide what the map says."""
    return list(
        db.scalars(
            select(WhiteboardObject)
            .where(_board_filter(WhiteboardObject, board_id))
            .order_by(WhiteboardObject.id)
        )
    )


def _cross_links(db: Session, board_id: int | None, node_ids: set[int]) -> list[dict]:
    """The non-tree edges: link sketches whose two ends are both map nodes.

    Kept as link sketches rather than given a table of their own, because
    that is what a link between two things on a board already is, the
    frontend draws them and `_forget_links_to` cleans them up, and a second
    representation would need both written again.
    """
    out: list[dict] = []
    for sketch in db.scalars(
        select(WhiteboardSketch)
        .where(_board_filter(WhiteboardSketch, board_id))
        .order_by(WhiteboardSketch.id)
    ):
        try:
            data = json.loads(sketch.data or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or not str(data.get("type", "")).startswith("link-"):
            continue
        source_kind = data.get("sourceKind") or "node"
        target_kind = data.get("targetKind") or "node"
        if source_kind != "object" or target_kind != "object":
            continue
        source, target = data.get("sourceId"), data.get("targetId")
        if source in node_ids and target in node_ids:
            out.append(
                {"from_id": source, "to_id": target, "label": str(data.get("label") or "")}
            )
    return out


class MapTreeOut(BaseModel):
    board_id: int
    title: str
    type: str
    layout: str
    #: Nested `{id, kind, text, ref_id, x, y, color, collapsed, pinned,
    #: style, children}`, where `style` holds whichever of
    #: `MAP_STYLE_FIELDS` the node actually carries. Typed as `list[dict]`
    #: rather than as a self-referencing
    #: model: OpenAPI's handling of recursive schemas buys nothing here, and
    #: the shape is documented above and asserted in `tests/test_mindmap.py`.
    roots: list[dict]
    cross_links: list[dict]


def _board_entry(db: Session, board_id: int) -> Entry:
    """The note behind a board, or the 404 `rename_board` already gives: 
    `board_id=0` and negative ids can't resolve to a real note either."""
    entry = db.get(Entry, board_id) if board_id > 0 else None
    if entry is None or entry.is_deleted:
        raise HTTPException(status_code=404, detail=f"No board with id {board_id}")
    return entry


@router.get("/boards/{board_id}/tree", response_model=MapTreeOut)
def board_tree(board_id: int, db: Session = Depends(get_session)) -> MapTreeOut:
    """The board as a nested tree, plus its cross-links.

    The one endpoint a map client cannot do without: `GET /whiteboard/` hands
    back a flat list of objects, and rebuilding the tree from it client-side
    means every reader (the canvas, the Library thumbnail, an export, the
    agent) writes the same walk again, including the dangling-parent and
    ring cases, which is exactly the sort of thing four copies get subtly
    differently.
    """
    entry = _board_entry(db, board_id)
    board_type, layout = _board_settings(entry)
    objects = _map_objects(db, board_id)
    return MapTreeOut(
        board_id=board_id,
        title=extract_title(entry.content) or entry.content.strip()[:40] or f"Note {board_id}",
        type=board_type,
        layout=layout,
        roots=_build_tree(db, objects),
        cross_links=_cross_links(db, board_id, {obj.id for obj in objects}),
    )


class MapNodeCreate(BaseModel):
    kind: str = MAP_TOPIC_KIND
    #: The parent this node hangs off, or None for a root topic.
    parent_id: int | None = None
    text: str = Field(default="", max_length=MAX_OBJECT_TEXT_CHARS)
    #: For a `note`/`document`/`file`/`link` node: what it stands for.
    ref_id: int | None = Field(default=None, ge=1)
    #: Omitted means "put it somewhere sensible", see `_next_position`. A
    #: caller that has to invent coordinates gets them wrong, which is the
    #: whole reason `generate_diagram` computes them server-side too.
    x: float | None = None
    y: float | None = None
    color: str | None = Field(default=None, max_length=20)


def _next_position(
    db: Session, board_id: int, parent: WhiteboardObject | None
) -> tuple[float, float]:
    """Where a new node goes when the caller did not say.

    One column right of its parent, one row below the last sibling, the same
    row/column convention `wbArrangeMindMap` and `generate_diagram` already
    use, so a map built by hand, by import and by the agent does not read as
    three different tools' opinions. Roots stack down the left edge.
    """
    siblings = db.scalars(
        select(func.count())
        .select_from(WhiteboardObject)
        .where(
            _board_filter(WhiteboardObject, board_id),
            WhiteboardObject.parent_id == parent.id
            if parent is not None
            else WhiteboardObject.parent_id.is_(None),
        )
    ).one()
    if parent is None:
        return 0.0, float(siblings) * MAP_ROW
    return float(parent.x) + MAP_COL, float(parent.y) + float(siblings) * MAP_ROW


@router.post(
    "/boards/{board_id}/nodes", response_model=WhiteboardObjectOut, status_code=201
)
@events.writes("whiteboard_object", "created")
def create_map_node(
    board_id: int, body: MapNodeCreate, db: Session = Depends(get_session)
) -> WhiteboardObjectOut:
    """Add a node under a parent, or as a new root.

    Not a second CRUD for `whiteboard_objects`, `PUT`/`DELETE /objects/{id}`
    still own the rest of a node's life. This exists for the two things the
    generic create cannot do without a client that already knows the whole
    tree: attach the node to a parent (with the board scoping that implies)
    and work out where it goes.
    """
    _require_board(db, board_id)
    _map_kind_ok(body.kind)
    if body.kind in MAP_REFERENCE_KINDS:
        _require_reference(db, body.kind, body.ref_id)

    parent = None
    if body.parent_id is not None:
        parent = db.get(WhiteboardObject, body.parent_id)
        # Scoped to the board it claims, the rule this module opens with. A
        # parent on another board would build a tree spanning two boards,
        # which renders on neither.
        if parent is None or parent.board_id != board_id:
            raise HTTPException(
                status_code=404,
                detail=f"No node with id {body.parent_id} on this board",
            )

    if body.x is not None and body.y is not None:
        x, y = body.x, body.y
    else:
        x, y = _next_position(db, board_id, parent)
    data = WhiteboardObjectData(
        content=body.text,
        ref_id=body.ref_id if body.kind in MAP_REFERENCE_KINDS else None,
        color=body.color,
    )
    obj = WhiteboardObject(
        board_id=board_id,
        kind=body.kind,
        data=data.model_dump_json(exclude_none=True),
        x=x,
        y=y,
        z=1,
        parent_id=parent.id if parent is not None else None,
    )
    db.add(obj)
    db.flush()  # so the event can name the node's id
    events.record(
        db,
        "created",
        "whiteboard_object",
        obj.id,
        f"{obj.kind} on map {board_id}",
        payload={"after": _object_state(obj)},
    )
    db.commit()
    db.refresh(obj)
    return _object_to_out(obj)


class MapNodeMove(BaseModel):
    #: The new parent, or None to promote the node to a root. The node keeps
    #: its own children either way, moving a node moves its branch.
    parent_id: int | None = None


def _is_descendant(
    db: Session, node_id: int, candidate_id: int, board_id: int | None
) -> bool:
    """Is `candidate_id` somewhere under `node_id`?

    Walks down rather than up, and iteratively: walking up from the candidate
    follows `parent_id` pointers that may already be broken, and a recursive
    walk of a tree that is not one is a stack overflow rather than a refusal.
    """
    seen = {node_id}
    frontier = [node_id]
    depth = 0
    while frontier and depth < MAX_MAP_DEPTH:
        children = list(
            db.scalars(
                select(WhiteboardObject.id).where(
                    WhiteboardObject.parent_id.in_(frontier),
                    _board_filter(WhiteboardObject, board_id),
                )
            )
        )
        if candidate_id in children:
            return True
        frontier = [child for child in children if child not in seen]
        seen.update(frontier)
        depth += 1
    return False


@router.put(
    "/boards/{board_id}/nodes/{node_id}/move", response_model=WhiteboardObjectOut
)
@events.writes("whiteboard_object", "edited")
def move_map_node(
    board_id: int, node_id: int, body: MapNodeMove, db: Session = Depends(get_session)
) -> WhiteboardObjectOut:
    """Re-parent a node, and with it its whole branch.

    **The cycle check is why this endpoint exists at all**, and why `PUT
    /objects/{id}` deliberately does not touch `parent_id`: a node made its
    own descendant produces a ring no tree walk can leave, so the map becomes
    unreadable: and the only UI that could undo it is the one that has just
    stopped rendering.
    """
    _require_board(db, board_id)
    node = db.get(WhiteboardObject, node_id)
    if node is None or node.board_id != board_id:
        raise HTTPException(
            status_code=404, detail=f"No node with id {node_id} on this board"
        )

    before = _object_state(node)
    if body.parent_id is None:
        node.parent_id = None
    else:
        if body.parent_id == node.id:
            raise HTTPException(
                status_code=422,
                detail="A node can't be its own parent, that makes it a descendant of itself.",
            )
        parent = db.get(WhiteboardObject, body.parent_id)
        if parent is None or parent.board_id != board_id:
            raise HTTPException(
                status_code=404,
                detail=f"No node with id {body.parent_id} on this board",
            )
        if _is_descendant(db, node.id, parent.id, board_id):
            raise HTTPException(
                status_code=422,
                detail="That would make the node a descendant of itself, move the branch out first.",
            )
        node.parent_id = parent.id
    events.record(
        db,
        "edited",
        "whiteboard_object",
        node.id,
        f"moved under {node.parent_id}" if node.parent_id else "moved to a root",
        payload={"after": _object_state(node), "before": before},
    )
    db.commit()
    db.refresh(node)
    return _object_to_out(node)


# --- export and import: text formats, so a map is not a lock-in -------------
#
# MINDMAP_PLAN.md §5 items 16-17. PNG/SVG/PDF come from the canvas and are the
# frontend's; Markdown and OPML are text, cost nothing, and are what every
# other mindmapper reads: which is the difference between a map you can take
# with you and a map you can only look at here.


def _outline_rows(roots: list[dict]) -> list[tuple[int, dict]]:
    """The tree flattened to `(depth, node)` in reading order. Iterative for
    the same reason every other walk in this file is.

    **And guarded by a seen set, which is a different reason.** Iterative made
    this safe against a deep map and did nothing at all about a *ring*.
    `_build_tree` deliberately re-roots the lowest id of an unreachable ring
    so its rows are not silently dropped, which means a ring arrives here as a
    root whose descendants lead back to it: a to b to a, forever, appending a
    row each time. That is not a crash, it is a Markdown export that never
    returns and grows until the process dies, which is worse than a 500.

    The depth is clamped rather than the walk cut short: an outline is a
    picture of the whole map, and dropping a subtree past some depth loses
    rows a person typed. `MAX_MAP_DEPTH` is the figure every other walk in
    this file stops at.
    """
    rows: list[tuple[int, dict]] = []
    seen: set[int] = set()
    stack = [(0, node) for node in reversed(roots)]
    while stack:
        depth, node = stack.pop()
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        rows.append((min(depth, MAX_MAP_DEPTH), node))
        for child in reversed(node["children"]):
            stack.append((depth + 1, child))
    return rows


def _export_tree(root_element, roots: list[dict], build) -> None:
    """Build one element per node, under the element its parent built.

    **The two XML exports used to recurse, and they were the only walks in
    this file that did.** Every other one is iterative with a seen set, and
    `_is_descendant`'s comment says why: a walk of a tree that is not one is a
    stack overflow rather than a refusal. These two had the same exposure from
    two directions. Nothing caps how deep a map built by hand can go
    (`MAX_IMPORT_DEPTH` caps an import; the Tab key is not an import), so a
    branch deeper than Python's own recursion headroom exported as a
    `RecursionError`, which reaches the person downloading it as a 500. And
    `_build_tree` re-roots the lowest id of an unreachable ring rather than
    dropping its rows, so a ring arrives here as a root whose descendants lead
    back to it, and a recursive walk of that never returns at all.

    `build(parent_element, node)` returns the element it made, so the walk
    holds no state of its own between calls: two exports running at once share
    nothing, which a module-level map of node id to element would not have
    given.

    Nesting is clamped at `MAX_MAP_DEPTH` rather than cut: a node past the cap
    is written as a sibling at the cap instead of being dropped, so the file
    still holds every topic a person typed. Two hundred levels is also about
    where a serialiser's own recursion becomes the next question, and
    `ElementTree.tostring` is recursive in CPython.
    """
    seen: set[int] = set()
    stack = [(root_element, 0, node) for node in reversed(roots)]
    while stack:
        parent_element, depth, node = stack.pop()
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        element = build(parent_element, node)
        below = element if depth < MAX_MAP_DEPTH else parent_element
        for child in reversed(node["children"]):
            stack.append((below, depth + 1, child))


def _export_markdown(title: str, roots: list[dict]) -> str:
    """`# Title`, then a two-space-per-level bullet outline.

    A reference node carries what it points at on the same line, `- Sources
    (note 12)`, because an outline of bare titles is a picture of the map
    rather than a working document: the ids are what let it be read back, or
    followed by hand.

    **Everything a node wears is deliberately dropped here**, and that is the
    one export where dropping it is right: this format's whole promise is
    that the file is an outline anybody can paste into anything. The two XML
    exports carry the style (`MAP_STYLE_FIELDS`), and a bold marker or an
    icon name smuggled into a bullet would come back in on the Markdown
    import as part of somebody's topic text.
    """
    lines = [f"# {title}"]
    rows = _outline_rows(roots)
    if rows:
        lines.append("")
    for depth, node in rows:
        text = node["text"] or "(untitled)"
        suffix = ""
        if node["kind"] != MAP_TOPIC_KIND and node["ref_id"] is not None:
            suffix = f" ({node['kind']} {node['ref_id']})"
        lines.append(f"{'  ' * depth}- {text}{suffix}")
    return "\n".join(lines) + "\n"


#: How this map's three line shapes are spelled in FreeMind's own `<edge
#: STYLE>` vocabulary, and back. FreeMind's list is `linear`, `bezier`,
#: `sharp_linear`, `sharp_bezier`, `horizontal` and `hide_edge`: `bezier` is
#: a curve, `linear` is a straight segment, and `horizontal` is the
#: right-angled run this map calls an elbow. Writing the native spelling
#: rather than a private attribute is what makes a map exported here open in
#: FreeMind, Freeplane and Coggle *looking* the way it did.
_FREEMIND_EDGE_STYLE = {"curve": "bezier", "elbow": "horizontal", "straight": "linear"}
_FREEMIND_EDGE_STYLE_BACK = {value: key for key, value in _FREEMIND_EDGE_STYLE.items()}
#: And the ones with no native home, written as private attributes on the
#: node, the same device `_kind` and `_ref` already use here: an unknown
#: attribute is ignored by every other reader and survives a round trip
#: through this one. Per field, why it is here rather than in the format:
#:
#: - `icon`: FreeMind's `<icon BUILTIN>` is a closed enumeration of its own
#:   icon names, and this app's are Phosphor names. Writing a Phosphor name
#:   into BUILTIN would claim an icon FreeMind does not have, which renders
#:   as a gap there and does not come back as itself here.
#: - `edge_label`: FreeMind has no label on an edge at all. Freeplane grew
#:   one much later, in its own namespace, which FreeMind then refuses.
#: - `edge_dashed`: `<edge>` has STYLE, COLOR and WIDTH, and no dash.
#: - `align`: FreeMind aligns a node by which side of the root it sits on,
#:   not by a text alignment, so there is nothing to write it into.
_FREEMIND_PRIVATE = {
    #: `_shape` as well as the native `STYLE` below, not instead of it:
    #: FreeMind's node style is `bubble` or `fork` and has no third value, so
    #: STYLE alone cannot tell a pill from a box on the way back in. STYLE is
    #: what makes the file look right where it is opened; `_shape` is what
    #: makes it come back as itself.
    "shape": "_shape",
    "icon": "_icon",
    "edge_label": "_edge_label",
    "edge_dashed": "_edge_dashed",
    "align": "_align",
}
#: OPML 2.0 defines `text`, `type`, `url`, `isComment`, `isBreakpoint`,
#: `created` and `category` and nothing else, so `url` is the only native
#: home any of these have and the rest ride as private attributes. Reading a
#: map's look back out of an OPML file is then exact, and an OPML reader that
#: knows none of them still sees the outline it came for.
_OPML_PRIVATE = {
    "shape": "_shape",
    "bold": "_bold",
    "italic": "_italic",
    "font_size": "_font_size",
    "align": "_align",
    "icon": "_icon",
    "edge_label": "_edge_label",
    "edge_style": "_edge_style",
    "edge_dashed": "_edge_dashed",
}


def _xml_attribute(value) -> str:
    """A style value as an XML attribute. `True` is written as the string
    every XML format in this area uses, and the bool that comes back through
    `_clean_import_style` is Pydantic's own lax parse of it."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _export_opml(title: str, roots: list[dict]) -> str:
    """OPML 2.0: the interchange format every mindmapper reads.

    Built with ElementTree rather than by formatting strings, so that a topic
    containing `&`, `<` or a quote is escaped by something that knows the
    rules: which hand-written XML reliably gets wrong on the first
    apostrophe.
    """
    import xml.etree.ElementTree as ET

    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = title
    body = ET.SubElement(opml, "body")

    def build(parent_element, node: dict):
        attrs = {"text": node["text"] or "(untitled)"}
        if node["kind"] != MAP_TOPIC_KIND:
            # `_kind`/`_ref`, not `type`/`ref`: OPML's own `type` attribute
            # already means something else (how a reader should treat the
            # outline), and quietly redefining it would make this file wrong
            # for every other tool that opens it. An unknown attribute is
            # ignored by other readers and survives a round trip through
            # this one.
            attrs["_kind"] = node["kind"]
            if node["ref_id"] is not None:
                attrs["_ref"] = str(node["ref_id"])
        style = node.get("style") or {}
        if style.get("link"):
            # `url` is OPML 2.0's own attribute for where an outline points,
            # and it is the one thing on this list another reader will do
            # something useful with. `type="link"` is deliberately *not* set
            # alongside it: that would say the outline *is* a link rather
            # than a topic that has one, and a reader honouring it would drop
            # the children hanging underneath.
            attrs["url"] = style["link"]
        for field, attribute in _OPML_PRIVATE.items():
            if field in style:
                attrs[attribute] = _xml_attribute(style[field])
        if node.get("color"):
            attrs["_color"] = str(node["color"])
        return ET.SubElement(parent_element, "outline", attrs)

    _export_tree(body, roots, build)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(opml, encoding="unicode")
        + "\n"
    )


def _export_freemind(title: str, roots: list[dict]) -> str:
    """FreeMind `.mm`: the other format every mindmapper reads, and the one
    Coggle, Freeplane, XMind and MindMeister all import (§4's list).

    **A `.mm` file has exactly one root.** A map here may have several, which
    is a real shape (two unrelated trunks on one board), so a multi-root map is
    exported under one node named after the map rather than as several
    documents or as a file only this app can read back. A single-root map is
    written as itself, so the common case round-trips unchanged.

    `_kind`/`_ref` ride along for the same reason they do in the OPML export:
    FreeMind ignores attributes it does not know, and they are what lets a
    reference node come back as a reference node rather than as a topic.
    """
    import xml.etree.ElementTree as ET

    document = ET.Element("map", {"version": "1.0.1"})

    def build(parent_element, node: dict):
        attrs = {"TEXT": node["text"] or "(untitled)"}
        if node["kind"] != MAP_TOPIC_KIND:
            attrs["_kind"] = node["kind"]
            if node["ref_id"] is not None:
                attrs["_ref"] = str(node["ref_id"])
        style = node.get("style") or {}
        if style.get("link"):
            attrs["LINK"] = style["link"]
        for field, attribute in _FREEMIND_PRIVATE.items():
            if field in style:
                attrs[attribute] = _xml_attribute(style[field])
        if style.get("shape"):
            # FreeMind's own two: `fork` is a label on the line with no box
            # around it, which is exactly this map's "plain", and `bubble` is
            # the boxed node every other shape here is a variety of.
            attrs["STYLE"] = "fork" if style["shape"] == "none" else "bubble"
        element = ET.SubElement(parent_element, "node", attrs)
        # `<font>` and `<edge>` are FreeMind's own children of a node, and
        # they are written only when something was actually chosen: an empty
        # `<font/>` on every node would triple the size of a plain map's file
        # and say nothing. NAME is left off rather than filled with
        # "SansSerif": this app sets no font family, and writing one would be
        # a claim about the map that nobody here made.
        font = {}
        if style.get("bold"):
            font["BOLD"] = "true"
        if style.get("italic"):
            font["ITALIC"] = "true"
        if style.get("font_size"):
            font["SIZE"] = str(int(style["font_size"]))
        if font:
            ET.SubElement(element, "font", font)
        edge = {}
        if style.get("edge_style") in _FREEMIND_EDGE_STYLE:
            edge["STYLE"] = _FREEMIND_EDGE_STYLE[style["edge_style"]]
        if node.get("color"):
            # A map's node colour paints the spine down the node's leading
            # edge and the line coming into it (§12.0, "a node carries its
            # colour on its own card"), which is `<edge COLOR>` here rather
            # than `<node COLOR>`: FreeMind's node colour is its *text*
            # colour, and writing it there would recolour the words.
            edge["COLOR"] = str(node["color"])
        if edge:
            ET.SubElement(element, "edge", edge)
        return element

    under = document
    if len(roots) != 1:
        under = ET.SubElement(document, "node", {"TEXT": title})
    _export_tree(under, roots, build)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(document, encoding="unicode")
        + "\n"
    )


#: What each export format is called on the way out: the media type a browser
#: should treat it as, and the extension the file has to have. A `.md` file
#: holding OPML is a file nothing will open.
EXPORT_FORMATS = {
    "markdown": ("text/markdown", "md"),
    "opml": ("text/x-opml", "opml"),
    "freemind": ("application/x-freemind", "mm"),
}


@router.get("/boards/{board_id}/export")
def export_board(board_id: int, format: str = "markdown", db: Session = Depends(get_session)):
    """A map as an indented Markdown outline, or as OPML.

    Returned as a text response with a filename rather than as JSON: what a
    caller wants from this is a file, and a JSON envelope means every client
    writes the same unwrapping code before it can save one.
    """
    from fastapi.responses import Response

    if format not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown export format {format!r}: expected one of "
            + ", ".join(sorted(EXPORT_FORMATS)),
        )
    entry = _board_entry(db, board_id)
    title = extract_title(entry.content) or entry.content.strip()[:40] or f"Note {board_id}"
    roots = _build_tree(db, _map_objects(db, board_id))
    media, suffix = EXPORT_FORMATS[format]
    if format == "markdown":
        text = _export_markdown(title, roots)
    elif format == "opml":
        text = _export_opml(title, roots)
    else:
        text = _export_freemind(title, roots)
    # The filename is built from the board's id, never from its title: a
    # title is free text, and a Content-Disposition header is exactly where
    # free text becomes a header-injection question nobody wants to answer
    # twice.
    return Response(
        content=text,
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="board-{int(board_id)}.{suffix}"'
        },
    )


class MapImport(BaseModel):
    format: str
    content: str = Field(max_length=MAX_IMPORT_CHARS)
    #: What to call the new map. Omitted means "whatever the document calls
    #: itself", an OPML `<head><title>`, or a Markdown `#` heading.
    name: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("format")
    @classmethod
    def _known_format(cls, value: str) -> str:
        if value not in IMPORT_FORMATS:
            raise ValueError(
                f"Unknown import format {value!r}: expected one of "
                + ", ".join(sorted(IMPORT_FORMATS))
            )
        return value


#: The formats `import_board` reads. Markdown and OPML both round-trip with
#: the exports above; FreeMind `.mm` is the format Coggle, Freeplane, XMind and
#: MindMeister all write, which is what section 4's list meant by "an existing
#: map can come in".
IMPORT_FORMATS = ("markdown", "opml", "freemind")


def _parse_xml_document(content: str, label: str):
    """The XML door, for both formats that come through it.

    **A document type declaration is refused outright**, before the parser
    ever sees the string. `xml.etree` does not resolve *external* entities,
    but it does expand internal ones, which is the billion-laughs shape: a
    dozen nested entity definitions turn a 1KB file into gigabytes of memory
    inside the parse call, where no size cap on the way in can see it coming.
    Nothing else in this app parses XML from anywhere, and no real OPML or
    FreeMind file needs a DTD: so the door refuses one, which is a check that
    stays correct even if the parser behind it is swapped later.

    The parser behind it is `defusedxml`, not the stdlib: the string check
    above is belt, this is braces. defusedxml refuses entity declarations at
    the parser level, and it is also the only shape CodeQL's `py/xml-bomb`
    query accepts as safe, the stdlib call was flagged as a high-severity
    alert on this PR even with the guard in front of it.

    One function rather than one per format because a second copy of a
    security check is a second copy that can drift: the FreeMind import
    arrived after the OPML one and is exactly where the DOCTYPE guard would
    otherwise have been quietly left out.
    """
    try:
        from defusedxml import ElementTree as ET
        from defusedxml.common import DefusedXmlException
    except ImportError as exc:  # a hand-rolled install that skipped requirements.txt
        raise HTTPException(
            status_code=503,
            detail=f"{label} import needs the defusedxml package: pip install defusedxml",
        ) from exc

    lowered = content.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise HTTPException(
            status_code=422,
            detail=f"That {label} declares a document type. Remove the <!DOCTYPE ...> line and try again.",
        )
    try:
        return ET.fromstring(content)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise HTTPException(
            status_code=422, detail=f"That isn't valid {label}: {exc}"
        ) from exc


#: A colour arriving from a file is held to a hex literal, which is stricter
#: than the object PUT path (`max_length=20`, any string) on purpose. This
#: value is written into a CSS custom property on the node, and the door a
#: *file somebody was sent* comes through is not the door to widen: every
#: colour this app itself writes is a `<input type="color">` value, so the
#: rule costs nothing real and refuses everything else.
_IMPORT_COLOUR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _clean_import_style(raw: dict) -> dict:
    """The style attributes read off an imported node, validated one at a
    time, with anything that does not pass simply left out.

    **Validated by `WhiteboardObjectData` itself, field by field.** These
    values come off an XML attribute in a file from somewhere else, and they
    are written straight into `data`, which is the same blob the object PUT
    endpoint validates: so the rules that endpoint enforces (a Phosphor icon
    name and nothing else, an http/https/mailto link and nothing else, a font
    size in range, one of three line shapes) have to hold here too, and a
    second hand-written copy of them is a second copy that drifts. One field
    per `model_validate` call rather than the whole dict at once, because a
    file with one bad attribute should lose that attribute, not every
    attribute it had.
    """
    clean: dict = {}
    for field, value in raw.items():
        if value is None or value == "":
            continue
        if field == "color":
            text = str(value).strip()
            if _IMPORT_COLOUR.match(text):
                clean[field] = text
            continue
        try:
            checked = WhiteboardObjectData.model_validate({field: value})
        except ValidationError:
            continue
        settled = getattr(checked, field, None)
        if settled is not None and settled is not False:
            clean[field] = settled
    return clean


def _freemind_style(element) -> dict:
    """What a `<node>` wears, read back out of the shape `_export_freemind`
    writes: FreeMind's own `LINK`, `<font>` and `<edge>`, and the private
    attributes for the four things FreeMind has nowhere to put."""
    raw: dict = {"link": element.get("LINK")}
    for field, attribute in _FREEMIND_PRIVATE.items():
        raw[field] = element.get(attribute)
    if not raw.get("shape") and element.get("STYLE") == "fork":
        # A `.mm` from somewhere else has no `_shape`, and `fork` is the one
        # of FreeMind's two styles that means something here. `bubble` is left
        # alone: it is the boxed node, which is this map's own default, and
        # reading it as a shape would put a field on every imported node.
        raw["shape"] = "none"
    font = element.find("font")
    if font is not None:
        raw["bold"] = font.get("BOLD")
        raw["italic"] = font.get("ITALIC")
        raw["font_size"] = font.get("SIZE")
    edge = element.find("edge")
    if edge is not None:
        raw["edge_style"] = _FREEMIND_EDGE_STYLE_BACK.get(edge.get("STYLE") or "")
        raw["color"] = edge.get("COLOR")
    return _clean_import_style(raw)


def _opml_style(element) -> dict:
    """The same, for an `<outline>`: OPML's `url`, and the private attributes
    for everything OPML 2.0 has no word for."""
    raw: dict = {"link": element.get("url"), "color": element.get("_color")}
    for field, attribute in _OPML_PRIVATE.items():
        raw[field] = element.get(attribute)
    return _clean_import_style(raw)


def _parse_freemind(content: str) -> tuple[str, list[dict]]:
    """FreeMind `.mm` in, `(title, nested {text, children})` out.

    The format is one `<node TEXT="...">` inside another, and the document's
    single root node *is* its title: so the root's own text names the map and
    its children become the map's roots, which is the shape `_export_freemind`
    writes and the shape Freeplane and Coggle export. A file with several
    top-level nodes (not legal FreeMind, but files are files) keeps all of
    them and takes no title from them.

    Text can also live in a `<richcontent>` element rather than in `TEXT`.
    That body is HTML, and rendering someone else's HTML into a node is not a
    thing this import is going to do: such a node comes in unlabelled rather
    than with its markup as its label.
    """
    root = _parse_xml_document(content, "FreeMind")
    counted = [0]

    def walk(element, depth: int) -> list[dict]:
        out: list[dict] = []
        if depth >= MAX_IMPORT_DEPTH:
            return out
        for child in element.findall("node"):
            counted[0] += 1
            if counted[0] > MAX_IMPORT_NODES:
                raise HTTPException(
                    status_code=422,
                    detail=f"That outline has more than {MAX_IMPORT_NODES} nodes: split it up first.",
                )
            text = (child.get("TEXT") or child.get("text") or "").strip()
            out.append(
                {
                    "text": text[:MAX_OBJECT_TEXT_CHARS],
                    "style": _freemind_style(child),
                    "children": walk(child, depth + 1),
                }
            )
        return out

    tops = root.findall("node")
    if len(tops) == 1:
        # The one legal shape: the document's root node names the map, and the
        # map's own roots are its children.
        title = (tops[0].get("TEXT") or "").strip()
        return title, walk(tops[0], 0)
    return "", walk(root, 0)


def _parse_opml(content: str) -> tuple[str, list[dict]]:
    """OPML in, `(title, nested {text, children})` out.

    **A document type declaration is refused outright**, before the parser
    ever sees the string. `xml.etree` does not resolve *external* entities,
    but it does expand internal ones, which is the billion-laughs shape: a
    dozen nested entity definitions turn a 1KB file into gigabytes of memory
    inside the parse call, where no size cap on the way in can see it coming.
    Both guards live in `_parse_xml_document`, which is the one XML door in
    this app: see it for the billion-laughs reasoning and for why the parser
    is defusedxml rather than the stdlib.
    """
    root = _parse_xml_document(content, "OPML")

    title = ""
    head_title = root.find("./head/title")
    if head_title is not None and head_title.text:
        title = head_title.text.strip()

    body = root.find("./body")
    if body is None:
        # Some exporters leave out <body> and hang the outlines off the root.
        body = root

    counted = [0]

    def walk(element, depth: int) -> list[dict]:
        out: list[dict] = []
        if depth >= MAX_IMPORT_DEPTH:
            return out
        for child in element.findall("outline"):
            counted[0] += 1
            if counted[0] > MAX_IMPORT_NODES:
                raise HTTPException(
                    status_code=422,
                    detail=f"That outline has more than {MAX_IMPORT_NODES} nodes: split it up first.",
                )
            text = (child.get("text") or child.get("title") or "").strip()
            out.append(
                {
                    "text": text[:MAX_OBJECT_TEXT_CHARS],
                    "style": _opml_style(child),
                    "children": walk(child, depth + 1),
                }
            )
        return out

    return title, walk(body, 0)


def _parse_markdown_outline(content: str) -> tuple[str, list[dict]]:
    """An indented `- bullet` outline in, `(title, nested nodes)` out.

    Indentation decides depth, and a jump of more than one level is treated
    as one level: a hand-written outline that indents four spaces in one
    place and two in another is a normal thing to be handed, and refusing it
    would make the import useless for exactly the files people have.
    """
    title = ""
    roots: list[dict] = []
    #: (indent, node) down the path from the current root to the last node
    #: seen: the standard outline-parsing stack.
    stack: list[tuple[int, dict]] = []
    counted = 0
    for raw in content.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if not title:
                title = stripped.lstrip("#").strip()
            continue
        if stripped[0] not in "-*+":
            continue
        text = stripped[1:].strip()
        if not text:
            continue
        counted += 1
        if counted > MAX_IMPORT_NODES:
            raise HTTPException(
                status_code=422,
                detail=f"That outline has more than {MAX_IMPORT_NODES} nodes: split it up first.",
            )
        # A tab counts as one level however wide it is drawn, so a file
        # indented with tabs nests the same way one indented with spaces does.
        prefix = line[: len(line) - len(stripped)]
        indent = len(prefix) + prefix.count("\t")
        node: dict = {"text": text[:MAX_OBJECT_TEXT_CHARS], "children": []}
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack and len(stack) < MAX_IMPORT_DEPTH:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
            stack = []
        stack.append((indent, node))
    return title, roots


def _place_map_nodes(
    db: Session,
    board_id: int,
    parsed: list[dict],
    reference_for=None,
) -> list[WhiteboardObject]:
    """Write a parsed outline onto a board as map nodes, returning them.

    Returns the objects rather than a count because both callers have to
    record one `whiteboard_object`/`created` event each: a map whose nodes
    have no events of their own replays to an empty board (Brief 7, open
    item 4, `agent-remaining/brief7-event-log.md`).

    One walk for both doors onto a map made from text: an import, and the
    AI proposal the user accepted. They differ in exactly one thing, whether
    a line stands for a note the user already has, and that is what
    `reference_for` answers: given a node's text it returns `(kind, ref_id)`
    or None. An import passes nothing, because guessing that a line reading
    "Chapter three" means a particular note in *this* notebook is the kind of
    helpfulness whose mistakes are invisible until much later; the proposal
    passes a lookup over the notes the user themselves chose, which is not a
    guess.

    A single running row counter is shared by the whole walk, so the map lands
    as a readable ladder rather than with every branch stacked on top of the
    last one at y=0.
    """
    created: list[WhiteboardObject] = []
    row = [0]

    def place(nodes: list[dict], parent: WhiteboardObject | None, depth: int) -> None:
        for node in nodes:
            reference = reference_for(node["text"]) if reference_for else None
            kind, ref_id = reference if reference else (MAP_TOPIC_KIND, None)
            data: dict = {"content": node["text"]}
            if ref_id is not None:
                data["ref_id"] = ref_id
            # Whatever the file said the node looks like, already validated
            # by `_clean_import_style`. A Markdown outline and an AI proposal
            # carry no style at all, which is why this is a `get`.
            data.update(node.get("style") or {})
            obj = WhiteboardObject(
                board_id=board_id,
                kind=kind,
                data=json.dumps(data),
                x=float(depth) * MAP_COL,
                y=float(row[0]) * MAP_ROW,
                z=1,
                parent_id=parent.id if parent is not None else None,
            )
            row[0] += 1
            db.add(obj)
            db.flush()  # its children need its id
            created.append(obj)
            place(node["children"], obj, depth + 1)

    place(parsed, None, 0)
    return created


#: The most notes one proposal is built from. Matches
#: `librarian.MAP_PROPOSAL_NOTES`, and is repeated here rather than imported
#: because a Pydantic field's bound is read at import time and this module is
#: imported by things that have no business pulling in the AI package.
MAP_PROPOSAL_MAX_NOTES = 40


class MapProposal(BaseModel):
    """"Make a map of these notes" (MINDMAP_PLAN.md section 5 item 15): which
    notes, and what to call the result."""

    note_ids: list[int] = Field(min_length=1, max_length=MAP_PROPOSAL_MAX_NOTES)
    name: str | None = Field(default=None, min_length=1, max_length=100)


def _proposal_notes(db: Session, note_ids: list[int]) -> list[Entry]:
    """The chosen notes, in the order they were chosen, minus anything that is
    not a readable note.

    A private note is dropped rather than refused: this is a bulk action over
    a list someone assembled by ticking boxes, and failing the whole thing
    because one of thirty is private would be a dead end with no obvious way
    out. The same boundary every AI-facing read path in this codebase holds
    (search, embeddings, the janitor, chat linking) still holds: its text
    never reaches the model.
    """
    found = {
        entry.id: entry
        for entry in db.scalars(select(Entry).where(Entry.id.in_(note_ids))).all()
        if not entry.is_deleted and not entry.is_private and not entry.is_board
    }
    return [found[note_id] for note_id in note_ids if note_id in found]


def _note_titles(db: Session, notes: list[Entry]) -> list[tuple[Entry, str, str]]:
    """`(entry, title, first line)` for each note, which is everything both
    the prompt and the fallback need and all either of them gets."""
    from memorymap.ai import librarian
    from memorymap.entry import manager

    out = []
    for entry in notes:
        text = manager.readable_content(entry)
        title = (manager.extract_title(text) or text.strip().split("\n")[0] or "Untitled")[:100]
        body = " ".join(text.replace(title, "", 1).split())[: librarian.MAP_PROPOSAL_CHARS]
        out.append((entry, title, body))
    return out


def _outline_from_filing(db: Session, rows: list[tuple[Entry, str, str]], name: str) -> str:
    """The proposal the notebook can make on its own: one branch per category,
    the notes filed under it.

    **Why this exists at all.** The plan asks the agent to propose the tree,
    and it does; but a 4B model asked for an outline answers with a paragraph
    often enough that a feature which only works when the model behaves is a
    feature most people meet broken. This is what the notebook already knows,
    it is never wrong (it is the user's own filing), and the proposal says
    which of the two produced it rather than passing this off as the model's
    work.
    """
    from memorymap.core.database import Category

    by_category: dict[str, list[str]] = {}
    for entry, title, _ in rows:
        label = "Unfiled"
        if entry.category_id is not None:
            category = db.get(Category, entry.category_id)
            if category is not None:
                label = category.name
        by_category.setdefault(label, []).append(title)
    lines = [f"- {name}"]
    for label, titles in by_category.items():
        lines.append(f"  - {label}")
        lines.extend(f"    - {title}" for title in titles)
    return "\n".join(lines) + "\n"


def _outline_covering(outline: str, rows: list[tuple[Entry, str, str]]) -> str:
    """The model's outline with every note it forgot added back.

    A proposal for "map these thirty notes" that quietly contains eleven of
    them is the failure mode worth guarding: it looks like a map, it reads
    like an answer, and the nineteen that are missing are invisible unless you
    count. The strays go under one heading at the end rather than being
    scattered, so what the model did and what this added stay legible.
    """
    seen = {line.strip().lstrip("-*+ ").strip().casefold() for line in outline.splitlines()}
    missing = [title for _, title, _ in rows if title.casefold() not in seen]
    if not missing:
        return outline
    lines = [outline.rstrip("\n"), "  - Other notes"]
    lines.extend(f"    - {title}" for title in missing)
    return "\n".join(lines) + "\n"


@router.post("/boards/propose")
def propose_map(body: MapProposal, db: Session = Depends(get_session)) -> dict:
    """Propose a map of these notes, and write nothing.

    Preview before commit, the convention `generate_diagram` and the note
    extractor already follow in this app: the answer comes back as the outline
    text the user then edits, and `POST /boards/generate` creates the map from
    what they actually saw. A generator that wrote straight to a new board
    would make "undo" mean "find and delete the board it just made".
    """
    from memorymap.ai import librarian

    notes = _proposal_notes(db, body.note_ids)
    if not notes:
        raise HTTPException(
            status_code=404,
            detail="None of those notes can be mapped (deleted, private, or already a board).",
        )
    rows = _note_titles(db, notes)
    name = (body.name or f"Map of {len(rows)} notes").strip()[:100]

    outline = ""
    source = "notebook"
    #: Why the notebook wrote it, when it did. The dialog says this out loud,
    #: and the three cases want three different sentences: "your model is not
    #: running" is a thing the reader can go and fix, "the model answered with
    #: a paragraph" is a thing about the model they chose, and neither should
    #: be reported as the other. `sources`/`reason` rather than one string
    #: because the client also styles on `source`.
    reason = "offline"
    ollama = deps.get_ollama()
    if ollama.is_running():
        try:
            outline = librarian.propose_map_outline(
                [(title, body_text) for _, title, body_text in rows],
                deps.get_model_manager(),
                ollama,
            )
            reason = "unusable"
        except Exception:
            # A model that is running and still fails (a pulled-out model, a
            # timeout) is a reason to fall back, not to lose the action: the
            # notebook's own filing is a proposal too.
            logging.getLogger("memorymap.whiteboard").warning(
                "Map proposal failed, falling back to the notebook's own filing",
                exc_info=True,
            )
            outline = ""
            reason = "failed"
        # A reply with no bullets in it is prose, which is what a small model
        # answers with often enough to plan for; and one bullet is not a map.
        if len([line for line in outline.splitlines() if line.strip()[:1] in "-*+"]) >= 2:
            source = "model"
            reason = "model"
        else:
            outline = ""
    if not outline:
        outline = _outline_from_filing(db, rows, name)
    outline = _outline_covering(outline, rows)
    return {
        "name": name,
        "outline": outline,
        "source": source,
        "reason": reason,
        "note_ids": [entry.id for entry, _, _ in rows],
        "notes": len(rows),
    }


class MapGenerate(BaseModel):
    """The proposal as the user accepted it, possibly edited."""

    name: str = Field(min_length=1, max_length=100)
    outline: str = Field(min_length=1, max_length=MAX_IMPORT_CHARS)
    #: The notes the proposal was built from. A line whose text is one of
    #: their titles becomes a node that *is* that note; everything else is a
    #: topic. Sent back by the client rather than remembered server-side
    #: because nothing was written by the proposal, so there is no proposal to
    #: remember, which is the point of preview-before-commit.
    note_ids: list[int] = Field(default_factory=list, max_length=MAP_PROPOSAL_MAX_NOTES)


def _record_map_creation(
    db: Session,
    board_id: int,
    name: str,
    detail: str,
    extra: dict,
    created: list[WhiteboardObject],
) -> None:
    """The board event, then one event per node it was built with.

    Both map doors used to record a single `board`/`created` event whose
    payload held the outline and a node *count*, so `events.replay` rebuilt
    the board and nothing on it: a generated or imported map replayed empty
    (Brief 7, open item 4). The AI's own `generate_diagram` already records
    one event per item, which is the shape decision 4 asks for; these two
    predate it and now match.

    Written here rather than inside `_place_map_nodes` because of how
    `events.writes` nests: "the outermost write wins", so a decorated helper
    called from inside a decorated route opens no scope of its own and its
    event would be folded into the board's. Both routes therefore drop the
    decorator and record explicitly, in the order replay needs, the board
    first and its objects after.
    """
    events.record(
        db,
        "created",
        "board",
        board_id,
        detail,
        payload={
            "after": events.board_state(name, "map", DEFAULT_BOARD_LAYOUT),
            "nodes": len(created),
            **extra,
        },
    )
    for obj in created:
        events.record(
            db,
            "created",
            "whiteboard_object",
            obj.id,
            f"{obj.kind} on board {board_id}",
            payload={"after": _object_state(obj)},
        )


@router.post("/boards/generate", response_model=BoardOut, status_code=201)
def generate_map(body: MapGenerate, db: Session = Depends(get_session)) -> BoardOut:
    """Create the map the user accepted.

    The nodes that match one of their notes are `note` nodes carrying that
    note's id, which is the whole difference the plan names between this and
    a mindmapper's "AI generation": the map is made of the user's real notes,
    not of invented text that happens to look like them. Editing such a node
    edits the note, and deleting the map leaves the notes alone (section 5
    item 4).
    """
    _, parsed = _parse_markdown_outline(body.outline)
    if not parsed:
        raise HTTPException(
            status_code=422,
            detail="That outline has no nodes in it: each line starts with '- '.",
        )
    rows = _note_titles(db, _proposal_notes(db, body.note_ids))
    #: Matched on the casefolded title, because the one thing the user is most
    #: likely to change in the outline is capitalisation, and because a model
    #: told to copy a title exactly will still sometimes retitle its case.
    by_title = {title.casefold(): entry.id for entry, title, _ in rows}
    used: set[int] = set()

    def reference_for(text: str):
        note_id = by_title.get(text.strip().casefold())
        # Once each: an outline that repeats a title (a model's habit when it
        # cannot decide where a note belongs) would otherwise put the same
        # note on the board twice, and two nodes editing one note is a
        # confusion that only shows up later.
        if note_id is None or note_id in used:
            return None
        used.add(note_id)
        return ("note", note_id)

    name = body.name.strip()[:100] or "Generated map"
    entry = Entry(content=f"# {name}", is_board=True)
    _store_board_settings(entry, "map", DEFAULT_BOARD_LAYOUT)
    db.add(entry)
    db.flush()
    created = _place_map_nodes(db, entry.id, parsed, reference_for)
    _record_map_creation(
        db,
        entry.id,
        name,
        f"generated map, {len(created)} nodes",
        {"outline": body.outline},
        created,
    )
    db.commit()
    db.refresh(entry)
    return BoardOut(
        id=entry.id,
        title=name,
        node_count=0,
        sketch_count=0,
        object_count=len(created),
        type="map",
        layout=DEFAULT_BOARD_LAYOUT,
        **_preview_fields(db, entry.id),
    )


@router.post("/boards/import", response_model=BoardOut, status_code=201)
def import_board(body: MapImport, db: Session = Depends(get_session)) -> BoardOut:
    """Create a map from an OPML file or an indented Markdown outline.

    Every node comes in as a `topic`: an imported outline is text written
    somewhere else, and guessing that a line reading "Chapter three" means a
    particular note in *this* notebook is the kind of helpfulness that
    silently attaches the wrong thing. Linking a topic to a note afterwards
    is one action; finding out which of two hundred nodes was mis-linked is
    not.
    """
    parsers = {
        "opml": _parse_opml,
        "freemind": _parse_freemind,
        "markdown": _parse_markdown_outline,
    }
    title, parsed = parsers[body.format](body.content)
    name = (body.name or title or "Imported map").strip()[:100] or "Imported map"
    entry = Entry(content=f"# {name}", is_board=True)
    _store_board_settings(entry, "map", DEFAULT_BOARD_LAYOUT)
    db.add(entry)
    db.flush()  # the nodes need the board's id before they can point at it

    created = _place_map_nodes(db, entry.id, parsed)
    _record_map_creation(
        db,
        entry.id,
        name,
        f"imported {body.format} map, {len(created)} nodes",
        {"format": body.format},
        created,
    )
    db.commit()
    db.refresh(entry)
    return BoardOut(
        id=entry.id,
        title=name,
        node_count=0,
        sketch_count=0,
        object_count=len(created),
        type="map",
        layout=DEFAULT_BOARD_LAYOUT,
        **_preview_fields(db, entry.id),
    )
