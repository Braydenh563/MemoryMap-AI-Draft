"""A sketch is a picture like any other (§ sketches).

Two halves of one report:

    "also add captioning and vision and ocr for sketches the user draws and
     saves as well."
    "and allow captions if they accompany images of sketches to be read by the
     ai if they appear in semantic searches."

A saved sketch used to go to `POST /entries/{id}/files`, the *attachment*
table, which is a different pipeline from `MediaUpload`. Only MediaUpload rows
are captioned, OCR'd, read by a vision model or listed in the Library gallery,
so a drawing was the one image in this app none of that ever touched. And even
once it is captioned, a caption on a MediaUpload row is invisible to search:
the note's vector is built from the note's own words.
"""

from __future__ import annotations

from pathlib import Path

from memorymap.core import media_process
from memorymap.core.database import Entry, MediaUpload


def _upload(session, filename="sketch-2026-01-01.png", **fields):
    upload = MediaUpload(
        filename=filename, original_name="sketch.png", **fields
    )
    session.add(upload)
    session.commit()
    return upload


# --- what a picture says, as text -----------------------------------------------


def test_a_notes_pictures_contribute_their_readings(client):
    from memorymap.core import deps

    with deps.get_db().session() as session:
        _upload(
            session,
            caption="A pond with a leafy creature beside it",
            vision_ocr_text="24-12-2018",
        )
        text = media_process.media_text_for(
            session, "my drawing\n\n![](/media/sketch-2026-01-01.png)"
        )
    assert "A pond with a leafy creature" in text
    assert "24-12-2018" in text
    # Named, so a model can tell the app's reading of a picture from the
    # note's own sentences.
    assert text.startswith("[image: sketch.png]")


def test_a_note_with_no_pictures_adds_nothing(client):
    from memorymap.core import deps

    with deps.get_db().session() as session:
        assert media_process.media_text_for(session, "just words") == ""


def test_a_picture_nothing_has_read_yet_adds_nothing(client):
    """Captioning runs in the background. A note saved a second before its
    picture was described must embed as itself, not as an empty label."""
    from memorymap.core import deps

    with deps.get_db().session() as session:
        _upload(session, filename="plain.png")
        assert media_process.media_text_for(session, "![](/media/plain.png)") == ""


def test_one_picture_cannot_swamp_the_note(client):
    """A transcribed page is thousands of characters; a note whose embedding is
    nine-tenths OCR is no longer a vector for the note."""
    from memorymap.core import deps

    with deps.get_db().session() as session:
        _upload(session, filename="long.png", vision_ocr_text="x" * 5000)
        text = media_process.media_text_for(session, "![](/media/long.png)")
    assert len(text) < media_process.MAX_MEDIA_TEXT_CHARS + 100


# --- and it reaches the vector ---------------------------------------------------


def test_the_embedded_text_carries_the_caption(client):
    """The half that makes it searchable. "the diagram of the pond" matched
    nothing at all before this, however good the caption was."""
    from memorymap.ai.embeddings import embedding_text
    from memorymap.core import deps

    with deps.get_db().session() as session:
        _upload(session, caption="A pond with a leafy creature beside it")
        entry = Entry(content="my drawing\n\n![](/media/sketch-2026-01-01.png)")
        session.add(entry)
        session.commit()
        text = embedding_text(session, entry)
    assert "my drawing" in text
    assert "A pond with a leafy creature" in text


def test_the_note_itself_is_never_rewritten(client):
    """The caption is the app's reading of a picture, not something the user
    typed. Derived on the way past, so a picture captioned later improves
    search without the note being edited."""
    from memorymap.ai.embeddings import embedding_text
    from memorymap.core import deps

    with deps.get_db().session() as session:
        _upload(session, caption="described later")
        entry = Entry(content="![](/media/sketch-2026-01-01.png)")
        session.add(entry)
        session.commit()
        before = entry.content
        embedding_text(session, entry)
        session.refresh(entry)
        assert entry.content == before


def test_a_plain_note_embeds_exactly_what_it_did_before(client):
    from memorymap.ai.embeddings import embedding_text
    from memorymap.core import deps

    with deps.get_db().session() as session:
        entry = Entry(content="beans need netting")
        session.add(entry)
        session.commit()
        assert embedding_text(session, entry) == "beans need netting"


def test_enrichment_never_blocks_an_embedding(client, monkeypatch):
    """It runs inside the save path for every note. A failure here must cost
    the caption, not the vector."""
    from memorymap.ai.embeddings import embedding_text
    from memorymap.core import deps

    def boom(*_args, **_kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(media_process, "media_text_for", boom)
    with deps.get_db().session() as session:
        entry = Entry(content="still fine")
        session.add(entry)
        session.commit()
        assert embedding_text(session, entry) == "still fine"


# --- the frontend half: a sketch goes through the media pipeline -----------------


def test_saving_a_sketch_uploads_it_as_media():
    """`/entries/{id}/files` is the attachment table and a different pipeline.
    Only a MediaUpload is captioned, OCR'd, read by a vision model, or listed
    in the gallery."""
    source = Path("frontend/app.js").read_text(encoding="utf-8")
    block = source.split("async function saveSketch()")[1].split("\n}")[0]
    assert '"/media/upload"' in block
    # The old path, in code rather than in the comment explaining why it went.
    code = "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("//")
    )
    assert "/files`" not in code, "the old attachment path is gone"
    # Referenced from the note's markdown, which is what triggers
    # `_process_committed_media` on the way in, and what puts the drawing in
    # the note where you can see it.
    assert "![" in block and "uploaded.url" in block


# --- the AI Skills log panel, which read rows nobody wrote -----------------------


def test_a_skill_run_is_recorded(client):
    """Reported: "I dont think the skill logs work in the ai skills section in
    the library??" Correct, and the panel was not the broken half, a grep for
    a `log_action` call with entity_type "skill" returned nothing at all, so
    the reader was reading rows no writer produced."""
    from memorymap.ai import skill_runner
    from memorymap.core import deps

    with deps.get_db().session() as session:
        skill_runner._record_run(
            session, {"name": "Tidy my tags"}, [{"x": 1}], None, 3, False
        )

    rows = client.get("/audit?entity_type=skill").json()
    assert rows, "the run wrote nothing"
    assert rows[0]["action"] == "ran"
    assert "Tidy my tags" in rows[0]["detail"]
    assert "completed" in rows[0]["detail"]
    assert "3 step(s)" in rows[0]["detail"]


def test_a_stopped_run_says_where_it_stopped(client):
    from memorymap.ai import skill_runner
    from memorymap.core import deps

    with deps.get_db().session() as session:
        skill_runner._record_run(session, {"name": "Half a job"}, [], 2, 5, False)
    detail = client.get("/audit?entity_type=skill").json()[0]["detail"]
    assert "stopped at step 3" in detail  # 0-based index, 1-based for a reader


def test_a_paused_run_is_not_reported_as_a_failure(client):
    """Manual mode stops after every step on purpose."""
    from memorymap.ai import skill_runner
    from memorymap.core import deps

    with deps.get_db().session() as session:
        skill_runner._record_run(session, {"name": "Careful"}, [], 1, 4, True)
    assert "paused" in client.get("/audit?entity_type=skill").json()[0]["detail"]


def test_recording_never_fails_a_finished_run(client, monkeypatch):
    """A run that did real work must not raise at its last line over its own
    bookkeeping."""
    from memorymap.ai import skill_runner
    from memorymap.core import deps

    with deps.get_db().session() as session:
        monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError))
        skill_runner._record_run(session, {"name": "x"}, [], None, 1, False)


def test_the_filter_happens_before_the_limit(client):
    """The other half of the same report. `/audit?limit=20` returns the last
    twenty events *of any kind*; filtering those in the browser meant a real
    history of skill runs showed as "none found" on any notebook where the
    last twenty things were note edits."""
    from memorymap.ai import skill_runner
    from memorymap.core import deps

    with deps.get_db().session() as session:
        skill_runner._record_run(session, {"name": "Early run"}, [], None, 1, False)
    # Bury it under plenty of unrelated activity.
    for i in range(30):
        client.post("/entries", json={"content": f"note {i}"})

    assert client.get("/audit?limit=20&entity_type=skill").json(), (
        "the skill run is invisible under a browser-side filter"
    )


def test_the_panel_asks_the_server_to_filter():
    from pathlib import Path as _Path

    source = _Path("frontend/library.js").read_text(encoding="utf-8")
    block = source.split("async function renderSkillLogs()")[1].split("\n}")[0]
    assert "entity_type=skill" in block
    assert "logs.filter(" not in block, "the browser-side filter is what hid them"
