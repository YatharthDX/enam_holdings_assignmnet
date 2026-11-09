"""Operator commands for refresh status and official NSE CSV imports."""
import argparse
import json
import sys
from pathlib import Path

from . import desk, live, live_store as store, providers


def main():
    parser = argparse.ArgumentParser(description="Refresh FINN's public data sources.")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--once", action="store_true", help="Fetch portfolio filings and daily bars now")
    choice.add_argument("--status", action="store_true", help="Print the last refresh and source states")
    choice.add_argument("--nse-csv", type=Path, help="Import a CSV downloaded from NSE's announcements page")
    args = parser.parse_args()
    if args.once:
        result = live.refresh(force_prices=True)
        print(json.dumps(result, indent=2))
        return int(bool(result.get("errors")))
    if args.nse_csv:
        try:
            if args.nse_csv.stat().st_size > providers.MAX_RESPONSE:
                raise ValueError("Choose a CSV smaller than 12 MiB.")
            rows, skipped = providers.parse_csv(args.nse_csv.read_bytes(), desk.COMPANIES)
            now = live.clock()
            if any(providers.timestamp(row["published"]) > now for row in rows):
                raise ValueError("The CSV contains future publication times.")
            with store.connection() as db:
                store.put_filings(db, rows)
                store.state(db, "nse-csv", providers.iso(now), "ok",
                            f"Operator import of {len(rows)} records; {skipped} invalid records.",
                            providers.NSE_PAGE, "operator_import")
                live.evaluate(db, now)
            print(json.dumps({"imported": len(rows), "skipped": skipped}))
            return 0
        except (OSError, ValueError, providers.SourceError) as exc:
            parser.exit(2, f"Could not import CSV: {exc}\n")
    with store.connection() as db:
        print(json.dumps({"job": store.job(db),
                          "sources": [dict(row) for row in db.execute("SELECT * FROM source_state ORDER BY key")]},
                         indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
