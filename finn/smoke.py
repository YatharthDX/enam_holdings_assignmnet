"""Read-only checks of a running FINN deployment, without upstream/model calls."""
import argparse
import json
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class SmokeError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SmokeError(message)


def run(base_url="http://127.0.0.1:8080", *, expect_public_demo=False, timeout=15):
    parsed = urlsplit(base_url)
    require(parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment,
            "Use an HTTP(S) origin without credentials, a path, query or fragment.")
    require(1 <= timeout <= 60, "Timeout must be between 1 and 60 seconds.")
    base_url = base_url.rstrip("/")

    def read(path, *, html=False):
        request = Request(base_url + path, headers={"Accept": "text/html" if html else "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read(2 * 1024 * 1024 + 1)
            require(len(body) <= 2 * 1024 * 1024, "Unexpectedly large response from " + path)
            return body if html else json.loads(body)
        except (URLError, OSError, UnicodeError, json.JSONDecodeError):
            raise SmokeError("Could not read " + path + ". Check the service URL, startup and logs.") from None

    checks = []
    health = read("/health")
    require(health.get("status") == "ok" and health.get("version") == "0.6.4", "Expected a healthy FINN 0.6.4 service.")
    checks.append("Health and release version")
    require(b"/assets/app.js" in read("/", html=True), "The application shell is unavailable.")
    checks.append("Browser application shell")
    catalog = read("/api/catalog")
    require(15 <= sum(c.get("holding", False) for c in catalog["companies"]) <= 20, "Portfolio size is outside the demo scope.")
    checks.append("Portfolio catalog")
    brief = read("/api/brief?mode=replay&window=7d")
    require(brief["rows"] and brief["focus"] == "INFY" and brief["people"], "Historical filing-to-contact workflow is unavailable.")
    checks.append("Historical brief and inline network")
    research = read("/api/research/INFY?q=currency")
    comparison = research["comparison"]
    require(comparison and comparison["actual"]["value"] == 4.2 and len(comparison["forecasts"]) == 4,
            "Historical guidance data is incomplete.")
    require(comparison["forecasts"][0]["position"] == "above" and comparison["forecasts"][0]["points"] == 1.2
            and comparison["forecasts"][-1]["position"] == "below" and comparison["forecasts"][-1]["points"] == .3,
            "Historical guidance comparison is incorrect.")
    checks.append("Original/revised guidance arithmetic")
    require(research["matches"] and any(m.get("page") and m["url"].startswith("https://") for m in research["matches"]),
            "Page-linked evidence search is unavailable.")
    checks.append("Evidence search and original PDF links")
    people = read("/api/people")["people"]
    require(people and all(p["fictional"] for p in people) and {p["distance"] for p in people} == {1, 2},
            "Fictional direct/second-degree network is incomplete.")
    checks.append("Direct People search and recorded paths")
    empty = read("/api/research/UNCOVERED")
    require(not empty["sources"] and empty["comparison"] is None, "An uncovered ticker was supplied with unsupported evidence.")
    checks.append("Missing-evidence state")
    model = read("/api/llm/status")
    if expect_public_demo:
        require(health.get("public_demo") is True and catalog.get("runtime", {}).get("read_only") is True,
                "The deployment is not configured for public mode with anonymous read-only access.")
        require(health["llm_enabled"] is model["enabled"], "AI capability reports disagree.")
        if model["enabled"]:
            require(model.get("provider") == "openrouter" and model.get("free_only") is True,
                    "Public demo AI must use free-only OpenRouter.")
        checks.append("Public demo capabilities and free-only AI policy")
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--expect-public-demo", action="store_true")
    parser.add_argument("--timeout", type=float, default=15, help="Per-request timeout in seconds (1–60).")
    args = parser.parse_args(argv)
    try:
        checks = run(args.base_url, expect_public_demo=args.expect_public_demo, timeout=args.timeout)
    except (SmokeError, KeyError, TypeError) as exc:
        # Expected check failures are concise; do not print raw HTTP bodies or credentials.
        print("FAIL: " + (str(exc) if isinstance(exc, SmokeError) else "Unexpected response structure."))
        return 1
    for check in checks:
        print("PASS: " + check)
    print("Read-only checks passed. No refresh, discovery or generation request was sent.")
    print("Live-source availability and clean-cache ticker discovery still need an operator check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
