from __future__ import annotations

import os
import logging
import re
import tempfile
import threading
from typing import Literal
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
import requests

from .database import EventStore
from .exports import build_export
from .report_pdf import build_report_pdf
from .models import AlarmInspectionIn, AppSettings, ComponentStatus, DashboardState, Device, DeviceCreate, EnrollmentStatus, HealthConfirmation, HealthConfirmationIn, Hive, HiveCreate, HiveEvent, HiveEventIn, HiveUpdate, Report, ReportIn, SensorAnalysis, SystemStatus, WeatherState
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
    verify_credentials,
    verify_password,
    verify_device_key,
    validate_security_config,
)
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("WAGGLE_DB", BASE_DIR.parent / "data" / "waggle.db"))
store = EventStore(DB_PATH)
WEATHER_LAT = float(os.getenv("WAGGLE_LAT", "41.0082"))
WEATHER_LON = float(os.getenv("WAGGLE_LON", "28.9784"))
WEATHER_LOCATION = os.getenv("WAGGLE_LOCATION", "Gölbaşı Arılığı")
weather_cache: tuple[datetime, WeatherState] | None = None
logger = logging.getLogger("waggle")
MAX_BACKUP_BYTES = int(os.getenv("WAGGLE_MAX_BACKUP_BYTES", str(100 * 1024 * 1024)))
DEVICE_STALE_SECONDS = int(os.getenv("WAGGLE_DEVICE_STALE_SECONDS", "900"))
REPORT_STALE_SECONDS = int(os.getenv("WAGGLE_REPORT_STALE_SECONDS", "691200"))
SENSOR_MODEL_PATH = Path(os.getenv("WAGGLE_SENSOR_MODEL", BASE_DIR.parent.parent / "results" / "mendeley_isolation_monitor.onnx"))
HIVE_PROFILE_DIR = Path(os.getenv("WAGGLE_HIVE_PROFILE_DIR", BASE_DIR.parent.parent / "results" / "hive_profiles"))
MAX_SENSOR_AUDIO_BYTES = int(os.getenv("WAGGLE_MAX_SENSOR_AUDIO_BYTES", str(25 * 1024 * 1024)))
# Model-backed report generation stays off unless it is switched on deliberately,
# so a panel without a local model never advertises a capability it does not have.
LLM_ENABLED = os.getenv("WAGGLE_LLM_ENABLED", "0") == "1"
LLM_MODEL = os.getenv("WAGGLE_LLM_MODEL", "phi-3.5-mini")
DEVICE_KEY = os.getenv("WAGGLE_DEVICE_KEY", "waggle-device-demo")
REPORT_GENERATION: dict = {
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
    username = read_session(request.cookies.get(COOKIE_NAME))
    if username:
        # Sessions are signed tokens with no server-side record, so this lookup is what
        # makes deactivating a worker take effect now instead of whenever their cookie
        # happens to expire.
        account = effective_account(username)
        if account is not None and not account["active"]:
            return _rejected(path, "Hesabınız devre dışı bırakıldı.", 401)
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
    return FileResponse(BASE_DIR / "static" / "login.html")


@app.get("/setup", include_in_schema=False)
def setup_page(request: Request) -> Response:
    if read_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)
    if store.has_users():
        return RedirectResponse("/login", status_code=303)
    return FileResponse(BASE_DIR / "static" / "setup.html")


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
        create_session(credentials.username, session_seconds),
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
        create_session(username),
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
    return Response(status_code=204)


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
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/guidance")
def guidance_notes(
    language: Literal["tr", "en"] = "tr",
    ids: str | None = Query(default=None, max_length=500),
) -> list[dict]:
    """The reviewed local notes a report was grounded in.

    A report stores only the ids of the passages it used. The panel needs their text to
    show what the assessment actually rested on — an assessment you cannot trace back to
    its sources is just an opinion with a logo on it.
    """
    from brain.local_rag import load_knowledge

    wanted = {item.strip() for item in ids.split(",") if item.strip()} if ids else None
    return [
        {"id": entry["id"], "text": entry[language], "tags": entry["tags"]}
        for entry in load_knowledge()
        if wanted is None or entry["id"] in wanted
    ]


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
        "ok": ("Canlı veri alınıyor", "Cihaz veya model sonuçları güvenli bağlantı üzerinden panele ulaşıyor."),
        "waiting": ("İlk veri bekleniyor", "Kovan cihazı veya akustik analiz servisi ilk olayı gönderdiğinde bağlantı zamanı burada görünecek."),
        "warning": ("Cihaz verisi gecikiyor", "Son olay beklenen süreden eski. Kovan cihazını, modeli ve yerel ağ bağlantısını kontrol edin."),
    }
    report_messages = {
        "ok": ("Rapor entegrasyonu çalışıyor", "Üretilen değerlendirme raporları panele kaydediliyor."),
        "waiting": ("İlk rapor bekleniyor", "İlk haftalık değerlendirme gönderildiğinde burada son rapor zamanı görünecek."),
        "warning": ("Rapor güncel değil", "Son haftalık değerlendirme beklenen süreden eski. Rapor üretim akışını kontrol edin."),
    }
    components = [
        ComponentStatus(key="panel", name="Waggle paneli", status="ok", summary="Panel çalışıyor", detail="Kullanıcı arayüzü ve API istekleri yanıt veriyor."),
        ComponentStatus(key="database", name="Veri kayıt sistemi", status="ok" if database_ok else "warning", summary="Veritabanı sağlam" if database_ok else "Veritabanını kontrol edin", detail=f'{counts["hives"]} kovan, {counts["events"]} olay ve {counts["reports"]} rapor kayıtlı.'),
        ComponentStatus(key="device", name="Kovan cihazları ve yapay zekâ modeli", status=device_status, summary=device_messages[device_status][0], detail=device_messages[device_status][1], last_seen_at=last_event),
        ComponentStatus(key="reports", name="Haftalık yapay zekâ raporları", status=report_status, summary=report_messages[report_status][0], detail=report_messages[report_status][1], last_seen_at=last_report),
    ]
    return SystemStatus(overall="ok" if all(item.status == "ok" for item in components) else "attention", components=components)


@app.post("/api/events", response_model=HiveEvent, status_code=201)
def create_event(event: HiveEventIn) -> HiveEvent:
    if not store.has_hive(event.hive_id):
        raise HTTPException(status_code=404, detail="Kovan bulunamadı")
    try:
        return store.add(event)
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
                    train_verified_profile(
                        training_values, training_names, hive_id,
                        HIVE_PROFILE_DIR / f"{hive_id}.joblib", onnx_path,
                    )
                    progress = store.activate_profile(hive_id, str(onnx_path))
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

        previous = next((item for item in store.recent(500) if item.hive_id == hive_id), None)
        initial_run = previous.consecutive_anomalies if previous else 0
        result = analyze_wav(model_path, uploaded_path, initial_run)
        store.touch_device(device_id)
        event = store.add(HiveEventIn(
            hive_id=hive_id,
            timestamp=datetime.now(timezone.utc),
            status=result["status"],
            anomaly_fraction=result["anomaly_fraction"],
            consecutive_anomalies=result["consecutive_anomalies"],
            source_file=f"phone:{safe_name}",
        ))
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
    saved = AppSettings(**store.update_settings(cleaned.model_dump()))
    weather_cache = None
    return saved


@app.get("/api/hives", response_model=list[Hive])
def list_hives(include_inactive: bool = False) -> list[Hive]:
    return store.hives(include_inactive=include_inactive)


@app.post("/api/hives", response_model=Hive, status_code=201)
def create_hive(hive: HiveCreate) -> Hive:
    return store.add_hive(hive)


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
        from brain.weekly_agent import run_period_report

        created = run_period_report(
            panel_url,
            DEVICE_KEY,
            LLM_MODEL,
            report_type=report_type,
            event_id=event_id,
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
    elapsed = None
    if state["started_at"]:
        reference = state["finished_at"] or datetime.now(timezone.utc).isoformat()
        elapsed = int((datetime.fromisoformat(reference) - datetime.fromisoformat(state["started_at"])).total_seconds())
    return {
        "enabled": LLM_ENABLED,
        "model": LLM_MODEL,
        "elapsed_seconds": elapsed,
        "stalled": bool(state["running"] and elapsed is not None and elapsed > REPORT_GENERATION_STALL_SECONDS),
        **state,
    }


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


@app.get("/api/export/{dataset}.{file_format}")
def export_data(dataset: str, file_format: str) -> Response:
    if dataset not in {"hives", "events", "alarms", "reports"}:
        raise HTTPException(status_code=404, detail="Dışa aktarma veri kümesi bulunamadı")
    if file_format not in {"csv", "json"}:
        raise HTTPException(status_code=404, detail="Dışa aktarma biçimi desteklenmiyor")
    content, media_type, filename = build_export(store, dataset, file_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/backup/database")
def backup_database() -> FileResponse:
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
    if weather_cache and (now - weather_cache[0]).total_seconds() < 600:
        return weather_cache[1]
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": WEATHER_LAT,
                "longitude": WEATHER_LON,
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
        weather_cache = (now, state)
        return state
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Hava durumu şu anda alınamıyor") from exc


@app.post("/api/demo", response_model=list[HiveEvent], status_code=201)
def demo_scenario() -> list[HiveEvent]:
    timestamp = datetime.now().astimezone().replace(microsecond=0)
    scenario = [
        HiveEventIn(hive_id="H1", timestamp=timestamp, status="NORMAL", anomaly_fraction=0.08),
        HiveEventIn(hive_id="H2", timestamp=timestamp, status="WATCH", anomaly_fraction=0.68, consecutive_anomalies=5),
        HiveEventIn(hive_id="H3", timestamp=timestamp, status="ALARM", anomaly_fraction=1.0, consecutive_anomalies=30),
    ]
    return [store.add(event) for event in scenario]
