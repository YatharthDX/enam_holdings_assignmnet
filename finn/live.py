"""Refresh orchestration, live digest, end-of-day signals and durable in-app alerts."""
import json
import logging
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from . import desk, live_store as store, providers

LOGGER = logging.getLogger("finn.live")
CATEGORIES = {
    "results": "Financial results", "M&A": "Mergers and acquisitions",
    "management_change": "Management changes", "litigation": "Regulatory and legal",
    "capex": "Capital expenditure", "fund_raise": "Fund raising",
    "credit_rating": "Credit ratings", "dividend": "Dividends",
    "notice": "Meeting notices", "compliance": "Routine compliance",
    "earnings_call": "Earnings calls", "press_release": "Company updates",
}
DEFAULT_INTERVAL = 900


def clock():
    return datetime.now(timezone.utc)


def classify(title, details=""):
    text = (title + " " + details).casefold()
    checks = [
        ("notice", ("board meeting intimation", "board meeting to be held", "intimation of board meeting",
                    "analyst/investor meet", "schedule of", "newspaper publication", "trading window")),
        ("compliance", ("reconciliation of share", "certificate under", "regulation 74", "loss of share",
                        "compliance certificate", "esop", "employee stock", "appointment of auditor",
                        "appointment of statutory auditor", "appointment of secretarial auditor")),
        ("litigation", ("litigation", "penalty", "regulatory order", "fine imposed", "insolvency")),
        ("management_change", ("resignation", "appointment of", "change in management", "change in director")),
        ("M&A", ("acquisition", "merger", "demerger", "joint venture", "sale of stake")),
        ("capex", ("capacity expansion", "capital expenditure", "new plant", "capex")),
        ("earnings_call", ("transcript", "earnings call", "conference call")),
        ("results", ("financial results", "audited results", "unaudited results", "quarterly results")),
        ("fund_raise", ("fund rais", "fund-rais", "rights issue", "preferential issue", "qualified institutional")),
        ("credit_rating", ("credit rating", "rating upgrade", "rating downgrade")),
        ("dividend", ("dividend", "record date")),
    ]
    category = next((kind for kind, terms in checks if any(term in text for term in terms)), "press_release")
    if category in {"notice", "compliance", "earnings_call"}:
        return category, 3, "Routine", CATEGORIES[category]
    if category == "press_release":
        return category, 2, "Other", "Company update; inspect the filing"
    return category, 1, "Material", CATEGORIES[category]


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


def evaluate(db, now):
    preferences = store.settings(db)
    if not preferences["enabled"]:
        return
    recent = providers.iso(now - timedelta(hours=24))
    for saved in db.execute("SELECT body FROM live_filings WHERE published>=? AND published<=?",
                            (recent, providers.iso(now))).fetchall():
        row = json.loads(saved["body"])
        category, _, _, _ = classify(row["title"], row["details"])
        if category in preferences["categories"]:
            put_alert(db, "filing-" + row["id"], row["published"], now, {
                "kind": "filing", "symbol": row["symbol"], "title": row["title"],
                "reason": CATEGORIES[category], "source": source_of(row)
            })
    for symbol, company in desk.COMPANIES.items():
        if not company["holding"]:
            continue
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
            put_alert(db, "price-" + source["id"], providers.iso(event_time), now, {
                **common, "kind": "price", "title": f"{symbol} moved {change:+.2f}%",
                "reason": f"Absolute daily change ≥ {preferences['price_pct']:g}%"
            })
        ratio = item["volume_ratio"]
        if ratio is not None and ratio > preferences["volume_multiple"]:
            put_alert(db, "volume-" + source["id"], providers.iso(event_time), now, {
                **common, "kind": "volume", "title": f"{symbol} volume reached {ratio:.2f}× its average",
                "reason": f"Above {preferences['volume_multiple']:g}× the previous 20-session mean"
            })


def put_alert(db, event_id, event_at, now, data):
    # The event identity survives retries and preference changes. A new filing,
    # session or signal type can alert once. Seen alerts stay seen after refresh.
    data = {**data, "id": event_id, "event_at": event_at}
    db.execute("""INSERT INTO live_alerts VALUES(?, ?, ?, ?, 0)
        ON CONFLICT(id) DO UPDATE SET body=excluded.body""",
               (event_id, event_at, providers.iso(now), json.dumps(data)))


def update_settings(value, now=None):
    now = now or clock()
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
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


def refresh(now=None, filing_fetch=providers.filings, price_fetch=providers.prices, force_prices=False):
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
    errors, updated = [], 0
    try:
        today = now.astimezone(providers.IST).date()
        first = today - timedelta(days=7)
        try:
            fetched = filing_fetch(holdings, first, today)
            rows = [row for row in fetched["rows"] if row["published"] <= started]
            with store.connection() as db:
                store.put_filings(db, rows)
                detail = fetched["warning"] or f"Requested {first} through {today}; {len(rows)} portfolio filings."
                store.state(db, "nse", started, "ok", detail, fetched["url"], fetched["coverage"])
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
            evaluate(db, now)
    except Exception:
        LOGGER.exception("Live refresh failed")
        errors.append("Refresh interrupted. Cached source records remain available.")
    finally:
        with store.connection() as db:
            db.execute("""UPDATE refresh_job SET status=?, finished=?, detail=?
                WHERE id=1 AND token=?""",
                       ("partial" if errors else "complete", providers.iso(clock()),
                        json.dumps({"prices_updated": updated, "errors": errors}), token))
    return {"status": "partial" if errors else "complete", "prices_updated": updated, "errors": errors}


def snapshot(window, start=None, end=None, now=None):
    now = now or clock()
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
        rows = []
        for stored in db.execute("SELECT body FROM live_filings WHERE published>=? AND published<?",
                                 (providers.iso(lower), providers.iso(upper))).fetchall():
            record = json.loads(stored["body"])
            company = desk.COMPANIES.get(record["symbol"])
            if not company or not company["holding"]:
                continue
            category, rank, priority, reason = classify(record["title"], record["details"])
            rows.append({**record, "company": company["name"], "date": record["published"],
                         "category": category, "label": CATEGORIES[category], "rank": rank,
                         "priority": priority, "reason": reason, "source": source_of(record)})
        rows.sort(key=lambda row: row["date"], reverse=True)
        rows.sort(key=lambda row: row["rank"])
        quotes = []
        for symbol, company in desk.COMPANIES.items():
            if company["holding"]:
                item = signal(store.bars(db, symbol))
                quotes.append({"symbol": symbol, "company": company["name"], **(item or {})})
        source_status = [dict(row) for row in db.execute("SELECT * FROM source_state ORDER BY key")]
        preferences = store.settings(db)
        notifications = store.alerts(db)
        progress = store.job(db)
    focus = rows[0]["symbol"] if rows else None
    return {"mode": "live", "as_of": today, "now": providers.iso(now), "start": start, "end": end,
            "window_start": providers.iso(lower), "window_end": providers.iso(upper), "rows": rows,
            "focus": focus, "people": desk.people(symbol=focus)[:2] if focus else [],
            "comparison": None, "holdings": len(quotes), "quotes": quotes, "sources": source_status,
            "settings": preferences, "alerts": notifications, "job": progress, "categories": CATEGORIES}


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
            except Exception:
                LOGGER.exception("Scheduled refresh interrupted; retrying on the next interval")
            self.stop_event.wait(interval)

    def stop(self):
        self.stop_event.set()
