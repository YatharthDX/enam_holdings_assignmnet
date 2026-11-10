"""Discover issuer documents via public link metadata and index the originals."""
import hashlib
import ipaddress
import json
import socket
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from pypdf.errors import PyPdfError

from . import documents, live, live_store as store, providers

LIMIT = 5


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    parent: object = None
    children: list = field(default_factory=list)

    def text(self):
        return " ".join(child if isinstance(child, str) else child.text() for child in self.children).strip()


class DocumentPage(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node.parent and node.tag != tag:
            node = node.parent
        if node.parent:
            self.current = node.parent

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, dict(attrs), self.current))

    def handle_data(self, text):
        self.current.children.append(text)


def nodes(root):
    for child in root.children:
        if isinstance(child, Node):
            yield child
            yield from nodes(child)


def public_url(value, resolve=False):
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        port = parts.port
    except ValueError as exc:
        raise providers.SourceError("Document link is invalid.") from exc
    if parts.scheme != "https" or parts.username or parts.password or port not in {None, 443}:
        raise providers.SourceError("Documents must have a public HTTPS address.")
    if "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise providers.SourceError("Document link is not a public host.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise providers.SourceError("Document link points to a private address.")
    if resolve:
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise providers.SourceError("Document host could not be resolved.") from exc
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise providers.SourceError("Document host does not resolve to public addresses.")
    return value


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl, resolve=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_public(url):
    public_url(url, resolve=True)
    return providers.request_bytes(url, build_opener(PublicRedirect()), limit=documents.limits()[0])


def parse_links(body, symbol, page_url):
    parser = DocumentPage()
    parser.feed(body.decode("utf-8"))
    issuer_verified = any(
        node.tag == "a" and "".join(node.text().upper().split()) == "NSE:" + symbol
        for node in nodes(parser.root)
    )
    if not issuer_verified:
        raise providers.SourceError("The document index could not be matched to the requested NSE symbol.")
    heading = ""
    found = []
    seen = set()
    for node in nodes(parser.root):
        if node.tag in {"h2", "h3"}:
            heading = " ".join(node.text().casefold().split())
        if node.tag != "a":
            continue
        label = " ".join(node.text().split())
        if heading == "annual reports" and "annual report" in label.casefold():
            kind = "annual_report"
        elif heading == "concalls" and label.casefold() == "transcript":
            kind = "transcript"
        else:
            continue
        try:
            url = public_url(urljoin(page_url, node.attrs.get("href", "")))
        except providers.SourceError:
            continue
        if url in seen or not urlsplit(url).path.casefold().endswith(".pdf"):
            continue
        ancestor = node
        while ancestor.parent and ancestor.tag != "li":
            ancestor = ancestor.parent
        context = " ".join(ancestor.text().split())
        if len(context) > 200:
            context = label
        title = label if kind == "annual_report" else context.split("Transcript")[0].strip() + " earnings-call transcript"
        found.append({"kind": kind, "url": url, "title": symbol + " · " + title,
                      "period_label": context, "published": None})
        seen.add(url)
    annual = [row for row in found if row["kind"] == "annual_report"][:1]
    calls = [row for row in found if row["kind"] == "transcript"][:4]
    return annual + calls


def discover_links(symbol, fetch=fetch_public):
    last_error = None
    for suffix in ("/consolidated/", "/"):
        page = "https://www.screener.in/company/" + quote(symbol, safe="") + suffix
        try:
            body = fetch(page)
            links = parse_links(body, symbol, page)
            if links:
                return links
            last_error = "No PDF annual reports or call transcripts were found on the public page."
        except providers.SourceError as exc:
            # An access rejection is reported without probing alternate page routes.
            if "HTTP" in str(exc):
                raise
            last_error = str(exc)
    raise providers.SourceError(last_error or "No primary document links were found.")


def status(symbol):
    with store.connection() as db:
        row = db.execute("SELECT * FROM document_jobs WHERE symbol=?", (symbol,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["sources"] = json.loads(result.pop("sources_json"))
    if result["status"] == "running" and result["expires"] < providers.iso(live.clock()):
        result["status"] = "interrupted"
        result["detail"] = "Indexing was interrupted. Retry discovery."
    result.pop("token")
    result.pop("expires")
    return result


def begin(symbol):
    from . import runtime
    symbol = documents.ticker(symbol)
    now = live.clock()
    token = hashlib.sha256((symbol + providers.iso(now)).encode()).hexdigest()[:24]
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT * FROM document_jobs WHERE symbol=?", (symbol,)).fetchone()
        if previous and previous["status"] == "running" and previous["expires"] > providers.iso(now):
            return None
        busy = db.execute("SELECT COUNT(*) FROM document_jobs WHERE status='running' AND expires>?",
                          (providers.iso(now),)).fetchone()[0]
        limit = 1 if runtime.public_demo() else 2
        if busy >= limit:
            raise ValueError("Document lookups are busy. Try again when one finishes.")
        db.execute("""INSERT INTO document_jobs VALUES(?, ?, 'running', ?, NULL, ?, ?, '[]')
            ON CONFLICT(symbol) DO UPDATE SET token=excluded.token, status='running',
            started=excluded.started, finished=NULL, expires=excluded.expires, detail=excluded.detail""",
                   (symbol, token, providers.iso(now), providers.iso(now + timedelta(minutes=10)),
                    "Locating original annual reports and call transcripts…"))
    return token


@contextmanager
def keep_lease(symbol, token):
    def renew():
        with store.connection() as db:
            return db.execute("UPDATE document_jobs SET expires=? WHERE symbol=? AND token=? AND status='running'",
                              (providers.iso(live.clock() + timedelta(minutes=10)), symbol, token)).rowcount == 1
    if not renew():
        yield False
        return
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(20):
            try:
                if not renew():
                    return
            except Exception:
                pass
    thread = threading.Thread(target=heartbeat, name="finn-document-lease", daemon=True)
    thread.start()
    try:
        yield True
    finally:
        stopped.set()
        thread.join(timeout=1)


def run(symbol, token, fetch=fetch_public):
    with keep_lease(symbol, token) as owned:
        if owned:
            _run(symbol, token, fetch)


def _run(symbol, token, fetch=fetch_public):
    errors, indexed = [], 0
    candidates = []
    try:
        candidates = discover_links(symbol, fetch)
        with store.connection() as db:
            db.execute("UPDATE document_jobs SET sources_json=?, detail=? WHERE symbol=? AND token=?",
                       (json.dumps(candidates), f"Found {len(candidates)} originals; indexing their pages…",
                        symbol, token))
        for candidate in candidates:
            try:
                with store.connection() as db:
                    owned = db.execute("SELECT 1 FROM document_jobs WHERE symbol=? AND token=? AND status='running'", (symbol, token)).fetchone()
                if not owned:
                    return
                body = fetch(candidate["url"])
                with store.connection() as db:
                    if not db.execute("SELECT 1 FROM document_jobs WHERE symbol=? AND token=? AND status='running'", (symbol,token)).fetchone():
                        return
                if not body.lstrip().startswith(b"%PDF-"):
                    raise providers.SourceError("The source did not return a PDF.")
                with tempfile.TemporaryDirectory(prefix="finn-doc-") as folder:
                    path = Path(folder) / "primary.pdf"
                    path.write_bytes(body)
                    _, pages, _ = documents.import_pdf(path, symbol, candidate["kind"], candidate["title"],
                                                      candidate["url"], published="")
                    candidate.update(index_status="indexed", pages=pages, error=None)
                indexed += 1
            except (providers.SourceError, PyPdfError, ValueError, OSError) as exc:
                errors.append(candidate["title"] + ": " + str(exc))
                candidate.update(index_status="error", error=str(exc)[:300])
            with store.connection() as db:
                db.execute("UPDATE document_jobs SET expires=? WHERE symbol=? AND token=?",
                           (providers.iso(live.clock() + timedelta(minutes=10)), symbol, token))
                db.execute("UPDATE document_jobs SET sources_json=? WHERE symbol=? AND token=?", (json.dumps(candidates), symbol, token))
    except providers.SourceError as exc:
        errors.append(str(exc))
    except Exception:
        live.LOGGER.exception("Document discovery failed for %s", symbol)
        errors.append("Document indexing was interrupted. Existing sources are still available.")
    detail = f"Indexed {indexed} of {len(candidates)} documents."
    if errors:
        detail += " " + " ".join(errors)
    with store.connection() as db:
        db.execute("UPDATE document_jobs SET status=?, finished=?, detail=? WHERE symbol=? AND token=?",
                   ("partial" if indexed and errors else "complete" if indexed else "error",
                    providers.iso(live.clock()), detail[:2400], symbol, token))
