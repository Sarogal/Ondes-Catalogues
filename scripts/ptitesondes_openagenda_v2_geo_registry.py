"""Trust boundary: attach venue sources ONLY from a separate curated registry.

No source assertion, URL, approval flag or GPS supplied by the collector can
select its own independent proof. Reject ambiguous city/venue aliases rather
than preferring a convenient institutional page. No publication or file I/O.
"""
from datetime import date
from proof import norm
from ptitesondes_openagenda_v2_geo_bridge import _url
from ptitesondes_openagenda_v2_geo_batch import diagnose_batch, MAX_BATCH

MAX_REVIEWED_SOURCES = 1500
MAX_ALIASES = 25


def _validate_registry(entries):
    if (not isinstance(entries, list) or len(entries) > MAX_REVIEWED_SOURCES):
        raise ValueError("invalid_reviewed_venue_registry")
    indexed = {}
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {
                "city", "aliases", "approved_host", "exact_url"}
                or not isinstance(entry["city"], str)
                or not 1 <= len(entry["city"].strip()) <= 120
                or not isinstance(entry["aliases"], list)
                or not 1 <= len(entry["aliases"]) <= MAX_ALIASES
                or not all(isinstance(a, str) and 1 <= len(a.strip()) <= 180
                           for a in entry["aliases"])
                or not isinstance(entry["approved_host"], str)
                or not isinstance(entry["exact_url"], str)
                or _url(entry["exact_url"],
                        host=entry["approved_host"]) is None):
            raise ValueError("invalid_reviewed_venue_registry")
        city = norm(entry["city"])
        urls = (entry["approved_host"], entry["exact_url"])
        for alias in entry["aliases"]:
            identity = (city, norm(alias))
            if not all(identity):
                raise ValueError("invalid_reviewed_venue_registry")
            indexed.setdefault(identity, set()).add(urls)
    return indexed


def diagnose_with_curated_registry(
        raw_cases, curated_sources, today, *, official_reader, geo_reader):
    """Review a bounded backlog sample; no source URL is trusted from intake.

    raw_cases must contain only lead/api_event/reviewed_agenda; the registry is
    independently maintained elsewhere. This function will NEVER use a host,
    official URL, 'approved' flag or coordinates embedded in an intake lead
    to pin a source, and never emits registry entries in its output.
    """
    if (type(today) is not date or not isinstance(raw_cases, list)
            or not 1 <= len(raw_cases) <= MAX_BATCH):
        raise ValueError("invalid_geometry_batch")
    trusted = _validate_registry(curated_sources)
    prepared = []
    for row in raw_cases:
        pin = None
        if (isinstance(row, dict) and set(row) == {
                "lead", "api_event", "reviewed_agenda"}
                and isinstance(row["lead"], dict)):
            lead = row["lead"]
            city, venue = lead.get("city"), lead.get("venue")
            if isinstance(city, str) and isinstance(venue, str):
                matches = trusted.get((norm(city), norm(venue)), set())
                if len(matches) == 1:
                    host, exact_url = next(iter(matches))
                    pin = {"approved_host": host, "exact_url": exact_url}
            prepared.append({
                "lead": row["lead"],
                "api_event": row["api_event"],
                "reviewed_agenda": row["reviewed_agenda"],
                "reviewed_source": pin,
            })
        else:
            # Preserve a safe input-shape rejection without forwarding
            # arbitrary fields from the collector to the network layer.
            prepared.append({"invalid_untrusted_case": True})
    report = diagnose_batch(
        prepared, today, official_reader=official_reader, geo_reader=geo_reader)
    return dict(report, registry_identity_attested=False,
                source_pins_selected_from_curated_registry_only=True)
