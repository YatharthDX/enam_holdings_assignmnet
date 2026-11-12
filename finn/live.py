"""Refresh orchestration, live digest, end-of-day signals and durable in-app alerts."""
import json
import logging
import os
import secrets
import threading
import re
import hashlib
import time as system_time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from . import desk, live_store as store, providers, workspaces

LOGGER = logging.getLogger("finn.live")
CATEGORIES = {
    "results": "Financial results", "M&A": "Mergers and acquisitions",
    "management_change": "Management changes", "litigation": "Regulatory and legal",
    "capex": "Capital expenditure", "fund_raise": "Fund raising and buybacks",
    "pledging": "Promoter pledging", "insider_trading": "Insider trading",
    "disruption": "Operational disruption", "credit_rating": "Credit ratings",
    "dividend": "Dividends", "bonus_split": "Bonus issues and splits",
    "press_release": "Company updates", "earnings_call": "Earnings calls",
    "investor_meetings": "Investor meetings", "agm_egm": "General meetings",
    "postal_ballot": "Postal ballots", "notice": "Meeting notices", "compliance": "Routine compliance",
}
DEFAULT_INTERVAL = 900


def clock():
    return datetime.now(timezone.utc)


# Ordered keyword rules over NSE's own subject plus the filing's detail text.
# The first matching rule wins, so specific routine paperwork precedes broad words.
RULES = [
    ("notice", ("board meeting intimation", "board meeting to be held", "intimation of board meeting",
                "prior intimation", "trading window", "newspaper publication", "copy of newspaper")),
    ("compliance", ("reconciliation of share", "certificate under", "regulation 74", "loss of share",
                    "compliance certificate", "esop", "esos", "employee stock", "stock option", "restricted stock unit",
                    "appointment of auditor", "appointment of statutory auditor", "appointment of secretarial auditor",
                    "registrar and share transfer", "share transfer agent", "monitoring agency", "statement of deviation",
                    "duplicate share", "change in corporate office address", "business responsibility", "esg report")),
    ("pledging", ("pledge", "encumbrance", "invocation")),
    ("insider_trading", ("insider trading", "prohibition of insider", "regulation 7(2)", "disclosure under regulation 29",
                         "substantial acquisition of shares")),
    ("litigation", ("litigation", "penalty", "regulatory order", "fine imposed", "insolvency", "nclt", "nclat",
                    "orders passed", "show cause", "arbitration", "tax demand", "search and seizure", "court")),
    ("disruption", ("strikes/lockouts", "lockout", "disturbance", "fire at", "cyber", "shutdown", "force majeure")),
    ("earnings_call", ("transcript", "audio recording", "earnings call", "conference call", "concall")),
    ("investor_meetings", ("analyst", "investor meet", "institutional investor", "investor conference", "schedule of meet")),
    ("results", ("financial results", "audited results", "unaudited results", "quarterly results", "financial result",
                 "results for the quarter", "q1 results", "q2 results", "q3 results", "q4 results")),
    ("management_change", ("resignation", "resigned", "appointment of", "appointed", "re-appointment", "cessation",
                           "ceased", "change in management", "change in director", "change in managing director",
                           "change in chief", "key managerial", "senior management",
                           "assumed charge", "assumed office", "vacated", "superannuation", "retirement")),
    ("M&A", ("acquisition", "acquire", "merger", "amalgamation", "demerger", "joint venture", "sale of stake",
             "sale or disposal", "divest", "scheme of arrangement", "restructuring", "strike off", "strike-off",
             "incorporation of", "wholly owned subsidiary")),
    ("capex", ("capacity addition", "capacity expansion", "capital expenditure", "new plant", "capex",
               "commissioning", "commercial production", "greenfield", "brownfield")),
    ("fund_raise", ("fund rais", "fund-rais", "rights issue", "preferential", "qualified institutional", "qip",
                    "buyback", "buy back", "buy-back", "non-convertible debenture", "commercial paper", "bond issue")),
    ("bonus_split", ("bonus issue", "bonus shares", "sub-division", "subdivision", "stock split", "split of")),
    ("credit_rating", ("credit rating", "rating upgrade", "rating downgrade", "ratings")),
    ("dividend", ("dividend",)),
    ("agm_egm", ("annual general meeting", "extra-ordinary general meeting", "extraordinary general meeting",
                 "shareholders meeting", "agm", "egm")),
    ("postal_ballot", ("postal ballot", "e-voting", "voting results", "scrutinizer")),
]
ROUTINE = {"notice", "compliance", "earnings_call", "investor_meetings", "agm_egm", "postal_ballot"}
OTHER = {"press_release", "credit_rating", "dividend", "bonus_split", "insider_trading"}
SENIOR = re.compile(r"managing director|\bmd\b|chief executive|\bceo\b|chief financial|\bcfo\b|chairman|chairperson|"
                    r"whole[- ]time director|executive director|\bpresident\b|chief operating|\bcoo\b")


def classify(title, details=""):
    """(category, rank, priority, reason). Rank 1 is material, 2 notable, 3 routine."""
    text = " ".join((title + " " + details).casefold().split())
    if re.search(r"news verification|rumou?r verification|sought clarification", text):
        return "press_release", 2, "Other", "Exchange asked the company to clarify a news report"
    category = next((kind for kind, terms in RULES if any(term in text for term in terms)), "press_release")
    if category == "results" and re.search(r"presentation|press release|newspaper|communication to shareholders", text) \
            and not re.search(r"submitted to the exchange,? (?:the )?(?:unaudited |audited )?financial results", text):
        return category, 2, "Other", "Results material (deck, release or letter)"
    if category == "management_change":
        if SENIOR.search(text) and not re.search(r"independent director|nominee director|subsidiary|re-?appointment", text):
            return category, 1, "Material", "Change at the top (CEO, MD, CFO, chair or executive director)"
        return category, 2, "Other", "Board or senior-management change"
    if category == "M&A" and re.search(r"strike[- ]?off|incorporation of|name (?:of .{0,60})?(?:has been )?changed", text):
        return category, 2, "Other", "Group-structure housekeeping"
    if category == "credit_rating" and re.search(r"downgrad|negative|watch", text):
        return category, 1, "Material", "Credit rating downgrade or negative outlook"
    if category in ROUTINE:
        return category, 3, "Routine", CATEGORIES[category]
    if category == "press_release":
        if re.search(r"order|contract|bidder|agreement|launch|approval|partnership|commission", text):
            return category, 2, "Other", "Business update: order, contract, approval or launch"
        if re.search(r"general updates?$|has informed the exchange about general updates|^updates", text):
            return category, 3, "Routine", "Generic update with no stated subject; open the filing"
        return category, 2, "Other", "Company update; inspect the filing"
    if category in OTHER:
        return category, 2, "Other", CATEGORIES[category]
    return category, 1, "Material", CATEGORIES[category]


def headline(row):
    """The filing's own sentence without exchange boilerplate; NSE subjects are often just "Updates"."""
    text = " ".join(row.get("details", "").split())
    text = re.sub(r"^.{0,120}?\b(?:has|have)\s+(?:informed|submitted to)\s+the\s+Exchange,?\s*(?:about|regarding|that|on)?\s*", "", text)
    text = re.sub(r"^(?:the\s+)?(?:disclosure under regulation 30.{0,160}?-\s*)", "", text, flags=re.I)
    if len(text) < 12 or re.fullmatch(r"(?:general )?updates?\.?", text, re.I):
        return row["title"]
    text = text[0].upper() + text[1:]
    return text if len(text) <= 120 else text[:text.rfind(" ", 0, 117)] + "…"


def source_of(row):
    return {"id": row["id"], "symbol": row["symbol"], "title": row["title"],
            "kind": "Exchange filing", "date": row["published"], "url": row["url"],
            "locator": "NSE publication metadata", "excerpt": "", "page": None}


def signal(rows):
    if not rows:
        return None
    latest = rows[-1]
    result = {**latest, "price_change": None, "volume_ratio": None, "baseline_sessions": min(20, len(rows)-1),
              "note": "", "url": "https://finance.yahoo.com/quote/" + latest["symbol"] + ".NS/history/"}
    if latest["close"] is None:
        result["note"] = "The latest completed session has no valid closing price."
        return result
    if len(rows) > 1 and rows[-2]["close"] and not latest["split"]:
        result["price_change"] = float(
            (Decimal(str(latest["close"])) / Decimal(str(rows[-2]["close"])) - 1) * 100
        )
    baseline = rows[-21:-1]
    if len(baseline) < 20:
        result["note"] = "Volume comparison needs 20 previous sessions."
    elif any(row["split"] for row in baseline + [latest]):
        result["note"] = "Split in the volume baseline; volume signal suppressed."
    elif any(row["volume"] is None for row in baseline) or latest["volume"] is None:
        result["note"] = "Volume data is incomplete."
    else:
        average = sum(row["volume"] for row in baseline) / 20
        if average > 0:
            result["volume_ratio"] = latest["volume"] / average
        else:
            result["note"] = "The volume baseline is zero."
    if latest["split"]:
        result["note"] = "Split session; price and volume signals suppressed."
        result["volume_ratio"] = None
    return result


def triggered(db, now):
    """Alerts the current owner's rules produce at `now`: [(event_id, event_at, data)]."""
    found = []
    preferences = workspaces.settings(db)
    held = set(workspaces.holdings(db))
    if not preferences["enabled"]:
        return found
    recent = providers.iso(now - timedelta(days=7))
    for saved in db.execute("SELECT body FROM live_filings WHERE published>=? AND published<=?",
                            (recent, providers.iso(now))).fetchall():
        row = json.loads(saved["body"])
        if row["symbol"] not in held:
            continue
        category, _, _, _ = classify(row["title"], row["details"])
        if category in preferences["categories"]:
            found.append(("filing-" + row["id"], row["published"], {
                "kind": "filing", "symbol": row["symbol"], "title": headline(row),
                "reason": CATEGORIES[category], "source": source_of(row)
            }))
    for symbol in sorted(held):
        company = desk.COMPANIES.get(symbol, {"name": symbol})
        item = signal(store.bars(db, symbol))
        if item is None:
            continue
        session_day = providers.timestamp(item["day"]).astimezone(providers.IST).date()
        event_time = datetime.combine(session_day, time(16, 15), providers.IST)
        if not now - timedelta(days=7) <= event_time <= now:
            continue
        source = {"id": "yahoo-" + symbol + "-" + item["day"], "symbol": symbol,
                  "title": company["name"] + " daily price history", "date": item["day"],
                  "kind": "EOD market data", "url": item["url"], "page": None,
                  "locator": "Provider daily close and share volume", "excerpt": ""}
        common = {"symbol": symbol, "source": source}
        change = item["price_change"]
        if change is not None and abs(change) >= preferences["price_pct"]:
            found.append(("price-" + source["id"], providers.iso(event_time), {
                **common, "kind": "price", "title": f"{symbol} moved {change:+.2f}%",
                "reason": f"Absolute daily change ≥ {preferences['price_pct']:g}%"
            }))
        ratio = item["volume_ratio"]
        if ratio is not None and ratio > preferences["volume_multiple"]:
            found.append(("volume-" + source["id"], providers.iso(event_time), {
                **common, "kind": "volume", "title": f"{symbol} volume reached {ratio:.2f}× its average",
                "reason": f"Above {preferences['volume_multiple']:g}× the previous 20-session mean"
            }))
    return found


def evaluate(db, now):
    for event_id, event_at, data in triggered(db, now):
        put_alert(db, event_id, event_at, now, data)


def put_alert(db, event_id, event_at, now, data):
    # The event identity survives retries and preference changes. A new filing,
    # session or signal type can alert once. Seen alerts stay seen after refresh.
    data = {**data, "id": event_id, "event_at": event_at}
    if workspaces.private():
        db.execute("INSERT INTO workspace_alerts VALUES(?,?,?,?,?,0) ON CONFLICT(workspace,id) DO UPDATE SET body=excluded.body",
                   (workspaces.current(), event_id, event_at, providers.iso(now), json.dumps(data)))
        return
    if workspaces.current() == "public":
        return
    db.execute("""INSERT INTO live_alerts VALUES(?, ?, ?, ?, 0)
        ON CONFLICT(id) DO UPDATE SET body=excluded.body""",
               (event_id, event_at, providers.iso(now), json.dumps(data)))


def update_settings(value, now=None):
    now = now or clock()
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if workspaces.private():
            db.execute("UPDATE workspaces SET settings=? WHERE id=?", (json.dumps(value), workspaces.current()))
        else:
            db.execute("UPDATE alert_settings SET body=? WHERE id=1", (json.dumps(value),))
        evaluate(db, now)
    return value


def price_due(success, now, latest_day=None):
    if not success:
        return True
    previous = providers.timestamp(success).astimezone(providers.IST)
    current = now.astimezone(providers.IST)
    missing_today = latest_day != current.date().isoformat()
    retry_after_close = missing_today and time(16, 15) <= current.time() < time(22)
    return (previous.date() < current.date() or retry_after_close or
            (current.time() >= time(16, 15) and previous.time() < time(16, 15)))


def refresh(now=None, filing_fetch=providers.filings, price_fetch=providers.prices, force_prices=False, enrich=None):
    now = now or clock()
    started = providers.iso(now)
    token = secrets.token_hex(16)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = store.job(db)
        if previous and previous["status"] == "running" and previous["expires"] > started:
            return {"status": "running", "detail": "A refresh is already running."}
        db.execute("""INSERT INTO refresh_job VALUES(1, ?, 'running', ?, NULL, ?, '')
            ON CONFLICT(id) DO UPDATE SET token=excluded.token, status=excluded.status,
            started=excluded.started, finished=NULL, expires=excluded.expires, detail=''""",
                   (token, started, providers.iso(now + timedelta(minutes=10))))

    holdings = {key: value for key, value in desk.COMPANIES.items() if value["holding"]}
    with store.connection() as db:
        workspaces.expire(db)
        for row in db.execute("SELECT holdings FROM workspaces"):
            for symbol in json.loads(row[0]):
                holdings.setdefault(symbol, {"name": symbol, "symbol": symbol, "holding": True})
    errors, updated = [], 0
    try:
        today = now.astimezone(providers.IST).date()
        first = today - timedelta(days=7)
        try:
            fetched = filing_fetch(holdings, first, today)
            rows = [row for row in fetched["rows"] if row["published"] <= started]
            with store.connection() as db:
                previous_rows = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id,body FROM live_filings")}
                store.put_filings(db, rows)
                tracked = {r[0] for r in db.execute("SELECT symbol FROM document_jobs")}
                for filing in rows:
                    category = classify(filing["title"], filing["details"])[0]
                    if previous_rows.get(filing["id"]) != filing and filing["symbol"] in tracked and category in {"results", "earnings_call"}:
                        event = filing["id"] + ":" + hashlib.sha256(json.dumps(filing, sort_keys=True).encode()).hexdigest()[:16]
                        inserted = db.execute("INSERT OR IGNORE INTO document_refresh_events VALUES(?,?)", (event, filing["symbol"]))
                        if inserted.rowcount:
                            db.execute("INSERT INTO document_refresh_queue VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET event=excluded.event,requested=excluded.requested",
                                       (filing["symbol"], event, started))
                fresh = [f for f in rows if f["id"] not in previous_rows]
                detail = fetched["warning"] or f"Requested {first} through {today}; {len(rows)} portfolio filings."
                store.state(db, "nse", started, "ok", detail, fetched["url"], fetched["coverage"])
            if enrich is None and filing_fetch is providers.filings:
                enrich = enrich_filings
            if enrich and fresh:
                try:
                    enrich(fresh)
                except Exception:
                    LOGGER.exception("Filing enrichment interrupted")
            if fetched["skipped"]:
                errors.append(f"{fetched['skipped']} portfolio filings could not be parsed.")
            if fetched["coverage"] != "range":
                errors.append("NSE coverage is partial; the selected window may have gaps.")
        except providers.SourceError as exc:
            errors.append("NSE: " + str(exc))
            with store.connection() as db:
                store.state(db, "nse", started, "error", str(exc), providers.NSE_PAGE, "gap")

        with store.connection() as db:
            states = {row["key"]: dict(row) for row in db.execute("SELECT * FROM source_state")}
            latest_days = {row["symbol"]: row["day"] for row in db.execute(
                "SELECT symbol, MAX(day) AS day FROM daily_bars GROUP BY symbol"
            )}
        pending = [symbol for symbol in holdings if force_prices or
                   price_due(states.get("yahoo:" + symbol, {}).get("success"), now,
                             latest_days.get(symbol))]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(price_fetch, symbol, now): symbol for symbol in pending}
            for future in as_completed(futures):
                symbol = futures[future]
                url = "https://finance.yahoo.com/quote/" + symbol + ".NS/history/"
                try:
                    rows = future.result()
                    if not rows or any(row["symbol"] != symbol for row in rows):
                        raise providers.SourceError("No matching daily bars were returned.")
                    with store.connection() as db:
                        store.put_bars(db, rows, started)
                        store.state(db, "yahoo:" + symbol, started, "ok",
                                    f"{len(rows)} completed daily sessions.", url, "daily")
                    updated += 1
                except providers.SourceError as exc:
                    errors.append(symbol + ": " + str(exc))
                    with store.connection() as db:
                        store.state(db, "yahoo:" + symbol, started, "error", str(exc), url, "gap")
        with store.connection() as db:
            active = [None, *[r[0] for r in db.execute("SELECT id FROM workspaces WHERE expires>?", (system_time.time(),))]]
            for wid in active:
                context = workspaces._current.set(wid)
                try:
                    evaluate(db, now)
                finally:
                    workspaces._current.reset(context)
    except Exception:
        LOGGER.exception("Live refresh failed")
        errors.append("Refresh interrupted. Cached source records remain available.")
    finally:
        with store.connection() as db:
            db.execute("""UPDATE refresh_job SET status=?, finished=?, detail=?
                WHERE id=1 AND token=?""",
                       ("partial" if errors else "complete", providers.iso(clock()),
                        json.dumps({"prices_updated": updated, "errors": errors}), token))
    refresh_documents(limit=1)
    return {"status": "partial" if errors else "complete", "prices_updated": updated, "errors": errors}


def refresh_documents(limit=1):
    from . import discovery
    with store.connection() as db:
        queued = [dict(r) for r in db.execute("SELECT * FROM document_refresh_queue ORDER BY requested LIMIT ?", (limit,))]
    for item in queued:
        try:
            token = discovery.begin(item["symbol"])
            if token:
                discovery.run(item["symbol"], token, force=True)
                with store.connection() as db:
                    db.execute("DELETE FROM document_refresh_queue WHERE symbol=? AND event=?", (item["symbol"], item["event"]))
        except ValueError:
            break


def anchor():
    """(time, snapshot_iso): the shipped snapshot anchors windows until a live fetch is newer."""
    now = clock()
    with store.connection() as db:
        rows = {r["key"]: r["success"] for r in db.execute(
            "SELECT key, success FROM source_state WHERE key IN ('nse','snapshot')")}
    snap, live_success = rows.get("snapshot"), rows.get("nse")
    if snap and not (live_success and live_success > snap):
        return min(providers.timestamp(snap), now), snap
    return now, None


def enrich_filings(filings, limit=6, log=LOGGER.info):
    """Results cards and named people for new material filings, bounded per cycle."""
    from . import people_filings, results
    wanted = []
    for filing in filings:
        category, rank, _, _ = classify(filing["title"], filing["details"])
        if category == "results" and rank == 1 or category == "management_change":
            wanted.append((category, filing))
    if not wanted:
        return
    opener = providers.nse_session()
    for category, filing in wanted[:limit]:
        try:
            with store.connection() as db:
                if category == "results":
                    card = results.card_for(db, filing["symbol"])
                    if card and card["published"][:10] >= filing["published"][:10]:
                        continue
                elif people_filings.for_filing(db, filing["id"]):
                    continue
            if category == "results":
                card = results.fetch(filing["symbol"], opener)
                with store.connection() as db:
                    results.store_cards(db, {filing["symbol"]: card})
            else:
                items = people_filings.collect([filing], opener, log=log)
                with store.connection() as db:
                    people_filings.store(db, items)
        except (providers.SourceError, ValueError, OSError) as exc:
            log("enrichment %s %s: %s", filing["symbol"], category, exc)


def attach_card(db, row):
    from . import results
    card = results.card_for(db, row["symbol"])
    if not card:
        return None
    filed = datetime.fromisoformat(row["published"]).date()
    published = date.fromisoformat(card["published"][:10])
    # The XBRL instance is broadcast alongside the results outcome, rarely days apart.
    return card if -1 <= (published - filed).days <= 3 else None


def snapshot(window, start=None, end=None, now=None):
    snapshot_at = None
    if now is None:
        now, snapshot_at = anchor()
    today = now.astimezone(providers.IST).date()
    if window == "custom":
        if not start or not end or start > end or end > today:
            raise ValueError("Choose a valid date range ending today or earlier.")
        lower = datetime.combine(start, time(), providers.IST)
        upper = min(datetime.combine(end + timedelta(days=1), time(), providers.IST), now)
    elif window in {"24h", "7d"}:
        lower, upper = now - timedelta(hours=24 if window == "24h" else 168), now
        start, end = lower.astimezone(providers.IST).date(), today
    else:
        raise ValueError("Choose 24h, 7d or custom.")
    with store.connection() as db:
        db.execute("BEGIN")
        held = set(workspaces.holdings(db))
        rows = []
        for stored in db.execute("SELECT body FROM live_filings WHERE published>=? AND published<?",
                                 (providers.iso(lower), providers.iso(upper))).fetchall():
            record = json.loads(stored["body"])
            company = desk.COMPANIES.get(record["symbol"])
            company = company or {"name": record["symbol"]}
            if record["symbol"] not in held:
                continue
            category, rank, priority, reason = classify(record["title"], record["details"])
            rows.append({**record, "headline": headline(record), "company": company["name"], "date": record["published"],
                         "category": category, "label": CATEGORIES[category], "rank": rank,
                         "priority": priority, "reason": reason, "source": source_of(record)})
            if category == "management_change":
                from . import people_filings
                # Network matching opens its own connection; resolve it after this read transaction.
                rows[-1]["_people"] = people_filings.for_filing(db, record["id"])
            elif category == "results" and rank == 1:
                rows[-1]["results_card"] = attach_card(db, record)
            versions = [json.loads(r[0]) for r in db.execute("SELECT body FROM filing_versions WHERE event=?", (record["id"],))]
            if len(versions) > 1:
                rows[-1]["source"]["versions"] = [source_of(v) for v in versions]
        rows.sort(key=lambda row: row["date"], reverse=True)
        rows.sort(key=lambda row: row["rank"])
        quotes = []
        for symbol in sorted(held):
            company = desk.COMPANIES.get(symbol, {"name": symbol})
            item = signal(store.bars(db, symbol))
            quotes.append({"symbol": symbol, "company": company["name"], **(item or {})})
        source_status = [dict(row) for row in db.execute("SELECT * FROM source_state ORDER BY key") if row["key"] in ("nse", "snapshot") or row["key"][6:] in held]
        preferences = workspaces.settings(db)
        notifications = workspaces.alerts(db)
        if workspaces.current() == "public":
            # Anonymous visitors see what the default rules would raise, without storing it.
            notifications = sorted(({**data, "id": event_id, "event_at": event_at, "seen": False, "preview": True}
                                    for event_id, event_at, data in triggered(db, now)),
                                   key=lambda a: a["event_at"], reverse=True)
        progress = store.job(db)
    raw_filings = len(rows)
    rows = group_filings(rows)
    focus = rows[0]["symbol"] if rows else None
    from . import network
    contacts = {}
    for row in rows:
        if "_people" in row:
            row["management_context"] = network.management_context(row.pop("_people"), row)
        # The network rides inside each material event, not in a side panel.
        elif row["rank"] == 1 and row["category"] != "management_change":
            if row["symbol"] not in contacts:
                contacts[row["symbol"]] = (desk.people(symbol=row["symbol"]) or [None])[0]
            row["contact"] = contacts[row["symbol"]]
    return {"mode": "live", "as_of": today, "now": providers.iso(now), "start": start, "end": end,
            "snapshot_at": snapshot_at,
            "window_start": providers.iso(lower), "window_end": providers.iso(upper), "rows": rows,
            "focus": focus, "people": desk.people(symbol=focus)[:2] if focus else [],
            "comparison": None, "holdings": len(quotes), "quotes": quotes, "sources": source_status,
            "settings": preferences, "alerts": notifications, "job": progress, "categories": CATEGORIES,
            "reconnect": network.reconnect(focus, providers.iso(now)) if focus else [], "filing_count": raw_filings}


def group_filings(rows):
    """Group exact metadata duplicates; preserve distinct/amended statements."""
    grouped = {}
    for row in rows:
        key = (row["symbol"], row["published"][:10], " ".join(row["title"].casefold().split()),
               " ".join(row["details"].casefold().split()))
        if key not in grouped:
            grouped[key] = {**row, "other_sources": []}
        else:
            grouped[key]["other_sources"].append(row["source"])
    return list(grouped.values())


class Refresher:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if os.environ.get("FINN_AUTO_REFRESH", "1").lower() not in {"0", "false", "off"}:
            self.thread = threading.Thread(target=self.loop, name="finn-refresh", daemon=True)
            self.thread.start()

    def loop(self):
        try:
            interval = max(60, int(os.environ.get("FINN_REFRESH_SECONDS", str(DEFAULT_INTERVAL))))
        except ValueError:
            interval = DEFAULT_INTERVAL
        while not self.stop_event.is_set():
            try:
                refresh()
                with store.connection() as db:
                    workspaces.expire(db)
            except Exception:
                LOGGER.exception("Scheduled refresh interrupted; retrying on the next interval")
            self.stop_event.wait(interval)

    def stop(self):
        self.stop_event.set()
