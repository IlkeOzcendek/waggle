from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


COOKIE_NAME = "waggle_session"
SESSION_SECONDS = int(os.getenv("WAGGLE_SESSION_SECONDS", "28800"))
ADMIN_USERNAME = os.getenv("WAGGLE_ADMIN_USERNAME", "admin")
DEVICE_KEY_HEADER = "X-Device-Key"
_DEVICE_KEY = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo")
_PASSWORD = os.getenv("WAGGLE_ADMIN_PASSWORD", "waggle-demo")
_PASSWORD_SALT = os.getenv("WAGGLE_PASSWORD_SALT", "waggle-local-panel").encode()
_PASSWORD_HASH = hashlib.pbkdf2_hmac("sha256", _PASSWORD.encode(), _PASSWORD_SALT, 210_000)
_SESSION_SECRET_VALUE = os.getenv("WAGGLE_SESSION_SECRET")
_SESSION_SECRET = (_SESSION_SECRET_VALUE or secrets.token_urlsafe(32)).encode()
ENVIRONMENT = os.getenv("WAGGLE_ENV", "development").lower()


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


def create_session(username: str) -> str:
    expires_at = int(time.time()) + SESSION_SECONDS
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
        expected = hmac.new(_SESSION_SECRET, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        username, expires_at = payload.decode().rsplit("|", 1)
        if int(expires_at) < int(time.time()):
            return None
        return username
    except (ValueError, UnicodeDecodeError):
        return None
