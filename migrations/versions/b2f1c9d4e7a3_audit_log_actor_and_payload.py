"""audit_log: actor and payload (the event log, WORLD_CLASS_PLAN B1)

Additive only, and deliberately so: `AuditLog` gains the two columns the
event log needs (who did it, and the whole-field values it set) rather
than a second `events` table being added beside it.

Revision ID: b2f1c9d4e7a3
Revises: 8a8a14407cc0
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
#
# Read off this module by attribute name by Alembic's ScriptDirectory, never
# imported anywhere in this repo: the baseline migration's own comment
# explains why CodeQL calls these unused and why __all__ answers it without
# changing any behaviour.
__all__ = ["revision", "down_revision", "branch_labels", "depends_on"]
revision: str = "b2f1c9d4e7a3"
down_revision: Union[str, Sequence[str], None] = "8a8a14407cc0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set:
    """What `audit_log` already has.

    This app adds columns two ways and always has: `_add_missing_columns()`
    in `core/database.py` runs on every startup, before the Alembic step,
    and adds any column the models declare that the file lacks. So by the
    time this migration runs against a database that predates it, both
    columns are usually already there and a plain `add_column` would fail
    with "duplicate column name", leave `alembic_version` stuck at the
    baseline, and log a warning on every startup from then on. Checking
    first makes this migration agree with whichever mechanism got there
    first, which is the only way the two can coexist.
    """
    bind = op.get_bind()
    return {row[1] for row in bind.exec_driver_sql('PRAGMA table_info("audit_log")')}


def upgrade() -> None:
    """Upgrade schema."""
    existing = _existing_columns()
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        if "actor" not in existing:
            # `server_default` rather than a plain default: SQLite cannot add
            # a NOT NULL column without one, and the rows that predate this
            # are all user actions, so "user" is the honest backfill rather
            # than a placeholder.
            batch_op.add_column(
                sa.Column("actor", sa.String(length=60), nullable=False, server_default="user")
            )
        if "payload" not in existing:
            batch_op.add_column(sa.Column("payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    existing = _existing_columns()
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        if "payload" in existing:
            batch_op.drop_column("payload")
        if "actor" in existing:
            batch_op.drop_column("actor")
