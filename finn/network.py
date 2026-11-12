"""Workspace-owned profiles, dated experience and explicit introduction paths."""
import json
import re
from collections import defaultdict
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
        return {p["id"]: dict(p) for p in desk.NETWORK["people"]}, [list(e) for e in desk.NETWORK["edges"]], {}
    with store.connection() as db:
        profiles = {r["id"]: json.loads(r["body"]) for r in db.execute(
            "SELECT id,body FROM workspace_people WHERE workspace=?", (workspaces.current(),))}
        edges = [[r[0], r[1], r[2]] for r in db.execute(
            "SELECT left_id,right_id,strength FROM workspace_edges WHERE workspace=?", (workspaces.current(),))]
        notes = {r["person"]: dict(r) for r in db.execute(
            "SELECT person,note,last_contact FROM workspace_notes WHERE workspace=?", (workspaces.current(),))}
    return profiles, edges, notes


STRENGTH = {3: "close", 2: "regular", 1: "acquaintance"}


def weight(edge):
    value = edge[2] if len(edge) > 2 else 2
    return value if value in STRENGTH else 2


def weights(edges):
    return {frozenset(edge[:2]): weight(edge) for edge in edges}


def paths(profiles, edges):
    """Recorded introduction paths of at most two hops; among equal lengths, the strongest weakest link."""
    adjacent = defaultdict(dict)
    for edge in edges:
        a, b = edge[0], edge[1]
        if a in {*profiles, "investor"} and b in {*profiles, "investor"}:
            adjacent[a][b] = adjacent[b][a] = weight(edge)
    found = {"investor": (["investor"], 4)}
    for first, w1 in sorted(adjacent["investor"].items()):
        found[first] = (["investor", first], w1)
    for first, w1 in sorted(adjacent["investor"].items()):
        for second, w2 in sorted(adjacent[first].items()):
            if second == "investor" or second in adjacent["investor"]:
                continue
            strength = min(w1, w2)
            if second not in found or strength > found[second][1]:
                found[second] = (["investor", first, second], strength)
    return {pid: path for pid, (path, _) in found.items()}


def public_person(profile, path, profiles, notes, symbol="", links=None):
    history = employment(profile)
    match = next((e for e in history if e["employer"].upper() == symbol.upper()), history[0])
    company = desk.COMPANIES.get(match["employer"], {}).get("name", match["employer"])
    private_note = notes.get(profile["id"], {})
    named_path = ["You", *[profiles[x]["name"] for x in (path or [])[1:]]]
    hops = list(zip((path or [])[:-1], (path or [])[1:]))
    strength = min((links or {}).get(frozenset(h), 2) for h in hops) if hops else None
    last_contact = private_note.get("last_contact") or profile.get("last_contact", "")
    return {**profile, "employment": history, "company": company, "role": match["role"],
            "link": STRENGTH.get(strength), "last_contact": last_contact,
            "reason": "Recorded experience at " + company, "path": named_path, "distance": len(path)-1 if path else None,
            "fictional": profile.get("synthetic", True), "note": private_note.get("note", ""),
            "can_edit": workspaces.private() and runtime.interactive()}


RELATIONS = json.loads((desk.DATA / "relations.json").read_text(encoding="utf-8"))
ROLE_OF = {"competitors": "a competitor", "suppliers": "a supplier", "customers": "a customer"}


def relation(symbol, employer):
    """'a competitor' / 'a supplier' / 'a customer' when the employer is mapped to this company."""
    for kind, names in RELATIONS.get(symbol.upper(), {}).items():
        if any(same_org(name, alias) for name in org_names(employer) for named in names for alias in org_names(named)):
            return ROLE_OF.get(kind)
    return None


def people(query="", symbol=""):
    profiles, edges, notes = load()
    reach = paths(profiles, edges)
    links = weights(edges)
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
        level, reason = 0, None
        if symbol:
            exact = next((e for e in employers if e.upper() == symbol.upper()), None)
            related = next(((e, relation(symbol, e)) for e in employers if relation(symbol, e)), None)
            sector = company and next((e for e in employers if desk.COMPANIES.get(e, {}).get("sector") == company["sector"]), None)
            if exact:
                level = 0
            elif related:
                level, reason = 1, f"Worked at {org_names(related[0])[-1]}, {related[1]} of {company['name'] if company else symbol}"
            elif sector:
                level, reason = 2, "Sector experience at " + org_names(sector)[-1]
            else:
                continue
        result = public_person(p, path, profiles, notes, symbol, links)
        if reason:
            result["reason"] = reason
        recent = max((e.get("end") or "9999") for e in history)
        ranked.append((level, len(path), recent, p["name"], result))
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
    if value.get("last_contact"):
        if date.fromisoformat(value["last_contact"]) > date.today():
            raise ValueError("Last contact cannot be in the future.")
        profile["last_contact"] = value["last_contact"]
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
        clean = {}
        for edge in edges:
            if not isinstance(edge, list) or len(edge) not in (2, 3) or any(not isinstance(x, str) or x not in valid for x in edge[:2]) or edge[0] == edge[1]:
                raise ValueError("Every acquaintance link needs two distinct existing profile IDs.")
            if len(edge) == 3 and edge[2] not in STRENGTH:
                raise ValueError("Link strength is 1 (acquaintance), 2 (regular) or 3 (close).")
            clean[tuple(sorted(edge[:2]))] = edge[2] if len(edge) == 3 else 2
        if bundle.get("replace") is True:
            db.execute("DELETE FROM workspace_edges WHERE workspace=?", (workspaces.current(),))
            db.execute("DELETE FROM workspace_people WHERE workspace=?", (workspaces.current(),))
            for removed in previous - {p["id"] for p in profiles}:
                db.execute("DELETE FROM workspace_notes WHERE workspace=? AND person=?", (workspaces.current(), removed))
        db.executemany("INSERT INTO workspace_people VALUES(?,?,?) ON CONFLICT(workspace,id) DO UPDATE SET body=excluded.body",
                       [(workspaces.current(), p["id"], json.dumps(p)) for p in profiles])
        db.executemany("INSERT INTO workspace_edges(workspace,left_id,right_id,strength) VALUES(?,?,?,?) "
                       "ON CONFLICT(workspace,left_id,right_id) DO UPDATE SET strength=excluded.strength",
                       [(workspaces.current(), a, b, w) for (a, b), w in clean.items()])
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
            "person": public_person(p, reach.get(p["id"]), profiles, notes, employer, weights(edges))}


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


def org_names(employer):
    company = desk.COMPANIES.get(employer.upper()) if isinstance(employer, str) else None
    return [employer] + ([company["name"]] if company else [])


def same_org(left, right):
    """Exact legal-name-insensitive match, or a whole-word prefix of at least two words."""
    from .people_filings import org_key
    a, b = org_key(left), org_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    if (long + " ").startswith(short + " ") and len(short.split()) >= 2:
        return True
    # "ICICI Group" covers ICICI Bank, ICICI Prudential and other group companies.
    for group, other in ((a, b), (b, a)):
        if group.endswith(" group") and (other + " ").startswith(group[:-6] + " "):
            return True
    return False


def school_key(name):
    from .people_filings import org_key
    key = org_key(name.replace(",", " "))
    key = re.sub(r"^indian institute of management\b", "iim", key)
    key = re.sub(r"^indian institute of technology\b", "iit", key)
    return key


def same_school(left, right):
    """Schools match exactly; a bare "IIT" or "IIM" never matches a particular campus."""
    a, b = school_key(left), school_key(right)
    return bool(a) and a == b and a not in {"iit", "iim", "nit"}


def years(job):
    start = int(job["start"][:4]) if job.get("start") else None
    end = int(job["end"][:4]) if job.get("end") else None
    return start, end


def ties(person, limit=3):
    """Who in the investor's network can speak to this person, and how strong is that link.

    Evidence ladder, strongest first: the person is a recorded contact; a contact's
    dated tenure overlaps the person's stated tenure at the same organisation; a
    contact worked at one of the person's organisations (overlap unknown); a
    contact studied at the same institution. Each tie keeps its introduction path.
    """
    profiles, edges, notes = load()
    reach = paths(profiles, edges)
    target = " ".join(person["name"].casefold().replace(".", " ").split())
    found = []
    for p in profiles.values():
        path = reach.get(p["id"])
        if not path:
            continue
        reasons = []
        if " ".join(p["name"].casefold().replace(".", " ").split()) == target:
            reasons.append((0, "This is a contact in your network."))
        first = p["name"].split()[0]
        for org in person.get("organisations", []):
            for job in employment(p):
                if not any(same_org(name, org["name"]) for name in org_names(job["employer"])):
                    continue
                start, end = years(job)
                since = int(org["since"]) if org.get("since") else None
                employer = org_names(job["employer"])[-1]
                span = f"{start or '?'}–{end or 'present'}"
                if since and (end is None or end >= since):
                    reasons.append((1, f"{first} was at {employer} {span}; {person['name']} joined {org['name']} in {since}, "
                                       f"so their time there overlapped."))
                else:
                    reasons.append((2, f"{first} worked at {employer} ({span}); {person['name']}'s career includes "
                                       f"{org['name']}. The filing does not give years, so overlap is unconfirmed."))
                break
        for school in person.get("education", []):
            if any(same_school(school, own) for own in p.get("education", [])):
                reasons.append((3, f"Studied at {school}, like {person['name']}."))
        if not reasons:
            continue
        reasons.sort()
        card = public_person(p, path, profiles, notes, "", weights(edges))
        card["tie"] = {"strength": ["direct", "strong", "likely", "weak"][reasons[0][0]],
                       "reasons": [text for _, text in reasons]}
        card["reason"] = reasons[0][1]
        found.append((reasons[0][0], len(path), p["name"], card))
    found.sort(key=lambda item: item[:3])
    return [item[-1] for item in found[:limit]]


def own_ties(person):
    """Where the investor's own recorded career or schooling overlaps the person's."""
    me = desk.NETWORK.get("investor", {})
    reasons = [f"You also studied at {school}." for school in person.get("education", [])
               if any(same_school(school, mine) for mine in me.get("education", []))]
    for org in person.get("organisations", []):
        for job in me.get("employment", []):
            if same_org(org["name"], job["employer"]):
                reasons.append(f"You worked at {job['employer']} ({job['start'][:4]}–{job['end'][:4] or 'present'}).")
    return reasons


def management_context(item, filing):
    """Incoming/outgoing people for a management-change filing, enriched with network ties."""
    if not item:
        fallback = incoming_person(filing)
        return {"status": fallback["status"], "reason": fallback["reason"], "person": fallback["person"], "people": []}
    people = []
    for person in item["people"]:
        entry = {key: person.get(key) for key in ("name", "role", "change", "profile", "organisations", "education", "degrees", "method")}
        entry["ties"] = ties(person) if person["change"] == "appointment" else []
        entry["you"] = own_ties(person) if person["change"] == "appointment" else []
        people.append(entry)
    incoming = next((p for p in people if p["change"] == "appointment"), None)
    if incoming and incoming["ties"]:
        count = len(incoming["ties"])
        reason = f"{count} {'person' if count == 1 else 'people'} in your network can speak to {incoming['name']}."
    elif incoming:
        reason = f"No one in your recorded network overlaps with {incoming['name']}'s stated career."
    else:
        reason = "Departure only; no incoming person is named in this filing."
    return {"status": "named" if people else "unresolved", "reason": reason, "people": people,
            "person": (incoming["ties"][0] if incoming and incoming["ties"] else None), "source": item["source"]}
