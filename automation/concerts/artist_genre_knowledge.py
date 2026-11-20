"""Independent artist-level genre knowledge for national Concerts review.

An event's genres describe the EVENT, not each act on the bill. A catalogued
artist is an identification hint, never a genre proof. First-party artist
profiles may produce reusable, dated evidence, but only from exact,
unambiguous MusicGroup/Person structured data on a reviewed official page.

No method in this module mutates a registry, grants an approval or publishes.
The first integration is private aggregate reporting only.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from urllib.parse import urlsplit

from triage import genre_evidence, words

SCHEMA = "grossesondes.concert.artist-genre-evidence.v1"
REVIEW_SCHEMA = "grossesondes.concert.artist-genre-review.v1"
_DISALLOWED = (
    "hardcore techno", "techno hardcore", "electronic hardcore",
    "hardcore edm", "hardcore electronic", "electronic hardcore",
)


def _aliases(catalogue):
    """Return only unambiguous exact names/aliases (no fuzzy matching)."""
    ids = defaultdict(set)
    for artist in catalogue.get("artists", []):
        if not isinstance(artist, dict) or not isinstance(artist.get("id"), str):
            continue
        names = [artist.get("name"), *(artist.get("aliases") or [])]
        for name in names:
            if isinstance(name, str) and words(name):
                ids[words(name)].add(artist["id"])
    return {k: next(iter(v)) for k, v in ids.items() if len(v) == 1}, {
        k for k, v in ids.items() if len(v) > 1
    }


def _named_bill(candidate):
    # Never split on '&': some actual artist names contain that character.
    named = candidate.get("leadArtist")
    if not isinstance(named, str):
        return []
    return [x.strip() for x in re.split(r"\s+\+\s+", named) if words(x)]


def _relevant_genre(label):
    if not isinstance(label, str) or not 1 <= len(label) <= 100:
        return False
    normalized = words(label)
    if any(s in normalized for s in _DISALLOWED):
        return False
    # A generic 'Rock' or musician biography is insufficient. triage's
    # classification vocabulary is reused, but no venue-wide tags are read.
    return bool(genre_evidence({"classification": [label]}))


def private_genre_review(registry, catalogue, as_of, artist_preflight=None):
    """Report only counts of *hints*, never artists, IDs, URLs or approvals."""
    if (registry.get("schema") != "grossesondes.concert.intake.v1"
            or not isinstance(registry.get("items"), dict)
            or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("artists", []), list)
            or not isinstance(catalogue.get("events"), list)
            or not isinstance(as_of, dt.date)):
        raise ValueError("Artist genre review: incompatible inputs")
    aliases, collisions = _aliases(catalogue)
    event_hints = set()
    for event in catalogue["events"]:
        if not isinstance(event, dict):
            continue
        genres = event.get("genres") or []
        if isinstance(genres, list) and any(_relevant_genre(g) for g in genres):
            event_hints.update(
                artist_id for artist_id in event.get("artistIds", [])
                if isinstance(artist_id, str)
            )
    # Facts from fresh, separate official first-party preflight.
    # Private research prioritization only, never a publication gate.
    verified_individual = set()
    if artist_preflight is not None:
        if (not isinstance(artist_preflight, dict)
                or artist_preflight.get("schema") !=
                    "grossesondes.concert.artist-genre-source-preflight.v1"
                or artist_preflight.get("publicationAllowed") is not False
                or artist_preflight.get("approvalsProposed") != 0
                or not isinstance(artist_preflight.get("verifiedArtists"), list)):
            raise ValueError("Untrusted artist preflight snapshot")
        for fact in artist_preflight["verifiedArtists"]:
            if not isinstance(fact, dict):
                continue
            try:
                verified_day = dt.date.fromisoformat(fact.get("verifiedAt"))
            except (TypeError, ValueError):
                continue
            if (not dt.timedelta(0) <= as_of - verified_day <= dt.timedelta(days=60)
                    or fact.get("schema") != SCHEMA
                    or fact.get("scope") != "individual_artist_not_event"
                    or fact.get("evidenceKind") not in {
                        "first-party-artist-structured-profile",
                        "first-party-artist-visible-linked-bio",
                    }
                    or fact.get("publicationAllowed") is not False
                    or fact.get("eventDateLocationAndLineupProved") is not False
                    or not isinstance(fact.get("sourceUrl"), str)
                    or not fact["sourceUrl"].startswith("https://")
                    or not isinstance(fact.get("genres"), list)
                    or not any(_relevant_genre(g) for g in fact["genres"])):
                continue
            verified_individual.add(fact.get("artistId"))
    counters = Counter()
    unique_known = set()
    unique_verified = set()
    for record in registry["items"].values():
        if not isinstance(record, dict):
            raise ValueError("Corrupt private artist review row")
        candidate = record.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("Corrupt private artist review candidate")
        if (candidate.get("reviewBucket") != "genre_unknown"
                or record.get("status", "pending_review") != "pending_review"):
            continue
        counters["unknownGenreAllDates"] += 1
        try:
            day = dt.date.fromisoformat(candidate.get("date"))
        except (TypeError, ValueError):
            continue
        if day < as_of:
            continue
        counters["futureUnknownGenre"] += 1
        names = _named_bill(candidate)
        # Name matching is useful for queue priority, NEVER for publication.
        resolved = {aliases[words(name)] for name in names
                    if words(name) in aliases}
        ambiguous = any(words(name) in collisions for name in names)
        if ambiguous:
            counters["ambiguousAliasHeld"] += 1
        if resolved:
            counters["knownArtistExactMatch"] += 1
            unique_known.update(resolved)
        if resolved & event_hints:
            counters["eventGenreHintOnly"] += 1
        if resolved & verified_individual:
            counters["officialArtistGenreVerifiedResearchLead"] += 1
            unique_verified.update(resolved & verified_individual)
        if resolved and not resolved & event_hints:
            counters["knownArtistWithoutEventGenreHint"] += 1
        if not resolved:
            counters["noExactKnownArtistMatch"] += 1
        if candidate.get("possibleExistingConcert") is True:
            counters["duplicateAdvisory"] += 1
    return {
        "schema": REVIEW_SCHEMA,
        "asOf": as_of.isoformat(),
        "publicationAllowed": False,
        "approvalsProposed": 0,
        "evidenceLevel": (
            "official-individual-artist-and-catalogue-event-hints"
            if artist_preflight is not None else
            "catalogue-event-genre-hints-only"
        ),
        "knownDistinctArtists": len(unique_known),
        "officialGenreVerifiedDistinctArtists": len(unique_verified),
        "counts": dict(sorted(counters.items())),
        "note": (
            "Only first-party structured artist profiles provide independent "
            "individual genre signals. Event genres are separate hints. "
            "Exact matches still cannot approve, date or locate a concert."
        ),
    }


class _StructuredScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._active = False
        self._data = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attributes = dict(attrs)
        self._active = attributes.get("type", "").lower().strip() == "application/ld+json"
        self._data = []

    def handle_data(self, data):
        if self._active:
            self._data.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._active:
            self.scripts.append("".join(self._data))
            self._active = False
            self._data = []


def _nodes(data):
    if isinstance(data, list):
        for value in data[:40]:
            yield from _nodes(value)
    elif isinstance(data, dict):
        if isinstance(data.get("@graph"), (dict, list)):
            yield from _nodes(data["@graph"])
        else:
            yield data


def _node_types(node):
    kinds = node.get("@type") or []
    if not isinstance(kinds, list):
        kinds = [kinds]
    return {str(t).rstrip("/").rsplit("/", 1)[-1] for t in kinds}


def _genre_labels(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or len(value) > 30:
        return []
    result = []
    for label in value:
        if _relevant_genre(label) and label not in result:
            result.append(label.strip())
    return result


def independently_verify_artist_profile(source, catalogue, html, actual_url, checked_at):
    """Extract a verified artist-level fact from a *freshly fetched* official page.

    Caller is responsible for independent network fetching and robots checks.
    A source must already be documented as artist_official; promoter/ticketing
    pages do not provide this form of artist-level evidence.
    """
    if not isinstance(checked_at, dt.date):
        raise ValueError("Invalid evidence timestamp")
    if not isinstance(source, dict) or source.get("sourceRole") != "artist_official" or source.get("enabled") is not True:
        raise ValueError("Unreviewed first-party artist source")
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("artists"), list):
        raise ValueError("Untrusted artist catalogue")
    expected = source.get("url")
    if not isinstance(expected, str) or not isinstance(actual_url, str):
        raise ValueError("Missing artist source URL")
    e, a = urlsplit(expected), urlsplit(actual_url)
    if (e.scheme != "https" or not e.hostname or e.username or e.password
            or a.scheme != "https" or e.netloc.casefold() != a.netloc.casefold()
            or e.path.rstrip("/") != a.path.rstrip("/")
            or e.query != a.query or a.fragment):
        raise ValueError("Official artist source changed URL")
    if not isinstance(html, str) or not 0 < len(html) <= 900_000:
        raise ValueError("Artist official page unreadable")
    artist_id = source.get("artistId")
    artists = [artist for artist in catalogue["artists"]
               if isinstance(artist, dict) and artist.get("id") == artist_id]
    if len(artists) != 1:
        raise ValueError("Artist ID missing or ambiguous")
    aliases, collisions = _aliases(catalogue)
    artist = artists[0]
    known_names = {words(n) for n in [artist.get("name"), *(artist.get("aliases") or [])]
                   if isinstance(n, str) and words(n)}
    if (not known_names or any(n in collisions or aliases.get(n) != artist_id
                               for n in known_names)):
        raise ValueError("Ambiguous catalogue artist alias")
    parser = _StructuredScripts()
    parser.feed(html)
    if len(parser.scripts) > 30:
        raise ValueError("Too many structured data blocks")
    matches = []
    for script in parser.scripts:
        try:
            parsed = json.loads(script)
        except (ValueError, TypeError):
            continue
        for node in _nodes(parsed):
            if ("MusicGroup" not in _node_types(node)
                    and not ("Person" in _node_types(node)
                             and words(node.get("jobTitle")) in {"musician", "musicien", "singer", "chanteur"})):
                continue
            if words(node.get("name")) not in known_names:
                continue
            genres = _genre_labels(node.get("genre"))
            if genres:
                matches.append(genres)
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous official individual artist genre")
    return {
        "schema": SCHEMA,
        "artistId": artist_id,
        "artistName": artist["name"],
        "genres": matches[0],
        "sourceUrl": actual_url,
        "verifiedAt": checked_at.isoformat(),
        "evidenceKind": "first-party-artist-structured-profile",
        "scope": "individual_artist_not_event",
        "publicationAllowed": False,
        "approvalsProposed": 0,
        "eventDateLocationAndLineupProved": False,
    }
