"""Strict independent schema.org lineup proof for an EXISTING published edition.

The private intake proposes a field-level delta, but its HTML, URL, and
interpretation are never trusted. The cloud synchronizer must independently
fetch the original edition's registered officialSite and pass that HTML here.

No date, status, cancellation, ticket, venue or geography can be changed.
"""
from datetime import date
from html.parser import HTMLParser
import json
import re
import unicodedata

PROOF_MODE = "structured-roster.v1"
ALLOWED_EVENT_TYPES = {"musicevent", "musicfestival", "festival"}
SENSITIVE_STATUSES = {"eventcancelled", "eventpostponed", "eventrescheduled"}
MAX_JSONLD_BYTES = 120_000


def canonical(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return "".join(re.findall(r"[a-z0-9]+", value))


def edition_name(value):
    return canonical(re.sub(r"\b20[2-4][0-9]\b", " ", str(value)))


def iso_day(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", value):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class JsonLD(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").split(";")[0].strip().lower() == "application/ld+json"
            self.parts = []

    def handle_data(self, text):
        if self.active and sum(len(p) for p in self.parts) <= MAX_JSONLD_BYTES:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            raw = "".join(self.parts)
            if len(raw) <= MAX_JSONLD_BYTES:
                try:
                    self.documents.append(json.loads(raw))
                except (ValueError, TypeError):
                    pass
            self.active = False
            self.parts = []


def walk(value, depth=0):
    if depth > 5:
        return
    if isinstance(value, list):
        for item in value[:100]:
            yield from walk(item, depth + 1)
    elif isinstance(value, dict):
        if "@type" in value:
            yield value
        if "@graph" in value:
            yield from walk(value["@graph"], depth + 1)


def artists(event):
    items = event.get("performer", [])
    if not isinstance(items, list):
        items = [items]
    result = set()
    for item in items[:120]:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and 3 <= len(canonical(name)) <= 90:
            result.add(canonical(name))
    return result


def matched_roster(html, original):
    """Return proven artist alias keys only for the exact same edition.

    Conflicting event dates, cancelled status or other editions cause
    fail-closed rejection. A generic recurring festival without a named
    edition year cannot certify a 2027 lineup.
    """
    if not isinstance(html, str) or not html or len(html) > 1_400_000:
        return None
    start = iso_day(original.get("startDate"))
    end = iso_day(original.get("endDate"))
    if not start or not end or start > end:
        return None
    name = edition_name(original.get("name", ""))
    if len(name) < 8:
        return None
    parser = JsonLD()
    parser.feed(html)
    official = set()
    matched = False
    for doc in parser.documents[:30]:
        for event in walk(doc):
            types = event.get("@type")
            if not isinstance(types, list):
                types = [types]
            types = {str(v).rsplit("/", 1)[-1].casefold() for v in types}
            if not types.intersection(ALLOWED_EVENT_TYPES):
                continue
            event_name = event.get("name")
            if not isinstance(event_name, str) or edition_name(event_name) != name:
                continue
            # The official source must explicitly identify this particular year.
            if str(start.year) not in re.findall(r"\b20[2-4][0-9]\b", event_name):
                continue
            ev_start = iso_day(event.get("startDate"))
            ev_end = iso_day(event.get("endDate")) or ev_start
            if ev_start != start or ev_end != end:
                return None
            status = str(event.get("eventStatus", "")).rsplit("/", 1)[-1].casefold()
            if status in SENSITIVE_STATUSES:
                return None
            matched = True
            official.update(artists(event))
    return official if matched and official else None


def validate_structured_roster(original, proposal, html, today):
    """Return (new_row, changed_fields, pending) or None.

    A syntactically valid patch is not an official proof. This validator
    independently compares its proposed lineup with the re-fetched official
    JSON-LD, after checking every before/after value.
    """
    if proposal.get("proofMode") != PROOF_MODE:
        return None
    source = original.get("officialSite")
    if not isinstance(source, str) or proposal.get("evidence") != [source]:
        return None
    changes = proposal.get("changes")
    if not isinstance(changes, list) or len(changes) != 3:
        return None
    fields = {}
    for change in changes:
        if not isinstance(change, dict) or not {"field", "before", "after"} <= set(change):
            return None
        key = change["field"]
        if key in fields or key not in {"lineup", "bands", "lastVerified"}:
            return None
        fields[key] = change
        if original.get(key) != change["before"] or key not in original:
            return None
    if set(fields) != {"lineup", "bands", "lastVerified"}:
        return None
    old, new = original.get("lineup"), fields["lineup"]["after"]
    if not (isinstance(old, list) and isinstance(new, list)
            and len(old) > 0 and new[:len(old)] == old
            and 1 <= len(new) - len(old) <= 12
            and all(isinstance(name, str) and 3 <= len(canonical(name)) <= 90 for name in new)):
        return None
    keys = [canonical(n) for n in new]
    if len(keys) != len(set(keys)):
        return None
    if not (type(original.get("bands")) is int and original["bands"] == len(old)
            and type(fields["bands"]["after"]) is int and fields["bands"]["after"] == len(new)):
        return None
    check_day = iso_day(fields["lastVerified"]["after"])
    today_day = iso_day(today)
    before_day = iso_day(fields["lastVerified"]["before"])
    if not check_day or not today_day or not before_day or not before_day <= check_day <= today_day:
        return None
    if proposal.get("verified_at") != fields["lastVerified"]["after"]:
        return None
    evidence_names = matched_roster(html, original)
    proposed_names = set(keys[len(old):])
    if not evidence_names or not proposed_names <= evidence_names:
        return None
    revised = dict(original)
    revised["lineup"] = list(new)
    revised["bands"] = len(new)
    revised["lastVerified"] = fields["lastVerified"]["after"]
    return revised, ["lineup", "bands", "lastVerified"], []
