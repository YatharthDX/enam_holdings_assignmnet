"""Index operator-supplied public PDFs. The HTTP application only reads this index."""
import hashlib
import os
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9&.-]{0,24}")
KINDS = {"annual_report": "Annual report", "transcript": "Earnings call"}
MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 800


def ticker(value):
    symbol = value.strip().upper()
    if not SYMBOL.fullmatch(symbol):
        raise ValueError("Enter an NSE symbol of up to 25 characters.")
    return symbol


def source_url(value):
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Supply an HTTPS link to the original public document.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def database_path():
    return Path(os.environ.get("FINN_DATA_DIR", ".finn")) / "desk.sqlite3"


@contextmanager
def read_snapshot():
    path = database_path()
    if not path.is_file():
        yield None
        return
    with closing(sqlite3.connect(path, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        # A reader may first open the file while an importer is creating its schema.
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()
        yield db if exists else None


def symbols():
    with read_snapshot() as db:
        if db is None:
            return []
        return [r["symbol"] for r in db.execute("SELECT DISTINCT symbol FROM documents ORDER BY symbol")]


def for_symbol(symbol, include_pages):
    with read_snapshot() as db:
        if db is None:
            return [], []
        records = db.execute(
            "SELECT id, symbol, title, kind, published AS date, url FROM documents "
            "WHERE symbol=? ORDER BY published DESC, id", (symbol,)
        ).fetchall()
        passages = []
        if include_pages:
            passages = db.execute(
                "SELECT p.doc_id, p.page, p.body FROM pages p JOIN documents d ON d.id=p.doc_id "
                "WHERE d.symbol=? ORDER BY d.published DESC, d.id, p.page", (symbol,)
            ).fetchall()
        return [dict(r) for r in records], [dict(p) for p in passages]


def import_pdf(file, symbol, kind, title, url, published):
    from pypdf import PdfReader

    symbol = ticker(symbol)
    url = source_url(url)
    title = title.strip()
    if kind not in KINDS or not (0 < len(title) <= 240):
        raise ValueError("Select an annual report or transcript and provide a document title.")
    publication_date = date.fromisoformat(published)
    if publication_date > date.today():
        raise ValueError("The publication date must be today or earlier.")
    published = publication_date.isoformat()
    path = Path(file)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("Choose a local PDF smaller than 50 MiB.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    doc_id = "local-" + hashlib.sha256((symbol + "|" + url).encode()).hexdigest()[:24]
    reader = PdfReader(str(path))
    if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
        raise ValueError("Use an unencrypted PDF with at most 800 pages.")
    page_text = []
    for page_number, page in enumerate(reader.pages, 1):
        body = " ".join((page.extract_text() or "").split())
        if body:
            page_text.append((doc_id, page_number, body))
    if not page_text:
        raise ValueError("This PDF has no selectable text. Import a text-searchable original.")

    dest = database_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Parse completely before opening a write transaction. A failed replacement
    # must leave the previous searchable revision intact.
    with closing(sqlite3.connect(dest, timeout=15)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, symbol TEXT NOT NULL, kind TEXT NOT NULL,
            title TEXT NOT NULL, published TEXT NOT NULL, url TEXT NOT NULL, digest TEXT NOT NULL,
            UNIQUE(symbol, url))""")
        db.execute("""CREATE TABLE IF NOT EXISTS pages (
            doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(doc_id, page))""")
        old = db.execute("SELECT digest, kind, title, published FROM documents WHERE id=?",
                         (doc_id,)).fetchone()
        if old == (digest, KINDS[kind], title, published):
            return doc_id, len(page_text), "already indexed"
        db.execute("""INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, title=excluded.title,
            published=excluded.published, digest=excluded.digest""",
                   (doc_id, symbol, KINDS[kind], title, published, url, digest))
        db.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
        db.executemany("INSERT INTO pages VALUES (?, ?, ?)", page_text)
    return doc_id, len(page_text), "indexed"
