from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


COOKIE_NAME = "waggle_session"
SESSION_SECONDS = int(os.getenv("WAGGLE_SESSION_SECONDS", "28800"))
# Opt-in longer session for "keep me signed in". It extends the session; it never stores
# the password — remembering that is the browser's job, not the panel's.
REMEMBERED_SESSION_SECONDS = int(os.getenv("WAGGLE_REMEMBERED_SESSION_SECONDS", "2592000"))
ADMIN_USERNAME = os.getenv("WAGGLE_ADMIN_USERNAME", "admin")
DEVICE_KEY_HEADER = "X-Device-Key"
_DEVICE_KEY = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo")
_PASSWORD = os.getenv("WAGGLE_ADMIN_PASSWORD", "waggle-demo")
_PASSWORD_SALT = os.getenv("WAGGLE_PASSWORD_SALT", "waggle-local-panel").encode()
_PASSWORD_HASH = hashlib.pbkdf2_hmac("sha256", _PASSWORD.encode(), _PASSWORD_SALT, 210_000)
_SESSION_SECRET_VALUE = os.getenv("WAGGLE_SESSION_SECRET")
_SESSION_SECRET = (_SESSION_SECRET_VALUE or secrets.token_urlsafe(32)).encode()
ENVIRONMENT = os.getenv("WAGGLE_ENV", "development").lower()
LOGIN_MAX_ATTEMPTS = int(os.getenv("WAGGLE_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("WAGGLE_LOGIN_WINDOW_SECONDS", "300"))


class LoginAttemptGuard:
    """Small in-memory limiter for repeated failed logins from one client."""

    def __init__(self, max_attempts: int, window_seconds: int):
        if max_attempts < 1 or window_seconds < 1:
            raise ValueError("Giriş koruması değerleri pozitif olmalıdır")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, identifier: str, now: float) -> deque[float]:
        failures = self._failures[identifier]
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(identifier, None)
            return deque()
        return failures

    def retry_after(self, identifier: str, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        with self._lock:
            failures = self._prune(identifier, current)
            if len(failures) < self.max_attempts:
                return 0
            return max(1, int(failures[0] + self.window_seconds - current) + 1)

    def record_failure(self, identifier: str, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            failures = self._prune(identifier, current)
            failures.append(current)
            self._failures[identifier] = failures

    def reset(self, identifier: str) -> None:
        with self._lock:
            self._failures.pop(identifier, None)


login_attempt_guard = LoginAttemptGuard(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Return a per-user PBKDF2 salt and hash encoded for SQLite storage."""
    password_salt = salt or secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), password_salt, 310_000
    )
    return (
        base64.urlsafe_b64encode(password_salt).decode("ascii"),
        base64.urlsafe_b64encode(password_hash).decode("ascii"),
    )


# Unambiguous alphabet: no 0/O/1/I/l, because this code is read off paper and typed back
# in by hand, often months later. 24 characters from 32 symbols is ~120 bits of entropy.
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_GROUPS = 6
RECOVERY_GROUP_SIZE = 4


def generate_recovery_code() -> str:
    """A single-use code that can reset a password when there is no e-mail to send to."""
    characters = [
        secrets.choice(RECOVERY_ALPHABET)
        for _ in range(RECOVERY_GROUPS * RECOVERY_GROUP_SIZE)
    ]
    groups = [
        "".join(characters[index : index + RECOVERY_GROUP_SIZE])
        for index in range(0, len(characters), RECOVERY_GROUP_SIZE)
    ]
    return "-".join(groups)


def normalize_recovery_code(code: str) -> str:
    """Accept the code however it was retyped: lower case, spaces, missing dashes."""
    return "".join(character for character in code.upper() if character.isalnum())


def verify_password(password: str, encoded_salt: str, encoded_hash: str) -> bool:
    try:
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 310_000
    )
    return hmac.compare_digest(candidate, expected)


def security_warnings() -> list[str]:
    warnings = []
    if _PASSWORD == "waggle-demo":
        warnings.append("Varsayılan yönetici parolası kullanılıyor")
    if _DEVICE_KEY == "waggle-device-demo":
        warnings.append("Varsayılan cihaz anahtarı kullanılıyor")
    if not _SESSION_SECRET_VALUE:
        warnings.append("Kalıcı oturum anahtarı yapılandırılmadı")
    if os.getenv("WAGGLE_SECURE_COOKIE", "0") != "1":
        warnings.append("Güvenli HTTPS çerezi devre dışı")
    return warnings


def validate_security_config() -> list[str]:
    warnings = security_warnings()
    if ENVIRONMENT == "production" and warnings:
        raise RuntimeError("Production güvenlik yapılandırması eksik: " + "; ".join(warnings))
    return warnings


def _same_text(left: str, right: str) -> bool:
    """A constant-time comparison that survives a Turkish name.

    hmac.compare_digest refuses str arguments holding a character above ASCII, and raises
    TypeError rather than returning False. Every value compared here is text a person or a
    device sends, so on a Turkish panel that is not an edge case: signing in as "İlke"
    reached this function, raised inside it, and the sign-in screen answered 500 — the
    account could not be used at all while the panel had no row of its own for it.
    Comparing the encoded bytes is the same comparison without the restriction.
    """
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def verify_credentials(username: str, password: str) -> bool:
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), _PASSWORD_SALT, 210_000)
    return _same_text(username, ADMIN_USERNAME) and hmac.compare_digest(
        candidate, _PASSWORD_HASH
    )


def verify_device_key(device_key: str | None) -> bool:
    # The header arrives as latin-1 text, so a byte above 127 in it lands here as non-ASCII.
    return bool(device_key) and _same_text(device_key, _DEVICE_KEY)


def password_stamp(password_hash: str) -> str:
    """A short marker of the password a session was opened with.

    Sessions are signed tokens with no server-side record, so there is no list of open
    sessions to revoke. Carrying this marker in the token gives the same result: change the
    password and every token minted under the old one stops matching. It is keyed with the
    session secret rather than plainly hashed because whoever holds the cookie can read its
    payload, and a bare hash of the stored hash would be a stable handle on the password.
    """
    return hmac.new(_SESSION_SECRET, password_hash.encode(), hashlib.sha256).hexdigest()[:16]


def create_session(username: str, seconds: int | None = None, stamp: str = "") -> str:
    expires_at = int(time.time()) + (seconds or SESSION_SECONDS)
    payload = f"{username}|{expires_at}|{stamp}".encode()
    signature = hmac.new(_SESSION_SECRET, payload, hashlib.sha256).digest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def read_session(token: str | None) -> str | None:
    details = read_session_details(token)
    return details[0] if details else None


def read_session_details(token: str | None) -> tuple[str, str] | None:
    """The username a valid token names, and the password stamp it was minted with."""
    if not token:
        return None
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        canonical_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        canonical_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
        if not hmac.compare_digest(encoded_payload, canonical_payload) or not hmac.compare_digest(
            encoded_signature, canonical_signature
        ):
            return None
        expected = hmac.new(_SESSION_SECRET, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        # Usernames are restricted to letters, digits, - and _, so "|" only ever separates
        # fields. Tokens minted before the stamp existed have two fields, not three.
        fields = payload.decode().split("|")
        if len(fields) == 2:
            fields.append("")
        if len(fields) != 3:
            return None
        username, expires_at, stamp = fields
        if int(expires_at) < int(time.time()):
            return None
        return username, stamp
    except (ValueError, UnicodeDecodeError):
        return None
