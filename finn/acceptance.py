"""Exercise disposable private sessions and optional real-ticker discovery, never a model."""
import argparse
import json
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from . import documents, smoke


class AcceptanceError(ValueError):
    pass


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.csrf = None

    def call(self, path, *, method="GET", value=None):
        headers = {"Accept": "application/json"}
        if self.csrf and method != "GET":
            headers["X-FINN-CSRF"] = self.csrf
        body = json.dumps(value).encode() if value is not None else None
        if body:
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            raise AcceptanceError(path.split("?")[0] + " returned HTTP " + str(exc.code)) from None
        except (URLError, OSError, ValueError):
            raise AcceptanceError("Unable to read " + path.split("?")[0] + ". Check service startup and connectivity.") from None

    def start(self):
        result = self.call("/api/session?disposable=true", method="POST", value={})
        self.csrf = result["csrf"]


def run(base_url, *, ticker=None, query="revenue", allow_cached=False, wait_seconds=240):
    checks = smoke.run(base_url)
    clients = []
    report = {"status": "passed", "scope": "core_sessions" if not ticker else "core_sessions_and_ticker",
              "core_checks": checks, "generation_requests": 0, "private_isolation": False,
              "ticker": None, "notes": ["This does not reconcile a live exchange window or prove automatic financial interpretation."]}
    try:
        first, second = Client(base_url), Client(base_url)
        for client in (first, second):
            client.start()
            clients.append(client)
        marker = "Disposable acceptance note; synthetic profile only."
        first.call("/api/people/mira/note", method="PUT", value={"note": marker, "last_contact": "2025-01-01"})
        a, b = first.call("/api/people?q=Mira"), second.call("/api/people?q=Mira")
        if not any(p.get("note") == marker for p in a["people"]) or any(p.get("note") == marker for p in b["people"]):
            raise AcceptanceError("Two browser workspaces did not isolate their private notes.")
        report["private_isolation"] = True
        if ticker:
            symbol = documents.ticker(ticker)
            catalog = first.call("/api/catalog")
            if symbol in catalog.get("seed_symbols", []):
                raise AcceptanceError("Choose a ticker outside the built-in demo universe.")
            previous = first.call("/api/research/" + symbol)
            cold = not previous["sources"]
            if not cold and not allow_cached:
                raise AcceptanceError("This ticker already has evidence. Choose another for a clean-cache test, or explicitly use --allow-cached.")
            first.call("/api/research/" + symbol + "/discover", method="POST", value={})
            deadline = time.monotonic() + wait_seconds
            while True:
                state = first.call("/api/research/" + symbol + "/discovery")["job"]
                if state and state["status"] != "running":
                    break
                if time.monotonic() >= deadline:
                    raise AcceptanceError("Indexing exceeded the acceptance wait. Inspect its status in Research; no automatic retry was issued.")
                time.sleep(.5)
            from urllib.parse import urlencode
            data = first.call("/api/research/" + symbol + "?" + urlencode({"q": query}))
            brief = data["structured"]["brief"]
            evidence = [p for group in brief["groups"] for p in group["passages"]]
            if not data["imported"] or not evidence or state["status"] in {"error", "interrupted"}:
                raise AcceptanceError("No fresh cited source brief was available. Inspect document coverage and source access errors.")
            if state["status"] == "partial":
                report["status"] = "partial"
            if not data["matches"]:
                report["status"] = "partial"
                report["notes"].append("The selected search phrase had no page matches. Inspect an original and repeat with a phrase from it.")
            report["ticker"] = {"symbol": symbol, "cold_cache": cold, "index_status": state["status"],
                                "indexed_documents": data["imported"], "selected_passages": len(evidence),
                                "query": query, "search_matches": len(data["matches"]),
                                "example": {"url": evidence[0]["source"]["url"], "page": evidence[0]["source"]["page"]},
                                "coverage": [{"title": s["title"], "status": s.get("index_status", "unknown"),
                                              "error": s.get("error")} for s in state.get("sources", [])]}
        return report
    finally:
        for client in clients:
            try:
                client.call("/api/workspace", method="DELETE")
            except AcceptanceError:
                report.setdefault("notes", []).append("A disposable session could not be erased immediately; its 24-hour expiry still applies.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sessions-only", action="store_true", help="No upstream requests: test core views and private-session isolation.")
    mode.add_argument("--ticker", help="Request discovery for an unseeded NSE ticker; public network access required.")
    parser.add_argument("--query", default="revenue")
    parser.add_argument("--allow-cached", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=240)
    args = parser.parse_args(argv)
    try:
        if not 10 <= args.wait_seconds <= 600:
            raise AcceptanceError("Wait must be between 10 and 600 seconds.")
        report = run(args.base_url, ticker=args.ticker, query=args.query, allow_cached=args.allow_cached, wait_seconds=args.wait_seconds)
    except (AcceptanceError, smoke.SmokeError) as exc:
        print(json.dumps({"status": "failed", "detail": str(exc), "generation_requests": 0}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
