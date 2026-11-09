from datetime import date
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import desk, discovery, documents, live, live_store

WEB = Path(__file__).parent / "assets"


@asynccontextmanager
async def lifespan(application):
    with live_store.connection():
        pass
    refresher = live.Refresher()
    refresher.start()
    try:
        yield
    finally:
        refresher.stop()


app = FastAPI(title="FINN investor desk", version="0.2.0", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"status": "ok", "mode": "live_and_replay"}


@app.get("/api/catalog")
def catalog():
    return {"as_of": desk.REPLAY_END, "companies": desk.all_companies(),
            "sample_symbols": [s["symbol"] for s in desk.RESEARCH["snapshots"]]}


@app.get("/api/brief")
def get_brief(window: str = "24h", start: date | None = None, end: date | None = None,
              mode: str = "replay"):
    try:
        if mode == "live":
            return live.snapshot(window, start, end)
        if mode == "replay":
            return {**desk.brief(window, start, end), "mode": "replay"}
        raise ValueError("Choose live or replay.")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/research/{symbol}")
def get_research(symbol: str, q: str = Query("", max_length=160)):
    try:
        result = desk.research(symbol, q)
        result["discovery"] = discovery.status(result["company"]["symbol"])
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/people")
def get_people(q: str = Query("", max_length=120), symbol: str = Query("", max_length=25)):
    return {"people": desk.people(q, symbol)}


def same_origin(request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Open FINN on the same origin to change its demo settings.")


@app.get("/api/research/{symbol}/discovery")
def document_status(symbol: str):
    try:
        return {"job": discovery.status(documents.ticker(symbol))}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/research/{symbol}/discover", status_code=202)
def discover_documents(symbol: str, request: Request, tasks: BackgroundTasks):
    same_origin(request)
    try:
        symbol = documents.ticker(symbol)
        token = discovery.begin(symbol)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if token:
        tasks.add_task(discovery.run, symbol, token)
    return {"status": "running", "symbol": symbol}


class AlertSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: bool = True
    price_pct: float = Field(default=5.0, ge=0.1, le=100)
    volume_multiple: float = Field(default=2.0, ge=1, le=100)
    categories: list[str] = Field(default_factory=lambda: live_store.DEFAULT_SETTINGS["categories"].copy(),
                                  max_length=len(live.CATEGORIES))

    @field_validator("price_pct", "volume_multiple", mode="before")
    @classmethod
    def numeric_thresholds(cls, value):
        if isinstance(value, bool):
            raise ValueError("Alert thresholds must be numbers.")
        return value

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, values):
        if any(value not in live.CATEGORIES for value in values):
            raise ValueError("Choose one of the displayed filing categories.")
        return list(dict.fromkeys(values))


@app.get("/api/live/status")
def live_status():
    with live_store.connection() as db:
        return {"job": live_store.job(db),
                "sources": [dict(row) for row in db.execute("SELECT * FROM source_state ORDER BY key")],
                "unread": db.execute("SELECT COUNT(*) FROM live_alerts WHERE seen=0").fetchone()[0]}


@app.post("/api/live/refresh", status_code=202)
def refresh_live(request: Request, tasks: BackgroundTasks):
    same_origin(request)
    tasks.add_task(live.refresh, force_prices=True)
    return {"status": "queued"}


@app.get("/api/alert-settings")
def get_settings():
    with live_store.connection() as db:
        return {"settings": live_store.settings(db), "categories": live.CATEGORIES}


@app.put("/api/alert-settings")
def save_settings(request: Request, value: AlertSettings):
    same_origin(request)
    return {"settings": live.update_settings(value.model_dump())}


@app.post("/api/alerts/read")
def mark_alerts_read(request: Request):
    same_origin(request)
    with live_store.connection() as db:
        db.execute("UPDATE live_alerts SET seen=1")
    return {"status": "ok"}
