from __future__ import annotations

import hashlib
import json
import os
import logging
import re
import tempfile
import threading
from typing import Literal
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
import requests

from .database import EventStore
from .exports import build_bundle, build_export, export_summary
from .report_pdf import build_report_pdf
from .models import AlarmInspectionIn, AppSettings, ComponentHistory, ComponentStatus, ContactRecord, DashboardState, Device, DeviceCreate, EnrollmentStatus, HealthConfirmation, HealthConfirmationIn, Hive, HiveCreate, HiveEvent, HiveEventIn, HiveUpdate, Report, ReportIn, SensorAnalysis, SystemStatus, WeatherState
from .auth import (
    ADMIN_USERNAME,
    generate_recovery_code,
    normalize_recovery_code,
    COOKIE_NAME,
    DEVICE_KEY_HEADER,
    REMEMBERED_SESSION_SECONDS,
    SESSION_SECONDS,
    create_session,
    hash_password,
    login_attempt_guard,
    read_session,
    read_session_details,
    verify_credentials,
    verify_password,
    verify_device_key,
    validate_security_config,
)
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("WAGGLE_DB", BASE_DIR.parent / "data" / "waggle.db"))
store = EventStore(DB_PATH)
WEATHER_LOCATION = os.getenv("WAGGLE_LOCATION", "Gölbaşı Arılığı")
# When it was read, what it said, and the coordinates it was read for. WAGGLE_LAT and
# WAGGLE_LON now only seed a new panel's settings row — see database.DEFAULT_LATITUDE —
# because a position the panel cannot be told about is a position it reports wrongly.
weather_cache: tuple[datetime, WeatherState, tuple[float, float]] | None = None
logger = logging.getLogger("waggle")
MAX_BACKUP_BYTES = int(os.getenv("WAGGLE_MAX_BACKUP_BYTES", str(100 * 1024 * 1024)))
DEVICE_STALE_SECONDS = int(os.getenv("WAGGLE_DEVICE_STALE_SECONDS", "900"))
REPORT_STALE_SECONDS = int(os.getenv("WAGGLE_REPORT_STALE_SECONDS", "691200"))
SENSOR_MODEL_PATH = Path(os.getenv("WAGGLE_SENSOR_MODEL", BASE_DIR.parent.parent / "results" / "mendeley_isolation_monitor.onnx"))
HIVE_PROFILE_DIR = Path(os.getenv("WAGGLE_HIVE_PROFILE_DIR", BASE_DIR.parent.parent / "results" / "hive_profiles"))
# The recorded joblib-versus-ONNX decision comparison. It is the evidence behind "the
# conversion did not change any decision", which the panel asserted nowhere.
ONNX_PARITY_REPORT = Path(os.getenv("WAGGLE_ONNX_PARITY_REPORT", BASE_DIR.parent.parent / "results" / "mendeley_onnx_parity.json"))
MAX_SENSOR_AUDIO_BYTES = int(os.getenv("WAGGLE_MAX_SENSOR_AUDIO_BYTES", str(25 * 1024 * 1024)))
# Model-backed report generation stays off unless it is switched on deliberately,
# so a panel without a local model never advertises a capability it does not have.
LLM_ENABLED = os.getenv("WAGGLE_LLM_ENABLED", "0") == "1"
LLM_MODEL = os.getenv("WAGGLE_LLM_MODEL", "phi-3.5-mini")
DEVICE_KEY = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo")
REPORT_GENERATION: dict = {
    # Which device Foundry runs the model on, and how many characters it has written so
    # far. The panel showed a climbing counter and nothing else; both of these are facts it
    # can state instead of implying progress it could not see.
    "device": None,
    "written_characters": 0,
    "written_at": None,
    "running": False,
    "created": 0,
    "error": None,
    "generators": [],
    "started_at": None,
    "finished_at": None,
}
# Model loading and two languages can legitimately take minutes; past this the run is
# reported as stalled so the panel stops implying progress it cannot see.
REPORT_GENERATION_STALL_SECONDS = int(os.getenv("WAGGLE_REPORT_GENERATION_STALL_SECONDS", "600"))
REPORT_GENERATION_LOCK = threading.Lock()


class ReportGenerateIn(BaseModel):
    report_type: Literal["event", "daily", "weekly"] = "weekly"
    event_id: int | None = Field(default=None, ge=1)


def integration_freshness(
    last_seen: datetime | None,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> str:
    if last_seen is None:
        return "waiting"
    if stale_after_seconds < 1:
        raise ValueError("Güncellik eşiği pozitif olmalıdır")
    observed = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_seconds = (current - observed).total_seconds()
    return "warning" if age_seconds > stale_after_seconds else "ok"


@asynccontextmanager
async def lifespan(_: FastAPI):
    for warning in validate_security_config():
        logger.warning("Güvenlik uyarısı: %s", warning)
    store.initialize()
    if DEMO_MODE:
        salt, digest = hash_password(DEMO_PASSWORD)
        store.ensure_demo_owner(ADMIN_USERNAME, ADMIN_USERNAME, salt, digest)
        # Sample hives exist for the demo and only for the demo. A real panel starts with
        # nothing, so the first hive a beekeeper sees is one they added themselves.
        store.seed_sample_hives()
    # The demo account signs in whether or not demo mode is on, so the well-known password
    # it was seeded with is the panel's weakest point until someone changes it. Saying so
    # at every start is the price of keeping that account always reachable.
    elif any(user["demo_account"] for user in store.users()):
        logger.warning(
            "Güvenlik uyarısı: %s hesabı demo parolasıyla oluşturuldu ve hâlâ giriş "
            "yapabiliyor. Ayarlar → Hesap güvenliği bölümünden parolasını değiştirin.",
            ADMIN_USERNAME,
        )
    yield


app = FastAPI(title="Waggle API", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# Every asset link in the shells carries a ?v= marker that tells a browser its cached copy
# is stale. It used to be a number edited by hand beside each <link> and <script>, so a
# release could ship new code behind an old marker and every browser would keep serving the
# previous interface — the panel looked unchanged while the server had already changed.
# Forgetting is the normal case, so the marker is computed from the files themselves.
ASSET_MARKER = re.compile(r"(/static/[A-Za-z0-9_.\-]+)\?v=[A-Za-z0-9]+")
_asset_version: tuple[tuple[float, ...], str] | None = None


def asset_version() -> str:
    """A short digest of the shipped assets, recomputed only when one of them changes."""
    global _asset_version
    # Every asset the shells carry a ?v= marker for, not only the code: the illustrations
    # are versioned in the markup the same way, so leaving them out meant a replaced image
    # kept the previous release's marker and browsers kept serving the old one.
    static = BASE_DIR / "static"
    files = sorted(
        path for pattern in ("*.css", "*.js", "*.png", "*.svg") for path in static.glob(pattern)
    )
    stamps = tuple(path.stat().st_mtime_ns for path in files)
    if _asset_version and _asset_version[0] == stamps:
        return _asset_version[1]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.read_bytes())
    version = digest.hexdigest()[:10]
    _asset_version = (stamps, version)
    return version


def shell(name: str) -> Response:
    """One of the three HTML shells, with its asset markers pointing at what is on disk."""
    html = (BASE_DIR / "static" / name).read_text(encoding="utf-8")
    return Response(content=ASSET_MARKER.sub(rf"\1?v={asset_version()}", html),
                    media_type="text/html; charset=utf-8")


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


class OwnerSetupRequest(BaseModel):
    display_name: str
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordRecoveryRequest(BaseModel):
    username: str
    recovery_code: str
    new_password: str


class WorkerCreateRequest(BaseModel):
    display_name: str
    username: str
    password: str


class WorkerPasswordRequest(BaseModel):
    password: str


class WorkerStateRequest(BaseModel):
    active: bool


DEMO_MODE = os.getenv("WAGGLE_DEMO_MODE", "0") == "1"
DEMO_PASSWORD = os.getenv("WAGGLE_ADMIN_PASSWORD", "waggle-demo")
PUBLIC_PATHS = {
    "/login",
    "/setup",
    "/api/login",
    "/api/setup",
    "/api/setup-status",
    "/api/password-recovery",
    "/api/health",
    "/favicon.ico",
}
DEVICE_REQUESTS = {
    ("POST", "/api/events"),
    ("POST", "/api/reports"),
    ("GET", "/api/agent/events"),
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# What a field worker may change. Everything else that writes is the owner's: creating and
# deleting hives, pairing devices, panel settings, restoring a backup, managing accounts.
# The list is an allowlist on purpose — a new endpoint is owner-only until someone decides
# otherwise, rather than silently open to everyone.
WORKER_WRITE_PATHS = (
    re.compile(r"^/api/sensor-recordings$"),
    re.compile(r"^/api/hives/[^/]+/health-confirmations$"),
    re.compile(r"^/api/events/\d+/acknowledge$"),
    re.compile(r"^/api/reports/generate$"),
    re.compile(r"^/api/password$"),
    re.compile(r"^/api/recovery-code$"),
    re.compile(r"^/api/logout$"),
)
# While a temporary password is still in place the account is not yet one person, so it
# must not write anything attributable. Reading is harmless and keeps the panel usable
# enough to show the change-password prompt.
PASSWORD_CHANGE_PATHS = (
    re.compile(r"^/api/password$"),
    re.compile(r"^/api/logout$"),
)


def worker_may_write(path: str) -> bool:
    return any(pattern.match(path) for pattern in WORKER_WRITE_PATHS)


def _stamp_for(username: str) -> str:
    """The password stamp to mint a session with, empty for an account without a row."""
    account = store.user_account(username)
    return account["password_stamp"] if account else ""


def effective_account(username: str) -> dict | None:
    """The account behind a session, or None when the username has no row of its own."""
    return store.user_account(username)


def is_cross_site_request(origin: str | None, fetch_site: str | None, expected: str) -> bool:
    """Reject browser mutations coming from another site without blocking devices."""
    if fetch_site == "cross-site":
        return True
    return bool(origin) and origin.rstrip("/") != expected.rstrip("/")


def is_device_request(method: str, path: str) -> bool:
    return (method.upper(), path) in DEVICE_REQUESTS


def security_headers(path: str) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    if path not in {"/docs", "/redoc", "/openapi.json"}:
        headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
    # The panel shell carries the ?v= markers that invalidate the stylesheet and script,
    # so caching it defeats the whole scheme: a cached shell keeps asking for the previous
    # version of every asset and the interface silently stays one release behind.
    if path.startswith("/api/") or path in {"/", "/login", "/setup"}:
        headers["Cache-Control"] = "no-store"
    return headers


@app.middleware("http")
async def browser_security(request: Request, call_next):
    expected_origin = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    if request.method in UNSAFE_METHODS and is_cross_site_request(
        request.headers.get("origin"),
        request.headers.get("sec-fetch-site"),
        expected_origin,
    ):
        response = JSONResponse({"detail": "Çapraz site isteği reddedildi"}, status_code=403)
    else:
        response = await call_next(request)
    for name, value in security_headers(request.url.path).items():
        response.headers[name] = value
    return response


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)
    session = read_session_details(request.cookies.get(COOKIE_NAME))
    if session:
        username, stamp = session
        # Sessions are signed tokens with no server-side record, so this lookup is what
        # makes deactivating a worker take effect now instead of whenever their cookie
        # happens to expire.
        account = effective_account(username)
        if account is not None and not account["active"]:
            return _rejected(path, "Hesabınız devre dışı bırakıldı.", 401)
        # Someone who changed their password — or had it reset for them, after losing the
        # laptop it was signed in on — expects that to end the other sessions. Without this
        # the old cookie keeps working until it expires on its own.
        if account is not None and stamp != account["password_stamp"]:
            return _rejected(path, "Parolanız değişti; lütfen yeniden giriş yapın.", 401)
        request.state.username = username
        request.state.account = account
        if request.method in UNSAFE_METHODS and account is not None:
            if account["must_change_password"] and not any(
                pattern.match(path) for pattern in PASSWORD_CHANGE_PATHS
            ):
                return JSONResponse(
                    {"detail": "Devam etmek için önce parolanızı değiştirin."}, status_code=403
                )
            if account["role"] == "worker" and not worker_may_write(path):
                return JSONResponse(
                    {"detail": "Bu işlem için yetkiniz yok. Kovanlık sahibine başvurun."},
                    status_code=403,
                )
        return await call_next(request)
    if (
        is_device_request(request.method, path)
        and verify_device_key(request.headers.get(DEVICE_KEY_HEADER))
    ):
        request.state.device_authenticated = True
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Oturum açmanız gerekiyor"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


def _rejected(path: str, detail: str, status_code: int) -> Response:
    if path.startswith("/api/"):
        return JSONResponse({"detail": detail}, status_code=status_code)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/login", include_in_schema=False)
def login_page(request: Request) -> Response:
    if read_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)
    # A panel with no account yet cannot be signed in to, and the sign-in screen offering
    # "Tekrar hoş geldiniz" to someone who has never been here is the first thing a new
    # installation showed. The one thing they can do is the one they are sent to.
    if not store.has_users() and not DEMO_MODE:
        return RedirectResponse("/setup", status_code=303)
    return shell("login.html")


@app.get("/setup", include_in_schema=False)
def setup_page(request: Request) -> Response:
    if read_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)
    if store.has_users():
        return RedirectResponse("/login", status_code=303)
    return shell("setup.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return FileResponse(BASE_DIR / "static" / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/setup-status")
def setup_status() -> dict[str, object]:
    # A demo server never *demands* setup — it goes straight to the login screen with the
    # built-in demo account — but the setup page stays reachable so a real owner account
    # can be registered alongside it and shown as the normal, non-demo channel.
    return {
        "setup_required": not store.has_users() and not DEMO_MODE,
        "setup_available": not store.has_users(),
        "demo_mode": DEMO_MODE,
        "demo_username": ADMIN_USERNAME if DEMO_MODE else "",
    }


def credentials_are_valid(username: str, password: str) -> bool:
    stored = store.user_credentials(username)
    if stored is not None:
        _, password_salt, password_hash = stored
        return verify_password(password, password_salt, password_hash)
    return DEMO_MODE and verify_credentials(username, password)


@app.post("/api/login")
def login(credentials: LoginRequest, request: Request) -> Response:
    client_id = request.client.host if request.client else "unknown"
    retry_after = login_attempt_guard.retry_after(client_id)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla başarısız giriş denemesi. Lütfen kısa süre sonra tekrar deneyin.",
            headers={"Retry-After": str(retry_after)},
        )
    if not credentials_are_valid(credentials.username, credentials.password):
        login_attempt_guard.record_failure(client_id)
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya parola hatalı")
    account = store.user_account(credentials.username)
    if account is not None and not account["active"]:
        raise HTTPException(
            status_code=403, detail="Bu hesap devre dışı. Kovanlık sahibine başvurun."
        )
    login_attempt_guard.reset(client_id)
    session_seconds = REMEMBERED_SESSION_SECONDS if credentials.remember else SESSION_SECONDS
    response = JSONResponse({"username": credentials.username})
    response.set_cookie(
        COOKIE_NAME,
        create_session(credentials.username, session_seconds, _stamp_for(credentials.username)),
        max_age=session_seconds,
        httponly=True,
        samesite="lax",
        secure=os.getenv("WAGGLE_SECURE_COOKIE", "0") == "1",
    )
    return response


@app.post("/api/setup", status_code=201)
def create_owner_account(payload: OwnerSetupRequest, request: Request) -> Response:
    if store.has_users():
        raise HTTPException(status_code=409, detail="İlk kurulum zaten tamamlanmış")
    display_name = payload.display_name.strip()
    username = payload.username.strip()
    if len(display_name) < 2 or len(display_name) > 80:
        raise HTTPException(status_code=422, detail="Ad 2–80 karakter olmalıdır")
    if not (3 <= len(username) <= 32) or not username.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(
            status_code=422,
            detail="Kullanıcı adı 3–32 karakter olmalı; yalnızca harf, rakam, - ve _ içermelidir",
        )
    if len(payload.password) < 10 or len(payload.password) > 128:
        raise HTTPException(status_code=422, detail="Parola en az 10 karakter olmalıdır")
    password_salt, password_hash = hash_password(payload.password)
    try:
        store.create_owner(display_name, username, password_salt, password_hash)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = JSONResponse({"username": username, "display_name": display_name}, status_code=201)
    response.set_cookie(
        COOKIE_NAME,
        create_session(username, stamp=_stamp_for(username)),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.getenv("WAGGLE_SECURE_COOKIE", "0") == "1",
    )
    return response


@app.post("/api/password", status_code=204)
def change_password(payload: PasswordChangeRequest, request: Request) -> Response:
    """Change the signed-in account's password.

    There is no e-mail on a local panel, so there is no reset flow either: the current
    password is the only proof of ownership and it is always required.
    """
    # The built-in demo account lives in the environment, not the database.
    username, stored = stored_account(request)
    _, password_salt, password_hash = stored
    if not verify_password(payload.current_password, password_salt, password_hash):
        raise HTTPException(status_code=403, detail="Mevcut parola hatalı")
    if len(payload.new_password) < 10 or len(payload.new_password) > 128:
        raise HTTPException(status_code=422, detail="Yeni parola en az 10 karakter olmalıdır")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=422, detail="Yeni parola mevcut parolayla aynı olamaz")
    new_salt, new_hash = hash_password(payload.new_password)
    # Choosing their own password is what turns a handed-over account into one person.
    if not store.set_user_password(username, new_salt, new_hash, must_change=False):
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    # Every session opened with the old password is now stale, this one included, so the
    # person who just chose the password gets a fresh cookie rather than a sign-in screen.
    response = Response(status_code=204)
    response.set_cookie(
        COOKIE_NAME,
        create_session(username, stamp=_stamp_for(username)),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.getenv("WAGGLE_SECURE_COOKIE", "0") == "1",
    )
    return response


def require_owner(request: Request) -> str:
    """Only the apiary owner manages accounts."""
    account = getattr(request.state, "account", None)
    if account is None or account["role"] != "owner":
        raise HTTPException(status_code=403, detail="Bu işlem için yetkiniz yok.")
    return account["username"]


def validated_account_fields(display_name: str, username: str, password: str) -> tuple[str, str]:
    display_name, username = display_name.strip(), username.strip()
    if len(display_name) < 2 or len(display_name) > 80:
        raise HTTPException(status_code=422, detail="Ad 2–80 karakter olmalıdır")
    if not (3 <= len(username) <= 32) or not username.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(
            status_code=422,
            detail="Kullanıcı adı 3–32 karakter olmalı; yalnızca harf, rakam, - ve _ içermelidir",
        )
    if len(password) < 10 or len(password) > 128:
        raise HTTPException(status_code=422, detail="Parola en az 10 karakter olmalıdır")
    return display_name, username


@app.get("/api/users")
def list_users(request: Request) -> list[dict]:
    require_owner(request)
    return store.users()


@app.post("/api/users", status_code=201)
def create_worker(payload: WorkerCreateRequest, request: Request) -> dict:
    """Create a field worker account with a temporary password the owner hands over."""
    require_owner(request)
    display_name, username = validated_account_fields(
        payload.display_name, payload.username, payload.password
    )
    password_salt, password_hash = hash_password(payload.password)
    try:
        store.add_worker(display_name, username, password_salt, password_hash)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"username": username, "display_name": display_name, "role": "worker"}


@app.post("/api/users/{username}/password", status_code=204)
def reset_worker_password(
    username: str, payload: WorkerPasswordRequest, request: Request
) -> Response:
    """The everyday recovery path: the worker forgot, the owner issues a new password."""
    owner = require_owner(request)
    account = store.user_account(username)
    if account is None or account["role"] != "worker":
        raise HTTPException(status_code=404, detail="Çalışan hesabı bulunamadı")
    if account["username"].lower() == owner.lower():
        raise HTTPException(status_code=409, detail="Kendi parolanızı buradan değiştiremezsiniz")
    if len(payload.password) < 10 or len(payload.password) > 128:
        raise HTTPException(status_code=422, detail="Parola en az 10 karakter olmalıdır")
    password_salt, password_hash = hash_password(payload.password)
    store.set_user_password(account["username"], password_salt, password_hash, must_change=True)
    return Response(status_code=204)


@app.patch("/api/users/{username}", status_code=204)
def set_worker_state(username: str, payload: WorkerStateRequest, request: Request) -> Response:
    owner = require_owner(request)
    if username.lower() == owner.lower():
        raise HTTPException(status_code=409, detail="Kendi hesabınızı devre dışı bırakamazsınız")
    if not store.set_user_active(username, payload.active):
        raise HTTPException(status_code=404, detail="Çalışan hesabı bulunamadı")
    return Response(status_code=204)


def stored_account(request: Request) -> tuple[str, tuple[str, str, str]]:
    """The signed-in account's row, or a clear refusal for the env-based demo account."""
    username = getattr(request.state, "username", None)
    stored = store.user_credentials(username) if username else None
    if stored is None:
        raise HTTPException(
            status_code=409,
            detail="Bu hesap panelden yönetilemez. Kendi hesabınızla giriş yapın.",
        )
    return username, stored


@app.get("/api/recovery-code")
def recovery_code_state(request: Request) -> dict[str, object]:
    username, _ = stored_account(request)
    configured, created_at = store.recovery_code_state(username)
    return {"configured": configured, "created_at": created_at.isoformat() if created_at else None}


@app.post("/api/recovery-code", status_code=201)
def create_recovery_code(request: Request) -> dict[str, str]:
    """Generate a recovery code and return it exactly once.

    Only the hash is stored, so a lost code cannot be looked up — it can only be
    replaced. Generating a new one immediately invalidates the previous code.
    """
    username, _ = stored_account(request)
    code = generate_recovery_code()
    code_salt, code_hash = hash_password(normalize_recovery_code(code))
    created_at = store.set_recovery_code(username, code_salt, code_hash)
    if created_at is None:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    return {"code": code, "created_at": created_at}


@app.post("/api/password-recovery", status_code=204)
def recover_password(payload: PasswordRecoveryRequest, request: Request) -> Response:
    """Set a new password using the single-use recovery code.

    This is a second door on a page anyone can reach, so it is rate limited by the same
    guard as the login form and answers with one message whether the account, the code or
    nothing at all was wrong — otherwise it would confirm which usernames exist.
    """
    client_id = request.client.host if request.client else "unknown"
    retry_after = login_attempt_guard.retry_after(client_id)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Çok fazla başarısız deneme. Lütfen kısa süre sonra tekrar deneyin.",
            headers={"Retry-After": str(retry_after)},
        )
    if len(payload.new_password) < 10 or len(payload.new_password) > 128:
        raise HTTPException(status_code=422, detail="Yeni parola en az 10 karakter olmalıdır")
    rejected = HTTPException(status_code=403, detail="Kullanıcı adı veya kurtarma kodu hatalı")
    stored = store.recovery_credentials(payload.username)
    if stored is None:
        login_attempt_guard.record_failure(client_id)
        raise rejected
    code_salt, code_hash = stored
    if not verify_password(normalize_recovery_code(payload.recovery_code), code_salt, code_hash):
        login_attempt_guard.record_failure(client_id)
        raise rejected
    password_salt, password_hash = hash_password(payload.new_password)
    if not store.consume_recovery_code(payload.username, password_salt, password_hash):
        login_attempt_guard.record_failure(client_id)
        raise rejected
    login_attempt_guard.reset(client_id)
    return Response(status_code=204)


@app.post("/api/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/api/me")
def current_user(request: Request) -> dict[str, object]:
    username = getattr(request.state, "username", ADMIN_USERNAME)
    stored = store.user_credentials(username)
    # Demo is a property of the account, not the server. Only the built-in demo account
    # gets the demo channel — enrollment normally takes weeks, so it plays the finished
    # profile on the first recording. Every registered owner stays on the real panel.
    account = effective_account(username)
    return {
        "username": username,
        "display_name": stored[0] if stored else username,
        "demo_mode": bool(DEMO_MODE and account and account["demo_account"]),
        "role": account["role"] if account else "owner",
        "must_change_password": bool(account and account["must_change_password"]),
        "manages_accounts": bool(account and account["role"] == "owner"),
    }


@app.get("/", include_in_schema=False)
def panel() -> FileResponse:
    return shell("index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/guidance")
def guidance_notes(
    language: Literal["tr", "en"] = "tr",
    ids: str | None = Query(default=None, max_length=500),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    """The reviewed local notes a report was grounded in.

    A report stores only the ids of the passages it used. The panel needs their text to
    show what the assessment actually rested on — an assessment you cannot trace back to
    its sources is just an opinion with a logo on it.

    `q` runs the same retriever a report is grounded with, so searching the base and
    grounding a report rank passages identically. The panel used to filter the list with a
    plain substring match, which meant the one place a person can inspect the knowledge
    base behaved unlike the retrieval it was there to explain.
    """
    from brain.local_rag import guidance_category, guidance_title, load_knowledge, search_guidance

    entries = {entry["id"]: entry for entry in load_knowledge()}

    def presented(entry: dict) -> dict:
        # The note's own name and subject, not the retriever's index. The id still travels
        # because a report cites it, but it is no longer the only thing a reader is given.
        return {
            "id": entry["id"],
            "title": guidance_title(entry, language),
            "category": guidance_category(entry, language),
            "text": entry[language],
            "tags": entry["tags"],
        }

    if q and q.strip():
        return [
            presented(entries[found["id"]])
            for found in search_guidance(q.strip(), language, limit=limit)
            if found["id"] in entries
        ]

    wanted = {item.strip() for item in ids.split(",") if item.strip()} if ids else None
    return [presented(entry) for entry in entries.values() if wanted is None or entry["id"] in wanted]


@app.get("/api/events/{event_id}/guidance")
def event_guidance(
    event_id: int,
    language: Literal["tr", "en"] = "tr",
    limit: int = Query(default=2, ge=1, le=5),
) -> list[dict]:
    """The local notes that fit one event.

    Retrieval was reachable only through report generation, so an alarm sitting on the
    screen carried no guidance until a weekly report was written about it. The same
    retriever, given the single event, answers immediately and without a model.
    """
    from brain.local_rag import retrieve_guidance

    event = store.event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Olay bulunamadı")
    return retrieve_guidance([event.model_dump()], language, limit=limit)


def _resolved(path: Path) -> Path:
    return path if path.is_absolute() else BASE_DIR.parent.parent / path


def onnx_parity() -> dict | None:
    """The recorded joblib-versus-ONNX decision comparison for the reference model.

    The export refuses to write a model whose decisions differ, so this file is the
    evidence that the conversion preserved them. It existed in the repository and was
    shown nowhere, which left the panel's strongest verifiable claim unstated.
    """
    try:
        report = json.loads(ONNX_PARITY_REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or not report.get("verified"):
        return None
    # The row count is read out of a file on disk, so it is coerced here rather than where
    # it is formatted: a hand-edited or half-written report must leave the status page
    # saying "not verified", never raise out of it.
    try:
        rows = int(report["verification_rows"])
    except (KeyError, TypeError, ValueError):
        return None
    return {**report, "verification_rows": rows} if rows > 0 else None


def acoustic_model_status() -> ComponentStatus:
    """Whether the model that decides every event is actually there.

    The component carrying this name only ever checked how recently an event arrived, so a
    deleted or unreadable model file left the panel reporting a healthy acoustic pipeline
    right up until the next recording failed.
    """
    missing: list[str] = []
    packaged = _resolved(SENSOR_MODEL_PATH)
    if not packaged.exists():
        missing.append(SENSOR_MODEL_PATH.name)
    profiles = store.monitoring_profiles()
    for profile in profiles:
        # Path("") resolves to the directory the panel runs from, which exists — so an
        # empty model path would read as a healthy model rather than a missing one.
        stored = (profile["model_path"] or "").strip()
        if not stored or not _resolved(Path(stored)).exists():
            missing.append(f'{profile["hive_id"]}: {Path(stored).name if stored else "—"}')

    # A parity report is returned only when it is complete and says the decisions matched,
    # so its presence is the whole question here.
    parity = onnx_parity()
    parity_part = (
        f'referans modelde {parity["verification_rows"]} satırda karar eşleşmesi doğrulandı'
        if parity else "karar eşleşmesi raporu bulunamadı"
    )
    hives_part = f"{len(profiles)} kovan kendi profiliyle izleniyor"
    # A profile is published only after its ONNX conversion is compared with the joblib
    # model it came from, so a stored comparison is the per-hive counterpart of the
    # reference model's parity report. Said only when there is one to say.
    verified = [profile for profile in profiles if (profile["verification"] or {}).get("different_decisions") == 0]
    facts = [hives_part]
    if verified:
        facts.append(f"{len(verified)}/{len(profiles)} kovan profili karar eşleşmesiyle doğrulandı")

    if missing:
        return ComponentStatus(
            key="acoustic-model", name="Akustik model (ONNX)", status="warning",
            summary="Akustik model dosyası eksik",
            detail=" · ".join([f'model dosyası bulunamadı: {", ".join(missing)}', parity_part, *facts]),
        )
    return ComponentStatus(
        key="acoustic-model", name="Akustik model (ONNX)",
        # A model that is present but whose conversion was never verified is a weaker
        # claim than one that was, and the panel should not present them identically.
        status="ok" if parity else "waiting",
        summary="Akustik model hazır" if parity else "Karar eşleşmesi doğrulanmadı",
        detail=" · ".join(["ONNX Runtime", parity_part, *facts]),
    )


@app.get("/api/system-status", response_model=SystemStatus)
def system_status() -> SystemStatus:
    diagnostics = store.diagnostics()
    counts = diagnostics["counts"]
    last_event = diagnostics["last_event_at"]
    last_report = diagnostics["last_report_at"]
    database_ok = diagnostics["integrity"] == "ok"
    device_status = integration_freshness(last_event, DEVICE_STALE_SECONDS)
    report_status = integration_freshness(last_report, REPORT_STALE_SECONDS)
    device_messages = {
        "ok": ("Canlı veri alınıyor", "Kovan cihazları kayıtları panele göndermeye devam ediyor."),
        "waiting": ("İlk veri bekleniyor", "Kovan cihazı ilk kaydı gönderdiğinde bağlantı zamanı burada görünecek."),
        "warning": ("Cihaz verisi gecikiyor", "Beklenen aralıkta yeni kayıt gelmedi; zincir burada duruyor."),
    }
    report_messages = {
        "ok": ("Rapor entegrasyonu çalışıyor", "Üretilen değerlendirme raporları panele kaydediliyor."),
        "waiting": ("İlk rapor bekleniyor", "İlk haftalık değerlendirme gönderildiğinde burada son rapor zamanı görünecek."),
        "warning": ("Rapor güncel değil", "Son haftalık değerlendirme beklenen süreden eski. Rapor üretim akışını kontrol edin."),
    }
    device_remedies = {
        "waiting": ["Kovana bir dinleme cihazı ekleyin", "Kovanlarım sayfasından ilk kaydı gönderin"],
        "warning": ["Kovan cihazının açık ve şarjlı olduğunu doğrulayın",
                    "Cihazın yerel ağa bağlı olduğunu kontrol edin",
                    "Kovanlarım sayfasından elle bir kayıt göndererek zinciri sınayın"],
    }
    report_remedies = {
        "waiting": ["Raporlar sayfasından ilk değerlendirmeyi üretin"],
        "warning": ["Foundry Local sunucusunun çalıştığını doğrulayın",
                    "Raporlar sayfasından elle bir rapor üretmeyi deneyin",
                    "Sunucu günlüğünde model çağrısının hatasına bakın"],
    }
    # The order is the chain the data actually travels, not a layout choice: a microphone
    # records, the ONNX profile decides, the decision is stored, the report engine reads it
    # and the panel shows it. Returned in that order so a reader can see where it stopped
    # rather than which tile happens to be red.
    components = [
        ComponentStatus(key="device", name="Kovan cihazları", status=device_status,
                        summary=device_messages[device_status][0], detail=device_messages[device_status][1],
                        last_seen_at=last_event, stale_after_seconds=DEVICE_STALE_SECONDS,
                        remedies=device_remedies.get(device_status, []), has_history=True),
        acoustic_model_status(),
        ComponentStatus(key="database", name="Veri kayıt sistemi", status="ok" if database_ok else "warning",
                        summary="Veritabanı sağlam" if database_ok else "Veritabanını kontrol edin",
                        detail=f'{counts["hives"]} kovan, {counts["events"]} olay ve {counts["reports"]} rapor kayıtlı.',
                        remedies=[] if database_ok else [
                            "Dışa Aktar sayfasından hemen bir SQLite yedeği alın",
                            "Sağlam bir yedekten geri yükleyin"]),
        ComponentStatus(key="reports", name="Haftalık yapay zekâ raporları", status=report_status,
                        summary=report_messages[report_status][0], detail=report_messages[report_status][1],
                        last_seen_at=last_report, stale_after_seconds=REPORT_STALE_SECONDS,
                        remedies=report_remedies.get(report_status, []), has_history=True),
        ComponentStatus(key="panel", name="Waggle paneli", status="ok", summary="Panel çalışıyor",
                        detail="Kullanıcı arayüzü ve API istekleri yanıt veriyor."),
    ]
    return SystemStatus(overall="ok" if all(item.status == "ok" for item in components) else "attention", components=components)


# A recording can only be stamped with the weather of roughly the moment it was taken.
# An event posted for a timestamp further back than this gets no weather at all, because
# the current conditions are not the conditions it was recorded in.
WEATHER_STAMP_WINDOW = timedelta(minutes=30)


def observed_weather() -> WeatherState | None:
    """Current conditions, or None when the operator has weather off or the service is unreachable.

    Stamping must never cost an event: a recording is worth keeping without its weather.
    The privacy setting is the part that is not negotiable, and it is enforced where it
    already was — inside the endpoint this delegates to, so weather off means nothing
    leaves the device here either.
    """
    try:
        return weather()
    except HTTPException:
        return None


def with_conditions(event: HiveEventIn) -> HiveEventIn:
    """The event, carrying the conditions it was recorded in when those can be known.

    Values the caller already sent win: an edge device that read its own sensor knows the
    hive's own air better than the panel's single configured coordinate does.
    """
    already = (event.temperature_c, event.humidity_percent, event.wind_kmh, event.weather_code)
    if any(value is not None for value in already):
        return event
    recorded_at = event.timestamp
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    if abs(datetime.now(timezone.utc) - recorded_at) > WEATHER_STAMP_WINDOW:
        return event
    current = observed_weather()
    if current is None:
        return event
    return event.model_copy(update={
        "temperature_c": current.temperature_c,
        "humidity_percent": current.humidity_percent,
        "wind_kmh": current.wind_kmh,
        "weather_code": current.weather_code,
    })


@app.post("/api/events", response_model=HiveEvent, status_code=201)
def create_event(event: HiveEventIn) -> HiveEvent:
    if not store.has_hive(event.hive_id):
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    try:
        return store.add(with_conditions(event))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Olay kaydedilemedi") from exc


@app.get("/api/events", response_model=list[HiveEvent])
def list_events(limit: int = Query(default=50, ge=1, le=500)) -> list[HiveEvent]:
    return store.recent(limit)


@app.get("/api/agent/events", response_model=list[HiveEvent], include_in_schema=False)
def list_agent_events(limit: int = Query(default=200, ge=1, le=500)) -> list[HiveEvent]:
    """Read-only event feed for the authenticated local report agent."""
    return store.recent(limit)


@app.post("/api/events/{event_id}/acknowledge", response_model=HiveEvent)
def acknowledge_event(
    event_id: int, request: Request, inspection: AlarmInspectionIn | None = None
) -> HiveEvent:
    event = store.acknowledge(
        event_id,
        inspection.result if inspection else None,
        inspection.note if inspection else None,
        acknowledged_by=getattr(request.state, "username", None),
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Olay bulunamadı")
    return event


@app.get("/api/dashboard", response_model=DashboardState)
def dashboard() -> DashboardState:
    return DashboardState(hives=store.summaries(), events=store.recent(30))


@app.post("/api/sensor-recordings", response_model=SensorAnalysis, status_code=201)
async def analyze_sensor_recording(
    request: Request,
    hive_id: str = Query(pattern=r"^H[1-9][0-9]{0,2}$"),
    device_id: str = Query(min_length=4, max_length=40),
    filename: str = Query(default="phone-recording.wav", max_length=120),
) -> SensorAnalysis:
    """Collect enrollment audio or analyze it once the hive profile is ready."""
    if not store.has_hive(hive_id):
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_SENSOR_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Ses kaydı izin verilen boyutu aşıyor")
    contents = await request.body()
    if not contents or len(contents) > MAX_SENSOR_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Ses kaydı boş veya çok büyük")
    if len(contents) < 44 or contents[:4] != b"RIFF" or contents[8:12] != b"WAVE":
        raise HTTPException(status_code=415, detail="Ses kaydı WAV biçimine dönüştürülemedi")
    uploaded = tempfile.NamedTemporaryFile(prefix="waggle-phone-", suffix=".wav", delete=False)
    uploaded_path = Path(uploaded.name)
    try:
        uploaded.write(contents)
        uploaded.close()
        from ear.wav_isolation_monitor import analyze_wav, wav_features

        profile = store.enrollment_status(hive_id)
        safe_name = Path(filename).name or "phone-recording.wav"
        if not any(device.device_id == device_id and device.active for device in store.devices(hive_id)):
            raise HTTPException(status_code=404, detail="Cihaz bu kovana bağlı değil")
        if not profile.can_monitor:
            if profile.confirmation_due:
                raise HTTPException(status_code=422, detail="Yeni bir saha sağlık doğrulaması gerekiyor")
            values, feature_names = wav_features(uploaded_path)
            progress = store.add_enrollment_recording(hive_id, device_id, safe_name, values, feature_names)
            training_error = None
            if progress.ready_to_train:
                from ear.profile_training import train_verified_profile

                try:
                    training_values, training_names = store.enrollment_features(hive_id)
                    onnx_path = HIVE_PROFILE_DIR / f"{hive_id}.onnx"
                    # Training refuses to publish a profile whose ONNX decisions differ
                    # from the joblib ones it was converted from, and returned the
                    # comparison to a caller that dropped it. It is the evidence behind
                    # this hive's own model, so it is stored with the profile.
                    verification = train_verified_profile(
                        training_values, training_names, hive_id,
                        HIVE_PROFILE_DIR / f"{hive_id}.joblib", onnx_path,
                    )
                    progress = store.activate_profile(hive_id, str(onnx_path), verification)
                except Exception as error:  # noqa: BLE001 - recording is kept either way
                    # Reporting success while training failed hides the fault behind a
                    # full progress bar, so the reason travels back with the response.
                    logger.exception("Kovana özel profil oluşturulamadı: %s", hive_id)
                    training_error = str(error) or type(error).__name__
            if progress.can_monitor:
                note = "Kovana özel profil doğrulandı ve izleme etkinleştirildi. Bundan sonraki kayıtlar WATCH/ALARM akışında değerlendirilir."
            elif training_error:
                note = f"Kayıt alındı ancak model eğitimi tamamlanamadı: {training_error}"
            else:
                note = (
                    f"Sağlıklı başlangıç kaydı eklendi: {progress.recording_count}/{progress.required_recordings} kayıt, "
                    f"{progress.recording_days}/{progress.required_days} gün. Profil hazır olana kadar alarm üretilmez."
                )
            return SensorAnalysis(
                mode="enrollment", windows=len(values),
                model=Path(progress.model_path).name if progress.model_path else None,
                note=note,
            )
        model_path = Path(profile.model_path) if profile.model_path else SENSOR_MODEL_PATH
        if not model_path.is_absolute():
            model_path = BASE_DIR.parent.parent / model_path
        if not model_path.exists():
            raise HTTPException(status_code=503, detail="ONNX sensör modeli bulunamadı")

        # This hive's own last event, not the newest few hundred across the apiary. A hive
        # that had been quiet while its neighbours recorded fell out of that window, and
        # the run of consecutive anomalies behind WATCH and ALARM silently restarted at
        # zero — in the one place where the whole claim is that the change persisted.
        previous = store.latest_event(hive_id)
        initial_run = previous.consecutive_anomalies if previous else 0
        result = analyze_wav(model_path, uploaded_path, initial_run)
        store.touch_device(device_id)
        event = store.add(with_conditions(HiveEventIn(
            hive_id=hive_id,
            timestamp=datetime.now(timezone.utc),
            status=result["status"],
            anomaly_fraction=result["anomaly_fraction"],
            # Null when this hive's profile predates the stored decision offset; the ratio
            # is still measured, only the depth behind it is unavailable.
            anomaly_severity=result["anomaly_severity"],
            consecutive_anomalies=result["consecutive_anomalies"],
            source_file=f"phone:{safe_name}",
            # The event carries the ONNX profile that decided it: a report reading these
            # rows can then say which model measured them, not only which one wrote about them.
            model=model_path.name,
        )))
        return SensorAnalysis(
            mode="monitoring", event=event,
            windows=result["windows"],
            model=model_path.name,
            note="Bu sonuç kesin teşhis değildir; WATCH veya ALARM fiziksel kontrol gerektirir.",
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=f"Ses kaydı analiz edilemedi: {exc}") from exc
    finally:
        uploaded.close()
        uploaded_path.unlink(missing_ok=True)


@app.get("/api/hives/{hive_id}/devices", response_model=list[Device])
def list_hive_devices(hive_id: str) -> list[Device]:
    if not store.has_hive(hive_id):
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    return store.devices(hive_id)


@app.post("/api/hives/{hive_id}/devices", response_model=Device, status_code=201)
def create_hive_device(hive_id: str, device: DeviceCreate) -> Device:
    if not store.has_hive(hive_id):
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    try:
        return store.add_device(hive_id, device)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/hives/enrollment", response_model=dict[str, EnrollmentStatus])
def list_hive_enrollment(include_inactive: bool = False) -> dict[str, EnrollmentStatus]:
    """Enrollment for every hive at once, so the management list can show progress
    without one request per row."""
    return {hive.hive_id: store.enrollment_status(hive.hive_id) for hive in store.hives(include_inactive=include_inactive)}


@app.get("/api/hives/{hive_id}/enrollment", response_model=EnrollmentStatus)
def get_hive_enrollment(hive_id: str) -> EnrollmentStatus:
    if not store.has_hive(hive_id):
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    return store.enrollment_status(hive_id)


@app.post("/api/hives/{hive_id}/health-confirmations", response_model=HealthConfirmation, status_code=201)
def create_health_confirmation(
    hive_id: str, confirmation: HealthConfirmationIn, request: Request
) -> HealthConfirmation:
    if not store.has_hive(hive_id):
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    status = store.enrollment_status(hive_id)
    if status.state != "enrolling":
        raise HTTPException(status_code=409, detail="Saha doğrulaması yalnızca öğrenme döneminde eklenebilir")
    if confirmation.evidence != "uncertain" and not status.confirmation_due:
        raise HTTPException(status_code=409, detail="Yeni saha doğrulaması henüz gerekli değil")
    return store.add_health_confirmation(
        hive_id, confirmation, confirmed_by=getattr(request.state, "username", None)
    )


@app.get("/api/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    return AppSettings(**store.settings())


@app.put("/api/settings", response_model=AppSettings)
def update_settings(settings: AppSettings) -> AppSettings:
    global weather_cache
    cleaned = settings.model_copy(update={
        "panel_name": settings.panel_name.strip(),
        "location_name": settings.location_name.strip(),
    })
    # Only the fields the caller actually sent are written. The coordinates arrived after
    # the first clients did, and a body written without them would otherwise be read as
    # asking for the model's defaults — quietly moving the apiary to another town.
    provided = set(settings.model_fields_set)
    payload = {
        **store.settings(),
        **{name: value for name, value in cleaned.model_dump().items() if name in provided},
    }
    saved = AppSettings(**store.update_settings(payload))
    weather_cache = None
    return saved


@app.get("/api/hives", response_model=list[Hive])
def list_hives(include_inactive: bool = False) -> list[Hive]:
    return store.hives(include_inactive=include_inactive)


@app.post("/api/hives", response_model=Hive, status_code=201)
def create_hive(hive: HiveCreate) -> Hive:
    try:
        return store.add_hive(hive)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/hives/{hive_id}", response_model=Hive)
def update_hive(hive_id: str, hive: HiveUpdate) -> Hive:
    updated = store.update_hive(hive_id, hive)
    if updated is None:
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    return updated


@app.post("/api/hives/{hive_id}/archive", response_model=Hive)
def archive_hive(hive_id: str) -> Hive:
    updated = store.set_hive_active(hive_id, False)
    if updated is None:
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    return updated


@app.get("/api/hives/{hive_id}/footprint")
def hive_delete_footprint(hive_id: str) -> dict:
    footprint = store.hive_footprint(hive_id)
    if footprint is None:
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    return {"hive_id": hive_id, "name": footprint["hive"].name, "active": footprint["hive"].active, "events": footprint["events"], "devices": footprint["devices"]}


@app.delete("/api/hives/{hive_id}", status_code=200)
def delete_hive(hive_id: str) -> dict:
    footprint = store.hive_footprint(hive_id)
    if footprint is None:
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    # Archiving first is a deliberate speed bump: a live hive cannot be destroyed by one click.
    if footprint["hive"].active:
        raise HTTPException(status_code=409, detail="Önce kovanı arşivleyin, sonra kalıcı olarak silin")
    removed = store.delete_hive(hive_id)
    # The trained profile is the one part of a hive that lives outside the database. It was
    # left on disk under the hive's id, so the next hive to be given that id would be
    # monitored by the deleted colony's model until its own was trained over it.
    model_path = removed.pop("model_path", "")
    artefacts = {HIVE_PROFILE_DIR / f"{hive_id}.onnx", HIVE_PROFILE_DIR / f"{hive_id}.joblib"}
    if model_path:
        # The stored path wins where it differs: a profile trained before the directory
        # was reconfigured still sits wherever it was written.
        recorded = _resolved(Path(model_path))
        artefacts |= {recorded, recorded.with_suffix(".joblib")}
    for artefact in artefacts:
        try:
            artefact.unlink(missing_ok=True)
        except OSError:
            logger.warning("Kovan profili silinemedi: %s", artefact)
    logger.warning("Hive %s deleted permanently (%s events, %s devices)", hive_id, removed["events"], removed["devices"])
    return {"hive_id": hive_id, "deleted": True, **removed}


@app.post("/api/hives/{hive_id}/restore", response_model=Hive)
def restore_hive(hive_id: str) -> Hive:
    updated = store.set_hive_active(hive_id, True)
    if updated is None:
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    return updated


@app.post("/api/reports", response_model=Report, status_code=201)
def create_report(report: ReportIn) -> Report:
    if report.period_end < report.period_start:
        raise HTTPException(status_code=422, detail="Rapor bitişi başlangıçtan önce olamaz")
    return store.add_report(report)


@app.get("/api/reports", response_model=list[Report])
def list_reports(limit: int = Query(default=10, ge=1, le=100)) -> list[Report]:
    return store.reports(limit)


def _run_report_generation(panel_url: str, report_type: str, event_id: int | None) -> None:
    """Generate a report through the brain pipeline and record the outcome."""
    try:
        from brain.foundry_report import model_device
        from brain.weekly_agent import run_period_report

        # Read once, at the start: the catalogue lookup shells out to the Foundry CLI, and
        # the status endpoint is polled every few seconds while the run is in progress.
        REPORT_GENERATION["device"] = model_device(LLM_MODEL)

        def written(characters: int) -> None:
            # The count alone cannot say whether a run is stalled: it only ever grows, so
            # one character written early would clear the flag for the rest of the run.
            # When it last grew is the fact that answers the question.
            REPORT_GENERATION["written_characters"] = characters
            REPORT_GENERATION["written_at"] = datetime.now(timezone.utc).isoformat()

        created = run_period_report(
            panel_url,
            DEVICE_KEY,
            LLM_MODEL,
            report_type=report_type,
            event_id=event_id,
            on_progress=written,
        )
        REPORT_GENERATION.update(
            running=False,
            created=len(created),
            error=None,
            generators=sorted({item.get("generator", "") for item in created}),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        if not created:
            logger.info("Report generation produced nothing: no events in the period")
    except Exception as error:  # noqa: BLE001 - the outcome is surfaced, never swallowed
        logger.exception("Report generation failed")
        REPORT_GENERATION.update(
            running=False,
            created=0,
            error=f"{type(error).__name__}: {error}",
            generators=[],
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        # A stuck "running" flag would lock out every later attempt with a 409.
        REPORT_GENERATION["running"] = False


@app.post("/api/reports/generate", status_code=202)
def generate_report(request: Request, options: ReportGenerateIn | None = None) -> JSONResponse:
    if not LLM_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Rapor üretimi kapalı. Açmak için WAGGLE_LLM_ENABLED=1 ayarlayın.",
        )
    settings = options or ReportGenerateIn()
    if settings.report_type == "event" and settings.event_id is None:
        raise HTTPException(status_code=422, detail="Olay raporu için event_id gerekir")

    with REPORT_GENERATION_LOCK:
        if REPORT_GENERATION["running"]:
            raise HTTPException(status_code=409, detail="Rapor üretimi zaten sürüyor")
        REPORT_GENERATION.update(
            running=True,
            created=0,
            error=None,
            generators=[],
            device=None,
            written_characters=0,
            written_at=None,
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=None,
        )
    return JSONResponse(
        {"status": "started", "report_type": settings.report_type},
        status_code=202,
        background=BackgroundTask(
            _run_report_generation,
            str(request.base_url).rstrip("/"),
            settings.report_type,
            settings.event_id,
        ),
    )


@app.get("/api/reports/generation-status")
def report_generation_status() -> dict:
    state = dict(REPORT_GENERATION)
    elapsed = silent = None
    if state["started_at"]:
        reference = state["finished_at"] or datetime.now(timezone.utc).isoformat()
        elapsed = int((datetime.fromisoformat(reference) - datetime.fromisoformat(state["started_at"])).total_seconds())
        last_sign_of_life = state["written_at"] or state["started_at"]
        silent = int((datetime.fromisoformat(reference) - datetime.fromisoformat(last_sign_of_life)).total_seconds())
    return {
        "enabled": LLM_ENABLED,
        "model": LLM_MODEL,
        "elapsed_seconds": elapsed,
        "silent_seconds": silent,
        # Silence is measured from the last token the model wrote, not from the start of
        # the run. A run still writing is slow; a run that stopped writing is stalled, and
        # until the answer arrived token by token the two were the same long wait.
        "stalled": bool(state["running"] and silent is not None and silent > REPORT_GENERATION_STALL_SECONDS),
        **state,
    }


# Only the two components that receive something from outside keep a record of past
# contacts. The others are asked, not heard from, so there is nothing to list.
HISTORY_COMPONENTS = {"device", "reports"}


@app.get("/api/system-status/{component}/history", response_model=ComponentHistory)
def component_history(component: str, limit: int = Query(default=20, ge=1, le=100)) -> ComponentHistory:
    """When this component last got through, and what it brought.

    "Cihaz verisi gecikiyor" is a claim about a pattern, and a beekeeper deciding whether
    to walk to the apiary needs the pattern rather than the claim: a device that has been
    silent for an hour after months of hourly contact is a different problem from one that
    was always sporadic.
    """
    if component not in HISTORY_COMPONENTS:
        raise HTTPException(status_code=404, detail="Bu bileşenin bağlantı geçmişi tutulmuyor")
    if component == "device":
        hive_names = {hive.hive_id: hive.name for hive in store.hives(include_inactive=True)}
        entries = [
            ContactRecord(at=event.timestamp, status=event.status,
                          label=hive_names.get(event.hive_id, event.hive_id))
            for event in store.recent(limit)
        ]
    else:
        labels = {"event": "Olay raporu", "daily": "Günlük rapor", "weekly": "Haftalık rapor"}
        entries = [
            ContactRecord(at=report.created_at, status="ok",
                          label=labels.get(report.report_type, report.report_type))
            for report in store.reports(limit)
        ]
    return ComponentHistory(component=component, entries=entries)


@app.get("/api/reports/{report_id}/pdf")
def download_report_pdf(report_id: int, preview: bool = False) -> Response:
    report = store.report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Rapor bulunamadı")
    events = [event for event in store.recent(1_000_000) if report.period_start <= event.timestamp <= report.period_end and event.hive_id in report.hive_ids]
    hive_names = {hive.hive_id: hive.name for hive in store.hives(include_inactive=True)}
    try:
        content = build_report_pdf(report, events, hive_names)
    except ImportError as error:
        raise HTTPException(status_code=503, detail="PDF bileşeni kurulu değil") from error
    filename = f"waggle-{report.report_type}-report-{report.id}.pdf"
    disposition = "inline" if preview else "attachment"
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})


EXPORT_DATASETS = {"hives", "events", "alarms", "reports", "confirmations", "guidance", "enrollment", "devices"}


def _export_range(since: str | None, until: str | None) -> tuple[datetime | None, datetime | None]:
    """The requested period, as bounds the exporter can compare against.

    An unreadable date is refused rather than ignored: silently exporting everything when
    someone asked for a week hands them a file that does not answer their question.
    """
    def bound(value: str | None, end_of_day: bool):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Tarih aralığı okunamadı") from None
        if len(value) == 10:  # A plain date means the whole day it names.
            parsed = parsed.replace(hour=23, minute=59, second=59) if end_of_day else parsed
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    start, end = bound(since, False), bound(until, True)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="Başlangıç tarihi bitişten sonra olamaz")
    return start, end


@app.get("/api/export/summary")
def export_overview(since: str | None = None, until: str | None = None) -> dict:
    """What each dataset holds, so the page can show a count beside every choice."""
    start, end = _export_range(since, until)
    return {"datasets": export_summary(store, start, end)}


@app.get("/api/export/bundle")
def export_bundle(datasets: str, file_format: str = "csv", since: str | None = None,
                  until: str | None = None) -> Response:
    """Several datasets in one archive. A CSV holds one table, so more than one means a zip."""
    chosen = [name for name in dict.fromkeys(datasets.split(",")) if name]
    unknown = [name for name in chosen if name not in EXPORT_DATASETS]
    if not chosen or unknown:
        raise HTTPException(status_code=404, detail="Dışa aktarma veri kümesi bulunamadı")
    if file_format not in {"csv", "json"}:
        raise HTTPException(status_code=404, detail="Dışa aktarma biçimi desteklenmiyor")
    start, end = _export_range(since, until)
    content, media_type, filename = build_bundle(store, chosen, file_format, start, end)
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/{dataset}.{file_format}")
def export_data(dataset: str, file_format: str, since: str | None = None,
                until: str | None = None) -> Response:
    if dataset not in EXPORT_DATASETS:
        raise HTTPException(status_code=404, detail="Dışa aktarma veri kümesi bulunamadı")
    if file_format not in {"csv", "json"}:
        raise HTTPException(status_code=404, detail="Dışa aktarma biçimi desteklenmiyor")
    start, end = _export_range(since, until)
    content, media_type, filename = build_export(store, dataset, file_format, start, end)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/backup/database")
def backup_database(request: Request) -> FileResponse:
    # The write allowlist made every unlisted endpoint owner-only, and reading had no
    # equivalent. This file is the whole database, password and recovery-code hashes
    # included, so a field worker — including one still on the temporary password the
    # owner handed them, since that gate only guards writes — could take the owner's
    # credentials off the panel and work on them somewhere else.
    require_owner(request)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    temporary = tempfile.NamedTemporaryFile(prefix="waggle-backup-", suffix=".db", delete=False)
    backup_path = Path(temporary.name)
    temporary.close()
    try:
        store.backup_to(backup_path)
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    return FileResponse(
        backup_path,
        media_type="application/vnd.sqlite3",
        filename=f"waggle-backup-{timestamp}.db",
        background=BackgroundTask(backup_path.unlink, missing_ok=True),
    )


# How many pre-restore snapshots to keep. Each one is a full copy of the database, and
# nothing ever removed them: a panel restored a few times carried every version of itself
# forward for good. The recent ones are the ones anybody reaches for.
RECOVERY_BACKUP_KEEP = 10


def prune_recovery_backups(directory: Path, keep: int = RECOVERY_BACKUP_KEEP) -> None:
    """Drop all but the newest snapshots. Named by timestamp, so the sort is the age."""
    snapshots = sorted(directory.glob("waggle-before-restore-*.db"), reverse=True)
    for stale in snapshots[keep:]:
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            logger.warning("Eski kurtarma yedeği silinemedi: %s", stale.name)


@app.post("/api/backup/restore")
async def restore_database(request: Request) -> dict[str, str]:
    if request.headers.get("X-Waggle-Confirm-Restore") != "RESTORE":
        raise HTTPException(status_code=400, detail="Geri yükleme onayı eksik")
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="Yedek dosyası izin verilen boyutu aşıyor")
    contents = await request.body()
    if not contents or len(contents) > MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="Yedek dosyası boş veya çok büyük")

    uploaded = tempfile.NamedTemporaryFile(prefix="waggle-upload-", suffix=".db", delete=False)
    uploaded_path = Path(uploaded.name)
    try:
        uploaded.write(contents)
        uploaded.close()
        store.validate_backup(uploaded_path)
        recovery_directory = DB_PATH.parent / "recovery"
        recovery_directory.mkdir(parents=True, exist_ok=True)
        recovery_path = recovery_directory / f"waggle-before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        store.backup_to(recovery_path)
        prune_recovery_backups(recovery_directory)
        try:
            store.restore_from(uploaded_path)
            store.initialize()
        except Exception:
            store.restore_from(recovery_path)
            store.initialize()
            raise
        return {
            "message": "Yedek başarıyla geri yüklendi",
            "recovery_backup": recovery_path.name,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        uploaded.close()
        uploaded_path.unlink(missing_ok=True)


@app.get("/api/weather", response_model=WeatherState)
def weather() -> WeatherState:
    global weather_cache
    settings = AppSettings(**store.settings())
    if not settings.weather_enabled:
        raise HTTPException(
            status_code=503,
            detail="Çevrimiçi hava durumu Ayarlar bölümünden etkinleştirilmedi",
        )
    now = datetime.now()
    # The cache remembers which coordinates it holds. Keying it on time alone meant that
    # for ten minutes after someone corrected the apiary's position the panel kept
    # answering with the previous place's conditions — and stamping them onto events.
    coordinates = (settings.latitude, settings.longitude)
    if weather_cache and weather_cache[2] == coordinates and (now - weather_cache[0]).total_seconds() < 600:
        return weather_cache[1]
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": settings.latitude,
                "longitude": settings.longitude,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "timezone": "auto",
            },
            timeout=5,
        )
        response.raise_for_status()
        current = response.json()["current"]
        state = WeatherState(
            location=settings.location_name or WEATHER_LOCATION,
            temperature_c=current["temperature_2m"],
            humidity_percent=current["relative_humidity_2m"],
            wind_kmh=current["wind_speed_10m"],
            weather_code=current["weather_code"],
            observed_at=datetime.fromisoformat(current["time"]),
        )
        weather_cache = (now, state, coordinates)
        return state
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Hava durumu şu anda alınamıyor") from exc
