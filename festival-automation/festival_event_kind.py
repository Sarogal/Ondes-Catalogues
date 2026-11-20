"""Conservative event-type guard: touring metal concerts are not local festivals.

A lone concert can be marketed as a "Fest"; reject a single-city tour stop
only with *explicit visible touring evidence*. Genuine multi-day or multi-venue
festivals must not be excluded by artists' touring biographies alone.
This module never publishes and never processes hidden script/JSON-LD claims.
"""
from __future__ import annotations

from datetime import date
import re

from grossesondes_official_html_edition import VisibleText, fold

# Text is accent-folded by the existing audited HTML parser.
ITINERANT_FESTIVAL = re.compile(
    r"\b(?:festival itinerant(?: annuel)?|concept de festival itinerant|"
    r"touring festival(?: concept)?|travelling festival(?: concept)?)\b"
)
TOUR_STOP_EVIDENCE = re.compile(
    r"\b(?:[1-9][0-9]{1,2} concerts?|[1-9][0-9]{1,2} shows?|"
    r"tournee (?:europeenne|en europe|de concerts)|"
    r"(?:european|uk|world) tour|"
    r"concerts? sans aucun jour de repos)\b"
)


def touring_concert_stop(html, start, end):
    """True only for an explicitly itinerant, single-day tour event.

    A marketing word or a headliner's touring activity alone is not proof.
    Both separate signals must occur in visible organiser/editorial text.
    """
    if not isinstance(start, date) or not isinstance(end, date) or start != end:
        return False
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return False
    try:
        parser = VisibleText()
        parser.feed(html)
        parser.close()
        visible = " ".join(fold(" ".join(parser.parts)).split())
    except (ValueError, TypeError, UnicodeError):
        return False
    return bool(ITINERANT_FESTIVAL.search(visible)
                and TOUR_STOP_EVIDENCE.search(visible))
