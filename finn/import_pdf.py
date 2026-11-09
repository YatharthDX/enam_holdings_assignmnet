"""Run with python -m finn.import_pdf --help."""
import argparse
import sys

from pypdf.errors import PyPdfError

from .documents import KINDS, import_pdf


def main():
    parser = argparse.ArgumentParser(description="Index a public issuer PDF by ticker and original page.")
    parser.add_argument("--file", required=True)
    parser.add_argument("--ticker", dest="symbol", required=True)
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True, help="Original issuer or exchange HTTPS URL")
    parser.add_argument("--published", required=True, help="Publication date, YYYY-MM-DD")
    try:
        doc_id, count, status = import_pdf(**vars(parser.parse_args()))
    except (OSError, ValueError, PyPdfError) as exc:
        parser.exit(2, f"Could not index PDF: {exc}\n")
    print(f"{doc_id}: {status}, {count} searchable pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
