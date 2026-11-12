"""Signed, expiring browser workspaces; public issuer data remain shared."""
import contextvars
import hashlib
import hmac
import json
import os
import secrets
import time
import threading

from fastapi import HTTPException

from . import live_store as store, runtime

COOKIE = "finn_session"
TTL = 24 * 60 * 60
_current = contextvars.ContextVar("finn_workspace", default=None)
TABLES = [
    "CREATE TABLE IF NOT EXISTS workspace_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY,created REAL NOT NULL,
       expires REAL NOT NULL,settings TEXT NOT NULL,holdings TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS workspace_sessions (token_hash TEXT PRIMARY KEY,
       workspace TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,csrf TEXT NOT NULL,expires REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS workspace_people (workspace TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
       id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(workspace,id))""",
    """CREATE TABLE IF NOT EXISTS workspace_edges (workspace TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
       left_id TEXT NOT NULL,right_id TEXT NOT NULL,PRIMARY KEY(workspace,left_id,right_id))""",
    """CREATE TABLE IF NOT EXISTS workspace_notes (workspace TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
       person TEXT NOT NULL,note TEXT NOT NULL,last_contact TEXT NOT NULL,PRIMARY KEY(workspace,person))""",
    """CREATE TABLE IF NOT EXISTS workspace_alerts (workspace TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
       id TEXT NOT NULL,event_at TEXT NOT NULL,created TEXT NOT NULL,body TEXT NOT NULL,seen INTEGER NOT NULL DEFAULT 0,
       PRIMARY KEY(workspace,id))""",
    """CREATE TABLE IF NOT EXISTS reviewed_facts (workspace TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
       id TEXT NOT NULL,symbol TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(workspace,id))""",
    """CREATE TABLE IF NOT EXISTS source_actions (workspace TEXT NOT NULL,action TEXT NOT NULL,at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS workspace_expiry ON workspaces(expires)",
    "CREATE INDEX IF NOT EXISTS source_action_time ON source_actions(at)",
]


def prepare(db):
    for sql in TABLES:
        db.execute(sql)
    if "strength" not in {r[1] for r in db.execute("PRAGMA table_info(workspace_edges)")}:
        db.execute("ALTER TABLE workspace_edges ADD COLUMN strength INTEGER NOT NULL DEFAULT 2")


def current():
    """None is the legacy operator/CLI context; 'public' is an anonymous browser."""
    return _current.get()


def private():
    return current() not in {None, "public"}


def expire(db, now=None):
    now = time.time() if now is None else now
    db.execute("UPDATE workspace_meta SET value='complete' WHERE key='legacy_claimed' AND value IN (SELECT id FROM workspaces WHERE expires<=?)", (now,))
    db.execute("DELETE FROM workspaces WHERE expires<=?", (now,))
    db.execute("DELETE FROM workspace_sessions WHERE expires<=?", (now,))
    db.execute("DELETE FROM source_actions WHERE at<?", (now - TTL,))
    from datetime import datetime, timezone
    today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    expired = db.execute("SELECT workspace,id FROM workspace_people WHERE json_extract(body,'$.synthetic')=0 "
                         "AND json_extract(body,'$.consent.expires')<?", (today,)).fetchall()
    for row in expired:
        db.execute("DELETE FROM workspace_people WHERE workspace=? AND id=?", tuple(row))
        db.execute("DELETE FROM workspace_notes WHERE workspace=? AND person=?", tuple(row))
        db.execute("DELETE FROM workspace_edges WHERE workspace=? AND (left_id=? OR right_id=?)", (row[0], row[1], row[1]))


def secret(db):
    configured = os.environ.get("FINN_SESSION_SECRET", "").strip()
    if configured:
        if len(configured) < 32:
            raise ValueError("FINN_SESSION_SECRET needs at least 32 characters.")
        return configured.encode()
    db.execute("INSERT OR IGNORE INTO workspace_meta VALUES('session_secret',?)", (secrets.token_hex(32),))
    return db.execute("SELECT value FROM workspace_meta WHERE key='session_secret'").fetchone()[0].encode()


def signature(payload, key):
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def create(now=None, adopt_legacy=True):
    from . import desk
    now = time.time() if now is None else now
    wid, sid, csrf = secrets.token_hex(16), secrets.token_hex(32), secrets.token_hex(24)
    expires = int(now + TTL)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        expire(db, now)
        if db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] >= 100:
            raise ValueError("The demo is busy. Try again after an existing workspace expires.")
        settings = dict(store.DEFAULT_SETTINGS)
        claimed = db.execute("SELECT 1 FROM workspace_meta WHERE key='legacy_claimed'").fetchone()
        adopt = adopt_legacy and not runtime.public_demo() and not claimed
        if adopt:
            settings = store.settings(db)
        holdings = [c["symbol"] for c in desk.COMPANIES.values() if c["holding"]]
        db.execute("INSERT INTO workspaces VALUES(?,?,?,?,?)", (wid, now, expires, json.dumps(settings), json.dumps(holdings)))
        for person in desk.NETWORK["people"]:
            db.execute("INSERT INTO workspace_people VALUES(?,?,?)", (wid, person["id"], json.dumps(person)))
        db.executemany("INSERT INTO workspace_edges(workspace,left_id,right_id,strength) VALUES(?,?,?,?)",
                       [(wid, edge[0], edge[1], edge[2] if len(edge) > 2 else 2) for edge in desk.NETWORK["edges"]])
        if adopt:
            db.execute("INSERT INTO workspace_meta VALUES('legacy_claimed',?)", (wid,))
            db.execute("INSERT INTO workspace_alerts SELECT ?,id,event_at,created,body,seen FROM live_alerts", (wid,))
            db.execute("UPDATE alert_settings SET body=? WHERE id=1", (json.dumps(store.DEFAULT_SETTINGS),))
            db.execute("DELETE FROM live_alerts")
        payload = sid + "." + str(expires)
        token = payload + "." + signature(payload, secret(db))
        db.execute("INSERT INTO workspace_sessions VALUES(?,?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), wid, csrf, expires))
    return token, {"workspace": wid, "expires": expires, "csrf": csrf}


def identify(token, now=None):
    if not token or len(token) > 256:
        return None
    try:
        sid, raw_expiry, supplied = token.split(".")
        now = time.time() if now is None else now
        if len(sid) != 64 or int(raw_expiry) <= now:
            return None
        with store.connection() as db:
            if not hmac.compare_digest(signature(sid + "." + raw_expiry, secret(db)), supplied):
                return None
            row = db.execute("SELECT s.workspace,s.csrf,s.expires FROM workspace_sessions s JOIN workspaces w "
                             "ON w.id=s.workspace WHERE s.token_hash=? AND s.expires>? AND w.expires>?",
                             (hashlib.sha256(token.encode()).hexdigest(), now, now)).fetchone()
        return dict(row) if row else None
    except (ValueError, TypeError):
        return None


def require(request):
    session = getattr(request.state, "session", None)
    if not session:
        raise HTTPException(401, "Open your own workspace first.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("x-finn-csrf", "")
        if not supplied or not hmac.compare_digest(session["csrf"], supplied):
            raise HTTPException(403, "Refresh FINN before changing this workspace.")
    return session["workspace"]


def settings(db):
    if current() == "public":
        return dict(store.DEFAULT_SETTINGS)
    if not private():
        return store.settings(db)
    row = db.execute("SELECT settings FROM workspaces WHERE id=? AND expires>?", (current(), time.time())).fetchone()
    if not row:
        raise ValueError("This workspace has expired. Open a new workspace.")
    return json.loads(row[0])


def holdings(db=None):
    from . import desk
    default = [c["symbol"] for c in desk.COMPANIES.values() if c["holding"]]
    if not private():
        return default
    if db is None:
        with store.connection() as db:
            return holdings(db)
    row = db.execute("SELECT holdings FROM workspaces WHERE id=? AND expires>?", (current(), time.time())).fetchone()
    return json.loads(row[0]) if row else []


def set_holdings(symbols):
    from .documents import ticker
    values = list(dict.fromkeys(ticker(s) for s in symbols))
    if len(values) > 20:
        raise ValueError("Keep at most 20 companies in this demo portfolio.")
    with store.connection() as db:
        from . import desk
        union = {c["symbol"] for c in desk.COMPANIES.values() if c["holding"]}
        for row in db.execute("SELECT holdings FROM workspaces WHERE id<>? AND expires>?", (current(), time.time())):
            union.update(json.loads(row[0]))
        if len(union | set(values)) > 100:
            raise ValueError("The shared source cache has reached its 100-company demo limit.")
        db.execute("UPDATE workspaces SET holdings=? WHERE id=?", (json.dumps(values), current()))
    return values


def alerts(db):
    if current() == "public":
        return []
    if not private():
        return store.alerts(db)
    return [{**json.loads(r["body"]), "seen": bool(r["seen"])} for r in db.execute(
        "SELECT body,seen FROM workspace_alerts WHERE workspace=? ORDER BY event_at DESC,created DESC LIMIT 80", (current(),))]


def mark_read(db):
    db.execute("UPDATE workspace_alerts SET seen=1 WHERE workspace=?", (current(),))


def consume(action, *, public_limit=5, interval=3600):
    """Persistent per-workspace and global caps for public upstream work."""
    if not runtime.public_demo():
        return
    now = time.time()
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        expire(db, now)
        count = db.execute("SELECT COUNT(*) FROM source_actions WHERE workspace=? AND action=? AND at>?",
                           (current(), action, now - interval)).fetchone()[0]
        total = db.execute("SELECT COUNT(*) FROM source_actions WHERE action=? AND at>?", (action, now - interval)).fetchone()[0]
        total_limit = 1 if action == "refresh" else max(public_limit, 20)
        if count >= public_limit or total >= total_limit:
            raise ValueError("The public source limit has been reached. Existing evidence is still available; try later.")
        db.execute("INSERT INTO source_actions VALUES(?,?,?)", (current(), action, now))


def export_data():
    with store.connection() as db:
        row = db.execute("SELECT created,expires,settings,holdings FROM workspaces WHERE id=?", (current(),)).fetchone()
        if not row:
            raise ValueError("This workspace has expired.")
        return {"format": "finn-workspace-1", "created": row["created"], "expires": row["expires"],
                "settings": json.loads(row["settings"]), "holdings": json.loads(row["holdings"]),
                "people": [json.loads(r[0]) for r in db.execute("SELECT body FROM workspace_people WHERE workspace=?", (current(),))],
                "edges": [[r[0], r[1]] for r in db.execute("SELECT left_id,right_id FROM workspace_edges WHERE workspace=?", (current(),))],
                "notes": [dict(r) for r in db.execute("SELECT person,note,last_contact FROM workspace_notes WHERE workspace=?", (current(),))],
                "facts": [json.loads(r[0]) for r in db.execute("SELECT body FROM reviewed_facts WHERE workspace=?", (current(),))]}


def delete():
    with store.connection() as db:
        db.execute("UPDATE workspace_meta SET value='complete' WHERE key='legacy_claimed' AND value=?", (current(),))
        db.execute("DELETE FROM workspaces WHERE id=?", (current(),))
        db.execute("DELETE FROM source_actions WHERE workspace=?", (current(),))


class Janitor:
    """Expiry is checked on access; this removes expired rows while the app is idle."""
    def __init__(self):
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        def loop():
            while not self.stopped.wait(60):
                try:
                    with store.connection() as db:
                        expire(db)
                except Exception:
                    # The next access/startup also sweeps; never log private row contents.
                    pass
        self.thread = threading.Thread(target=loop, name="finn-expiry", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=1)
