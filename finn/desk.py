"""Portfolio ranking, dated evidence comparisons and explicitly recorded connections."""
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from . import documents

DATA = Path(__file__).parent / "data"
REPLAY_END = date(2025, 4, 17)


def load(name):
    return json.loads((DATA / (name + ".json")).read_text(encoding="utf-8"))


COMPANIES = {c["symbol"]: c for c in load("companies")}
SOURCES = {s["id"]: s for s in load("sources")}
RESEARCH = load("research")
FILINGS = load("filings")
NETWORK = load("network")
PEOPLE = {p["id"]: p for p in NETWORK["people"]}
RULES = {
    "results": (1, "Material", "Published financial results"),
    "notice": (3, "Routine", "Meeting notice"),
    "compliance": (4, "Routine", "Periodic compliance filing"),
}
STOP = set("who whom should can could i me my the a an in at by how to of and is are what with does "
           "know knows worked work has for about tell help understand us we on did which from "
           "network someone contacts contact experience".split())


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.casefold())) - STOP


def short_source(source):
    return {**source, "date": source.get("date") or "Publication date unverified",
            "page": source.get("page"), "locator": source.get("locator", ""),
            "excerpt": source.get("excerpt", "")}


def all_companies():
    from . import workspaces
    held = set(workspaces.holdings()) if workspaces.current() is not None else {c["symbol"] for c in COMPANIES.values() if c["holding"]}
    known = [{**c, "holding": c["symbol"] in held} for c in COMPANIES.values()]
    extra = set(documents.symbols()) | held
    return known + [
        {"symbol": s, "name": s, "sector": "Imported documents", "holding": False}
        | {"holding": s in held} for s in sorted(extra) if s not in COMPANIES
    ]




def people(query="", symbol=""):
    from . import network
    return network.people(query, symbol)


def distance(actual, lower, upper):
    a, lo, hi = [Decimal(str(n)) for n in (actual, lower, upper)]
    if lo > hi:
        raise ValueError("Forecast lower bound exceeds its upper bound.")
    if a < lo:
        return {"position": "below", "points": float(lo-a)}
    if a > hi:
        return {"position": "above", "points": float(a-hi)}
    return {"position": "within", "points": 0.0}


def comparison(symbol):
    series = next((s for s in RESEARCH["series"] if s["symbol"] == symbol), None)
    if not series:
        return None
    # A series owns its metric, period, unit and consolidation basis. Its
    # forecast rows therefore cannot be paired with another period's outcome.
    actual = series["actual"]
    forecasts = []
    for row in series["forecasts"]:
        source = SOURCES[row["source"]]
        if source["date"] >= SOURCES[actual["source"]]["date"]:
            continue
        forecasts.append({**row, "source": source,
                          **distance(actual["value"], row["low"], row["high"])})
    forecasts.sort(key=lambda f: f["source"]["date"])
    return {**series, "actual": {**actual, "source": SOURCES[actual["source"]]},
            "forecasts": forecasts}


def brief(window="24h", start=None, end=None):
    from . import workspaces
    held = set(workspaces.holdings()) if workspaces.current() is not None else {c["symbol"] for c in COMPANIES.values() if c["holding"]}
    if window == "custom":
        if not start or not end or start > end or end > REPLAY_END:
            raise ValueError("Choose a valid range ending on or before 17 April 2025.")
    else:
        if window not in {"24h", "7d"}:
            raise ValueError("Choose 24h, 7d or custom.")
        end = REPLAY_END
        start = end if window == "24h" else end - timedelta(days=6)
    rows = []
    for filing in FILINGS:
        source = SOURCES[filing["source"]]
        day = date.fromisoformat(source["date"])
        company = COMPANIES[source["symbol"]]
        if company["symbol"] not in held or not start <= day <= end:
            continue
        if filing.get("enrichment"):
            source = {**source, "related": SOURCES[filing["enrichment"]]}
        rank, priority, reason = RULES[filing["category"]]
        rows.append({**filing, "source": source, "symbol": company["symbol"],
                     "company": company["name"], "date": source["date"], "rank": rank,
                     "priority": priority, "reason": reason})
    rows.sort(key=lambda r: (r["rank"], -date.fromisoformat(r["date"]).toordinal(), r["symbol"]))
    feature = next((r for r in rows if r["priority"] == "Material"), None)
    focus = feature["symbol"] if feature else None
    return {"as_of": REPLAY_END, "start": start, "end": end, "rows": rows, "focus": focus,
            "comparison": comparison(focus), "people": people(symbol=focus)[:2] if focus else [],
            "holdings": len(held)}


def snippet(body, tokens, limit=260):
    if len(body) <= limit:
        return body
    # Start near a matched word, keeping words at snippet boundaries intact.
    hit = next((m.start() for m in re.finditer(r"[a-z0-9]+", body.casefold())
                if m.group() in tokens), 0)
    start = max(0, hit-60)
    if start:
        start = body.rfind(" ", 0, start) + 1
    stop = start + limit
    if stop < len(body):
        cut = body.rfind(" ", start + 1, stop)
        if cut > start:
            stop = cut
    return ("…" if start else "") + body[start:stop].strip() + ("…" if stop < len(body) else "")


def research(symbol, query=""):
    symbol = documents.ticker(symbol)
    company = COMPANIES.get(symbol, {"symbol": symbol, "name": symbol, "sector": "", "holding": False})
    snapshot = next((s for s in RESEARCH["snapshots"] if s["symbol"] == symbol), None)
    sources = [short_source(s) for s in SOURCES.values() if s["symbol"] == symbol and
               s["kind"] in {"Annual report", "Earnings call"}]
    tokens = words(query)
    records, indexed_pages = documents.for_symbol(symbol, include_pages=bool(tokens))
    if tokens:
        # BM25 narrows hundreds of report pages to the best candidates before snippet ranking.
        best = documents.search(symbol, sorted(tokens))
        if best is not None:
            keep = set(best)
            indexed_pages = [p for p in indexed_pages if (p["doc_id"], p["page"]) in keep]
    imported = {s["id"]: short_source(s) for s in records}
    passages = []
    for s in sources:
        if s["excerpt"]:
            passages.append((s, s["excerpt"]))
        elif snapshot and snapshot["source"] == s["id"]:
            passages.append(({**s, "excerpt_type": "summary"}, snapshot["text"]))
    for page in indexed_pages:
        source = imported.get(page["doc_id"])
        if source:
            passages.append(({**source, "page": page["page"]}, page["body"]))
    hits = []
    if tokens:
        for s, text in passages:
            overlap = tokens & words(text)
            if overlap:
                phrase = query.strip().casefold() in text.casefold()
                hits.append(((len(overlap), phrase), {**s, "excerpt": snippet(text, tokens)}))
        hits.sort(key=lambda hit: hit[0], reverse=True)
    return {"company": company, "snapshot": {**snapshot, "source": SOURCES[snapshot["source"]]} if snapshot else None,
            "comparison": comparison(symbol), "sources": [*sources, *imported.values()],
            "matches": [v for _, v in hits[:8]], "query": query,
            "people": people(symbol=symbol)[:3], "imported": len(imported)}
