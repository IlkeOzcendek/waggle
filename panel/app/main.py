from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import EventStore
from .models import DashboardState, HiveEvent, HiveEventIn


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("WAGGLE_DB", BASE_DIR.parent / "data" / "waggle.db"))
store = EventStore(DB_PATH)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    yield


app = FastAPI(title="Waggle API", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def panel() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/events", response_model=HiveEvent, status_code=201)
def create_event(event: HiveEventIn) -> HiveEvent:
    try:
        return store.add(event)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Olay kaydedilemedi") from exc


@app.get("/api/events", response_model=list[HiveEvent])
def list_events(limit: int = Query(default=50, ge=1, le=500)) -> list[HiveEvent]:
    return store.recent(limit)


@app.get("/api/dashboard", response_model=DashboardState)
def dashboard() -> DashboardState:
    return DashboardState(hives=store.summaries(), events=store.recent(30))

