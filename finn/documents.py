"""Index operator-supplied public PDFs. The HTTP application only reads this index."""
import hashlib
import os
import re
import sqlite3
import uuid
import json
import time
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9&.-]{0,24}")
KINDS = {"annual_report": "Annual report", "transcript": "Earnings call"}
MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 800
PARSER_VERSION = "pdfium-text-1"
INDEX_CACHE_SECONDS = 6 * 3600


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


def limits():
    from .runtime import public_demo
    # Complete annual reports often exceed 600 pages. Keep the same bounded page
    # coverage in both modes; public downloads retain their smaller byte budget.
    return (20 * 1024 * 1024 if public_demo() else MAX_BYTES, MAX_PAGES)


def original_path(digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid document revision.")
    return database_path().parent / "originals" / (digest + ".pdf")


def retain_original(raw, digest, quota=None):
    from .runtime import public_demo
    folder = database_path().parent / "originals"
    folder.mkdir(parents=True, exist_ok=True)
    if quota is None:
        quota = (64 if public_demo() else 256) * 1024 * 1024
    target = original_path(digest)
    if len(raw) > quota:
        return
    if not target.exists():
        temporary = folder / (uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(raw)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    target.touch()
    files = sorted(folder.glob("*.pdf"), key=lambda p:p.stat().st_mtime)
    size = sum(p.stat().st_size for p in files)
    for file in files:
        if size <= quota:
            break
        if file != target:
            size -= file.stat().st_size
            file.unlink(missing_ok=True)


def cached_url(doc_id, digest):
    return "/api/documents/" + doc_id + "/original?revision=" + digest if original_path(digest).is_file() else None


def cached_original(doc_id, revision=None):
    with read_snapshot() as db:
        if db is None:
            return None
        row = db.execute("SELECT id,symbol,digest FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return None
        digest = revision or row["digest"]
        if digest != row["digest"]:
            has_history = db.execute("SELECT 1 FROM sqlite_master WHERE name='document_versions'").fetchone()
            if not has_history or not db.execute("SELECT 1 FROM document_versions WHERE doc_id=? AND digest=?", (doc_id,digest)).fetchone():
                return None
        path = original_path(digest)
        if not path.is_file():
            return None
        path.touch()
        return path, row["symbol"] + "-" + digest[:8] + ".pdf"


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


def for_symbol(symbol, include_pages, include_revision=False):
    with read_snapshot() as db:
        if db is None:
            return [], []
        records = db.execute(
            "SELECT id, symbol, title, kind, published AS date, url,digest FROM documents "
            "WHERE symbol=? ORDER BY published DESC, id", (symbol,)
        ).fetchall()
        passages = []
        if include_pages:
            passages = db.execute(
                "SELECT p.doc_id, p.page, p.body FROM pages p JOIN documents d ON d.id=p.doc_id "
                "WHERE d.symbol=? ORDER BY d.published DESC, d.id, p.page", (symbol,)
            ).fetchall()
        result = [dict(r) for r in records]
        for row in result:
            cached = cached_url(row["id"], row["digest"])
            if cached:
                row["cached_url"] = cached
            if not include_revision:
                row.pop("digest")
        if include_revision:
            has_versions = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_parsers'").fetchone()
            versions = {r[0]: r[1] for r in db.execute("SELECT doc_id,version FROM document_parsers")} if has_versions else {}
            for row in result:
                row["parser_version"] = versions.get(row["id"], "legacy")
        return result, [dict(p) for p in passages]


def cached_index(symbol, kind, title, url, published="", max_age=INDEX_CACHE_SECONDS):
    """Reuse a recently checked exact source, without downloading it again."""
    doc_id = "local-" + hashlib.sha256((ticker(symbol) + "|" + source_url(url)).encode()).hexdigest()[:24]
    with read_snapshot() as db:
        if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='document_checked'").fetchone():
            return None
        row = db.execute("""SELECT d.kind,d.title,d.published,p.version,c.at FROM documents d
            JOIN document_parsers p ON p.doc_id=d.id JOIN document_checked c ON c.doc_id=d.id
            WHERE d.id=?""", (doc_id,)).fetchone()
        if (row is None or tuple(row[:4]) != (KINDS[kind], title.strip(), published, PARSER_VERSION)
                or row[4] < time.time() - max_age):
            return None
        pages = db.execute("SELECT COUNT(*) FROM pages WHERE doc_id=?", (doc_id,)).fetchone()[0]
        return {"pages": pages, "checked_at": row[4]} if pages else None


def import_pdf(file, symbol, kind, title, url, published, *, progress=None):
    from . import pdf_text, runtime

    symbol = ticker(symbol)
    url = source_url(url)
    title = title.strip()
    if kind not in KINDS or not (0 < len(title) <= 240):
        raise ValueError("Select an annual report or transcript and provide a document title.")
    if published:
        publication_date = date.fromisoformat(published)
        if publication_date > date.today():
            raise ValueError("The publication date must be today or earlier.")
        published = publication_date.isoformat()
    else:
        # Discovery knows the reporting-period label, while an exact release
        # date may be absent from the link index. Preserve that uncertainty.
        published = ""
    path = Path(file)
    max_bytes, max_pages = limits()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The PDF file is empty or unavailable.")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"The PDF exceeds FINN's {max_bytes // (1024*1024)} MiB file-size limit.")
    raw = path.read_bytes()
    if b"%PDF-" not in raw[:1024]:
        raise ValueError("The source is not a PDF original.")
    digest = hashlib.sha256(raw).hexdigest()
    doc_id = "local-" + hashlib.sha256((symbol + "|" + url).encode()).hexdigest()[:24]
    cached_count = None
    with read_snapshot() as existing:
        if existing is not None and existing.execute("SELECT 1 FROM sqlite_master WHERE name='document_parsers'").fetchone():
            cached = existing.execute("SELECT d.digest,d.kind,d.title,d.published,v.version FROM documents d "
                                      "JOIN document_parsers v ON v.doc_id=d.id WHERE d.id=?", (doc_id,)).fetchone()
            if cached and tuple(cached) == (digest, KINDS[kind], title, published, PARSER_VERSION):
                cached_count = existing.execute("SELECT COUNT(*) FROM pages WHERE doc_id=?", (doc_id,)).fetchone()[0]
    if cached_count is not None:
        retain_original(raw, digest)
        # Commit after the read snapshot closes, so the writer never waits on itself.
        with sqlite3.connect(database_path()) as writer:
            writer.execute("CREATE TABLE IF NOT EXISTS document_checked (doc_id TEXT PRIMARY KEY,at REAL NOT NULL)")
            writer.execute("INSERT OR REPLACE INTO document_checked VALUES(?,?)", (doc_id, time.time()))
        return doc_id, cached_count, "already indexed"
    # The worker must parse the same immutable bytes used for the digest/citation.
    rows = pdf_text.extract(raw, max_pages, progress=progress, timeout=180 if runtime.public_demo() else 300)
    page_text = [(doc_id, number, body) for number, body in rows]
    retain_original(raw, digest)

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
        db.execute("CREATE TABLE IF NOT EXISTS document_parsers (doc_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,version TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS document_checked (doc_id TEXT PRIMARY KEY,at REAL NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS document_versions (doc_id TEXT NOT NULL,digest TEXT NOT NULL,metadata TEXT NOT NULL,PRIMARY KEY(doc_id,digest))")
        old = db.execute("SELECT digest, kind, title, published FROM documents WHERE id=?",
                         (doc_id,)).fetchone()
        db.execute("""INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, title=excluded.title,
            published=excluded.published, digest=excluded.digest""",
                   (doc_id, symbol, KINDS[kind], title, published, url, digest))
        db.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
        db.executemany("INSERT INTO pages VALUES (?, ?, ?)", page_text)
        db.execute("INSERT INTO document_parsers VALUES(?,?) ON CONFLICT(doc_id) DO UPDATE SET version=excluded.version", (doc_id, PARSER_VERSION))
        db.execute("INSERT OR REPLACE INTO document_checked VALUES(?,?)", (doc_id, time.time()))
        db.execute("INSERT OR IGNORE INTO document_versions VALUES(?,?,?)", (doc_id,digest,json.dumps({"url":url,"title":title,"published":published})))
    return doc_id, len(page_text), "indexed"
