"""A dated snapshot of real public records, shipped with the image.

Free hosts lose their disk on restart and NSE rejects many cloud IP ranges. The
snapshot is built on a machine that can reach the sources, committed, and loaded
at startup, so a visitor lands on recent, real, dated filings instead of an
empty feed. A successful live refresh always supersedes it.

    python -m finn.snapshot build            # fetch and write finn/data/snapshot.json
    python -m finn.snapshot build --days 45
"""
import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from . import desk, live, live_store as store, providers

PATH = Path(__file__).parent / "data" / "snapshot.json"


def read(path=PATH):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


RESEARCH = ["LTTS", "SRF", "HAVELLS", "INFY", "TATAPOWER"]


def build(days=35, now=None, symbols=None, log=print, research=RESEARCH):
    now = now or live.clock()
    today = now.astimezone(providers.IST).date()
    companies = {s: c for s, c in desk.COMPANIES.items() if symbols is None or s in symbols}
    opener = providers.nse_session()
    fetched = providers.filings_by_symbol(companies, today - timedelta(days=days), today, opener)
    filings = sorted((r for r in fetched["rows"] if r["published"] <= providers.iso(now)),
                     key=lambda r: r["published"])
    log(f"filings: {len(filings)} rows; failed {fetched['failed'] or 'none'}")
    bars, failed_prices = {}, []
    for symbol in sorted(companies):
        try:
            bars[symbol] = providers.prices(symbol, now)
        except providers.SourceError as exc:
            failed_prices.append(symbol)
            log(f"prices {symbol}: {exc}")
    log(f"prices: {len(bars)} symbols")
    data = {"taken_at": providers.iso(now), "days": days, "filings": filings, "bars": bars,
            "coverage": {"filings_failed": fetched["failed"], "prices_failed": failed_prices}}
    from . import results, people_filings
    data["results"] = results.collect(companies, opener, log=log)
    data["appointments"] = people_filings.collect(filings, opener, log=log)
    data["guidance"] = promises(research or [], data["results"], log=log)
    return data


def promises(symbols, cards, log=print):
    """Index transcripts for the research names and ship their verified guidance statements."""
    from . import discovery, guidance, live_store
    shipped = {}
    for symbol in symbols:
        try:
            token = discovery.begin(symbol)
            if token:
                discovery.run(symbol, token)
            with live_store.connection() as db:
                if symbol in cards:
                    from . import results
                    results.store_cards(db, {symbol: cards[symbol]})
            guidance.refresh(symbol, log=log)
            with live_store.connection() as db:
                shipped[symbol] = guidance.items_for(db, symbol)
            log(f"guidance {symbol}: {len(shipped[symbol])} statements")
        except Exception as exc:  # one issuer's documents never block the snapshot
            log(f"guidance {symbol}: {exc}")
    return shipped


def load(db, path=PATH):
    """Idempotently merge the shipped snapshot into the shared public cache."""
    data = read(path)
    if not data:
        return None
    taken = data["taken_at"]
    store.put_filings(db, data.get("filings", []))
    for symbol, rows in data.get("bars", {}).items():
        store.put_bars(db, rows, taken)
    from . import results, people_filings
    results.store_cards(db, data.get("results", {}))
    people_filings.store(db, data.get("appointments", []))
    from . import guidance
    guidance.store_items(db, data.get("guidance", {}))
    store.state(db, "snapshot", taken, "ok",
                f"Shipped snapshot of NSE filings ({data.get('days', '?')} days) and Yahoo daily bars.",
                providers.NSE_PAGE, "snapshot")
    return taken


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("build")
    make.add_argument("--days", type=int, default=35)
    make.add_argument("--out", default=str(PATH))
    make.add_argument("--research", default=",".join(RESEARCH), help="tickers whose transcripts are read for guidance")
    args = parser.parse_args(argv)
    data = build(days=args.days, research=[s for s in args.research.split(",") if s])
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.out}: {len(data['filings'])} filings, {len(data['bars'])} price series, "
          f"{len(data['results'])} results cards, {len(data['appointments'])} appointments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
