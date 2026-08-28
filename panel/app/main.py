from __future__ import annotations

import os
import logging
import tempfile
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
from .models import AppSettings, ComponentStatus, DashboardState, Hive, HiveCreate, HiveEvent, HiveEventIn, HiveUpdate, Report, ReportIn, SystemStatus, WeatherState
from .auth import (
    ADMIN_USERNAME,
    COOKIE_NAME,
    DEVICE_KEY_HEADER,
    SESSION_SECONDS,
    create_session,
    login_attempt_guard,
    read_session,
    verify_credentials,
    verify_device_key,
    validate_security_config,
)
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("WAGGLE_DB", BASE_DIR.parent / "data" / "waggle.db"))
store = EventStore(DB_PATH)
WEATHER_LAT = float(os.getenv("WAGGLE_LAT", "41.0082"))
WEATHER_LON = float(os.getenv("WAGGLE_LON", "28.9784"))
WEATHER_LOCATION = os.getenv("WAGGLE_LOCATION", "Demo Kovanları")
weather_cache: tuple[datetime, WeatherState] | None = None
logger = logging.getLogger("waggle")
MAX_BACKUP_BYTES = int(os.getenv("WAGGLE_MAX_BACKUP_BYTES", str(100 * 1024 * 1024)))
DEVICE_STALE_SECONDS = int(os.getenv("WAGGLE_DEVICE_STALE_SECONDS", "900"))
REPORT_STALE_SECONDS = int(os.getenv("WAGGLE_REPORT_STALE_SECONDS", "691200"))


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
    yield


app = FastAPI(title="Waggle API", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class LoginRequest(BaseModel):
    username: str
    password: str


PUBLIC_PATHS = {"/login", "/api/login", "/api/health"}
DEVICE_POST_PATHS = {"/api/events", "/api/reports"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def is_cross_site_request(origin: str | None, fetch_site: str | None, expected: str) -> bool:
    """Reject browser mutations coming from another site without blocking devices."""
    if fetch_site == "cross-site":
        return True
    return bool(origin) and origin.rstrip("/") != expected.rstrip("/")


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
    if path.startswith("/api/") or path == "/login":
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
        request.state.username = username
        return await call_next(request)
    if (
        path in DEVICE_POST_PATHS
        and request.method == "POST"
        and verify_device_key(request.headers.get(DEVICE_KEY_HEADER))
    ):
        request.state.device_authenticated = True
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Oturum açmanız gerekiyor"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", include_in_schema=False)
def login_page(request: Request) -> Response:
    if read_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(BASE_DIR / "static" / "login.html")


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
    if not verify_credentials(credentials.username, credentials.password):
        login_attempt_guard.record_failure(client_id)
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya parola hatalı")
    login_attempt_guard.reset(client_id)
    response = JSONResponse({"username": credentials.username})
    response.set_cookie(
        COOKIE_NAME,
        create_session(credentials.username),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.getenv("WAGGLE_SECURE_COOKIE", "0") == "1",
    )
    return response


@app.post("/api/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/api/me")
def current_user(request: Request) -> dict[str, str]:
    return {"username": getattr(request.state, "username", ADMIN_USERNAME)}


@app.get("/", include_in_schema=False)
def panel() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
        "waiting": ("İlk veri bekleniyor", "Ilke'nin modeli ya da bir kovan cihazı ilk olayı gönderdiğinde burada bağlantı zamanı görünecek."),
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


@app.post("/api/events/{event_id}/acknowledge", response_model=HiveEvent)
def acknowledge_event(event_id: int) -> HiveEvent:
    event = store.acknowledge(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Olay bulunamadı")
    return event


@app.get("/api/dashboard", response_model=DashboardState)
def dashboard() -> DashboardState:
    return DashboardState(hives=store.summaries(), events=store.recent(30))


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
