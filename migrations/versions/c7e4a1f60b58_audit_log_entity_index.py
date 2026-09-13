"""audit_log: an index on (entity_type, entity_id, id) for a note's history

`events.events_for` filters both entity columns and pages newest-first by
id; neither column was indexed, so opening one note's History sheet read
the whole table, and `audit_log` is the table that only ever grows.

Revision ID: c7e4a1f60b58
Revises: b2f1c9d4e7a3
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
#
# Read off this module by attribute name by Alembic's ScriptDirectory, never
# imported anywhere in this repo: the baseline migration's own comment
# explains why CodeQL calls these unused and why __all__ answers it without
# changing any behaviour.
__all__ = ["revision", "down_revision", "branch_labels", "depends_on"]
revision: str = "c7e4a1f60b58"
down_revision: Union[str, Sequence[str], None] = "b2f1c9d4e7a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Spelled as raw DDL rather than `op.create_index` for one reason: the
#: trailing `id DESC`. SQLite will only skip the sort when the index's
#: trailing column matches the ORDER BY direction, and Alembic's
#: `create_index` has no portable way to say DESC on one column. The same
#: text is in `DatabaseManager._INDEXES`, which is what actually reaches an
#: existing notebook (it runs on every startup, before Alembic); this
#: migration exists so a database upgraded through Alembic alone is not left
#: without it, and so the two mechanisms cannot disagree about the shape.
_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_audit_log_entity "
    "ON audit_log (entity_type, entity_id, id DESC)"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.get_bind().exec_driver_sql(_INDEX)


def downgrade() -> None:
    """Downgrade schema."""
    op.get_bind().exec_driver_sql("DROP INDEX IF EXISTS ix_audit_log_entity")
