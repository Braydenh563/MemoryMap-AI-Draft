"""Changing the password, and the state Settings → Account reports.

The risk this file guards is specific: the vault key is wrapped with a key
derived from the password, so a password change that doesn't re-wrap it leaves
a notebook whose password no longer opens its own private notes, silently,
and unrecoverably.
"""

from __future__ import annotations

import pytest


def _setup(client, password="first-pass"):
    token = client.post("/auth/setup", json={"password": password}).json()["token"]
    return {"X-Auth-Token": token}


def test_account_reports_the_current_state(client):
    headers = _setup(client)
    body = client.get("/auth/account", headers=headers).json()
    assert body["configured"] is True
    assert body["username"] == "owner"
    assert body["active_sessions"] == 1
    # Nothing secret is exposed, no hash, no token.
    assert "password_hash" not in body
    assert "token" not in body


def test_account_needs_an_unlocked_session(client):
    _setup(client)
    assert client.get("/auth/account").status_code == 401


def test_password_change_swaps_the_password(client):
    headers = _setup(client)
    changed = client.post(
        "/auth/change-password",
        json={"current_password": "first-pass", "new_password": "second-pass"},
        headers=headers,
    )
    assert changed.status_code == 200

    client.post("/auth/lock", headers={"X-Auth-Token": changed.json()["token"]})
    assert client.post("/auth/unlock", json={"password": "first-pass"}).status_code == 401
    assert client.post("/auth/unlock", json={"password": "second-pass"}).status_code == 200


def test_password_change_keeps_private_notes_readable(client):
    """The reason the endpoint re-wraps the vault instead of just re-hashing.

    Without the re-wrap this note would still exist, still be flagged private,
    and never decrypt again.
    """
    headers = _setup(client)
    entry = client.post(
        "/entries", json={"content": "a private thought"}, headers=headers
    ).json()
    made = client.post(
        f"/entries/{entry['id']}/privacy", json={"private": True}, headers=headers
    )
    assert made.json()["is_private"] is True

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "first-pass", "new_password": "second-pass"},
        headers=headers,
    )
    assert changed.status_code == 200

    client.post("/auth/lock", headers={"X-Auth-Token": changed.json()["token"]})
    reopened = client.post("/auth/unlock", json={"password": "second-pass"}).json()
    assert reopened["vault_open"] is True
    after = client.get(
        f"/entries/{entry['id']}", headers={"X-Auth-Token": reopened["token"]}
    ).json()
    assert after["content"] == "a private thought"
    assert after["is_private"] is True


def test_password_change_refuses_a_wrong_current_password(client):
    """Holding a valid token proves the session is unlocked. It does not prove
    the person at the keyboard knows the password, and this is the one action
    that can lock someone out of their own notes."""
    headers = _setup(client)
    response = client.post(
        "/auth/change-password",
        json={"current_password": "not-it", "new_password": "second-pass"},
        headers=headers,
    )
    assert response.status_code == 401
    # The old password still works, i.e. nothing was half-applied.
    assert client.post("/auth/unlock", json={"password": "first-pass"}).status_code == 200


def test_password_change_refuses_reusing_the_same_password(client):
    headers = _setup(client)
    response = client.post(
        "/auth/change-password",
        json={"current_password": "first-pass", "new_password": "first-pass"},
        headers=headers,
    )
    assert response.status_code == 400


def test_password_change_ends_other_sessions(client):
    headers = _setup(client)
    other = client.post("/auth/unlock", json={"password": "first-pass"}).json()
    other_headers = {"X-Auth-Token": other["token"]}
    assert client.get("/auth/account", headers=other_headers).status_code == 200

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "first-pass", "new_password": "second-pass"},
        headers=headers,
    )
    assert changed.status_code == 200
    # The session that made the change keeps working, via a fresh token.
    assert client.get(
        "/auth/account", headers={"X-Auth-Token": changed.json()["token"]}
    ).status_code == 200
    # Everything else is signed out.
    assert client.get("/auth/account", headers=other_headers).status_code == 401
    assert client.get("/auth/account", headers=headers).status_code == 401


def test_lock_all_ends_every_session(client):
    headers = _setup(client)
    ended = client.post("/auth/lock-all", headers=headers)
    assert ended.status_code == 200
    assert client.get("/auth/account", headers=headers).status_code == 401


def test_rotate_vault_key_invalidates_old_tokens_and_unlock_still_works(client):
    headers = _setup(client)
    other = client.post("/auth/unlock", json={"password": "first-pass"}).json()
    other_headers = {"X-Auth-Token": other["token"]}
    assert client.get("/auth/account", headers=other_headers).status_code == 200

    rotated = client.post(
        "/auth/rotate-vault-key",
        json={"current_password": "first-pass"},
        headers=headers,
    )
    assert rotated.status_code == 200
    assert rotated.json()["rotated"] is True

    # Every session live before the rotation is gone, including the caller's
    # old token: a fresh one came back in the response instead.
    assert client.get("/auth/account", headers=other_headers).status_code == 401
    assert client.get("/auth/account", headers=headers).status_code == 401
    fresh_headers = {"X-Auth-Token": rotated.json()["token"]}
    assert client.get("/auth/account", headers=fresh_headers).status_code == 200

    # The password didn't change, so unlocking with it still works.
    client.post("/auth/lock", headers=fresh_headers)
    reopened = client.post("/auth/unlock", json={"password": "first-pass"})
    assert reopened.status_code == 200


def test_rotate_vault_key_keeps_private_notes_readable(client):
    """The point of the whole endpoint: notes survive under the new key."""
    headers = _setup(client)
    entry = client.post(
        "/entries", json={"content": "a private thought"}, headers=headers
    ).json()
    client.post(
        f"/entries/{entry['id']}/privacy", json={"private": True}, headers=headers
    )

    rotated = client.post(
        "/auth/rotate-vault-key",
        json={"current_password": "first-pass"},
        headers=headers,
    )
    assert rotated.status_code == 200
    assert rotated.json()["notes_reencrypted"] == 1

    fresh_headers = {"X-Auth-Token": rotated.json()["token"]}
    after = client.get(f"/entries/{entry['id']}", headers=fresh_headers).json()
    assert after["content"] == "a private thought"
    assert after["is_private"] is True

    # And after a lock/unlock cycle, i.e. from the wrapped key stored on disk.
    client.post("/auth/lock", headers=fresh_headers)
    reopened = client.post("/auth/unlock", json={"password": "first-pass"}).json()
    assert reopened["vault_open"] is True
    again = client.get(
        f"/entries/{entry['id']}", headers={"X-Auth-Token": reopened["token"]}
    ).json()
    assert again["content"] == "a private thought"


def test_rotate_vault_key_refuses_a_wrong_current_password(client):
    headers = _setup(client)
    entry = client.post(
        "/entries", json={"content": "a private thought"}, headers=headers
    ).json()
    client.post(
        f"/entries/{entry['id']}/privacy", json={"private": True}, headers=headers
    )

    response = client.post(
        "/auth/rotate-vault-key",
        json={"current_password": "not-it"},
        headers=headers,
    )
    assert response.status_code == 401
    # The session survives a refused rotation, nothing was touched.
    assert client.get("/auth/account", headers=headers).status_code == 200
    still_there = client.get(f"/entries/{entry['id']}", headers=headers).json()
    assert still_there["content"] == "a private thought"


def test_rotate_vault_key_refuses_an_unauthenticated_caller(client):
    _setup(client)
    response = client.post(
        "/auth/rotate-vault-key", json={"current_password": "first-pass"}
    )
    assert response.status_code == 401


def test_rotate_vault_key_interrupted_leaves_notes_readable_with_the_old_key(
    client, monkeypatch
):
    """Simulates a failure partway through re-encryption (a corrupt row, a
    crash mid-loop) and proves nothing was committed: the vault row and every
    note's ciphertext are untouched, and the OLD password still opens them."""
    from memorymap.api import routes_auth
    from memorymap.core import crypto

    headers = _setup(client)
    entry = client.post(
        "/entries", json={"content": "a private thought"}, headers=headers
    ).json()
    client.post(
        f"/entries/{entry['id']}/privacy", json={"private": True}, headers=headers
    )

    real_encrypt = crypto.encrypt
    calls = {"n": 0}

    def _boom(dek, plaintext):
        calls["n"] += 1
        raise RuntimeError("simulated crash mid-rotation")

    monkeypatch.setattr(routes_auth.crypto, "encrypt", _boom)
    with pytest.raises(RuntimeError):
        client.post(
            "/auth/rotate-vault-key",
            json={"current_password": "first-pass"},
            headers=headers,
        )
    assert calls["n"] >= 1
    monkeypatch.setattr(routes_auth.crypto, "encrypt", real_encrypt)

    # The session token from before the crash is still valid, commit never
    # ran: and the note is still readable under the untouched, old key.
    still_there = client.get(f"/entries/{entry['id']}", headers=headers).json()
    assert still_there["content"] == "a private thought"

    client.post("/auth/lock", headers=headers)
    assert client.post("/auth/unlock", json={"password": "first-pass"}).status_code == 200


def test_unlock_throttles_a_run_of_wrong_passwords(client, monkeypatch):
    """bcrypt makes each guess slow; this makes *many* guesses slow. The app
    binds localhost, but people put it behind tunnels to reach it from a
    phone, a server log showed a public address arriving through a proxy , 
    and a four-character floor is PIN territory without a throttle."""
    from memorymap.api import routes_auth

    monkeypatch.setattr(routes_auth, "_failed_unlocks", [])
    _setup(client)
    for _ in range(routes_auth._FAILURE_ALLOWANCE):
        assert client.post("/auth/unlock", json={"password": "nope"}).status_code == 401

    # Inside the earned wait even the right password is refused, the 429
    # names the wait so the owner knows it is a throttle, not a lockout.
    refused = client.post("/auth/unlock", json={"password": "first-pass"})
    assert refused.status_code == 429
    assert "try again" in refused.json()["detail"]


def test_unlock_forgives_once_the_wait_has_passed(client, monkeypatch):
    from memorymap.api import routes_auth

    monkeypatch.setattr(routes_auth, "_failed_unlocks", [])
    _setup(client)
    for _ in range(routes_auth._FAILURE_ALLOWANCE):
        client.post("/auth/unlock", json={"password": "nope"})

    # Age the failures past the wait they earned; the right password gets in
    # and wipes the slate, so the next wrong guess starts from zero.
    routes_auth._failed_unlocks[:] = [t - 5 for t in routes_auth._failed_unlocks]
    assert client.post("/auth/unlock", json={"password": "first-pass"}).status_code == 200
    assert routes_auth._failed_unlocks == []


def test_full_auth_flow(client):
    # Fresh app: setup required, API open (nothing to protect yet).
    assert client.get("/auth/status").json() == {"setup_required": True}
    assert client.post("/entries", json={"content": "pre-password note"}).status_code == 201

    token = client.post("/auth/setup", json={"password": "hunter2"}).json()["token"]
    assert client.get("/auth/status").json() == {"setup_required": False}

    # Once a password exists the data routes lock without a token…
    assert client.get("/entries").status_code == 401
    assert client.post("/auth/setup", json={"password": "again"}).status_code == 400

    # …and open with one.
    ok = client.get("/entries", headers={"X-Auth-Token": token})
    assert ok.status_code == 200 and len(ok.json()) == 1

    # Wrong password rejected; right password issues a fresh token.
    assert client.post("/auth/unlock", json={"password": "wrong"}).status_code == 401
    token2 = client.post("/auth/unlock", json={"password": "hunter2"}).json()["token"]

    # Locking kills that token.
    client.post("/auth/lock", headers={"X-Auth-Token": token2})
    assert client.get("/entries", headers={"X-Auth-Token": token2}).status_code == 401
