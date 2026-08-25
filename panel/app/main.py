from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import requests

from .database import EventStore
from .models import DashboardState, Hive, HiveCreate, HiveEvent, HiveEventIn, HiveUpdate, Report, ReportIn, WeatherState
from .auth import (
    ADMIN_USERNAME,
    COOKIE_NAME,
    DEVICE_KEY_HEADER,
    SESSION_SECONDS,
    create_session,
    read_session,
    verify_credentials,
    verify_device_key,
)
from pydantic import BaseModel


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("WAGGLE_DB", BASE_DIR.parent / "data" / "waggle.db"))
store = EventStore(DB_PATH)
WEATHER_LAT = float(os.getenv("WAGGLE_LAT", "41.0082"))
WEATHER_LON = float(os.getenv("WAGGLE_LON", "28.9784"))
WEATHER_LOCATION = os.getenv("WAGGLE_LOCATION", "Demo Kovanları")
weather_cache: tuple[datetime, WeatherState] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    yield


app = FastAPI(title="Waggle API", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class LoginRequest(BaseModel):
    username: str
    password: str


PUBLIC_PATHS = {"/login", "/api/login", "/api/health"}


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
        path == "/api/events"
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
def login(credentials: LoginRequest) -> Response:
    if not verify_credentials(credentials.username, credentials.password):
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya parola hatalı")
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


@app.get("/api/weather", response_model=WeatherState)
def weather() -> WeatherState:
    global weather_cache
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
            location=WEATHER_LOCATION,
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
        HiveEventIn(hive_id="H1", timestamp=timestamp, event="healthy", confidence=0.93),
        HiveEventIn(hive_id="H2", timestamp=timestamp, event="uncertain", confidence=0.68),
        HiveEventIn(hive_id="H3", timestamp=timestamp, event="queenless_suspected", confidence=0.91),
    ]
    return [store.add(event) for event in scenario]
