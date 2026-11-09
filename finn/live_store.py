"""Public source cache and the single synthetic workspace's alert settings."""
import json
import sqlite3
from contextlib import closing, contextmanager

from .documents import database_path

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS live_filings (
        id TEXT PRIMARY KEY, symbol TEXT NOT NULL, published TEXT NOT NULL, body TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS live_filings_date ON live_filings(published)",
    """CREATE TABLE IF NOT EXISTS daily_bars (
        symbol TEXT NOT NULL, day TEXT NOT NULL, close REAL, volume REAL,
        split INTEGER NOT NULL, fetched TEXT NOT NULL, PRIMARY KEY(symbol, day))""",
    """CREATE TABLE IF NOT EXISTS source_state (
        key TEXT PRIMARY KEY, attempt TEXT NOT NULL, success TEXT, status TEXT NOT NULL,
        detail TEXT NOT NULL, url TEXT NOT NULL, coverage TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS refresh_job (
        id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL, status TEXT NOT NULL,
        started TEXT NOT NULL, finished TEXT, expires TEXT NOT NULL, detail TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS alert_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS live_alerts (
        id TEXT PRIMARY KEY, event_at TEXT NOT NULL, created TEXT NOT NULL,
        body TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS document_jobs (
        symbol TEXT PRIMARY KEY, token TEXT NOT NULL, status TEXT NOT NULL,
        started TEXT NOT NULL, finished TEXT, expires TEXT NOT NULL,
        detail TEXT NOT NULL, sources_json TEXT NOT NULL)""",
]
DEFAULT_SETTINGS = {"enabled": True, "price_pct": 5.0, "volume_multiple": 2.0,
                    "categories": ["results", "M&A", "management_change", "litigation", "capex"]}


@contextmanager
def connection():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=15)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        for statement in SCHEMA:
            db.execute(statement)
        db.execute("INSERT OR IGNORE INTO alert_settings VALUES(1, ?)",
                   (json.dumps(DEFAULT_SETTINGS),))
        db.commit()
        with db:
            yield db


def settings(db):
    return json.loads(db.execute("SELECT body FROM alert_settings WHERE id=1").fetchone()["body"])


def put_filings(db, rows):
    for row in rows:
        db.execute("""INSERT INTO live_filings VALUES(?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET published=excluded.published, body=excluded.body""",
                   (row["id"], row["symbol"], row["published"], json.dumps(row)))


def put_bars(db, rows, fetched):
    for row in rows:
        db.execute("""INSERT INTO daily_bars VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, day) DO UPDATE SET close=COALESCE(excluded.close, daily_bars.close),
            volume=COALESCE(excluded.volume, daily_bars.volume),
            split=MAX(excluded.split, daily_bars.split), fetched=excluded.fetched""",
                   (row["symbol"], row["day"], row["close"], row["volume"], row["split"], fetched))


def state(db, key, attempted, status, detail, url, coverage):
    success = attempted if status == "ok" else None
    db.execute("""INSERT INTO source_state VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET attempt=excluded.attempt,
        success=COALESCE(excluded.success, source_state.success), status=excluded.status,
        detail=excluded.detail, url=excluded.url, coverage=excluded.coverage""",
               (key, attempted, success, status, detail, url, coverage))


def bars(db, symbol):
    return [dict(r) for r in db.execute(
        "SELECT * FROM (SELECT * FROM daily_bars WHERE symbol=? ORDER BY day DESC LIMIT 22) ORDER BY day",
        (symbol,)
    )]


def alerts(db):
    return [{**json.loads(row["body"]), "seen": bool(row["seen"])} for row in db.execute(
        "SELECT body, seen FROM live_alerts ORDER BY event_at DESC, created DESC LIMIT 80"
    )]


def job(db):
    row = db.execute("SELECT * FROM refresh_job WHERE id=1").fetchone()
    return dict(row) if row else None
