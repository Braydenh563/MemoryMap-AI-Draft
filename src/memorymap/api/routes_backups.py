"""Storage location and backup CRUD (backup/restore/delete).

Split out of `routes_settings.py`'s "backups" section
(ROADMAP.md §0/§4).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from memorymap.core import backup, deps
from memorymap.core.deps import get_session
from memorymap.entry import manager

router = APIRouter(tags=["settings"])

#: Bounds on the retention setting itself, 1 (barely a safety net) to 100
#: (a number chosen to still mean something rather than "unlimited" wearing
#: a costume, on a machine writing a database backup that could itself be
#: sizeable).
MIN_RETENTION = 1
MAX_RETENTION = 100


def _retention(config) -> int:
    return int(config.get_preference("backup_retention_count", backup.KEEP_BACKUPS))


class RetentionBody(BaseModel):
    keep: int = Field(ge=MIN_RETENTION, le=MAX_RETENTION)


@router.get("/storage")
def storage_location() -> dict:
    """Where everything actually lives on disk.

    "Where are my documents stored?" was asked outright, and the app had no
    answer anywhere in its interface. For a local-first app that is close to
    the whole promise: a notebook you can't locate is not obviously yours,
    and someone who can't see the file has no reason to believe a document
    they wrote is still there.
    """
    config = deps.get_config()
    db_path = Path(config.db_path)
    return {
        "data_dir": str(Path(config.data_dir).resolve()),
        "database": str(db_path.resolve()),
        "database_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "backups_dir": str(backup.backups_dir(config.data_dir).resolve()),
        "backup_retention_count": _retention(config),
        "backup_retention_min": MIN_RETENTION,
        "backup_retention_max": MAX_RETENTION,
        # ROADMAP.md's onboarding item named this a still-open gap: a
        # data-dir writability check. The database already opening here
        # implies the directory is writable *now*, but a machine can go
        # read-only under it later (a synced folder, a permissions change, a
        # full disk remounted read-only) with nothing in the interface ever
        # saying so until a save silently fails. `os.access` is the same
        # check `_validated_export_dir` below already trusts for the export
        # folder; this is the same question asked of the notebook's own
        # folder instead.
        "data_dir_writable": os.access(config.data_dir, os.W_OK),
    }


@router.get("/backups")
def list_backups() -> list[dict]:
    # Unchanged shape (a plain list): `keep`/the retention bounds live on
    # GET /storage instead, which already answers "what does this app keep
    # on disk and where," rather than reshaping an endpoint existing callers
    # (including this app's own tests) already treat as one.
    return backup.list_backups(deps.get_config().data_dir)


@router.post("/backups", status_code=201)
def backup_now(session: Session = Depends(get_session)) -> dict:
    config = deps.get_config()
    path = backup.backup_now(config.db_path, config.data_dir, _retention(config))
    manager.log_action(session, "backed_up", "data", detail=path.name)
    session.commit()
    return {"name": path.name}


@router.put("/backups/retention")
def set_retention(body: RetentionBody) -> dict:
    """How many backups to keep, and prune immediately to match, asked
    about directly ("backup retention should be a setting"). Immediate,
    not just for the next scheduled backup: lowering the number and still
    seeing the old count is the "did that even save" moment every other
    preference in this app avoids by writing straight through.
    """
    config = deps.get_config()
    config.set_preference("backup_retention_count", body.keep)
    removed = backup.prune(config.data_dir, body.keep)
    return {"keep": body.keep, "removed": removed}


class RestoreBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.post("/backups/restore")
def restore_backup(body: RestoreBody) -> dict:
    """Swap the live database for a backup. A safety snapshot of the
    current state is taken first, so a restore is itself undoable."""
    config = deps.get_config()
    # Every connection must be closed while the file is replaced.
    deps.get_db().engine.dispose()
    try:
        backup.restore_backup(body.name, config.db_path, config.data_dir, _retention(config))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        deps.reload_db()
    session = deps.get_db().session()
    try:
        manager.log_action(session, "restored", "data", detail=body.name)
        session.commit()
    finally:
        session.close()
    return {"restored": body.name}


@router.delete("/backups/{name}")
def delete_backup(name: str) -> dict:
    folder = backup.backups_dir(deps.get_config().data_dir)
    path = folder / name
    # Path(name).name guards traversal; only files inside backups/ die.
    if path.name != name or not path.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")
    path.unlink()
    return {"deleted": name}
