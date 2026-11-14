"""Read-only, deterministic regional coverage of the published outings catalogue.

Never writes/normalizes historic public entries or infers a region from a city.
A lexical alias is joined ONLY for reporting. All counts refer to Git main
catalogue snapshot, not a verified GitHub Pages/browser deployment.
"""
from collections import Counter
from datetime import date
import re

REGIONS = (
    "Auvergne-Rhône-Alpes",
    "Bourgogne-Franche-Comté",
    "Bretagne",
    "Centre-Val de Loire",
    "Corse",
    "Grand Est",
    "Guadeloupe",
    "Guyane",
    "Hauts-de-France",
    "Île-de-France",
    "La Réunion",
    "Martinique",
    "Mayotte",
    "Normandie",
    "Nouvelle-Aquitaine",
    "Occitanie",
    "Pays de la Loire",
    "Provence-Alpes-Côte d’Azur",
)
KNOWN = frozenset(REGIONS)
ALIASES = {
    "Provence-Alpes-Côte d'Azur": "Provence-Alpes-Côte d’Azur",
}
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def as_day(raw):
    """Invalid dates remain visible in the quality count, never guessed."""
    if not isinstance(raw, str) or ISO_DAY.fullmatch(raw) is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def regional_coverage(events, today):
    if not isinstance(today, date) or not isinstance(events, list):
        raise ValueError("Périmètre du catalogue régional invalide")
    totals = Counter()
    missing = 0
    unknown = 0
    alias_merges = 0
    invalid_dates = 0
    future = 0

    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Événement du catalogue incorrect")
        beginning = as_day(event.get("date_start"))
        end = as_day(event.get("date_end"))
        if beginning is None or end is None or end < beginning:
            invalid_dates += 1
            continue
        if end < today:
            continue
        future += 1
        raw_region = event.get("region")
        if raw_region is None or raw_region == "":
            missing += 1
            continue
        if not isinstance(raw_region, str):
            unknown += 1
            continue
        canon = ALIASES.get(raw_region, raw_region)
        if canon not in KNOWN:
            unknown += 1
            continue
        alias_merges += int(canon != raw_region)
        totals[canon] += 1

    reported = sum(totals.values())
    if reported + missing + unknown != future:
        raise ValueError("Totaux de couverture régionale non réconciliés")
    rows = [
        {"region": region, "future_events": totals[region]}
        for region in sorted(REGIONS, key=lambda x: (totals[x], x))
    ]
    return {
        "schema": "ptitesondes.public_catalogue_region_coverage.v1",
        "as_of": today.isoformat(),
        "scope": "public_git_catalogue_snapshot_not_browser",
        "future_events": future,
        "attributed_region": reported,
        "missing_region": missing,
        "unrecognized_region": unknown,
        "invalid_or_missing_dates": invalid_dates,
        "alias_spellings_collapsed": alias_merges,
        "regions_with_zero_events": sum(x["future_events"] == 0 for x in rows),
        "regions": rows,
    }
