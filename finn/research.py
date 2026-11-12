"""Key-free extractive research and explicitly reviewed, comparable facts."""
import hashlib
import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from . import desk, documents, live_store as store, workspaces, runtime

THEMES = {
    "business": ("Business and revenue drivers", ["business overview", "principal activities", "our business", "segments", "customers", "products", "services"]),
    "guidance": ("Management outlook", ["guidance", "outlook", "we expect", "we anticipate", "target", "forecast"]),
    "cash": ("Cash and funding", ["cash flow", "cash flows", "working capital", "borrowings", "operating activities", "debt"]),
    "risk": ("Risks and constraints", ["risk management", "principal risks", "risks", "uncertainty", "headwinds"]),
}
METRICS = {"revenue_growth": "Revenue growth", "operating_margin": "Operating margin", "capex": "Capital expenditure",
           "revenue": "Revenue", "ebitda": "EBITDA", "pbt": "Profit before tax", "pat": "Profit after tax",
           "operating_cash_flow": "Operating cash flow", "debt": "Debt"}
UNITS = {"%", "INR crore", "INR million", "USD million", "USD billion"}
SCOPES = {"consolidated", "standalone", "not_stated"}
BASES = {"constant_currency", "INR", "USD", "not_stated"}


def compact(value):
    return " ".join(value.split())


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Use a finite decimal number.")
    try:
        parsed = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        raise ValueError("Use a finite decimal number.") from None
    if not parsed.is_finite() or len(parsed.as_tuple().digits) > 18 or abs(parsed) > Decimal("1e15"):
        raise ValueError("Use a finite decimal number within the supported range.")
    return parsed


def period(value):
    if not isinstance(value, str):
        raise ValueError("Choose an explicit fiscal period, such as FY25 or Q4 FY25.")
    cleaned = compact(value.upper())
    match = re.fullmatch(r"(?:(Q[1-4])\s*)?FY(?:20)?(\d{2})", cleaned)
    if not match:
        raise ValueError("Choose an explicit fiscal period, such as FY25 or Q4 FY25.")
    return ((match[1] + " ") if match[1] else "") + "FY" + match[2]


def corpus(symbol, as_of=None):
    records, pages = documents.for_symbol(symbol, include_pages=True, include_revision=True)
    if records:
        by_id = {r["id"]: {**desk.short_source(r), "revision": r["digest"] + ":" + r["parser_version"]} for r in records}
        items = [{"source": {**by_id[p["doc_id"]], "page": p["page"]}, "text": p["body"]} for p in pages]
        kind = "indexed_originals"
    else:
        items = [{"source": {**desk.short_source(s), "revision": hashlib.sha256(s["excerpt"].encode()).hexdigest()}, "text": s["excerpt"]}
                 for s in desk.SOURCES.values() if s["symbol"] == symbol and s.get("excerpt") and s.get("page")
                 and s["kind"] in {"Annual report", "Earnings call"}]
        kind = "historical_excerpts" if items else "none"
    excluded = 0
    if as_of:
        date.fromisoformat(as_of)
        kept = [p for p in items if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["source"]["date"]) and p["source"]["date"] <= as_of]
        excluded = len(items) - len(kept)
        items = kept
    return items, kind, excluded


def passages(symbol, as_of=None):
    pages, kind, excluded = corpus(symbol, as_of)
    groups = []
    for key, (title, terms) in THEMES.items():
        ranked = []
        candidates = pages
        if kind == "indexed_originals":
            best = documents.search(symbol, terms, limit=30)
            if best:
                keep = set(best)
                candidates = [p for p in pages if (p["source"]["id"], p["source"]["page"]) in keep]
        for page in candidates:
            body, lower = compact(page["text"]), page["text"].casefold()
            hits = [(lower.find(term), term) for term in terms if term in lower]
            if not hits:
                continue
            hit = min(hits)[0]
            boundary = body.rfind(". ", 0, hit)
            start = boundary + 2 if boundary >= 0 else 0
            # Preserve an exact contiguous passage. No generated paraphrase is presented as a quote.
            quote = body[start:start + 900]
            if len(quote) == 900 and " " in quote:
                quote = quote[:quote.rfind(" ")]
            score = len(hits) + sum(4 for _, term in hits if len(term.split()) > 1)
            ranked.append((score, page["source"]["date"], {"text": quote, "source": {**page["source"], "excerpt": quote}}))
        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        chosen, documents_used = [], set()
        for _, _, item in ranked:
            identity = item["source"]["id"]
            if identity in documents_used and len(chosen) >= 1:
                continue
            chosen.append(item)
            documents_used.add(identity)
            if len(chosen) == 3:
                break
        groups.append({"id": key, "title": title, "passages": chosen})
    return {"corpus": kind, "documents": len({p["source"]["id"] for p in pages}), "pages": len(pages),
            "as_of": as_of, "excluded_pages": excluded, "groups": groups,
            "method": "Exact passages selected by section/topic terms. Selection is partial; inspect the original context."}


def candidates(symbol, as_of=None):
    pages, _, _ = corpus(symbol, as_of)
    results = []
    pattern = re.compile(r"(?:guidance|guide|expect|forecast|reported|achieved|delivered|closed).{0,200}?\d+(?:\.\d+)?\s*%", re.I)
    for page in pages:
        body = compact(page["text"])
        for match in pattern.finditer(body):
            boundary = body.rfind(". ", 0, match.start())
            start = boundary + 2 if boundary >= 0 else 0
            end = body.find(". ", match.end())
            quote = body[start:min(end + 1 if end >= 0 else len(body), start + 1100)]
            prefix = body[max(0, start - 180):match.start()]
            marker = list(re.finditer(r"\b(Analyst|Participant|Operator|Management|CEO|CFO)\s*:", prefix, re.I))
            speaker = marker[-1][1] if marker else "Unidentified"
            question = speaker.casefold() in {"analyst", "participant", "operator"} or quote.rstrip().endswith("?")
            suggested = suggest_fields(quote)
            results.append({"quote": quote, "source": {**page["source"], "excerpt": quote},
                            "speaker": speaker, "speaker_kind": "question" if question else "management" if marker else "unidentified",
                            "state": "Needs review", "suggested": suggested,
                            "kind": "guidance" if re.search(r"guid|expect|forecast", quote, re.I) else "actual"})
            if len(results) >= 12:
                return results
    return results


def suggest_fields(quote):
    """Conservative conveniences for a human review, never accepted facts."""
    lower = quote.casefold()
    result = {}
    if "revenue" in lower and "growth" in lower:
        result["metric"] = "revenue_growth"
    elif "operating margin" in lower:
        result["metric"] = "operating_margin"
    values = re.findall(r"(-?\d+(?:\.\d+)?)\s*%", quote)
    if len(values) == 1:
        result.update(low=values[0], high=values[0], unit="%")
    elif len(values) == 2 and re.search(r"%\s*(?:to|and|[-–])\s*-?\d", quote, re.I):
        result.update(low=values[0], high=values[1], unit="%")
    fiscal = set(re.findall(r"\bFY\s*['’]?(?:20)?(\d{2})\b", quote, re.I))
    if len(fiscal) == 1:
        q = re.search(r"\bQ([1-4])\s+FY", quote, re.I)
        result["period"] = ("Q" + q[1] + " " if q else "") + "FY" + next(iter(fiscal))
    scopes = [s for s in ("consolidated", "standalone") if s in lower]
    if len(scopes) == 1:
        result["scope"] = scopes[0]
    if "constant currency" in lower:
        result["basis"] = "constant_currency"
    elif "rupee" in lower or "inr" in lower or "₹" in quote:
        result["basis"] = "INR"
    elif "usd" in lower or "us dollar" in lower:
        result["basis"] = "USD"
    return result


def source_for(symbol, source_id, page):
    items, _, _ = corpus(symbol)
    found = next((p for p in items if p["source"]["id"] == source_id and p["source"]["page"] == page), None)
    if found:
        return found
    source = desk.SOURCES.get(source_id)
    if source and source["symbol"] == symbol and source.get("page") == page and source.get("excerpt") and source["kind"] in {"Annual report", "Earnings call"}:
        return {"source": {**desk.short_source(source), "revision": hashlib.sha256(source["excerpt"].encode()).hexdigest()}, "text": source["excerpt"]}
    return None


def save_fact(symbol, value):
    if not isinstance(value, dict) or value.get("reviewed") is not True:
        raise ValueError("Review the source and explicitly confirm the fact fields.")
    if value.get("kind") not in {"guidance", "actual", "qualitative"} or value.get("metric") not in METRICS:
        raise ValueError("Choose a supported fact kind and metric.")
    if type(value.get("page")) is not int or value["page"] < 1:
        raise ValueError("Choose an explicit PDF page number.")
    source = source_for(symbol, value.get("source_id"), value.get("page"))
    if not source:
        raise ValueError("Choose a current source page indexed for this ticker.")
    quote = value.get("quote")
    if not isinstance(quote, str) or not 16 <= len(quote) <= 1200 or compact(quote) not in compact(source["text"]):
        raise ValueError("The exact quote must occur on the selected source page.")
    if value.get("speaker_kind") != "management" and value["kind"] == "guidance":
        raise ValueError("An analyst question or unidentified speaker cannot become management guidance.")
    speaker = value.get("speaker", "").strip()
    if not speaker or len(speaker) > 100:
        raise ValueError("Record the speaker or reporting authority you reviewed.")
    if value.get("unit") not in UNITS or value.get("scope") not in SCOPES or value.get("basis") not in BASES:
        raise ValueError("Record the unit, accounting scope and currency basis explicitly.")
    fiscal = period(value.get("period"))
    if value.get("published"):
        published = date.fromisoformat(value["published"])
        if published > date.today():
            raise ValueError("Publication date cannot be in the future.")
        known = source["source"]["date"]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", known) and published.isoformat() != known:
            raise ValueError("Use the indexed publication date for this source.")
        published = published.isoformat()
    else:
        published = source["source"]["date"] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["source"]["date"]) else ""
    low = high = None
    if value["kind"] != "qualitative":
        low, high = number(value.get("low")), number(value.get("high", value.get("low")))
        literals = {number(m) for m in re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?", compact(quote))}
        literals.update(-number(m) for m in re.findall(r"\(\s*(\d[\d,]*(?:\.\d+)?)\s*%?\s*\)", compact(quote)))
        if low not in literals or high not in literals:
            raise ValueError("Every fact value must appear literally in its source quote; no inferred figures.")
        if low > high or value["kind"] == "actual" and low != high:
            raise ValueError("Use an ordered guidance range or one actual value.")
    item = {"id": uuid.uuid4().hex, "symbol": symbol, "kind": value["kind"], "metric": value["metric"],
            "period": fiscal, "unit": value["unit"], "scope": value["scope"], "basis": value["basis"],
            "low": str(low) if low is not None else None, "high": str(high) if high is not None else None,
            "speaker": speaker, "speaker_kind": value.get("speaker_kind", "unidentified"), "published": published,
            "quote": compact(quote), "source": {**source["source"], "excerpt": compact(quote)},
            "revision": source["source"]["revision"], "reviewed": True}
    if published and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["source"]["date"]):
        item["source"]["date"] = published
        item["source"]["date_note"] = "Publication date explicitly reviewed in this workspace."
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM reviewed_facts WHERE workspace=?", (workspaces.current(),)).fetchone()[0] >= 400:
            raise ValueError("Keep at most 400 reviewed facts per demo workspace.")
        duplicate = db.execute("SELECT body FROM reviewed_facts WHERE workspace=? AND symbol=?", (workspaces.current(), symbol)).fetchall()
        identity = {k: item[k] for k in ("kind", "metric", "period", "unit", "scope", "basis", "low", "high", "quote")}
        for row in duplicate:
            old = json.loads(row[0])
            if old["source"]["id"] == item["source"]["id"] and old["revision"] == item["revision"] and all(old.get(k) == v for k, v in identity.items()):
                return old
        db.execute("INSERT INTO reviewed_facts VALUES(?,?,?,?)", (workspaces.current(), item["id"], symbol, json.dumps(item)))
    return item


def facts(symbol, as_of=None):
    if not workspaces.private():
        return []
    with store.connection() as db:
        rows = db.execute("SELECT body FROM reviewed_facts WHERE workspace=? AND symbol=?", (workspaces.current(), symbol)).fetchall()
    pages, _, _ = corpus(symbol)
    revisions = {(p["source"]["id"], p["source"]["page"]): p["source"]["revision"] for p in pages}
    for source in desk.SOURCES.values():
        if source["symbol"] == symbol and source.get("excerpt") and source.get("page"):
            revisions[(source["id"], source["page"])] = hashlib.sha256(source["excerpt"].encode()).hexdigest()
    result = []
    for row in rows:
        item = json.loads(row[0])
        if item["published"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["source"]["date"]):
            item["source"]["date"] = item["published"]
            item["source"]["date_note"] = "Publication date explicitly reviewed in this workspace."
        if item["source"]["id"].startswith("local-"):
            cached = documents.cached_url(item["source"]["id"], item["revision"].split(":")[0])
            if cached:
                item["source"]["cached_url"] = cached
            else:
                item["source"].pop("cached_url", None)
        item["stale"] = revisions.get((item["source"]["id"], item["source"]["page"])) != item["revision"]
        if as_of and (not item["published"] or item["published"] > as_of):
            continue
        result.append(item)
    return sorted(result, key=lambda f: (f["published"], f["id"]))


def compare(items):
    comparisons = []
    actuals = [f for f in items if f["kind"] == "actual" and not f.get("stale")]
    keys = ("metric", "period", "scope", "basis", "unit")
    for forecast in (f for f in items if f["kind"] == "guidance"):
        same_period = [a for a in actuals if a["metric"] == forecast["metric"] and a["period"] == forecast["period"]]
        matching = [a for a in same_period if all(a[k] == forecast[k] for k in keys)]
        result = {"forecast": forecast, "actual": None, "position": "pending", "points": None,
                  "reason": "No matching delivered result has been reviewed."}
        if forecast.get("stale"):
            result.update(position="not_comparable", reason="The source revision changed; review this forecast again.")
        elif forecast["scope"] == "not_stated" or forecast["basis"] == "not_stated":
            result.update(position="not_comparable", reason="Accounting scope and currency basis must both be explicit.")
        elif same_period and not matching:
            result.update(position="not_comparable", reason="The available result has a different scope, unit or currency basis.")
        elif matching:
            dated = [a for a in matching if a["published"] and forecast["published"] and a["published"] > forecast["published"]]
            if not dated:
                result.update(position="not_comparable", reason="Verified dates must establish that guidance preceded the outcome.")
            else:
                latest = max(a["published"] for a in dated)
                options = [a for a in dated if a["published"] == latest]
                if len({number(a["low"]) for a in options}) > 1:
                    result.update(position="not_comparable", reason="Conflicting outcomes share the latest verified date. Resolve which source is authoritative.")
                else:
                    actual = options[0]
                    delta = desk.distance(actual["low"], forecast["low"], forecast["high"])
                    result.update(actual=actual, **delta, reason="Same metric, period, accounting scope, unit and currency basis; dates checked.")
        comparisons.append(result)
    return comparisons


def financials(items):
    groups = {}
    for item in (f for f in items if f["kind"] == "actual" and not f.get("stale")):
        groups.setdefault(tuple(item[k] for k in ("metric","period","unit","scope","basis")), []).append(item)
    actuals = []
    for values in groups.values():
        latest = max(v["published"] for v in values)
        newest = [v for v in values if v["published"] == latest]
        if len({number(v["low"]) for v in newest}) == 1:
            actuals.append(newest[0])
    rows = []
    for f in actuals:
        match = re.fullmatch(r"Q([1-4]) FY(\d{2})", f["period"])
        qoq = yoy = None
        if match:
            quarter, year = int(match[1]), int(match[2])
            previous = f"Q{quarter-1 if quarter>1 else 4} FY{year if quarter>1 else year-1:02}"
            prior_year = f"Q{quarter} FY{year-1:02}"
            for target, name in [(previous, "qoq"), (prior_year, "yoy")]:
                peers = [a for a in actuals if a["period"] == target and all(a[k] == f[k] for k in ("metric", "unit", "scope", "basis"))]
                if peers and f["scope"] != "not_stated" and f["basis"] != "not_stated":
                    base = max(peers, key=lambda a: a["published"])
                    if f["unit"] == "%" or number(base["low"]) > 0:
                        change = float(number(f["low"]) - number(base["low"])) if f["unit"] == "%" else float((number(f["low"]) / number(base["low"]) - 1) * 100)
                        entry = {"percent": round(change, 4), "unit": "pp" if f["unit"] == "%" else "%", "source": base["source"], "base_period": target}
                        if name == "qoq": qoq = entry
                        else: yoy = entry
        rows.append({"fact": f, "qoq": qoq, "yoy": yoy})
    return rows


def view(symbol, as_of=None):
    symbol = documents.ticker(symbol)
    items = facts(symbol, as_of)
    return {"brief": passages(symbol, as_of), "candidates": candidates(symbol, as_of), "facts": items,
            "comparisons": compare(items), "financials": financials(items), "metrics": METRICS,
            "units": sorted(UNITS), "scopes": sorted(SCOPES), "bases": sorted(BASES), "can_review": workspaces.private() and runtime.interactive()}


def delete_fact(fact_id):
    with store.connection() as db:
        db.execute("DELETE FROM reviewed_facts WHERE workspace=? AND id=?", (workspaces.current(), fact_id))
