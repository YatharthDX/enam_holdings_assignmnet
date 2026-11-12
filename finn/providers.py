"""Small adapters for public NSE disclosures and Yahoo daily bars."""
import csv
import hashlib
import html
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

IST = timezone(timedelta(hours=5, minutes=30), "IST")
UTC = timezone.utc
NSE_API = "https://www.nseindia.com/api/corporate-announcements"
NSE_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
USER_AGENT = "FINN/0.2 (public company research prototype)"
MAX_RESPONSE = 12 * 1024 * 1024


class SourceError(Exception):
    pass


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(html.unescape(str(value or "")))
    return " ".join(" ".join(parser.parts).split())


def timestamp(value):
    value = str(value or "").strip()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        result = None
        for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%m-%Y %H:%M:%S",
                    "%d-%b-%Y", "%d/%m/%Y %H:%M:%S", "%d%m%Y%H%M%S"):
            try:
                result = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        if result is None:
            try:
                result = parsedate_to_datetime(value)
            except (ValueError, TypeError) as exc:
                raise SourceError("Source supplied an unrecognised publication time.") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=IST)
    return result.astimezone(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds")


def attachment(value):
    url = html.unescape(str(value or "")).strip()
    if url.startswith("/"):
        url = "https://www.nseindia.com" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host == "nseindia.com" or host.endswith(".nseindia.com")):
        raise SourceError("Announcement has no usable NSE attachment.")
    if parts.username or parts.password or parts.port not in {None, 443}:
        raise SourceError("Announcement attachment has an invalid address.")
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ""))


def request_bytes(url, opener=None, limit=MAX_RESPONSE, timeout=12):
    client = opener or build_opener()
    request = Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml, */*",
        "Referer": NSE_PAGE if "nseindia.com" in (urlsplit(url).hostname or "") else
                   "https://" + urlsplit(url).netloc + "/"
    })
    try:
        with client.open(request, timeout=timeout) as response:
            body = response.read(limit + 1)
    except HTTPError as exc:
        raise SourceError(f"Source returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise SourceError("The source's HTTPS certificate could not be verified (often an incomplete "
                              "certificate chain on the issuer's site). FINN does not bypass verification.") from exc
        raise SourceError("Source connection failed or timed out.") from exc
    if len(body) > limit:
        raise SourceError("Source response exceeded the size limit.")
    return body


def normal_filing(symbol, title, details, url, published, provider_id=""):
    when = timestamp(published)
    url = attachment(url)
    # One attachment rebroadcast by the exchange remains one event.
    key = hashlib.sha256((symbol + "|" + url).encode()).hexdigest()
    return {
        "id": "nse-" + key[:32], "provider_id": str(provider_id), "symbol": symbol,
        "title": plain(title)[:500], "details": plain(details)[:2000],
        "url": url, "published": iso(when), "provider": "NSE"
    }


def parse_announcements(payload, companies):
    if not isinstance(payload, list):
        raise SourceError("NSE announcement response has an unexpected format.")
    rows, skipped = [], 0
    for record in payload:
        if not isinstance(record, dict):
            skipped += 1
            continue
        symbol = str(record.get("symbol", "")).upper()
        if symbol not in companies:
            continue
        try:
            title = record.get("desc") or record.get("subject") or record.get("attchmntText")
            if not title:
                raise SourceError("Announcement has no subject.")
            rows.append(normal_filing(
                symbol, title, record.get("attchmntText") or record.get("sm_name", ""),
                record.get("attchmntFile") or record.get("attachment"),
                record.get("an_dt") or record.get("sort_date") or record.get("dt"),
                record.get("seq_id", "")
            ))
        except (SourceError, TypeError, ValueError):
            skipped += 1
    return rows, skipped


def identify(text, companies):
    # RSS can identify an issuer by company name rather than NSE symbol.
    lowered = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    for symbol in sorted(companies, key=len, reverse=True):
        if re.search(r"(?<![A-Z0-9&])" + re.escape(symbol) + r"(?![A-Z0-9&])", text.upper()):
            return symbol
    for symbol, company in companies.items():
        name = re.sub(r"[^a-z0-9]+", " ", company["name"].casefold()).strip()
        if name and name in lowered:
            return symbol
    return None


def parse_rss(body, companies):
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise SourceError("RSS contains unsupported XML declarations.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise SourceError("NSE RSS response is not valid XML.") from exc
    channel = root.find("channel")
    if channel is None:
        raise SourceError("NSE RSS response has no feed channel.")
    rows, skipped = [], 0
    for item in channel.findall("item"):
        title = plain(item.findtext("title"))
        details = plain(item.findtext("description"))
        symbol = identify(title + " " + details, companies)
        if symbol is None:
            continue
        try:
            rows.append(normal_filing(symbol, title, details, item.findtext("link"),
                                      item.findtext("pubDate"), item.findtext("guid") or ""))
        except (SourceError, TypeError, ValueError):
            skipped += 1
    return rows, skipped


def filings(companies, start, end):
    params = {"index": "equities", "from_date": start.strftime("%d-%m-%Y"),
              "to_date": end.strftime("%d-%m-%Y")}
    url = NSE_API + "?" + urlencode(params)
    opener = build_opener(HTTPCookieProcessor())
    try:
        # Establish the ordinary public site session once. Access failures are
        # reported rather than retried with alternate identities or proxies.
        request_bytes(NSE_PAGE, opener)
        payload = json.loads(request_bytes(url, opener))
        rows, skipped = parse_announcements(payload, companies)
        return {"rows": rows, "coverage": "range" if not skipped else "partial",
                "url": url, "skipped": skipped, "warning": ""}
    except (SourceError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        api_error = str(exc)
    try:
        rows, skipped = parse_rss(request_bytes(NSE_RSS), companies)
        return {"rows": rows, "coverage": "partial", "url": NSE_RSS, "skipped": skipped,
                "warning": f"Date-filtered feed unavailable ({api_error}) Latest RSS items are available; the requested range may have gaps."}
    except SourceError as exc:
        raise SourceError(f"NSE feed unavailable. API: {api_error} RSS: {exc}") from exc


def nse_session():
    """One cookie-carrying opener after the ordinary public page visit."""
    opener = build_opener(HTTPCookieProcessor())
    request_bytes(NSE_PAGE, opener)
    return opener


def nse_json(path, params, opener):
    url = "https://www.nseindia.com/api/" + path + "?" + urlencode(params)
    try:
        return json.loads(request_bytes(url, opener))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceError("NSE returned an unreadable response.") from exc


def filings_by_symbol(companies, start, end, opener=None):
    """Per-issuer announcement queries: bounded responses for any window length."""
    opener = opener or nse_session()
    rows, skipped, failed = [], 0, []
    for symbol in sorted(companies):
        try:
            payload = nse_json("corporate-announcements", {
                "index": "equities", "symbol": symbol,
                "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}, opener)
            found, bad = parse_announcements(payload, {symbol: companies[symbol]})
            rows.extend(found)
            skipped += bad
        except SourceError:
            failed.append(symbol)
    return {"rows": rows, "skipped": skipped, "failed": failed,
            "coverage": "range" if not failed and not skipped else "partial"}


def finite_number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if (positive and value <= 0) or (not positive and value < 0):
        return None
    return float(value)


def parse_chart(payload, symbol, now):
    chart = payload.get("chart", {}) if isinstance(payload, dict) else {}
    results = chart.get("result")
    if chart.get("error") or not isinstance(results, list) or not results:
        raise SourceError("Yahoo returned no daily series.")
    data = results[0]
    if data.get("meta", {}).get("symbol", "").upper() != symbol + ".NS":
        raise SourceError("Yahoo returned a different ticker.")
    if data.get("meta", {}).get("currency") != "INR":
        raise SourceError("Yahoo did not identify this daily series as INR.")
    times = data.get("timestamp") or []
    quotes = data.get("indicators", {}).get("quote", [])
    if not quotes or not isinstance(quotes[0], dict):
        raise SourceError("Yahoo daily series has no prices.")
    closes, volumes = quotes[0].get("close", []), quotes[0].get("volume", [])
    if not (len(times) == len(closes) == len(volumes)):
        raise SourceError("Yahoo daily series has inconsistent lengths.")
    splits = {
        datetime.fromtimestamp(event["date"], IST).date().isoformat()
        for event in data.get("events", {}).get("splits", {}).values()
        if event.get("date")
    }
    local_now = now.astimezone(IST)
    cutoff = datetime.combine(local_now.date(), time(16, 15), IST)
    regular = data.get("meta", {}).get("currentTradingPeriod", {}).get("regular", {})
    closing_stamp = finite_number(regular.get("end"))
    if closing_stamp is not None:
        scheduled_end = datetime.fromtimestamp(closing_stamp, IST)
        if scheduled_end.date() == local_now.date():
            cutoff = max(cutoff, scheduled_end + timedelta(minutes=15))
    rows = {}
    for stamp, close, volume in zip(times, closes, volumes):
        day = datetime.fromtimestamp(stamp, IST).date()
        # The interval is daily. Today's changing candle enters the database
        # only after the local post-close buffer, regardless of the request time.
        if day > local_now.date() or (day == local_now.date() and local_now < cutoff):
            continue
        rows[day.isoformat()] = {"symbol": symbol, "day": day.isoformat(),
                                "close": finite_number(close, positive=True), "volume": finite_number(volume),
                                "split": day.isoformat() in splits}
    rows = [rows[key] for key in sorted(rows)]
    # Yahoo sometimes leaves the final daily close empty while its quote metadata
    # carries the settled price. Use it only when stamped after that session closed.
    meta = data.get("meta", {})
    settled, market_time = finite_number(meta.get("regularMarketPrice"), positive=True), finite_number(meta.get("regularMarketTime"))
    if rows and rows[-1]["close"] is None and settled and market_time:
        stamped = datetime.fromtimestamp(market_time, IST)
        if stamped.date().isoformat() == rows[-1]["day"] and stamped.time() >= time(15, 25):
            rows[-1]["close"] = settled
    if not rows or not any(row["close"] is not None for row in rows):
        raise SourceError("Yahoo returned no completed daily prices.")
    return rows


def prices(symbol, now):
    params = urlencode({"range": "3mo", "interval": "1d", "events": "splits"})
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol + ".NS", safe="") + "?" + params
    try:
        payload = json.loads(request_bytes(url))
        return parse_chart(payload, symbol, now)
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError,
            AttributeError, IndexError, OverflowError) as exc:
        raise SourceError("Yahoo returned an unreadable daily series.") from exc


def parse_csv(body, companies):
    """Import the CSV exported by NSE's public announcements page."""
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    required = {"SYMBOL", "SUBJECT", "ATTACHMENT", "BROADCAST DATE/TIME"}
    if not reader.fieldnames or not required.issubset({v.strip().upper() for v in reader.fieldnames}):
        raise SourceError("Choose the announcements CSV exported by NSE.")
    rows, skipped = [], 0
    for raw in reader:
        record = {key.strip().upper(): value for key, value in raw.items() if key}
        symbol = str(record.get("SYMBOL", "")).strip().upper()
        if symbol not in companies:
            continue
        try:
            rows.append(normal_filing(symbol, record["SUBJECT"], record.get("DETAILS", ""),
                                      record["ATTACHMENT"], record["BROADCAST DATE/TIME"]))
        except (SourceError, TypeError, ValueError):
            skipped += 1
    return rows, skipped
