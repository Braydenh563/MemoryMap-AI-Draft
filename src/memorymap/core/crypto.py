"""Encryption at rest for notes you mark private.

The design is an envelope, not direct password-to-note encryption, and the
reason matters: with direct encryption, changing your password means
re-encrypting every private note, and an interruption halfway through that
loses data permanently. Here a random data key (the DEK) encrypts the notes,
and the password only encrypts the DEK. Changing your password re-wraps 32
bytes and touches no notes at all.

  password --scrypt--> KEK --AES-GCM--> unwraps DEK --AES-GCM--> note content

Everything is authenticated (AES-GCM), so a wrong key fails loudly rather than
returning garbage. The DEK exists in memory only while the app is unlocked; it
is never written to disk unwrapped.

What this protects against: someone reading the database file, a stolen
laptop, a synced backup, a shared machine. What it cannot protect against:
someone who has your password, or a running unlocked app.

There is no recovery path. That is inherent to encryption rather than a
shortcut taken here: a backdoor that let the app recover notes without the
password would equally let anyone else.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# scrypt parameters. n=2**15 costs ~100ms and ~32MB, which is a deliberate
# trade: slow enough to make guessing a short PIN expensive, fast enough that
# unlocking doesn't feel broken on a laptop.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_BYTES = 32
NONCE_BYTES = 12
SALT_BYTES = 16

# Marks a stored string as ciphertext produced here. Without it there is no way
# to tell an encrypted note from one that happens to look like base64.
PREFIX = "mmenc1:"


class DecryptionError(RuntimeError):
    """The key was wrong, or the stored data was tampered with."""


def derive_kek(password: str, salt: bytes) -> bytes:
    """Password + salt -> the key that wraps the DEK."""
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
        maxmem=64 * 1024 * 1024,
    )


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


def new_dek() -> bytes:
    """A fresh random data key. This is what actually encrypts notes."""
    return AESGCM.generate_key(bit_length=256)


def wrap_dek(dek: bytes, password: str, salt: bytes) -> bytes:
    """Encrypt the DEK with a key derived from the password."""
    kek = derive_kek(password, salt)
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(kek).encrypt(nonce, dek, None)


def unwrap_dek(wrapped: bytes, password: str, salt: bytes) -> bytes:
    """Recover the DEK, or raise DecryptionError for a wrong password.

    GCM authenticates, so a wrong password can't silently yield a plausible
    key that would then corrupt every note it touched.
    """
    kek = derive_kek(password, salt)
    nonce, body = wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:]
    try:
        return AESGCM(kek).decrypt(nonce, body, None)
    except (InvalidTag, ValueError) as exc:
        raise DecryptionError("Wrong password for the vault") from exc


def encrypt(dek: bytes, plaintext: str) -> str:
    """Note text -> a storable string, tagged so it's recognisable."""
    nonce = os.urandom(NONCE_BYTES)
    blob = nonce + AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), None)
    return PREFIX + base64.b64encode(blob).decode("ascii")


def decrypt(dek: bytes, stored: str) -> str:
    """Reverse of encrypt. Raises DecryptionError on a wrong key."""
    if not is_encrypted(stored):
        # Already plaintext: returning it unchanged makes the read path safe
        # to call on any note, private or not.
        return stored
    try:
        blob = base64.b64decode(stored[len(PREFIX) :])
        nonce, body = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        return AESGCM(dek).decrypt(nonce, body, None).decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise DecryptionError("Couldn't decrypt this note") from exc


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)
