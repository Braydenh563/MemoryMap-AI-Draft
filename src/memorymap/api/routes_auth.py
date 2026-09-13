"""Single-user unlock.

One password (or PIN), bcrypt-hashed in the `users` table. Unlocking
issues a random token the frontend sends back as X-Auth-Token; tokens
live in memory only, so restarting the app locks it again, and they
expire on their own after a spell unused, see _SESSION_IDLE_TTL.

Before a password has been set there is nothing to protect (the app is
brand new and empty), so the API stays open and the frontend forces the
setup screen first.
"""

from __future__ import annotations

import secrets
import time

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from memorymap.core import crypto, vault
from memorymap.core.config import ConfigManager
from memorymap.core.deps import get_config, get_session, register_cache_reset
from memorymap.core.database import Entry, User, Vault
from memorymap.entry.manager import log_action

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory sessions: fine for a single-user local app.
#
# Each token remembers when it was issued and when it was last used, because a
# token that never expires is a second key to the notebook that nobody can take
# back. Restarting the app clears them, which sounds like it covers this, but
# the app this is built for is a desktop notebook that stays open for weeks, so
# "until the next restart" can be a very long time. Two clocks, doing different
# jobs:
#
#   idle: you walked away. The notebook locks itself like a phone does.
#   max age: you did not walk away, but a token issued a fortnight ago should
#             not still be valid; this is the ceiling that a token leaked from
#             a proxy log or a synced browser profile eventually hits.
#
# There is no cookie here to mark SameSite=Strict: the token travels as an
# X-Auth-Token header the frontend sets explicitly, so a browser never attaches
# it to a cross-site request on its own. That is a stronger position than a
# SameSite cookie rather than a gap in one, the risk a SameSite flag addresses
# is the browser sending credentials unprompted, and nothing here does.
_SESSION_IDLE_TTL = 12 * 60 * 60  # fallback default; overridden by the
# session_idle_ttl_minutes preference (Settings → Account) once one is set
_SESSION_MAX_AGE = 7 * 24 * 60 * 60  # this old → expired, however busy

# token -> [issued_at, last_used_at]
_active_tokens: dict[str, list[float]] = {}
# Module state, not app state, so `deps.reset_app_state()` (the thing every
# test's `app_state` fixture calls) threw the database away and kept the
# tokens. Any test that ran `/auth/setup` before `test_account.py` in the same
# process left it counting four active sessions instead of one; the suite only
# stayed green because of alphabetical order. Registered as a cache reset so
# the store is dropped with everything else.
register_cache_reset(_active_tokens.clear)


def _sweep_expired(idle_ttl: int) -> None:
    """Drop dead tokens, and forget the data key once none are left.

    Closing the vault matters as much as dropping the token: expiry that left
    private notes decrypted in memory would be a lock that only locks the door
    it is written on.
    """
    now = time.time()
    dead = [
        token
        for token, (issued, seen) in _active_tokens.items()
        if now - seen > idle_ttl or now - issued > _SESSION_MAX_AGE
    ]
    for token in dead:
        del _active_tokens[token]
    if dead and not _active_tokens:
        vault.close()


def _token_valid(token: str | None, idle_ttl: int) -> bool:
    """Is this token live? Using it also keeps it alive."""
    _sweep_expired(idle_ttl)
    if not token or token not in _active_tokens:
        return False
    _active_tokens[token][1] = time.time()
    return True

# Brute-force throttle for unlock attempts. The app binds 127.0.0.1, but a
# server log showed a public client address arriving through a proxy header, 
# people do put this behind tunnels to reach it from a phone. bcrypt makes
# each guess slow; nothing made *many* guesses slow, and the password floor
# is four characters, which is PIN territory. One global bucket, not per-IP:
# there is a single user to protect, and per-IP buckets are exactly what a
# botnet has plenty of. Wrong guesses beyond the free allowance earn an
# exponentially growing wait; a right password inside the wait still waits.
_FAILURE_ALLOWANCE = 5  # free tries before the waits start
_FAILURE_WINDOW = 15 * 60  # forgiven this long after the last failure
_WAIT_CEILING = 300  # the wait stops growing at five minutes
_failed_unlocks: list[float] = []


def _refuse_if_throttled() -> None:
    """429 while inside the wait a run of wrong passwords has earned."""
    now = time.time()
    if _failed_unlocks and now - _failed_unlocks[-1] > _FAILURE_WINDOW:
        _failed_unlocks.clear()  # long quiet: forgiven
    over = len(_failed_unlocks) - _FAILURE_ALLOWANCE
    if over < 0:
        return
    wait = min(2 ** over, _WAIT_CEILING)
    remaining = wait - (now - _failed_unlocks[-1])
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong passwords, try again in {int(remaining) + 1}s",
        )


def _unlock_failed() -> None:
    _failed_unlocks.append(time.time())


def _unlock_succeeded() -> None:
    _failed_unlocks.clear()


class PasswordBody(BaseModel):
    password: str = Field(min_length=4, description="Password or PIN, 4+ characters")


def _get_user(session: Session) -> User | None:
    return session.scalar(select(User))


def require_unlock(
    session: Session = Depends(get_session),
    config: ConfigManager = Depends(get_config),
    x_auth_token: str | None = Header(default=None),
) -> None:
    """Dependency that gates every data route once a password exists."""
    if _get_user(session) is None:
        return  # setup not done yet, nothing to protect
    idle_ttl = config.get_preference("session_idle_ttl_minutes", _SESSION_IDLE_TTL // 60) * 60
    if not _token_valid(x_auth_token, idle_ttl):
        raise HTTPException(status_code=401, detail="Locked: unlock first")


def require_unlock_media(
    session: Session = Depends(get_session),
    config: ConfigManager = Depends(get_config),
    x_auth_token: str | None = Header(default=None),
    token: str | None = None,
) -> None:
    """Same gate as `require_unlock`, plus a query-param fallback.

    For the handful of routes a plain `<img src>` points at directly
    (`/media/{filename}`, `/files/{attachment_id}`), a declarative resource
    load never attaches a custom header, only `fetch`/`XHR` can, so every
    such image was a silent 401 (an empty/broken `<img>`, nothing thrown,
    nothing logged) on any notebook with a password set, which is the normal
    case. Scoped to just these routes rather than widened onto
    `require_unlock` itself: that would put the token in every access-log
    line for every request, not only the two that actually need it in a URL.
    """
    if _get_user(session) is None:
        return
    idle_ttl = config.get_preference("session_idle_ttl_minutes", _SESSION_IDLE_TTL // 60) * 60
    if not _token_valid(x_auth_token or token, idle_ttl):
        raise HTTPException(status_code=401, detail="Locked: unlock first")


def _issue_token() -> str:
    token = secrets.token_hex(32)
    now = time.time()
    _active_tokens[token] = [now, now]
    return token


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    return {"setup_required": _get_user(session) is None}


@router.post("/setup")
def setup(body: PasswordBody, session: Session = Depends(get_session)) -> dict:
    """First run: create the single user. Refuses to run twice."""
    if _get_user(session) is not None:
        raise HTTPException(status_code=400, detail="A password is already set")
    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    session.add(User(username="owner", password_hash=password_hash))
    # Create the vault now, while the password is in hand. Deferring it would
    # mean a second prompt later, and a second chance to lose access.
    vault.create(session, body.password)
    log_action(session, "created", "user", detail="password set")
    session.commit()
    return {"token": _issue_token()}


@router.post("/unlock")
def unlock(body: PasswordBody, session: Session = Depends(get_session)) -> dict:
    _refuse_if_throttled()
    user = _get_user(session)
    if user is None:
        raise HTTPException(status_code=400, detail="No password set yet, use setup")
    if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        _unlock_failed()
        raise HTTPException(status_code=401, detail="Wrong password")
    _unlock_succeeded()
    # Unwrap the data key so private notes are readable for this session.
    vault_open = vault.open_with(session, body.password)
    log_action(session, "unlocked", "user", user.id)
    session.commit()
    return {"token": _issue_token(), "vault_open": vault_open}


@router.post("/lock")
def lock(x_auth_token: str | None = Header(default=None)) -> dict:
    """Log out: the token stops working immediately."""
    _active_tokens.pop(x_auth_token or "", None)
    # Forget the data key too, or "lock" would leave private notes readable.
    if not _active_tokens:
        vault.close()
    return {"locked": True}


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=4, description="Password or PIN, 4+ characters")


@router.get("/account", dependencies=[Depends(require_unlock)])
def account(
    session: Session = Depends(get_session),
    config: ConfigManager = Depends(get_config),
) -> dict:
    """What Settings → Account needs to describe the current state.

    Deliberately says nothing secret: whether a password exists, whether the
    vault is open, and how many sessions are live.
    """
    user = _get_user(session)
    idle_ttl = config.get_preference("session_idle_ttl_minutes", _SESSION_IDLE_TTL // 60) * 60
    _sweep_expired(idle_ttl)  # or the session count reports tokens that no longer work
    return {
        "configured": user is not None,
        "username": user.username if user else None,
        "created_at": user.created_at.isoformat() if user and user.created_at else None,
        "vault_open": vault.is_open(),
        "vault_exists": vault.exists(session),
        "active_sessions": len(_active_tokens),
    }


@router.post("/change-password", dependencies=[Depends(require_unlock)])
def change_password(
    body: ChangePasswordBody,
    session: Session = Depends(get_session),
    x_auth_token: str | None = Header(default=None),
) -> dict:
    """Change the password, re-wrapping the vault key onto the new one.

    The current password is required even though the caller already holds a
    valid token. The token proves the session is unlocked; it does not prove
    the person at the keyboard knows the password, and this is the one action
    that can lock someone out of their own private notes.

    Order matters. The vault is re-wrapped BEFORE the password hash changes,
    because a failure between the two would otherwise leave a notebook whose
    password no longer opens its own private notes.
    """
    user = _get_user(session)
    if user is None:
        raise HTTPException(status_code=400, detail="No password set yet, use setup")
    if not bcrypt.checkpw(body.current_password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="That isn't your current password")
    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="That's already your password")

    if vault.exists(session) and not vault.is_open():
        # Without the data key in hand the vault cannot be re-wrapped, and
        # changing the password anyway would strand every private note.
        raise HTTPException(
            status_code=409,
            detail="Unlock the app before changing your password, so your "
            "private notes can be moved across to it.",
        )
    if vault.exists(session) and not vault.rewrap(session, body.new_password):
        raise HTTPException(
            status_code=500, detail="Couldn't move your private notes to the new password"
        )

    user.password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    log_action(session, "edited", "user", user.id, "password changed")
    session.commit()

    # Every other session is invalidated: a password change is exactly when
    # you want anything already open elsewhere to stop working. The caller
    # keeps working via a freshly issued token.
    _active_tokens.pop(x_auth_token or "", None)
    signed_out = len(_active_tokens)
    _active_tokens.clear()
    return {"changed": True, "token": _issue_token(), "other_sessions_ended": signed_out}


class RotateVaultKeyBody(BaseModel):
    current_password: str = Field(min_length=1)


@router.post("/rotate-vault-key", dependencies=[Depends(require_unlock)])
def rotate_vault_key(
    body: RotateVaultKeyBody,
    session: Session = Depends(get_session),
    x_auth_token: str | None = Header(default=None),
) -> dict:
    """Re-key the vault: a fresh DEK, with every private note moved onto it.

    `/change-password` deliberately does NOT do this, see crypto.py's own
    design note. It only re-wraps the DEK (32 bytes); the DEK ITSELF never
    changes, on purpose, so an ordinary password change can't touch a single
    note. That is the right trade for that endpoint, but it leaves exactly
    one long-lived secret in this app that nothing ever rotates: the key
    that actually encrypts every private note. If an old wrapped-DEK ever
    got out: a stolen backup made before a password change, a copied
    database file: it still opens *today's* notes, because they are still
    under the very same DEK the backup was wrapped around. This endpoint is
    the fix for that: generate a new DEK and move every note onto it, so an
    old exposure stops mattering.

    All-or-nothing, deliberately paranoid (this is the HIGH RISK direction
    CLAUDE.md calls out for this exact feature): every note is decrypted
    with the OLD key and re-encrypted with the NEW one entirely in memory
    first; nothing is written to the database, and the in-memory key is not
    swapped, until every note round-trips cleanly under the new key AND the
    vault row's re-wrap succeeds: all inside the one commit below. A
    DecryptionError, a crash, or any other exception before that commit
    leaves the OLD key and OLD ciphertext exactly as they were; there is no
    step where a note is only half-migrated.
    """
    user = _get_user(session)
    if user is None:
        raise HTTPException(status_code=400, detail="No password set yet, use setup")
    if not bcrypt.checkpw(body.current_password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="That isn't your current password")

    if not vault.exists(session):
        raise HTTPException(status_code=400, detail="There's no vault to rotate yet")
    old_key = vault.key()
    if old_key is None:
        raise HTTPException(
            status_code=409,
            detail="Unlock the app before rotating the encryption key.",
        )

    # "all": every note in every workspace, deleted or not, a note this
    # misses would be left encrypted under the OLD key forever, because the
    # vault row (and therefore the only wrapped copy of that key) is about to
    # point at the NEW one instead.
    session.info["workspace_id"] = "all"
    private_entries = [
        entry
        for entry in session.scalars(select(Entry))
        if crypto.is_encrypted(entry.content)
    ]

    new_key = crypto.new_dek()

    # Decrypt with the OLD key and re-encrypt with the NEW one, entirely in
    # memory, before a single ORM object is touched, so a DecryptionError
    # partway through leaves nothing staged that would need undoing.
    try:
        rewritten = [
            (entry, plaintext, crypto.encrypt(new_key, plaintext))
            for entry in private_entries
            for plaintext in [crypto.decrypt(old_key, entry.content)]
        ]
    except crypto.DecryptionError:
        raise HTTPException(
            status_code=500,
            detail="Couldn't read one of your private notes with the current "
            "key: nothing was changed.",
        )

    # Verify the round trip against the REAL ciphertext just produced, not a
    # throwaway marker, before any of it becomes the only copy on disk.
    for entry, plaintext, new_ciphertext in rewritten:
        if crypto.decrypt(new_key, new_ciphertext) != plaintext:
            raise HTTPException(
                status_code=500,
                detail="Re-encryption didn't verify: nothing was changed.",
            )

    for entry, _plaintext, new_ciphertext in rewritten:
        entry.content = new_ciphertext

    vault_row = session.scalar(select(Vault))
    new_salt = crypto.new_salt()
    vault_row.kdf_salt = new_salt
    vault_row.wrapped_dek = crypto.wrap_dek(new_key, body.current_password, new_salt)

    log_action(
        session, "edited", "vault",
        detail=f"encryption key rotated ({len(rewritten)} note(s) re-encrypted)",
    )
    session.commit()  # one transaction: every note and the vault row, or none

    # Only now, after the commit that made it real, does memory follow.
    vault.set_key(new_key)

    # Same reasoning as change-password: rotating a key you suspect is
    # compromised should not leave anything already open still trusted on
    # the old one.
    _active_tokens.pop(x_auth_token or "", None)
    ended = len(_active_tokens)
    _active_tokens.clear()
    return {
        "rotated": True,
        "notes_reencrypted": len(rewritten),
        "token": _issue_token(),
        "other_sessions_ended": ended,
    }


@router.post("/lock-all", dependencies=[Depends(require_unlock)])
def lock_all() -> dict:
    """End every session, including this one. The panic button."""
    ended = len(_active_tokens)
    _active_tokens.clear()
    vault.close()
    return {"locked": True, "sessions_ended": ended}
