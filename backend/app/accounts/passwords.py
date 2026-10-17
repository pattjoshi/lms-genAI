"""Password hashing and the password rules.

scrypt (Python's standard library) is a memory-hard password hash: every guess costs ~16 MB of RAM and
tens of milliseconds, so a leaked hash can't be brute-forced quickly the way a SHA-256 could. Each
password gets its own random salt, so equal passwords get different hashes. The parameters are stored
with the hash, so they can be raised later without breaking existing passwords.
"""

import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1  # cost: ~16 MB, the common interactive-login setting
KEY_LEN = 32
MIN_LENGTH = 8
MAX_LENGTH = 128  # scrypt is fine with long inputs, but an unbounded field is a cheap denial-of-service

# The most used passwords; length rules alone let these through.
COMMON = frozenset(
    {
        "password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123",
        "qwertyuiop", "11111111", "iloveyou", "abc12345", "welcome1", "letmein1", "admin123", "passw0rd",
    }
)  # fmt: skip


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=KEY_LEN)
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)  # constant time: no timing hint about how close a guess was


# Checked against when the email is unknown, so "no such user" takes as long as "wrong password"
# and response times don't reveal which emails have accounts.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problem(password: str, email: str = "") -> str | None:
    """Why this password can't be used, or None if it is fine."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    if password.lower() in COMMON or len(set(password)) < 4:
        return "This password is too easy to guess. Try a short sentence or mix in more words."
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in password.lower():
        return "Don't use your email address in your password."
    return None
