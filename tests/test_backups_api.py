"""Local backups: create, list, delete, and restore."""

from __future__ import annotations

from memorymap.core import backup, deps


def _save(client, content, **extra):
    response = client.post("/entries", json={"content": content, **extra})
    assert response.status_code == 201
    return response.json()


def test_backup_create_list_delete(client):
    # create_app() already took a startup backup, work relative to it.
    baseline = {b["name"] for b in client.get("/backups").json()}
    _save(client, "worth keeping")
    created = client.post("/backups")
    assert created.status_code == 201
    name = created.json()["name"]

    listed = client.get("/backups").json()
    assert {b["name"] for b in listed} == baseline | {name}
    assert all(b["size"] > 0 for b in listed)

    # The request goes on its own line, not inside the assert: `python -O`
    # strips assert statements wholesale, which would delete the deletion and
    # leave the test passing while exercising nothing.
    deleted = client.delete(f"/backups/{name}")
    assert deleted.json() == {"deleted": name}
    assert {b["name"] for b in client.get("/backups").json()} == baseline
    missing = client.delete("/backups/nope.db")
    assert missing.status_code == 404


def test_storage_reports_whether_the_data_dir_is_writable(client, tmp_path):
    """ROADMAP.md's onboarding item named this the one still-open gap: a
    data-dir writability check. The database opening at all already implies
    the directory was writable at boot, but nothing before this told anyone
    whether it *still* is, a synced folder, a permissions change, or a disk
    remounted read-only can flip that later with no visible symptom until a
    save silently fails. This is the same `os.access` check
    `_validated_export_dir` already trusts for the export folder, asked of
    the notebook's own folder instead."""
    storage = client.get("/storage").json()
    # The sandbox's own data dir is writable, the client fixture would not
    # have been able to create the database otherwise.
    assert storage["data_dir_writable"] is True


def test_retention_is_a_setting_and_prunes_immediately(client):
    """Asked about directly: "backup retention should be a setting, 
    backups accumulate with no cap the user can see or change." The prune
    itself already existed; this is the missing control, and lowering it
    has to take effect now, not just on the next scheduled backup."""
    storage = client.get("/storage").json()
    assert storage["backup_retention_count"] == backup.KEEP_BACKUPS

    for _ in range(4):
        client.post("/backups")
    assert len(client.get("/backups").json()) >= 4

    trimmed = client.put("/backups/retention", json={"keep": 2})
    assert trimmed.status_code == 200
    assert trimmed.json()["keep"] == 2
    assert trimmed.json()["removed"] >= 2
    assert len(client.get("/backups").json()) == 2
    assert client.get("/storage").json()["backup_retention_count"] == 2

    # A later backup respects the new, lower limit too, not just the prune
    # that ran at the moment it was set.
    client.post("/backups")
    assert len(client.get("/backups").json()) == 2

    out_of_range = client.put("/backups/retention", json={"keep": 0})
    assert out_of_range.status_code == 422


def test_backup_restore_rolls_the_database_back(client):
    keep = _save(client, "note before the backup")
    before_count = len(client.get("/backups").json())
    name = client.post("/backups").json()["name"]
    _save(client, "note after the backup")

    response = client.post("/backups/restore", json={"name": name})
    assert response.status_code == 200

    entries = client.get("/entries").json()
    assert [e["content"] for e in entries] == ["note before the backup"]
    assert keep["id"] in [e["id"] for e in entries]
    # The named backup + a pre-restore safety snapshot both exist.
    assert len(client.get("/backups").json()) == before_count + 2


def test_backup_if_due_skips_recent(app_state):
    config = deps.get_config()
    config.db_path.touch()
    first = backup.backup_if_due(config.db_path, config.data_dir)
    assert first is not None
    assert backup.backup_if_due(config.db_path, config.data_dir) is None  # too soon
