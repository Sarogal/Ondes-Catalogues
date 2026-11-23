"""One first-party venue event is sufficient: NO second concert witness.

A source domain is bound to the already published venue by a previously
registered OFFICIAL venue agenda URL. The catalogue of source websites is
a discovery seed (not an artist allowlist); unlisted venues remain eligible
for the existing generic OSM/BAN paths. Re-reading the same published site
and official event is the Publisher check, not a second event-source demand.

Never trust an unverified private lead's claimed source/genre, a ticket
seller, or a similarly named venue. Only strict name, city, HTTPS origin and
a fresh full dated named event may create this profile.
"""
from __future__ import annotations
import json
from pathlib import Path

import source_admission_intake as intake

SOURCES = Path(__file__).with_name("sources.json")


def official_origin(venue, event_url, sources_path=None):
    """Return exact registered official venue agenda URL, or None.

    Matching is identity-based rather than an allowlist of artists/events:
    any newly discovered and verified source may be registered in the same
    discovery manifest, and unlisted sources still have other admission paths.
    """
    if not isinstance(venue, dict) or not isinstance(event_url, str):
        return None
    host = intake.valid_https(event_url)
    if not host:
        return None
    try:
        sources = json.loads(Path(sources_path or SOURCES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(sources, dict) or
            sources.get("schema") != "grossesondes.concert.sourcelist.v1" or
            not isinstance(sources.get("venues"), list)):
        return None
    candidates = []
    for row in sources["venues"]:
        if not isinstance(row, dict) or row.get("kind") != "official_venue_agenda_candidate":
            continue
        venue_name = intake.normalized(venue.get("name"))
        venue_city = intake.normalized(venue.get("city"))
        source_name = intake.normalized(row.get("name"))
        # A published room "Le Forum" can be registered under the explicit
        # official title "Le Forum de Vauréal". This precise city suffix is
        # not a fuzzy name match: the registered city must ALSO match, and
        # the HTTPS host must still be exactly the one recorded in sources.
        if (not venue_name or not venue_city
                or source_name not in {
                    venue_name, venue_name + " de " + venue_city}
                or intake.normalized(row.get("city")) != venue_city):
            continue
        trusted = row.get("url")
        other_host = intake.valid_https(trusted)
        if (other_host and host.removeprefix("www.") ==
                other_host.removeprefix("www.")):
            candidates.append(trusted)
    # Two competing venue-source records mean not enough provenance to choose.
    return candidates[0] if len(candidates) == 1 else None
