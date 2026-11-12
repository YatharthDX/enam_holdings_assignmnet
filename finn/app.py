from datetime import date
import logging
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
import os
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import analysis, desk, discovery, documents, live, live_store, llm, runtime, workspaces, network, research

WEB = Path(__file__).parent / "assets"


@asynccontextmanager
async def lifespan(application):
    with live_store.connection():
        pass
    with live_store.connection() as db:
        workspaces.expire(db)
    logging.getLogger("uvicorn.access").disabled = True
    janitor = workspaces.Janitor()
    janitor.start()
    refresher = None if runtime.public_demo() else live.Refresher()
    if refresher:
        refresher.start()
    try:
        yield
    finally:
        janitor.stop()
        if refresher:
            refresher.stop()


app = FastAPI(title="FINN investor desk", version="0.6.3", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


class BodyLimit:
    def __init__(self, app, max_bytes=256 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                raise HTTPException(413, "Keep request bodies within 256 KiB.")
            return message
        await self.app(scope, bounded_receive, send)


app.add_middleware(BodyLimit)


@app.middleware("http")
async def public_demo_boundary(request, call_next):
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > 256 * 1024:
        return JSONResponse(status_code=413, content={"detail": "Keep request bodies within 256 KiB."})
    if runtime.public_demo() and not runtime.interactive() and request.method not in {"GET", "HEAD", "OPTIONS"}:
        return JSONResponse(status_code=403, content={"detail":
            "This public demo is read-only. Run FINN locally to index documents, change alerts or enable optional AI."})
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    with live_store.connection() as db:
        workspaces.expire(db)
    session = workspaces.identify(request.cookies.get(workspaces.COOKIE))
    request.state.session = session
    token = workspaces._current.set(session["workspace"] if session else "public")
    try:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    finally:
        workspaces._current.reset(token)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"status": "ok", "mode": "live_and_replay", "version": "0.6.3", "llm_enabled": llm.enabled(),
            "public_demo": runtime.public_demo(), "interactive_demo": runtime.interactive()}


def client_capabilities():
    return {**runtime.capabilities(), "read_only": not workspaces.private() or not runtime.interactive(),
            "authenticated": workspaces.private()}


@app.get("/api/session")
def session_status(request: Request):
    session = request.state.session
    return {"authenticated": bool(session), "expires": session["expires"] if session else None,
            "csrf": session["csrf"] if session else None, "runtime": client_capabilities()}


@app.post("/api/session", status_code=201)
def open_workspace(request: Request, disposable: bool = False):
    same_origin(request)
    if not runtime.interactive():
        raise HTTPException(403, "This deployment is read-only.")
    if request.state.session:
        return session_status(request)
    try:
        cookie, session = workspaces.create(adopt_legacy=not disposable)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    response = JSONResponse({"authenticated": True, "expires": session["expires"], "csrf": session["csrf"]}, status_code=201)
    response.set_cookie(workspaces.COOKIE, cookie, max_age=workspaces.TTL, httponly=True,
                        samesite="lax", secure=https_request(request), path="/")
    return response


@app.get("/api/workspace/export")
def export_workspace(request: Request):
    workspaces.require(request)
    return JSONResponse(workspaces.export_data(), headers={"Content-Disposition": 'attachment; filename="finn-workspace.json"'})


@app.delete("/api/workspace")
def delete_workspace(request: Request):
    same_origin(request)
    workspaces.require(request)
    workspaces.delete()
    response = JSONResponse({"status": "deleted"})
    response.delete_cookie(workspaces.COOKIE, path="/")
    return response


@app.get("/api/llm/status")
def model_configuration():
    try:
        return llm.public_config()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/catalog")
def catalog():
    return {"as_of": desk.REPLAY_END, "companies": desk.all_companies(),
            "seed_symbols": list(desk.COMPANIES),
            "sample_symbols": [s["symbol"] for s in desk.RESEARCH["snapshots"]],
            "runtime": client_capabilities()}


@app.get("/api/documents/{doc_id}/original")
def retained_original(doc_id: str, revision: str | None = None):
    try:
        found = documents.cached_original(doc_id, revision)
    except ValueError:
        found = None
    if not found:
        raise HTTPException(404, "This original is no longer cached. Use its issuer link or index it again.")
    path, filename = found
    return FileResponse(path, media_type="application/pdf", filename=filename, content_disposition_type="inline",
                        headers={"Cache-Control":"no-cache", "Content-Security-Policy":"sandbox", "X-Content-Type-Options":"nosniff"})


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
def get_research(symbol: str, q: str = Query("", max_length=160), lens: str = "business", as_of: date | None = None):
    try:
        result = desk.research(symbol, q)
        if as_of and as_of > date.today():
            raise ValueError("Research as-of date cannot be in the future.")
        cutoff = as_of.isoformat() if as_of else None
        result["structured"] = research.view(result["company"]["symbol"], cutoff)
        result["as_of"] = cutoff
        if cutoff:
            known = lambda source: bool(source.get("date")) and len(source["date"]) == 10 and source["date"] <= cutoff
            result["sources"] = [s for s in result["sources"] if known(s)]
            result["matches"] = [s for s in result["matches"] if known(s)]
            if result["snapshot"] and not known(result["snapshot"]["source"]):
                result["snapshot"] = None
            if result["comparison"] and not known(result["comparison"]["actual"]["source"]):
                result["pending_guidance"] = {"period": result["comparison"]["period"],
                                              "forecasts": [f for f in result["comparison"]["forecasts"] if known(f["source"])]}
                result["comparison"] = None
        result["discovery"] = discovery.status(result["company"]["symbol"])
        try:
            result["analysis"] = ({"enabled": False, "job": None, "lens": lens, "lenses": [], "date_filtered": bool(cutoff),
                                   "public_demo": runtime.public_demo(), "needs_workspace": not workspaces.private()}
                                  if cutoff or not workspaces.private() else analysis.status(result["company"]["symbol"], lens))
            result["reconnect"] = network.reconnect(result["company"]["symbol"])
        except ValueError as exc:
            # Optional model settings must never take down source research.
            result["analysis"] = {"enabled": llm.enabled(), "job": None, "lens": lens,
                                  "configuration_error": str(exc)}
        except Exception:
            logging.getLogger(__name__).warning("Optional AI status unavailable; primary research is still served")
            result["analysis"] = {"enabled": llm.enabled(), "job": None, "lens": lens,
                                  "configuration_error": "Optional AI status is unavailable. Primary research remains accessible."}
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/people")
def get_people(q: str = Query("", max_length=120), symbol: str = Query("", max_length=25)):
    profiles, edges, _ = network.load()
    return {"people": network.people(q, symbol), "can_edit": workspaces.private(), "profile_count": len(profiles),
            "edge_count": len(edges)}


@app.get("/api/people/resolve")
def resolve_person(name: str = Query("", max_length=100), employer: str = Query("", max_length=100),
                   role: str = Query("", max_length=100), on: date | None = None):
    return network.resolve(name, employer, role, on.isoformat() if on else "")


@app.post("/api/network/import")
async def import_network(request: Request):
    same_origin(request)
    workspaces.require(request)
    body = await request.body()
    if len(body) > 256 * 1024:
        raise HTTPException(413, "Keep the network JSON below 256 KiB.")
    try:
        value = json.loads(body)
        return {"imported": network.import_bundle(value)}
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else "Use the documented network JSON format.") from exc


class ContactNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=2000)
    last_contact: date | None = None


@app.put("/api/people/{person}/note")
def save_contact_note(person: str, value: ContactNote, request: Request):
    same_origin(request)
    workspaces.require(request)
    try:
        network.save_note(person, value.note, value.last_contact.isoformat() if value.last_contact else "")
        return {"status": "saved"}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete("/api/people/{person}")
def remove_person(person: str, request: Request):
    same_origin(request)
    workspaces.require(request)
    network.delete_person(person)
    return {"status": "deleted"}


class Holdings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(max_length=20)


@app.put("/api/portfolio")
def save_portfolio(value: Holdings, request: Request):
    same_origin(request)
    workspaces.require(request)
    try:
        return {"symbols": workspaces.set_holdings(value.symbols)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/research/{symbol}/facts", status_code=201)
async def review_fact(symbol: str, request: Request):
    same_origin(request)
    workspaces.require(request)
    body = await request.body()
    if len(body) > 8192:
        raise HTTPException(413, "Keep a reviewed fact within 8 KiB.")
    try:
        return research.save_fact(documents.ticker(symbol), json.loads(body))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else "Use the displayed fact fields.") from exc


@app.delete("/api/research/{symbol}/facts/{fact_id}")
def remove_fact(symbol: str, fact_id: str, request: Request):
    same_origin(request)
    workspaces.require(request)
    research.delete_fact(fact_id)
    return {"status": "deleted"}


def same_origin(request):
    origin = request.headers.get("origin")
    expected = str(request.base_url).rstrip("/")
    if https_request(request) and expected.startswith("http://"):
        expected = "https://" + expected[7:]
    if origin and origin.rstrip("/") != expected:
        raise HTTPException(403, "Open FINN on the same origin to change its demo settings.")


def https_request(request):
    return request.url.scheme == "https" or (os.environ.get("FINN_TRUST_PROXY", "0") == "1" and
                                             request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https")


@app.get("/api/research/{symbol}/analysis")
def analysis_status(symbol: str, request: Request, lens: str = "business"):
    workspaces.require(request)
    try:
        return analysis.status(symbol, lens)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lens: str = Field(default="business", max_length=30)


@app.post("/api/research/{symbol}/analyze", status_code=202)
def analyze_documents(symbol: str, value: AnalysisRequest, request: Request, tasks: BackgroundTasks):
    same_origin(request)
    workspaces.require(request)
    try:
        result, work = analysis.begin(symbol, value.lens)
    except ValueError as exc:
        status = 429 if getattr(exc, "code", "") in {"PUBLIC_AI_LIMIT", "PUBLIC_AI_BUSY"} else 422
        raise HTTPException(status, str(exc)) from exc
    if work:
        tasks.add_task(analysis.run, *work)
    return result


@app.get("/api/research/{symbol}/discovery")
def document_status(symbol: str):
    try:
        return {"job": discovery.status(documents.ticker(symbol))}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/research/{symbol}/discover", status_code=202)
def discover_documents(symbol: str, request: Request, tasks: BackgroundTasks):
    same_origin(request)
    workspaces.require(request)
    try:
        symbol = documents.ticker(symbol)
        workspaces.consume("documents")
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
                "unread": sum(not a["seen"] for a in workspaces.alerts(db))}


@app.post("/api/live/refresh", status_code=202)
def refresh_live(request: Request, tasks: BackgroundTasks):
    same_origin(request)
    workspaces.require(request)
    try:
        workspaces.consume("refresh", public_limit=1, interval=900)
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc
    tasks.add_task(live.refresh, force_prices=True)
    return {"status": "queued"}


@app.get("/api/alert-settings")
def get_settings():
    with live_store.connection() as db:
        return {"settings": workspaces.settings(db), "categories": live.CATEGORIES}


@app.put("/api/alert-settings")
def save_settings(request: Request, value: AlertSettings):
    same_origin(request)
    workspaces.require(request)
    return {"settings": live.update_settings(value.model_dump())}


@app.post("/api/alerts/read")
def mark_alerts_read(request: Request):
    same_origin(request)
    workspaces.require(request)
    with live_store.connection() as db:
        workspaces.mark_read(db)
    return {"status": "ok"}
