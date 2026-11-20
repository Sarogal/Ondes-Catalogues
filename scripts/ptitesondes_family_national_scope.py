"""National P'tites Ondes family-outing scope: a PROPOSAL, never admission.

The historical musical catalogue and OpenAgenda checks are unchanged.
This standalone taxonomy defines extra subjects for future independently
verified dated events and routes permanent venues to "Lieux pour enfants".
No collector text, dates or claims confer official verification or approval.
No file, network, catalogue, publisher or patch access is provided here.
"""
from collections import Counter
from datetime import date
import re
from urllib.parse import urlsplit

SCHEMA = "ptitesondes.family_national_scope_readonly.v1"
MAX_ITEMS = 100

# The four Gosier categories from #323/#327 are immutable here. Do not
# update their specialized municipal SERIES matcher or approval pathways.
FAMILY_TYPES = {
    "lecture-jeunesse": ("Lecture jeunesse", "lecture"),
    "atelier-numerique": ("Atelier numérique", "atelier"),
    "lecture-cinema": ("Lecture et cinéma", "cinema"),
    "jeux-famille": ("Jeux en famille", "jeux"),
    "atelier-creatif": ("Atelier créatif", "atelier"),
    "atelier-scientifique": ("Atelier scientifique", "atelier"),
    "spectacle-jeunesse": ("Spectacle jeune public", "spectacle"),
    "cinema-jeunesse": ("Cinéma jeune public", "cinema"),
    "sortie-nature": ("Sortie nature", "nature"),
    "animaux-ferme": ("Animaux et ferme pédagogique", "nature"),
    "musee-patrimoine": ("Musée et patrimoine", "culture"),
    "fete-familiale": ("Fête et animation familiale", "evenement"),
    "activite-sportive": ("Activité sportive jeunesse", "sport"),
}

# Editorial policy: P'tites Ondes is a children's RADIO app, not a
# general-purpose family outing directory. Retain the historical taxonomy
# for compatibility, but propose only storytelling or youth performances.
RADIO_EDITORIAL_NONMUSIC = frozenset({
    "lecture-jeunesse", "spectacle-jeunesse",
})

# Existing musical publishing categories are not re-routed or revalidated by
# this experimental contract. Their own proof and OpenAgenda path is retained.
LEGACY_MUSICAL = frozenset({
    "concert", "conte-musical", "spectacle-musical", "eveil-musical",
    "atelier-musical", "cine-concert", "festival",
})
KNOWN_AUDIENCES = frozenset({
    "explicit_child", "explicit_family", "explicit_baby",
})
KNOWN_PRICE = frozenset({
    "explicit_free", "explicit_price", "not_stated", "ambiguous",
    "contradictory",
})
KNOWN_REGISTRATION = frozenset({
    "explicit_required", "explicit_not_required", "not_stated",
    "ambiguous", "contradictory",
})
_CANDIDATE_FIELDS = frozenset({
    "record_kind", "title", "city", "venue", "source_url",
    "audience_claim", "age_min", "age_max", "price_evidence",
    "registration_evidence", "category", "category_label",
    "date_start", "date_end",
})
_FORBIDDEN_OUTPUT_KEYS = frozenset({
    "events", "additions", "updates", "patch", "patch.v1",
    "catalogue", "source_url", "review_id", "candidates",
})
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _official_url_shape(url):
    """HTTPS shape is a *precheck*, absolutely NOT proof of an official page."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https"
                and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and parsed.port in (None, 443)
                and not parsed.fragment)
    except ValueError:
        return False


def _valid_age_claim(row):
    if not isinstance(row.get("audience_claim"), str) or row["audience_claim"] not in KNOWN_AUDIENCES:
        return False
    lo, hi = row.get("age_min"), row.get("age_max")
    if not all(
        v is None or (type(v) is int and 0 <= v <= 17)
        for v in (lo, hi)
    ):
        return False
    return lo is None or hi is None or lo <= hi


def _event_dates(row, today):
    first, last = row.get("date_start"), row.get("date_end")
    if (not isinstance(first, str) or not ISO_DAY.fullmatch(first)
            or not isinstance(last, str) or not ISO_DAY.fullmatch(last)):
        return False
    try:
        start, end = date.fromisoformat(first), date.fromisoformat(last)
    except ValueError:
        return False
    # This stage never expands recurrences, guesses sessions, or recycles
    # expired dates. A range here is *not* a proof of all intermediate dates.
    return first == start.isoformat() and last == end.isoformat() and (
        start <= end and end >= today
    )


def _candidate_issues(row, today):
    if not isinstance(row, dict):
        return {"invalid_scope_item"}, None, None
    blockers = set()
    if set(row) - _CANDIDATE_FIELDS:
        blockers.add("unexpected_collector_field")
    kind = row.get("record_kind")
    route = "sorties" if kind == "dated_event" else (
        "lieux" if kind == "permanent_place" else None
    )
    if route is None:
        blockers.add("unknown_record_kind")
    if not all(isinstance(row.get(k), str) and row[k].strip()
               for k in ("title", "city", "venue")):
        blockers.add("missing_place_or_title")
    if not _official_url_shape(row.get("source_url")):
        blockers.add("source_url_shape_unverified")
    if not _valid_age_claim(row):
        blockers.add("explicit_family_audience_claim_missing_or_invalid")

    if (not isinstance(row.get("price_evidence"), str)
            or row["price_evidence"] not in KNOWN_PRICE
            or not isinstance(row.get("registration_evidence"), str)
            or row["registration_evidence"] not in KNOWN_REGISTRATION):
        blockers.add("access_evidence_state_missing_or_invalid")

    category, facet = None, None
    if kind == "dated_event":
        code = row.get("category")
        if isinstance(code, str) and code in LEGACY_MUSICAL:
            blockers.add("legacy_musical_pipeline_unchanged")
        elif not isinstance(code, str) or code not in FAMILY_TYPES:
            blockers.add("nonmusical_category_not_in_explicit_contract")
        else:
            label, facet = FAMILY_TYPES[code]
            if row.get("category_label") != label:
                blockers.add("category_label_mismatch")
            category = code
            if code not in RADIO_EDITORIAL_NONMUSIC:
                blockers.add("outside_radio_editorial_scope")
        if not _event_dates(row, today):
            blockers.add("dated_occurrence_unverified_or_expired")
    elif kind == "permanent_place":
        # Permanent places belong in the existing "Lieux pour enfants" layer,
        # not as infinite recurring fake events or permanent calendar rows.
        if (row.get("date_start") is not None
                or row.get("date_end") is not None
                or row.get("category") is not None
                or row.get("category_label") is not None):
            blockers.add("permanent_place_must_not_be_dated_outing")
    return blockers, route, facet


def audit_family_scope(proposals, today):
    """Return counts and generic refusal reasons only, never publishable data.

    Every "possible" item still requires independently checked official
    details, identity, location, family audience, admission and duplication.
    The input audience, URL, tariff and registration labels are only
    *untrusted claims*. Nothing is auto-certified or made available to users.
    """
    if type(today) is not date:
        raise ValueError("invalid_scope_day")
    if (not isinstance(proposals, list)
            or not 1 <= len(proposals) <= MAX_ITEMS):
        raise ValueError("invalid_scope_batch")
    issues = Counter()
    routes = Counter()
    facets = Counter()
    category_counts = Counter()
    plausible = 0
    for row in proposals:
        reasons, route, facet = _candidate_issues(row, today)
        if reasons:
            issues.update(sorted(reasons))
            continue
        plausible += 1
        routes[route] += 1
        if facet:
            facets[facet] += 1
            category_counts[row["category"]] += 1

    result = {
        "schema": SCHEMA,
        "mode": "national_editorial_scope_proposal_never_publish",
        "input_count": len(proposals),
        "structurally_plausible_for_independent_review": plausible,
        "rejected_scope_items": len(proposals) - plausible,
        "proposed_routes": dict(sorted(routes.items())),
        "proposed_facets": dict(sorted(facets.items())),
        "proposed_category_counts": dict(sorted(category_counts.items())),
        "blocked_reason_counts": dict(sorted(issues.items())),
        "scope_is_not_source_evidence": True,
        "source_officiality_and_age_not_verified": True,
        "geographic_provenance_not_verified": True,
        "cross_source_duplicates_not_checked": True,
        "private_approval_not_checked": True,
        "price_or_registration_not_inferred": True,
        "recurrences_not_inferred": True,
        "existing_musical_and_openagenda_paths_unchanged": True,
        "new_family_publisher_not_connected": True,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "public_writes": 0,
    }
    if _FORBIDDEN_OUTPUT_KEYS & set(result):
        raise ValueError("unsafe_scope_output")
    return result
