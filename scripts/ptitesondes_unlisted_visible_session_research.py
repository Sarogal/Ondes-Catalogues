"""Private HTML-only evidence for unknown first-party event pages.

NO allowlist of hosts, venues, agendas, or organizers. The HTTPS reader owns
network safety; this module only parses already fetched untrusted HTML.
Even a perfect match is an UNVERIFIED research hint, not authorship, venue
geolocation, source rights, ticket access, or permission to publish.
"""
from datetime import datetime
import re

from proof import norm
from proof_text import Visible, headline_matches

SCHEMA = "ptitesondes.unlisted_visible_session_research.v1"
MAX_HTML = 350_000
MAX_SESSIONS = 800
MONTH_LABELS = (
    ("janvier", "janv", "jan"),
    ("fevrier", "fevr", "fev"),
    ("mars",), ("avril", "avr"), ("mai",), ("juin",),
    ("juillet", "juil"), ("aout",), ("septembre", "sept"),
    ("octobre", "oct"), ("novembre", "nov"),
    ("decembre", "dec"),
)
ADULT_ONLY = re.compile(
    r"\b(?:reserve aux adultes|adultes uniquement|18 ans et plus"
    r"|interdit aux enfants|sans enfants)\b"
)
CHILD = re.compile(
    r"\b(?:jeune public|tout petits|enfants|petits et grands"
    r"|bebes|des 1 an|de 0 a [0-9]+ ans)\b"
)
MONTHS_RE = "|".join(sorted(
    {name for labels in MONTH_LABELS for name in labels}, key=len,
    reverse=True))


def _dated_anchor(text, start):
    d = start.date()
    month = "|".join(MONTH_LABELS[d.month - 1])
    pattern = (r"\b0?" + str(d.day) + r"\s+(?:" + month +
               r")\s+" + str(d.year) + r"\b")
    return re.search(pattern, text)


def _clock_visible(text, local_stamp):
    hh, mm = local_stamp.strftime("%H:%M").split(":")
    # Both 11:00 and 11h00 (or 11h for whole-hour showtimes).
    pattern = (r"\b0?" + str(int(hh)) +
               r"(?:\s+h\s*|h\s*|\s+)" + mm + r"\b")
    if re.search(pattern, text):
        return True
    return mm == "00" and bool(re.search(
        r"\b0?" + str(int(hh)) + r"\s*h\b", text))


def visible_unlisted_sessions(html, lead, intervals):
    out = {
        "schema": SCHEMA, "status": "visible_session_not_confirmed",
        "exact_visible_session_claims_unverified": 0,
        "source_title_heading_visible": False,
        "source_venue_visible": False,
        "family_audience_visible": False,
        "source_author_independently_verified": False,
        "gps_independently_verified": False,
        "rights_reviewed": False,
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
    if (type(html) is not str or len(html.encode("utf-8")) > MAX_HTML
            or type(lead) is not dict
            or type(lead.get("title")) is not str
            or type(lead.get("venue_unverified")) is not str
            or type(intervals) is not list
            or not 1 <= len(intervals) <= MAX_SESSIONS):
        return out
    parser = Visible()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return out
    heading = " ".join(parser.headers + parser.titles)
    if not headline_matches(lead["title"], heading):
        return out
    out["source_title_heading_visible"] = True
    body = norm(" ".join(parser.words))
    venue = norm(lead["venue_unverified"])
    if not venue or not re.search(
            r"(?<![a-z0-9])" + re.escape(venue) + r"(?![a-z0-9])", body):
        return out
    out["source_venue_visible"] = True
    if ADULT_ONLY.search(body[:4500]):
        out["status"] = "adult_only_source_held"
        return out
    out["family_audience_visible"] = bool(CHILD.search(body[:4500]))
    if not out["family_audience_visible"]:
        return out
    # Locate the first exact visible date within the event body. Never infer
    # recurring days from a month heading, range, or the page publication date.
    counts = 0
    for slot in intervals:
        if (type(slot) is not dict
                or set(slot) != {"begin", "end"}):
            return out
        try:
            begin = datetime.fromisoformat(slot["begin"])
            end = datetime.fromisoformat(slot["end"])
        except (ValueError, TypeError, KeyError):
            return out
        if (begin.tzinfo is None or end.tzinfo is None
                or begin.utcoffset() is None or end.utcoffset() is None
                or not begin < end):
            return out
        match = _dated_anchor(body, begin)
        if match is None:
            continue
        # The next explicit full date begins a distinct dated occurrence;
        # do not borrow its hours. Window is bounded even for long pages.
        window = body[match.end():match.end() + 3500]
        next_day = re.search(r"\b[0-3]?[0-9]\s+(?:" + MONTHS_RE +
                             r")\s+20[0-9]{2}\b", window)
        if next_day:
            window = window[:next_day.start()]
        if _clock_visible(window, begin):
            counts += 1
    out["exact_visible_session_claims_unverified"] = counts
    if counts == len(intervals):
        out["status"] = "all_exact_visible_sessions_unverified"
    elif counts:
        out["status"] = "partial_exact_visible_sessions_unverified"
    return out
