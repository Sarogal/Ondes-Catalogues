"""Read-only first-party evidence for a narrow editorial reconciliation.

No approval or deletion is authorized by this module. The consumer must
independently replay the evidence against the immutable signed original.
Network errors, changed dates, cancellations and absence of genre alone are
not evidence that an event should be removed.
"""
from __future__ import annotations

import datetime as dt
import re

from automation.concerts import openagenda_official_concert as oa

SCHEMA = "grossesondes.concert.editorial-genre-contamination.v1"
PROFILES = frozenset({
    "dynamic-openagenda-new-site-v1",
    "dynamic-existing-venue-openagenda-single-source-v1",
})
# Positive, explicit out-of-scope labels, not a blacklist of artists.
# Mixed or unfamiliar labels stay held rather than triggering retraction.
OUTSIDE = frozenset({
    "chaabi", "rai", "arabic pop", "arabic house", "r b", "rnb",
    "hip hop", "rap", "jazz", "techno", "house", "classical",
    "musique classique", "chanson francaise", "salsa", "reggaeton",
    "disco", "afrobeats", "soul", "gospel", "trance",
})


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _norm_list(values):
    _require(isinstance(values, list) and 1 <= len(values) <= 20
             and all(isinstance(v, str) and 1 <= len(v) <= 120 for v in values),
             "missing explicit labels")
    return [oa.normalized(v) for v in values]


def _phrase(phrase, text):
    return bool(phrase and re.search(
        r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))


def source(approval, event, venue):
    """Bind the source to the exact previously approved public event."""
    _require(isinstance(approval, dict)
             and approval.get("reviewDecision") == "approved"
             and approval.get("reviewedBy") == "independent-official-verifier",
             "independent original approval missing")
    original = approval.get("event")
    _require(isinstance(original, dict)
             and all(original.get(k) == event.get(k) for k in (
                 "id", "title", "date", "venueId", "artistIds", "genres",
                 "status", "sourceType", "officialUrl"))
             and event.get("status") == "confirmed"
             and event.get("venueId") == venue.get("id"),
             "published event identity differs from original signature")
    proofs = approval.get("officialEvidence")
    _require(isinstance(proofs, list), "missing original evidence")
    rows = [p for p in proofs if isinstance(p, dict)
            and p.get("proofType") in PROFILES]
    _require(len(rows) == 1, "missing unique original OpenAgenda proof")
    proof = rows[0]
    _require(proof.get("url") == event.get("officialUrl")
             and proof.get("checkedAt") == approval.get("reviewedAt")
             and oa.is_openagenda_event_url(event.get("officialUrl"))
             and _norm_list(proof.get("officialGenreLabels")) ==
                 _norm_list(event.get("genres")),
             "original genre or source differs from signature")
    original_names = proof.get("officialArtistNames")
    _require(isinstance(original_names, list)
             and isinstance(event.get("artistIds"), list)
             and len(original_names) == len(event["artistIds"])
             and all(isinstance(n, str) and oa.normalized(n)
                     for n in original_names), "original names missing")
    venue_name = oa.normalized(venue.get("name"))
    _require(all(_phrase(label, venue_name) for label in
                 _norm_list(event["genres"])), "no venue-label contamination candidate")
    return proof, oa.official_export_url(proof.get("officialOpenAgendaUid"),
                                         proof.get("officialOpenAgendaEventUid"))


def verify(approval, event, venue, today, *, fetch):
    """Return positive, source-bound editorial error evidence, or raise.

    Only a scheduled, identity-authenticated event with a fully explicit
    out-of-scope genre list, and an old label traceable to its physical venue
    qualifies. The standard corrected verifier must independently report
    missing genre evidence, not any other failure.
    """
    _require(isinstance(today, dt.date) and not isinstance(today, dt.datetime)
             and dt.date.fromisoformat(event["date"]) >= today,
             "not a future or current published event")
    proof, url = source(approval, event, venue)
    raw = fetch(url)
    args = dict(agenda_uid=proof["officialOpenAgendaUid"],
                event_uid=proof["officialOpenAgendaEventUid"])
    record, title = oa._verified_export_identity(
        raw, event["officialUrl"], event["date"], venue, **args)
    names = oa._bill({"@type": "MusicEvent", "name": title})
    _require([oa.normalized(n) for n in names] ==
             [oa.normalized(n) for n in proof["officialArtistNames"]],
             "fresh bill changed")
    keywords = record.get("keywords")
    labels = _norm_list((keywords.get("fr") or keywords.get("en"))
                        if isinstance(keywords, dict) else None)
    _require(all(v in OUTSIDE for v in labels),
             "mixed or unclassified explicit genre labels")
    desc = record.get("description")
    desc = (desc.get("fr") or desc.get("en")) if isinstance(desc, dict) else None
    _require(isinstance(desc, str) and 4 <= len(desc) <= 12000,
             "original description missing")
    reader = oa._LongDescriptionText()
    reader.feed(desc)
    reader.close()
    _require(_phrase(oa.normalized(venue["name"]),
                     oa.normalized(" ".join(reader.parts))),
             "venue phrase not present in original description")
    try:
        oa.verified_export(raw, event["officialUrl"], event["date"], venue, **args)
    except oa.MissingGenreEvidence:
        pass
    else:
        raise ValueError("current official evidence still qualifies")
    return {"schema": SCHEMA, "eventId": event["id"],
            "eventDate": event["date"], "venueId": venue["id"],
            "officialUrl": event["officialUrl"], "checkedAt": today.isoformat(),
            "agendaUid": int(args["agenda_uid"]), "eventUid": int(args["event_uid"]),
            "reason": "venue-name-genre-contamination",
            "oldGenres": event["genres"], "explicitOutsideGenres": labels,
            "publicationAllowed": False}
