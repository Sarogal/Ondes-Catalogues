"""Independent single-source proof for any future first-party Trabendo bill.

The venue's committed source-domain binding and exact physical catalogue
identity are checked BEFORE parsing. Discovery never grants authority.
No artist, date, or URL is individually allowlisted. The official event page
must display its own title, full future date, metal/punk genre and named room.
The preview and independent Publisher use the same strict HTML contract but
fetch the source separately. Door opening is never a music start time.
"""
from __future__ import annotations

import datetime as dt
import re

from automation.concerts import trabendo_adapter as adapter
from automation.concerts import official_venue_single_source as source

VENUE_ID = "le-trabendo-paris"
AGENDA = "https://www.letrabendo.net/programmation/"
FIRST_PARTY = {"name": "Le Trabendo", "city": "Paris", "url": AGENDA}


def supports(venue, url):
    """Never allow an untrusted lead to register the venue or host."""
    return (
        isinstance(venue, dict)
        and venue.get("id") == VENUE_ID
        and venue.get("name") == "Le Trabendo"
        and venue.get("city") == "Paris"
        and str(venue.get("department")) == "75"
        and str(venue.get("postalCode")) == "75019"
        and adapter.safe(url)
        and source.official_origin(venue, url) == AGENDA
    )


def verified_bill(html, url, venue, today):
    """First-party displayed bill; returned artist names were not invented."""
    if not supports(venue, url):
        raise ValueError("Trabendo: untrusted source or venue")
    if (not isinstance(today, dt.date) or isinstance(today, dt.datetime)
            or not isinstance(html, str) or not 150 <= len(html) <= 1_000_000):
        raise ValueError("Trabendo: missing bounded official HTML")
    observed = adapter.detail_candidate(
        html, url, FIRST_PARTY, today.isoformat())
    # The page's own <title> is the named billed act(s), and the local
    # 'concert - Genre → Trabendo' card is correlated to that same title.
    # Recommendations and biographies cannot add bands. Only an explicit
    # plus-separated billed headline can introduce additional named acts.
    title = observed["name"]
    names = [name.strip() for name in re.split(r"\s+\+\s+", title)]
    if (not names or any(not 2 <= len(name) <= 120 for name in names)
            or len({adapter.norm(name) for name in names}) != len(names)):
        raise ValueError("Trabendo: malformed named bill")
    genres = observed["classification"]
    if not genres or any(g not in adapter.GENRES for g in genres):
        raise ValueError("Trabendo: unsupported event-specific genre")
    return {
        "names": names,
        "genres": genres,
        "date": observed["date"],
        "venueId": VENUE_ID,
    }
