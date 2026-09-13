"""The unlocked data key, for as long as the app is unlocked.

The DEK lives here in memory and nowhere else. Locking, restarting, or simply
never unlocking all leave private notes unreadable, which is the intended
behaviour rather than a limitation.

Kept apart from the auth routes so the read/write paths can ask "is the vault
open?" without importing the API layer.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core import crypto
from memorymap.core.database import Vault

# Set on unlock, cleared on lock. Deliberately module-level: this app is
# single-user, and one process holds one notebook.
_dek: bytes | None = None


def is_open() -> bool:
    return _dek is not None


def key() -> bytes | None:
    return _dek


def close() -> None:
    """Forget the key. Called on lock and by tests."""
    global _dek
    _dek = None


def _row(session: Session) -> Vault | None:
    return session.scalar(select(Vault))


def exists(session: Session) -> bool:
    return _row(session) is not None


def create(session: Session, password: str) -> None:
    """Set up the vault on first run, and open it.

    Called from setup, so a notebook always has somewhere to put a private
    note: asking the user to "enable encryption" later would mean a second
    password prompt and a second chance to lose access.
    """
    global _dek
    if _row(session) is not None:
        return
    salt = crypto.new_salt()
    dek = crypto.new_dek()
    session.add(Vault(kdf_salt=salt, wrapped_dek=crypto.wrap_dek(dek, password, salt)))
    session.flush()
    _dek = dek


def open_with(session: Session, password: str) -> bool:
    """Unwrap the DEK on unlock. False if there's no vault or it won't open.

    A notebook created before this feature existed has no vault row; one is
    created on the next unlock so private notes work from then on, without
    touching anything already written.
    """
    global _dek
    row = _row(session)
    if row is None:
        create(session, password)
        return True
    try:
        _dek = crypto.unwrap_dek(bytes(row.wrapped_dek), password, bytes(row.kdf_salt))
    except crypto.DecryptionError:
        _dek = None
        return False
    return True


def set_key(dek: bytes) -> None:
    """Replace the in-memory DEK after a key rotation.

    Only ever called AFTER the rotation's database commit has already
    succeeded. Swapping the key first, or on any path that might still
    fail: would leave memory holding a key that disagrees with what is
    actually on disk if the process died between the two.
    """
    global _dek
    _dek = dek


def rewrap(session: Session, new_password: str) -> bool:
    """Point the vault at a new password. Notes are never re-encrypted.

    Only possible while unlocked, because the DEK has to be in hand, which
    also means a password change can't be used to lock yourself out.
    """
    row = _row(session)
    if row is None or _dek is None:
        return False
    salt = crypto.new_salt()
    row.kdf_salt = salt
    row.wrapped_dek = crypto.wrap_dek(_dek, new_password, salt)
    return True
