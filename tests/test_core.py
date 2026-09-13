"""Config and database core behavior: preferences persistence, entry
creation, title extraction, audit logging, soft delete, and migrations."""

from __future__ import annotations

import json

from sqlalchemy import select

from memorymap.core.config import ConfigManager
from memorymap.core.database import AuditLog, Category
from memorymap.entry import manager


def test_config_creates_data_dir_and_defaults(tmp_path):
    config = ConfigManager(data_dir=tmp_path / "data")
    assert config.data_dir.is_dir()
    assert config.get_preference("chat_model") == "llama3.2"
    assert config.get_preference("embedding_backend") == "sentence-transformers"
    assert config.get_preference("recycle_bin_days") == 30


def test_set_preference_persists_to_disk(tmp_path):
    config = ConfigManager(data_dir=tmp_path / "data")
    config.set_preference("chat_model", "qwen2.5:3b")

    # A brand-new instance (like an app restart) must see the change.
    reloaded = ConfigManager(data_dir=tmp_path / "data")
    assert reloaded.get_preference("chat_model") == "qwen2.5:3b"


def test_corrupt_preferences_file_falls_back_to_defaults(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "preferences.json").write_text("{not valid json")
    config = ConfigManager(data_dir=data_dir)
    assert config.get_preference("chat_model") == "llama3.2"


def test_set_preference_leaves_no_stray_temp_file(tmp_path):
    config = ConfigManager(data_dir=tmp_path / "data")
    config.set_preference("chat_model", "qwen2.5:3b")

    leftovers = list(config.data_dir.glob(".preferences.json.*.tmp"))
    assert leftovers == []


def test_set_preference_survives_a_write_failure_without_corrupting_the_file(
    tmp_path, monkeypatch
):
    """A crash mid-write must leave the old file intact, not a truncated one.

    Simulates the failure by making the fsync step raise partway through an
    atomic write, the shape a real crash/power-loss would hit, and asserts
    the previously-saved preferences are still readable afterwards.
    """
    config = ConfigManager(data_dir=tmp_path / "data")
    config.set_preference("chat_model", "first-good-value")
    before = config.preferences_path.read_text()

    import os as os_module

    def failing_fsync(fd):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(os_module, "fsync", failing_fsync)
    try:
        config.set_preference("chat_model", "never-should-land")
    except OSError as exc:
        # Expected in this test: simulated fsync failure during atomic write.
        _ = exc

    # The on-disk file must be exactly what it was before the failed write, 
    # never truncated, never half-written.
    assert config.preferences_path.read_text() == before
    assert json.loads(before)["chat_model"] == "first-good-value"
    # And no temp file left behind by the aborted write.
    assert list(config.data_dir.glob(".preferences.json.*.tmp")) == []


def test_create_and_list_entries(session):
    manager.create_entry(session, "remember the milk", tags=["shopping"])
    manager.create_entry(session, "a dad joke about cheese")

    entries = manager.list_entries(session)
    assert len(entries) == 2
    # Newest first.
    assert entries[0].content == "a dad joke about cheese"
    assert manager.entry_tags(entries[1]) == ["shopping"]
    assert manager.category_name_for(session, entries[0]) == "Uncategorised"


def test_a_leading_heading_becomes_the_title():
    assert manager.extract_title("# Trip to the coast\nPacked the tent.") == "Trip to the coast"


def test_a_note_with_no_heading_has_no_title():
    assert manager.extract_title("just a plain thought") is None


def test_blank_lines_before_the_heading_are_skipped():
    assert manager.extract_title("\n\n## Recipe idea\nmore flour next time") == "Recipe idea"


def test_a_heading_partway_through_the_note_is_not_the_title():
    """A `#` three paragraphs in is a section break, not what the note is
    called: only the first non-blank line counts."""
    assert manager.extract_title("some thoughts first\n# a heading later") is None


def test_a_hashtag_with_no_space_is_not_mistaken_for_a_heading():
    """"#recipe" typed as a tag-like opener must not read as an empty title."""
    assert manager.extract_title("#recipe good one this week") is None


def test_apply_title_prepends_a_heading_to_an_untitled_note():
    result = manager.apply_title("just a plain thought", "A plain thought")
    assert result == "# A plain thought\njust a plain thought"
    assert manager.extract_title(result) == "A plain thought"


def test_apply_title_replaces_an_existing_one():
    result = manager.apply_title("# Old title\nsome body text", "New title")
    assert result == "# New title\nsome body text"


def test_apply_title_on_empty_content_is_just_the_heading():
    assert manager.apply_title("", "A title") == "# A title"


def test_remove_title_takes_the_heading_line_back_out():
    assert manager.remove_title("# A trip\nPacked the tent.") == "Packed the tent."


def test_remove_title_also_drops_one_blank_line_after_it():
    assert manager.remove_title("# A trip\n\nPacked the tent.") == "Packed the tent."


def test_remove_title_on_an_untitled_note_is_a_no_op():
    assert manager.remove_title("just a plain thought") == "just a plain thought"


def test_the_api_reports_the_extracted_title(client):
    body = client.post(
        "/entries", json={"content": "# Trip to the coast\nPacked the tent."}
    ).json()
    assert body["title"] == "Trip to the coast"

    untitled = client.post("/entries", json={"content": "just a plain thought"}).json()
    assert untitled["title"] is None


def test_uncategorised_category_created_once(session):
    manager.create_entry(session, "first")
    manager.create_entry(session, "second")
    names = session.scalars(select(Category.name)).all()
    assert names.count("Uncategorised") == 1


def test_entry_creation_is_audit_logged(session):
    entry = manager.create_entry(session, "log me")
    actions = session.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == "entry", AuditLog.entity_id == entry.id
        )
    ).all()
    assert [a.action for a in actions] == ["created"]


def test_soft_deleted_entries_hidden_from_list(session):
    entry = manager.create_entry(session, "to be binned")
    entry.is_deleted = True
    session.commit()
    assert manager.list_entries(session) == []
    assert len(manager.list_entries(session, include_deleted=True)) == 1


def test_old_database_gains_new_columns_without_data_loss(tmp_path):
    """Reproduces the real-world bug: a database created by an older
    version lacks columns added since (e.g. entries.access_count), and
    every query used to 500. The auto-migration must add the column and
    keep the old rows."""
    import sqlite3

    from memorymap.core.database import DatabaseManager, Entry

    db_path = tmp_path / "old.db"
    connection = sqlite3.connect(db_path)
    # A pre-Phase-5 entries table: everything except access_count.
    connection.execute(
        """
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            category_id INTEGER,
            tags TEXT NOT NULL,
            ai_confidence INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            is_deleted BOOLEAN NOT NULL,
            deleted_at DATETIME
        )
        """
    )
    connection.execute(
        "INSERT INTO entries (content, tags, ai_confidence, created_at, "
        "updated_at, is_deleted) VALUES ('my movie note', '[]', 80, "
        "'2026-07-16 06:09:24', '2026-07-16 06:09:24', 0)"
    )
    connection.commit()
    connection.close()

    db = DatabaseManager(db_path)
    session = db.session()
    try:
        entry = session.get(Entry, 1)
        assert entry.content == "my movie note"  # old data intact
        assert entry.access_count == 0  # new column, backfilled default
        entry.access_count += 1  # and it's writable
        session.commit()
    finally:
        session.close()
        db.engine.dispose()


def test_bad_tags_json_returns_empty_list(session):
    entry = manager.create_entry(session, "tags test")
    entry.tags = "not json"
    assert manager.entry_tags(entry) == []
    assert json.loads('["ok"]') == ["ok"]  # sanity: helper mirrors json rules
