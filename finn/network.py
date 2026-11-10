"""Workspace-owned profiles, dated experience and explicit introduction paths."""
import json
import re
from collections import defaultdict, deque
from datetime import date, timedelta

from . import desk, documents, live_store as store, runtime, workspaces


def text(value, limit, label):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError("Provide a valid " + label + ".")
    return value.strip()


def employment(profile):
    if profile.get("employment"):
        return profile["employment"]
    years = re.findall(r"\d{4}", profile.get("tenure", ""))
    return [{"employer": profile["employer"], "role": profile["role"],
             "start": years[0] + "-01-01" if years else "", "end": years[-1] + "-12-31" if len(years) > 1 else "",
             "precision": "year"}]


def load():
    if not workspaces.private():
        return {p["id"]: dict(p) for p in desk.NETWORK["people"]}, desk.NETWORK["edges"], {}
    with store.connection() as db:
        profiles = {r["id"]: json.loads(r["body"]) for r in db.execute(
            "SELECT id,body FROM workspace_people WHERE workspace=?", (workspaces.current(),))}
        edges = [[r[0], r[1]] for r in db.execute("SELECT left_id,right_id FROM workspace_edges WHERE workspace=?", (workspaces.current(),))]
        notes = {r["person"]: dict(r) for r in db.execute(
            "SELECT person,note,last_contact FROM workspace_notes WHERE workspace=?", (workspaces.current(),))}
    return profiles, edges, notes


def paths(profiles, edges):
    adjacent = defaultdict(list)
    for a, b in edges:
        if a in {*profiles, "investor"} and b in {*profiles, "investor"}:
            adjacent[a].append(b)
            adjacent[b].append(a)
    found = {"investor": ["investor"]}
    queue = deque(["investor"])
    while queue:
        item = queue.popleft()
        if len(found[item]) >= 3:
            continue
        for other in sorted(adjacent[item]):
            if other not in found:
                found[other] = [*found[item], other]
                queue.append(other)
    return found


def public_person(profile, path, profiles, notes, symbol=""):
    history = employment(profile)
    match = next((e for e in history if e["employer"].upper() == symbol.upper()), history[0])
    company = desk.COMPANIES.get(match["employer"], {}).get("name", match["employer"])
    private_note = notes.get(profile["id"], {})
    named_path = ["You", *[profiles[x]["name"] for x in (path or [])[1:]]]
    return {**profile, "employment": history, "company": company, "role": match["role"],
            "reason": "Recorded experience at " + company, "path": named_path, "distance": len(path)-1 if path else None,
            "fictional": profile.get("synthetic", True), "note": private_note.get("note", ""),
            "last_contact": private_note.get("last_contact", ""), "can_edit": workspaces.private() and runtime.interactive()}


def people(query="", symbol=""):
    profiles, edges, notes = load()
    reach = paths(profiles, edges)
    tokens = desk.words(query)
    company = desk.COMPANIES.get(symbol.upper())
    ranked = []
    for p in profiles.values():
        path = reach.get(p["id"])
        if not path:
            continue
        history = employment(p)
        employers = [e["employer"] for e in history]
        words = desk.words(" ".join([p["name"], *p["topics"], *p.get("education", []), *[
            " ".join([e["employer"], e["role"], desk.COMPANIES.get(e["employer"], {}).get("name", ""),
                      desk.COMPANIES.get(e["employer"], {}).get("sector", "")]) for e in history]]))
        if tokens and not tokens.issubset(words) or query.strip() and not tokens:
            continue
        exact = any(e.upper() == symbol.upper() for e in employers) if symbol else False
        sector = company and any(desk.COMPANIES.get(e, {}).get("sector") == company["sector"] for e in employers)
        if symbol and not (exact or sector):
            continue
        result = public_person(p, path, profiles, notes, symbol)
        if symbol and not exact:
            result["reason"] = "Sector experience at " + result["company"]
        recent = max((e.get("end") or "9999") for e in history)
        ranked.append((not exact, len(path), recent, p["name"], result))
    ranked.sort(key=lambda x: x[2], reverse=True)
    ranked.sort(key=lambda x: (x[0], x[1]))
    return [p[-1] for p in ranked]


def validate_profile(value, synthetic):
    if not isinstance(value, dict):
        raise ValueError("Each profile must be an object.")
    pid = text(value.get("id"), 40, "profile id")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", pid) or pid == "investor":
        raise ValueError("Profile IDs use letters, numbers, underscores or dashes.")
    profile = {"id": pid, "name": text(value.get("name"), 100, "name"),
               "role": text(value.get("role"), 100, "role"), "employer": text(value.get("employer"), 100, "employer"),
               "tenure": text(value.get("tenure"), 50, "tenure"), "synthetic": synthetic}
    topics = value.get("topics")
    if not isinstance(topics, list) or not 1 <= len(topics) <= 12:
        raise ValueError("Each profile needs 1–12 areas of experience.")
    profile["topics"] = [text(t, 80, "topic") for t in topics]
    profile["question"] = text(value.get("question", "What would you ask about this company's operations?"), 400, "question")
    education = value.get("education", [])
    if not isinstance(education, list) or len(education) > 5:
        raise ValueError("Keep at most five education entries.")
    profile["education"] = [text(e, 120, "education entry") for e in education]
    history = value.get("employment", employment(profile))
    if not isinstance(history, list) or not 1 <= len(history) <= 10:
        raise ValueError("Provide 1–10 dated employment entries.")
    parsed = []
    for job in history:
        if not isinstance(job, dict):
            raise ValueError("Employment entries must be objects.")
        start, end = job.get("start", ""), job.get("end", "")
        for day in (start, end):
            if day:
                date.fromisoformat(day)
        if start and end and start > end:
            raise ValueError("Employment start must precede its end.")
        parsed.append({"employer": text(job.get("employer"), 100, "employer"),
                       "role": text(job.get("role"), 100, "role"), "start": start, "end": end,
                       "precision": "year" if job.get("precision") == "year" else "day"})
    profile["employment"] = parsed
    if not synthetic:
        consent = value.get("consent", {})
        if consent.get("granted") is not True or consent.get("purpose") != "investment research":
            raise ValueError("Real profiles require recorded opt-in consent for investment research.")
        expires = date.fromisoformat(consent.get("expires", ""))
        if expires < date.today():
            raise ValueError("Profile consent has expired.")
        profile["consent"] = {"granted": True, "purpose": "investment research", "expires": expires.isoformat(),
                              "source": text(consent.get("source"), 240, "consent provenance")}
    return profile


def import_bundle(bundle):
    if not isinstance(bundle, dict) or not isinstance(bundle.get("people"), list) or len(bundle["people"]) > 200:
        raise ValueError("Import a network object with at most 200 people.")
    synthetic = bundle.get("synthetic") is True
    profiles = []
    for p in bundle["people"]:
        fictional = p.get("synthetic", synthetic) is True if isinstance(p, dict) else synthetic
        if runtime.public_demo() and not fictional:
            raise ValueError("The public demo accepts fictional profiles only.")
        profiles.append(validate_profile(p, fictional))
    if len({p["id"] for p in profiles}) != len(profiles):
        raise ValueError("Profile IDs must be unique.")
    edges = bundle.get("edges", [])
    if not isinstance(edges, list) or len(edges) > 600:
        raise ValueError("Keep at most 600 recorded acquaintance links.")
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = {r[0] for r in db.execute("SELECT id FROM workspace_people WHERE workspace=?", (workspaces.current(),))}
        valid = {p["id"] for p in profiles} | (set() if bundle.get("replace") is True else previous) | {"investor"}
        if len(valid) > 201:
            raise ValueError("Keep at most 200 people in a workspace.")
        clean = set()
        for edge in edges:
            if not isinstance(edge, list) or len(edge) != 2 or any(not isinstance(x, str) or x not in valid for x in edge) or edge[0] == edge[1]:
                raise ValueError("Every acquaintance link needs two distinct existing profile IDs.")
            clean.add(tuple(sorted(edge)))
        if bundle.get("replace") is True:
            db.execute("DELETE FROM workspace_edges WHERE workspace=?", (workspaces.current(),))
            db.execute("DELETE FROM workspace_people WHERE workspace=?", (workspaces.current(),))
            for removed in previous - {p["id"] for p in profiles}:
                db.execute("DELETE FROM workspace_notes WHERE workspace=? AND person=?", (workspaces.current(), removed))
        db.executemany("INSERT INTO workspace_people VALUES(?,?,?) ON CONFLICT(workspace,id) DO UPDATE SET body=excluded.body",
                       [(workspaces.current(), p["id"], json.dumps(p)) for p in profiles])
        db.executemany("INSERT OR IGNORE INTO workspace_edges VALUES(?,?,?)", [(workspaces.current(), a, b) for a, b in clean])
    return len(profiles)


def save_note(person, note, last_contact):
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("Keep a contact note within 2,000 characters.")
    if last_contact and date.fromisoformat(last_contact) > date.today():
        raise ValueError("Last contact cannot be in the future.")
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM workspace_people WHERE workspace=? AND id=?", (workspaces.current(), person)).fetchone():
            raise ValueError("This profile is not in your workspace.")
        db.execute("INSERT INTO workspace_notes VALUES(?,?,?,?) ON CONFLICT(workspace,person) DO UPDATE SET "
                   "note=excluded.note,last_contact=excluded.last_contact", (workspaces.current(), person, note.strip(), last_contact))


def delete_person(person):
    with store.connection() as db:
        db.execute("DELETE FROM workspace_people WHERE workspace=? AND id=?", (workspaces.current(), person))
        db.execute("DELETE FROM workspace_notes WHERE workspace=? AND person=?", (workspaces.current(), person))
        db.execute("DELETE FROM workspace_edges WHERE workspace=? AND (left_id=? OR right_id=?)", (workspaces.current(), person, person))


def resolve(name, employer, role, on):
    profiles, edges, notes = load()
    reach = paths(profiles, edges)
    if not name.strip() or not employer.strip() or not role.strip() or not on:
        return {"status": "unresolved", "reason": "Name, employer, role and event date are needed to corroborate identity.", "person": None}
    day = date.fromisoformat(on).isoformat()
    if day > date.today().isoformat():
        return {"status": "unresolved", "reason": "A future role cannot be corroborated from recorded tenure.", "person": None}
    aliases = {"cfo":"chief financial officer", "ceo":"chief executive officer", "md":"managing director"}
    normalize_role = lambda v: aliases.get(v.casefold(), v.casefold())
    candidates = []
    for p in profiles.values():
        if " ".join(p["name"].casefold().split()) != " ".join(name.casefold().split()):
            continue
        for job in employment(p):
            company = desk.COMPANIES.get(job["employer"], {}).get("name", job["employer"])
            if employer.casefold() not in {job["employer"].casefold(), company.casefold()} or normalize_role(role) != normalize_role(job["role"]):
                continue
            if not job.get("start") or job["start"] > day or job.get("end") and job["end"] < day:
                continue
            candidates.append(p)
            break
    if len(candidates) != 1:
        return {"status": "ambiguous" if candidates else "unresolved", "reason":
                "More than one corroborated profile matches; no introduction was inferred." if candidates else "No corroborated employment match is recorded.", "person": None}
    p = candidates[0]
    return {"status": "matched", "reason": "Name, employer, role and dated tenure match a recorded profile.",
            "person": public_person(p, reach.get(p["id"]), profiles, notes, employer)}


def incoming_person(filing):
    """Only explicit appointment metadata can nominate a person; never infer a biography."""
    body = filing["title"] + " " + filing.get("details", "")
    roles = r"Chief Financial Officer|Chief Executive Officer|Managing Director|CFO|CEO|MD"
    pattern = r"(?:appointment of|appointed)\s+(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}?)\s+(?:as|to the position of)\s+(?:the\s+)?(" + roles + r")\b"
    match = re.search(pattern, body, re.I)
    if not match:
        return {"status": "unresolved", "person": None, "reason": "The filing metadata does not establish an incoming person's name and role. Inspect its original before linking a profile."}
    from .providers import timestamp, IST
    on = timestamp(filing["published"]).astimezone(IST).date().isoformat()
    return resolve(match[1], filing["symbol"], match[2], on)


def reconnect(symbol, event_date=None):
    today = date.fromisoformat(event_date[:10]) if event_date else date.today()
    result = []
    for p in people(symbol=symbol):
        if p["last_contact"] and date.fromisoformat(p["last_contact"]) <= today - timedelta(days=90):
            trigger = "A filing at " + symbol if event_date else "Your research on " + symbol
            result.append({"person": p, "reason": trigger + " is a reason to reconnect; last contact " + p["last_contact"] + "."})
    return result[:2]
