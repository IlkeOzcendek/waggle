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


def verify_credentials(username: str, password: str) -> bool:
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), _PASSWORD_SALT, 210_000)
    return hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(
        candidate, _PASSWORD_HASH
    )


def verify_device_key(device_key: str | None) -> bool:
    return bool(device_key) and hmac.compare_digest(device_key, _DEVICE_KEY)


def create_session(username: str, seconds: int | None = None) -> str:
    expires_at = int(time.time()) + (seconds or SESSION_SECONDS)
    payload = f"{username}|{expires_at}".encode()
    signature = hmac.new(_SESSION_SECRET, payload, hashlib.sha256).digest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded_payload}.{encoded_signature}"


def read_session(token: str | None) -> str | None:
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
        username, expires_at = payload.decode().rsplit("|", 1)
        if int(expires_at) < int(time.time()):
            return None
        return username
    except (ValueError, UnicodeDecodeError):
        return None
