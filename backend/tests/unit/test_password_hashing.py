"""
Tests for password hashing.

The scheme these cover replaced `sha256("hirelens_salt_" + password)`, which
used a single compile-time-constant salt shared by every account and a hash
function designed to be fast. See app/core/security.py for the full note.
"""

import hashlib

import pytest

from app.core.security import (
    _legacy_sha256,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_round_trip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("Correct horse battery staple", h)
    assert not verify_password("", h)


def test_hash_is_bcrypt_not_a_bare_digest():
    h = hash_password("Password123!")
    assert h.startswith("$2")
    assert len(h) > 50


def test_same_password_hashes_differently_each_time():
    """
    The defining property the old scheme lacked: a per-hash random salt. Two
    users with the same password must not share a stored hash, or one
    precomputed table breaks every account at once.
    """
    a = hash_password("Password123!")
    b = hash_password("Password123!")
    assert a != b
    assert verify_password("Password123!", a)
    assert verify_password("Password123!", b)


def test_legacy_hashes_still_verify():
    """Existing local accounts must keep working across the upgrade."""
    legacy = _legacy_sha256("Password123!")
    assert verify_password("Password123!", legacy)
    assert not verify_password("wrong", legacy)


def test_legacy_hashes_are_flagged_for_rehash():
    assert needs_rehash(_legacy_sha256("Password123!"))
    assert not needs_rehash(hash_password("Password123!"))


def test_legacy_hash_with_explicit_prefix_verifies():
    legacy = f"sha256$legacy${_legacy_sha256('Password123!')}"
    assert verify_password("Password123!", legacy)
    assert needs_rehash(legacy)


def test_passwords_over_bcrypt_72_byte_limit_are_not_truncated():
    """
    bcrypt ignores everything past 72 bytes. Without pre-hashing, a 200-char
    passphrase would be accepted by anyone who knew its first 72 characters.
    """
    long_pw = "a" * 200
    h = hash_password(long_pw)
    assert verify_password(long_pw, h)
    assert not verify_password("a" * 72, h)
    assert not verify_password("a" * 199, h)


def test_unicode_passwords():
    pw = "пароль-密码-🔐"
    h = hash_password(pw)
    assert verify_password(pw, h)
    assert not verify_password("пароль-密码", h)


@pytest.mark.parametrize("bad", ["", "not-a-hash", "$2b$broken", "x" * 60])
def test_malformed_stored_hash_returns_false_instead_of_raising(bad):
    assert verify_password("anything", bad) is False
    assert needs_rehash(bad) is True


def test_empty_stored_hash_never_authenticates():
    assert verify_password("", "") is False
    assert verify_password("anything", "") is False


def test_a_64_char_non_hex_string_is_not_treated_as_a_legacy_hash():
    # Guards the legacy sniff from misfiring on a bcrypt-ish string of the
    # same length that happens to contain non-hex characters.
    not_hex = "z" * 64
    assert verify_password("anything", not_hex) is False
