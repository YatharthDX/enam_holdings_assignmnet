from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import desk

WEB = Path(__file__).parent / "assets"
app = FastAPI(title="FINN investor desk", version="0.1.0", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"status": "ok", "mode": "historical_replay"}


@app.get("/api/catalog")
def catalog():
    return {"as_of": desk.REPLAY_END, "companies": desk.all_companies(),
            "sample_symbols": [s["symbol"] for s in desk.RESEARCH["snapshots"]]}


@app.get("/api/brief")
def get_brief(window: str = "24h", start: date | None = None, end: date | None = None):
    try:
        return desk.brief(window, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/research/{symbol}")
def get_research(symbol: str, q: str = Query("", max_length=160)):
    try:
        return desk.research(symbol, q)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/people")
def get_people(q: str = Query("", max_length=120), symbol: str = Query("", max_length=25)):
    return {"people": desk.people(q, symbol)}
