"""The encryption core.

These are the tests that matter most in the whole suite: a bug here loses
notes permanently, and unlike every other failure it isn't recoverable.
"""

from __future__ import annotations

import pytest

from memorymap.core import crypto


def test_encrypt_decrypt_round_trip():
    dek = crypto.new_dek()
    text = "A private note: with unicode, emoji 🔐, and\nnewlines."
    stored = crypto.encrypt(dek, text)

    assert stored != text
    assert text not in stored  # the plaintext is genuinely not sitting there
    assert crypto.decrypt(dek, stored) == text


def test_ciphertext_is_recognisable_and_plaintext_is_not():
    dek = crypto.new_dek()
    assert crypto.is_encrypted(crypto.encrypt(dek, "x")) is True
    assert crypto.is_encrypted("just a normal note") is False
    # Even something that looks like base64 isn't mistaken for ciphertext.
    assert crypto.is_encrypted("aGVsbG8gd29ybGQ=") is False


def test_decrypting_plaintext_returns_it_unchanged():
    """The read path is called on every note, private or not."""
    dek = crypto.new_dek()
    assert crypto.decrypt(dek, "an ordinary note") == "an ordinary note"


def test_the_wrong_key_fails_loudly_rather_than_returning_garbage():
    stored = crypto.encrypt(crypto.new_dek(), "secret")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(crypto.new_dek(), stored)


def test_tampering_is_detected():
    """AES-GCM authenticates, so an edited database row can't slip through."""
    dek = crypto.new_dek()
    stored = crypto.encrypt(dek, "the original text")
    tampered = stored[:-6] + ("AAAAA=" if not stored.endswith("AAAAA=") else "BBBBB=")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(dek, tampered)


def test_the_same_text_encrypts_differently_every_time():
    """A fresh nonce per note: identical notes must not look identical."""
    dek = crypto.new_dek()
    assert crypto.encrypt(dek, "same") != crypto.encrypt(dek, "same")


def test_vault_wrap_and_unwrap():
    dek = crypto.new_dek()
    salt = crypto.new_salt()
    wrapped = crypto.wrap_dek(dek, "correct horse", salt)

    assert wrapped != dek
    assert crypto.unwrap_dek(wrapped, "correct horse", salt) == dek


def test_the_wrong_password_cannot_unwrap_the_vault():
    salt = crypto.new_salt()
    wrapped = crypto.wrap_dek(crypto.new_dek(), "right", salt)
    with pytest.raises(crypto.DecryptionError):
        crypto.unwrap_dek(wrapped, "wrong", salt)


def test_changing_the_password_keeps_the_same_data_key():
    """This is the point of the envelope: notes are never re-encrypted.

    If a password change had to rewrite every note, an interruption halfway
    through would lose the ones it hadn't reached.
    """
    dek = crypto.new_dek()
    old_salt = crypto.new_salt()
    wrapped = crypto.wrap_dek(dek, "old password", old_salt)
    note = crypto.encrypt(dek, "written under the old password")

    # Re-wrap under a new password, with a fresh salt.
    recovered = crypto.unwrap_dek(wrapped, "old password", old_salt)
    new_salt = crypto.new_salt()
    rewrapped = crypto.wrap_dek(recovered, "new password", new_salt)

    dek_after = crypto.unwrap_dek(rewrapped, "new password", new_salt)
    assert dek_after == dek
    assert crypto.decrypt(dek_after, note) == "written under the old password"


def test_the_same_password_with_a_different_salt_gives_a_different_key():
    a = crypto.derive_kek("same password", crypto.new_salt())
    b = crypto.derive_kek("same password", crypto.new_salt())
    assert a != b
    assert len(a) == crypto.KEY_BYTES


def test_empty_and_very_long_notes_round_trip():
    dek = crypto.new_dek()
    for text in ["", "x", "y" * 200_000]:
        assert crypto.decrypt(dek, crypto.encrypt(dek, text)) == text
