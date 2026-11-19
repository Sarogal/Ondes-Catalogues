"""Reusable OFFICIAL visible-bill discovery for already reviewed venues.

Some concert sites (notably La Rayonne) publish an exact page headline, event
date and individually named + genre-labelled performers in visible HTML, but
NO usable JSON-LD MusicEvent. The generic JSON-LD discovery path therefore
misses them entirely. This module is discovery-only and NEVER approves.

No artist, event title, event ID or event date is hardcoded here. Only a
separately code-reviewed venue/HTTPS domain in generic_music_event.SPECS may
pass, and the official page must prove the ENTIRE named bill.
"""
from __future__ import annotations

import datetime as dt
import re

import generic_music_event as trusted
import official_html_evidence as visible
import official_rss_jsonld_bridge as bridge
from triage import words

UNNAMED = frozenset(words(x) for x in bridge._UNANNOUNCED)
CANCELLED = re.compile(
    r"\b(?:concert|evenement|date)\s+(?:annulee?|reportee?)\b|"
    r"\b(?:event|show)\s+(?:cancelled|postponed)\b",
)


def _visible_event(html_text, spec, day):
    """Extract a complete, explicitly labelled single concert or fail closed."""
    if not isinstance(html_text, str) or len(html_text) > 1_000_000:
        return None
    parser = visible.VisibleBlocks()
    try:
        parser.feed(html_text)
        parser.close()
    except (ValueError, TypeError, RecursionError):
        return None
    blocks = parser.blocks
    headings = [(i, txt) for i, (tag, txt) in enumerate(blocks)
                if tag == "h1"]
    if len(headings) != 1:
        return None
    index, title = headings[0]
    if not isinstance(title, str) or not 2 <= len(title) <= 1000:
        return None

    detail = blocks[index + 1:index + 201]
    if not detail:
        return None
    # A displayed first-party show date is mandatory. Publication dates,
    # sale announcements or later biography dates cannot serve as date proof.
    early = detail[:14]
    event_dates = [
        visible._date_in(text)
        for tag, text in early if tag in {"strong", "time"}
        and visible._date_in(text)
    ]
    if len(event_dates) != 1:
        return None
    show_date = event_dates[0]
    try:
        if dt.date.fromisoformat(show_date) < day:
            return None
    except ValueError:
        return None

    intro = words(" ".join(txt for _, txt in early))
    if CANCELLED.search(intro):
        return None
    if (not any(visible._contains(text, spec["name"])
                for _, text in early)
            or not any(visible._contains(text, spec["city"])
                       for _, text in early)):
        return None

    pieces = [x.strip() for x in re.split(r"\s+\+\s+", title)]
    if not pieces or any(not 2 <= len(x) <= 120 for x in pieces):
        return None
    unnamed = None
    if words(pieces[-1]) in UNNAMED:
        unnamed = pieces.pop()
    if not pieces:
        return None
    if len({words(x) for x in pieces}) != len(pieces):
        return None

    # A complete named bill requires exactly one explicit individual
    # musician+genre heading for EVERY announced artist. Any extra, missing
    # or ambiguous performer must be reviewed rather than invented.
    sections = []
    for tag, txt in detail:
        if tag in {"h2", "h3"} and words(txt) in visible.END_SECTION:
            break
        if tag == "h4" and txt.lstrip().startswith("►"):
            heading = txt.lstrip().lstrip("►").strip()
            parts = re.split(r"\s+[–—]\s+|\s+-\s+", heading, maxsplit=2)
            if len(parts) < 2 or not 2 <= len(parts[0].strip()) <= 120:
                return None
            genre = visible._explicit_label(parts[1])
            if genre is None:
                return None
            sections.append((parts[0].strip(), genre))
    if (len(sections) != len(pieces)
            or any(words(name) != words(piece)
                   for (name, genre), piece in zip(sections, pieces))):
        return None

    genres, seen = [], set()
    for _, genre in sections:
        key = words(genre)
        if key not in seen:
            seen.add(key)
            genres.append(genre)
    if not genres:
        return None
    return {"title": title, "date": show_date, "names": pieces,
            "genres": genres, "unnamedSupportLabel": unnamed}


def extract_candidate(html_text, url, source, day, known):
    """One quarantined lead from an already reviewed first-party event page."""
    if (not isinstance(source, dict)
            or not isinstance(day, dt.date)
            or isinstance(day, dt.datetime)):
        return None
    # Reuse the immutable, separately approved host/path/venue contract.
    match = trusted.trusted_spec({
        "venue": source.get("name"), "city": source.get("city"),
        "department": source.get("department"), "sourceUrl": url,
    })
    if match is None:
        return None
    venue_id, spec = match
    event = _visible_event(html_text, spec, day)
    if event is None:
        return None

    # The headline and individually labelled artist headings are first-
    # party discovery evidence, not a signed independent recheck.
    import discover
    row = {
        "candidateId": "visible:" + discover.norm(spec["name"]) + ":"
                       + event["date"] + ":" + discover.norm(event["title"]),
        "source": "agenda_officiel_visible_bill",
        "sourceUrl": url, "sourcePage": source.get("url"),
        "date": event["date"], "name": event["title"],
        "leadArtist": " + ".join(event["names"]),
        "venue": spec["name"], "city": spec["city"],
        "department": spec["department"],
        "classification": event["genres"],
        "sourceConfidence": "fiche officielle HTML individuelle ; contrôle indépendant requis",
        "officialDetailFound": True,
        "publicationAllowed": False, "reviewRequired": True,
        "verifiedVenueIdHint": venue_id,
    }
    if event["unnamedSupportLabel"]:
        row["unannouncedSupportLabel"] = event["unnamedSupportLabel"]
    return discover.mark_match(row, known)



def verify(candidate, html_text, catalogue, today):
    """Independently re-fetch and sign an EXACT visible venue bill.

    Approval is never made from the first discovery snapshot: the existing
    official_recheck worker fetches the official page again only after the
    two-distinct-day stability gate. All identity, genre, room and host fields
    must be unchanged from the quarantined lead.
    """
    if (not isinstance(candidate, dict)
            or not isinstance(today, dt.date)
            or candidate.get("source") != "agenda_officiel_visible_bill"
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is True
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("officialDetailFound") is not True):
        raise ValueError("Piste HTML officielle non agréée")
    match = trusted.trusted_spec(candidate)
    if match is None:
        raise ValueError("Salle ou domaine HTML officiel non agréés")
    venue_id, spec = match
    import discover
    page = candidate.get("sourcePage")
    if page is not None and not discover.same_host(page, spec["base"]):
        raise ValueError("Page d'origine non officielle")
    if not isinstance(catalogue, dict):
        raise ValueError("Catalogue absent")
    catalogued = [v for v in catalogue.get("venues", [])
                  if isinstance(v, dict) and v.get("id") == venue_id]
    if (len(catalogued) != 1 or
            trusted.norm(catalogued[0].get("name")) != trusted.norm(spec["name"])
            or trusted.norm(catalogued[0].get("city")) != trusted.norm(spec["city"])
            or str(catalogued[0].get("department")) != spec["department"]):
        raise ValueError("Identité de salle HTML non corroborée au catalogue")

    official_source = {"name": spec["name"], "city": spec["city"],
                       "department": spec["department"], "url": spec["base"]}
    fresh = extract_candidate(
        html_text, candidate["sourceUrl"], official_source, today, set())
    if fresh is None:
        raise ValueError("Plateau HTML officiel complet non corroboré")
    for field in ("date", "name", "leadArtist", "venue", "city",
                  "department", "classification", "sourceUrl",
                  "unannouncedSupportLabel", "verifiedVenueIdHint"):
        if candidate.get(field) != fresh.get(field):
            raise ValueError("Identité de la fiche HTML modifiée : " + field)
    if candidate.get("verifiedVenueIdHint") != venue_id:
        raise ValueError("Salle HTML candidate altérée")

    # The artist names come from corroborating individual h4 genre headings,
    # NOT from JSON-LD Organization, title keywords or biographies.
    names = fresh["leadArtist"].split(" + ")
    return trusted.approve_verified_bill(
        catalogue, venue_id, spec, candidate["sourceUrl"], today,
        fresh["date"], names, fresh["classification"],
        fresh.get("unannouncedSupportLabel"),
        "verified-first-party-visible-bill-v1")


def inspect_published(event, html_text, artists):
    """Read-only venue-wide watchdog: never auto-cancel or rewrite."""
    spec = trusted.SPECS.get(event.get("venueId"))
    if spec is None:
        return {"status": "unsupported",
                "reason": "Salle non agréée pour le détail officiel"}
    current = _visible_event(html_text, spec, dt.date(1900, 1, 1))
    if current is None:
        return {"status": "content_review",
                "reason": "Plateau HTML officiel disparu ou ambigu"}
    if current["date"] != event.get("date"):
        return {"status": "date_review", "observedDate": current["date"],
                "reason": "Date HTML officielle différente, confirmation requise"}
    expected = [artists.get(aid) for aid in event.get("artistIds", [])]
    if (len(current["names"]) != len(expected)
            or any(not isinstance(name, str)
                   or trusted.norm(name) != trusted.norm(observed)
                   for name, observed in zip(expected, current["names"]))):
        return {"status": "lineup_review",
                "reason": "Plateau HTML officiel différent du catalogue"}
    if ([trusted.norm(x) for x in current["genres"]] !=
            [trusted.norm(x) for x in event.get("genres", [])]):
        return {"status": "content_review",
                "reason": "Genres HTML officiels modifiés"}
    return {"status": "matched", "observedDate": current["date"]}
