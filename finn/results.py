"""Quarterly results cards from the exchange's own XBRL filings.

Since the March 2025 quarter, listed companies file results to NSE as
"Integrated Filing - Financials" with a machine-readable XBRL instance. Reading
those tags gives exact headline numbers with no PDF parsing and no model:

    Revenue  RevenueFromOperations
    EBITDA   PBT - exceptional items + finance costs + D&A - other income
    PBT      ProfitBeforeTax
    PAT      profit attributable to owners (consolidated) or profit for the period

Lenders report interest as their cost of goods, so EBITDA is not meaningful
there; their card shows net interest income (interest earned - interest
expended / finance costs) instead. Consolidated figures are preferred.
"""
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import desk, providers

FILING_TYPE = "Integrated Filing- Financials"
CRORE = Decimal(10_000_000)
LENDING_SECTORS = {"Banking", "Lending"}
SCHEMA = """CREATE TABLE IF NOT EXISTS results_cards (
    symbol TEXT NOT NULL, period_end TEXT NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY(symbol, period_end))"""
XBRLI = "{http://www.xbrl.org/2003/instance}"


def prepare(db):
    db.execute(SCHEMA)


def fiscal_label(period_end):
    """Indian fiscal year ends 31 March: Sep 2026 is Q2 FY27."""
    quarter = {6: 1, 9: 2, 12: 3, 3: 4}[period_end.month]
    year = period_end.year + (1 if period_end.month > 3 else 0)
    return f"Q{quarter} FY{year % 100:02d}"


def shift_quarter(period_end, quarters):
    month = period_end.month - 3 * quarters
    year = period_end.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = 30 if month in (6, 9) else 31
    return date(year, month, day)


def parse_instance(body):
    """Return {tag: Decimal} for the quarter's whole-entity duration context."""
    upper = body[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise providers.SourceError("XBRL contains unsupported XML declarations.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise providers.SourceError("XBRL instance is not valid XML.") from exc
    contexts = {}
    for ctx in root.iter(XBRLI + "context"):
        if ctx.find(f"{XBRLI}entity/{XBRLI}segment") is not None or ctx.find(XBRLI + "scenario") is not None:
            continue
        start, end = ctx.findtext(f"{XBRLI}period/{XBRLI}startDate"), ctx.findtext(f"{XBRLI}period/{XBRLI}endDate")
        if start and end:
            contexts[ctx.get("id")] = (date.fromisoformat(start.strip()), date.fromisoformat(end.strip()))
    quarter = [cid for cid, (s, e) in contexts.items() if 80 <= (e - s).days <= 95]
    if not quarter:
        raise providers.SourceError("XBRL instance has no quarterly context.")
    chosen = max(quarter, key=lambda cid: contexts[cid][1])
    period_end = contexts[chosen][1]
    values, text = {}, {}
    for element in root:
        if element.get("contextRef") != chosen:
            continue
        name = element.tag.rsplit("}", 1)[-1]
        raw = (element.text or "").strip()
        try:
            values[name] = Decimal(raw)
        except InvalidOperation:
            text[name] = raw
    return period_end, values, text


def first(values, *names):
    return next((values[n] for n in names if n in values), None)


def headline(values, kind):
    """Four headline lines in rupees (Decimal), or None where not reported."""
    if kind == "bank":
        revenue = first(values, "Income")
        nii = None
        if "InterestEarned" in values and "InterestExpended" in values:
            nii = values["InterestEarned"] - values["InterestExpended"]
        pbt = first(values, "ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitBeforeTax")
        pat = first(values, "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
                    "ProfitLossForThePeriod", "ProfitLossForPeriod")
        return {"revenue": revenue, "core": nii, "pbt": pbt, "pat": pat,
                "ppop": first(values, "OperatingProfitBeforeProvisionAndContingencies")}
    revenue = first(values, "RevenueFromOperations")
    pbt = first(values, "ProfitBeforeTax")
    pat = first(values, "ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod")
    if kind == "lender":
        interest = first(values, "InterestEarned")
        finance = first(values, "FinanceCosts")
        core = interest - finance if interest is not None and finance is not None else None
    else:
        finance = first(values, "FinanceCosts")
        depreciation = first(values, "DepreciationDepletionAndAmortisationExpense")
        core = ebit = None
        if pbt is not None and finance is not None:
            ebit = pbt - values.get("ExceptionalItemsBeforeTax", Decimal(0)) + finance - values.get("OtherIncome", Decimal(0))
            if depreciation is not None:
                core = ebit + depreciation
        return {"revenue": revenue, "core": core, "pbt": pbt, "pat": pat, "ebit": ebit, "tax": first(values, "TaxExpense")}
    return {"revenue": revenue, "core": core, "pbt": pbt, "pat": pat, "tax": first(values, "TaxExpense")}


def kind_of(symbol, values):
    if "InterestExpended" in values:
        return "bank"
    sector = desk.COMPANIES.get(symbol, {}).get("sector")
    if sector in LENDING_SECTORS or ("InterestEarned" in values and "FeesAndCommissionIncome" in values):
        return "lender"
    return "industrial"


def change(current, base):
    if current is None or base is None or base <= 0:
        return None
    return float(round((current / base - 1) * 100, 2))


def crore(value):
    return None if value is None else float(round(value / CRORE, 2))


def build_card(symbol, quarters):
    """quarters: {period_end: {"values":..., "meta":...}} with the latest first in importance."""
    latest_end = max(quarters)
    latest = quarters[latest_end]
    kind = kind_of(symbol, latest["values"])
    lines = {end: headline(q["values"], kind) for end, q in quarters.items()}
    prev, year_ago = shift_quarter(latest_end, 1), shift_quarter(latest_end, 4)
    core_label = {"bank": "Net interest income", "lender": "Net interest income"}.get(kind, "EBITDA")
    labels = {"revenue": "Total income" if kind == "bank" else "Revenue", "core": core_label,
              "pbt": "PBT", "pat": "PAT"}
    rows = []
    for key in ("revenue", "core", "pbt", "pat"):
        now_value = lines[latest_end][key]
        rows.append({"key": key, "label": labels[key], "value_cr": crore(now_value),
                     "qoq": change(now_value, lines.get(prev, {}).get(key)),
                     "yoy": change(now_value, lines.get(year_ago, {}).get(key))})
    margin = None
    if kind == "industrial":
        def pct(end):
            line = lines.get(end, {})
            return (line["core"] / line["revenue"] * 100) if line.get("core") is not None and line.get("revenue") else None
        m_now, m_prev, m_ago = pct(latest_end), pct(prev), pct(year_ago)
        if m_now is not None:
            margin = {"label": "EBITDA margin", "value": float(round(m_now, 2)),
                      "qoq_pp": float(round(m_now - m_prev, 2)) if m_prev is not None else None,
                      "yoy_pp": float(round(m_now - m_ago, 2)) if m_ago is not None else None}
    history = [{"quarter": fiscal_label(end), "period_end": end.isoformat(),
                **{k: crore(v) for k, v in lines[end].items() if k in ("revenue", "core", "pbt", "pat", "ebit", "tax")}}
               for end in sorted(quarters)]
    meta = latest["meta"]
    definition = ("EBITDA = PBT − exceptional items + finance costs + depreciation & amortisation − other income."
                  if kind == "industrial" else
                  "Lenders: net interest income replaces EBITDA, because interest is their cost of goods.")
    return {"symbol": symbol, "kind": kind, "core_label": core_label, "quarter": fiscal_label(latest_end), "period_end": latest_end.isoformat(),
            "scope": meta["scope"], "audited": meta.get("audited", ""), "published": meta["published"],
            "rows": rows, "margin": margin, "history": history,
            "compared": {"qoq": fiscal_label(prev) if prev in lines else None,
                         "yoy": fiscal_label(year_ago) if year_ago in lines else None},
            "source": {"id": "xbrl-" + symbol + "-" + latest_end.isoformat(), "symbol": symbol,
                       "title": f"{fiscal_label(latest_end)} {meta['scope'].lower()} results (exchange XBRL)",
                       "kind": "Exchange filing", "date": meta["published"][:10], "url": meta["url"],
                       "locator": "XBRL tags: RevenueFromOperations, ProfitBeforeTax, FinanceCosts, "
                                  "DepreciationDepletionAndAmortisationExpense, OtherIncome",
                       "excerpt": "", "page": None},
            "definition": definition + " ₹ crore. Figures read from the company's XBRL filing to NSE."}


def listing(symbol, opener):
    payload = providers.nse_json("integrated-filing-results", {
        "index": "equities", "symbol": symbol, "type": FILING_TYPE}, opener)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise providers.SourceError("NSE results listing has an unexpected format.")
    chosen = {}
    try:
        legacy = providers.nse_json("corporates-financial-results", {
            "index": "equities", "symbol": symbol, "period": "Quarterly"}, opener)
    except providers.SourceError:
        legacy = []
    # Before the March 2025 quarter, results were filed in the older (same-taxonomy) format.
    for row in legacy if isinstance(legacy, list) else []:
        if row.get("toDate") and row.get("xbrl"):
            rows.append({"qe_Date": row["toDate"], "consolidated": row.get("consolidated"),
                         "broadcast_Date": row.get("broadCastDate") or row.get("filingDate"),
                         "xbrl": row["xbrl"], "ixbrl": row["xbrl"], "audited": row.get("audited", ""), "_legacy": True})
    for row in rows:
        try:
            end = datetime.strptime(row["qe_Date"].title(), "%d-%b-%Y").date()
            scope = "Consolidated" if row.get("consolidated") == "Consolidated" else "Standalone"
            published = providers.iso(providers.timestamp(row.get("broadcast_Date") or row.get("creation_Date")))
            if not str(row.get("xbrl", "")).endswith(".xml"):
                continue
        except (KeyError, ValueError, TypeError, providers.SourceError):
            continue
        rank = (scope == "Consolidated", not row.get("_legacy"), published)
        if end not in chosen or rank > chosen[end]["rank"]:
            chosen[end] = {"rank": rank, "scope": scope, "published": published, "xbrl": row["xbrl"],
                           "url": row.get("ixbrl") or row["xbrl"], "audited": row.get("audited", "")}
    return chosen


def fetch(symbol, opener=None, quarters=10):
    """Download the latest `quarters` XBRL instances and build the latest card."""
    opener = opener or providers.nse_session()
    available = listing(symbol, opener)
    if not available:
        raise providers.SourceError("No XBRL results are listed for this symbol.")
    latest_scope = available[max(available)]["scope"]
    parsed = {}
    for end in sorted(available, reverse=True)[:quarters]:
        meta = available[end]
        if meta["scope"] != latest_scope:
            continue  # never compare consolidated with standalone
        period_end, values, _ = parse_instance(providers.request_bytes(meta["xbrl"], opener))
        parsed[period_end] = {"values": values, "meta": meta}
    return build_card(symbol, parsed)


def collect(companies, opener, log=print):
    cards = {}
    for symbol in sorted(companies):
        try:
            cards[symbol] = fetch(symbol, opener)
        except providers.SourceError as exc:
            log(f"results {symbol}: {exc}")
    log(f"results: {len(cards)} cards")
    return cards


def store_cards(db, cards):
    prepare(db)
    for symbol, card in cards.items():
        db.execute("INSERT INTO results_cards VALUES(?,?,?) ON CONFLICT(symbol,period_end) DO UPDATE SET body=excluded.body",
                   (symbol, card["period_end"], json.dumps(card)))


def card_for(db, symbol, on=None):
    """The latest card published on or before `on` (an ISO timestamp)."""
    prepare(db)
    rows = [json.loads(r[0]) for r in db.execute(
        "SELECT body FROM results_cards WHERE symbol=? ORDER BY period_end DESC", (symbol,))]
    for card in rows:
        if on is None or card["published"][:10] <= on[:10]:
            return card
    return None


def is_results_filing(title, details):
    text = (title + " " + details).casefold()
    return bool(re.search(r"financial results|results for the (quarter|period)|quarterly results|q[1-4] results", text))
