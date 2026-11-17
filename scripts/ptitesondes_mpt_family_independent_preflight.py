"""MPT family pilot: independently check municipal session + reviewed IGN venue.

READ ONLY, no producer connection, no event admission or private approvals.
The caller separately supplies a municipal HTML reader and an independent IGN
geocoder reader. Never accept location/host authority from discovery leads.
The first VISIBLE primary article is retained; related-event sidebars cannot
provide the required date, start clock, venue, audience or organizer cues.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from merge_policy import byid
from ptitesondes_family_national_scope import FAMILY_TYPES
from ptitesondes_family_national_source_preflight import (
    canonical_sha256, inspect_family_national_preflight,
    _session_pair_on_official_page, norm_text,
)
from ptitesondes_mpt_independent_geo_pilot import (
    reviewed_pilot_records, review_exact_venue_name,
    independent_geo_recheck, national_preflight_venue_registry,
)

SCHEMA = "ptitesondes.mpt_source_and_geo_diagnostic.v1"
MPT_HOST = "mpt.montpellier.fr"
MAX_LEADS = 24
MAX_HTML_SIZE = 1_500_000
KNOWN_PRICE = frozenset(("explicit_free", "explicit_price", "not_stated",
                         "ambiguous", "contradictory"))
KNOWN_REG = frozenset(("explicit_required", "explicit_not_required",
                       "not_stated", "ambiguous", "contradictory"))
KNOWN_AUDIENCE = frozenset(("explicit_child", "explicit_family",
                            "explicit_baby"))
NOT_PUBLIC = "discovery_only_needs_official_and_independent_proof"
_PRIVATE_ROOTLESS = frozenset({
    "no_curated_venue", "unsupported_discovery_or_category",
    "invalid_event_clock_or_date", "unsafe_official_url",
    "independent_geo_not_currently_verified",
    "official_primary_detail_unavailable",
    "primary_article_title_or_session_mismatch",
    "art_installation_requires_editorial_review",
})


def safe_mpt_event_url(url):
    if not isinstance(url, str) or len(url) > 700:
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == MPT_HOST
                and p.port in (None, 443) and not p.username
                and not p.password and not p.fragment and not p.query
                and p.path.startswith("/evenement/")
                and len(p.path) > len("/evenement/")
                and "//" not in p.path
                and not any(s in (".", "..") for s in p.path.split("/")))
    except ValueError:
        return False


class _FirstVisibleMptArticle(HTMLParser):
    VOID = frozenset(("area", "base", "br", "col", "embed", "hr",
                      "img", "input", "link", "meta", "param",
                      "source", "track", "wbr"))
    INVISIBLE = frozenset(("head", "script", "style", "noscript",
                           "template", "svg", "iframe"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.h1_active = False
        self.heading_parts = []
        self.heading_complete = False
        self.article_started = False
        self.article_complete = False
        self.article_depth = 0
        self.fragment = []

    def _hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = str(attrs.get("style") or "").casefold()
        hidden = (self._hidden() or tag in self.INVISIBLE
                  or "hidden" in attrs or "inert" in attrs
                  or str(attrs.get("aria-hidden") or "").casefold() == "true"
                  or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                               style) is not None)
        if (tag == "h1" and not hidden
                and not self.article_started and not self.heading_complete):
            self.h1_active = True
        if (tag == "article" and not self.article_complete
                and not self.article_started and not hidden
                and self.heading_complete):
            self.article_started = True
        if self.article_started and not self.article_complete:
            self.fragment.append(self.get_starttag_text())
            if tag == "article":
                self.article_depth += 1
        if tag not in self.VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        if self.article_started and not self.article_complete:
            self.fragment.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == "h1" and self.h1_active:
            self.h1_active = False
            self.heading_complete = True
        if self.article_started and not self.article_complete:
            self.fragment.append("</" + tag + ">")
            if tag == "article":
                self.article_depth -= 1
                if self.article_depth == 0:
                    self.article_complete = True
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.h1_active and not self._hidden():
            self.heading_parts.append(data)
        if self.article_started and not self.article_complete:
            # Restores entities on the reconstructed original article.
            self.fragment.append(escape(data, quote=False))


def exact_primary_mpt_html(full_html, *, expected_title, expected_day,
                           expected_clock):
    """Fail closed if a related card is the only source of date/time proof."""
    if (not isinstance(full_html, str)
            or not 50 <= len(full_html.encode("utf-8")) <= MAX_HTML_SIZE):
        return None
    p = _FirstVisibleMptArticle()
    try:
        p.feed(full_html)
        p.close()
    except (ValueError, TypeError):
        return None
    if not (p.heading_complete and p.article_complete
            and norm_text(" ".join(p.heading_parts)) == norm_text(expected_title)):
        return None
    primary = ("<h1>" + escape(" ".join(p.heading_parts)) + "</h1>"
               + "".join(p.fragment))
    if not _session_pair_on_official_page(
            primary, {"date_start": expected_day}, expected_clock):
        return None
    visible = norm_text(primary)
    if re.search(
        r"\b(?:reserve(?:e|s|es)? aux? (?:creches|etablissements scolaires|"
        r"classes|groupes scolaires)|seance scolaire uniquement)\b", visible
    ):
        return None
    return primary


def _scope_and_source(lead, reviewed):
    scope = {
        "record_kind": "dated_event",
        "title": lead["title"], "city": lead["city"],
        "venue": lead["venue"], "source_url": lead["source_url"],
        "audience_claim": lead["audience_claim"],
        # No ages are inferred from an event-listing label.
        "age_min": None, "age_max": None,
        "price_evidence": lead["price_evidence"],
        "registration_evidence": lead["registration_evidence"],
        "category": lead["category"],
        "category_label": FAMILY_TYPES[lead["category"]][0],
        "date_start": lead["date_start"], "date_end": lead["date_end"],
    }
    source = {
        "official_url": lead["source_url"], "start_local": lead["start_local"],
        "lat": reviewed["lat"], "lng": reviewed["lng"],
        "venue_key": reviewed["venue_key"],
        "region": reviewed["region"], "department": reviewed["department"],
    }
    return {"scope": scope, "source": source}


def independent_family_preview(leads, catalogue, today, *, official_get,
                               geocoder_get):
    """Review actual leads against separately reviewed venue + live proofs.

    Returned report is anonymized. The only events considered at the
    underlying independent preflight remain UNAPPROVED, and no publisher uses
    this result. Geo coordinates are those of separately checked buildings,
    not an invented or copied candidate GPS.
    """
    if (type(today) is not date or not isinstance(leads, list)
            or not 1 <= len(leads) <= MAX_LEADS
            or not callable(official_get) or not callable(geocoder_get)
            or not isinstance(catalogue, dict)):
        raise ValueError("invalid_mpt_source_preview")
    byid(catalogue)
    before = deepcopy(catalogue)
    pin = canonical_sha256(catalogue)
    reviewable = []
    source_text = {}
    held = Counter()
    checked_geos = {}
    for lead in leads:
        if not isinstance(lead, dict) or (
                lead.get("provider") != "montpellier_mpt"
                or lead.get("verification") != NOT_PUBLIC
                or lead.get("category") not in FAMILY_TYPES
                or lead.get("audience_claim") not in KNOWN_AUDIENCE
                or lead.get("price_evidence") not in KNOWN_PRICE
                or lead.get("registration_evidence") not in KNOWN_REG
                or not isinstance(lead.get("title"), str)
                or not lead["title"].strip()):
            held["unsupported_discovery_or_category"] += 1
            continue
        if not safe_mpt_event_url(lead.get("source_url")):
            held["unsafe_official_url"] += 1
            continue
        try:
            start = date.fromisoformat(lead["date_start"])
            valid_clock = bool(re.fullmatch(
                r"(?:[01]\d|2[0-3]):[0-5]\d",
                lead.get("start_local", "")))
            if (lead.get("date_end") != start.isoformat()
                    or not today <= start <= date.fromordinal(today.toordinal()+183)
                    or not valid_clock):
                raise ValueError("not_an_exact_future_session")
        except (TypeError, KeyError, ValueError):
            held["invalid_event_clock_or_date"] += 1
            continue
        reviewed = review_exact_venue_name(
            lead.get("city"), lead.get("venue"))
        if reviewed is None:
            held["no_curated_venue"] += 1
            continue
        key = reviewed["venue_key"]
        if key not in checked_geos:
            try:
                checked_geos[key] = independent_geo_recheck(
                    reviewed, geocoder_get(reviewed["geo_source_url"]))
            except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                checked_geos[key] = False
        if not checked_geos[key]:
            held["independent_geo_not_currently_verified"] += 1
            continue
        try:
            html = official_get(lead["source_url"])
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            held["official_primary_detail_unavailable"] += 1
            continue
        primary = exact_primary_mpt_html(
            html, expected_title=lead["title"],
            expected_day=lead["date_start"],
            expected_clock=lead["start_local"])
        if primary is None:
            held["primary_article_title_or_session_mismatch"] += 1
            continue
        if (lead["category"] == "sortie-nature"
                and "installation artistique" in norm_text(primary)):
            held["art_installation_requires_editorial_review"] += 1
            continue
        reviewable.append(_scope_and_source(lead, reviewed))
        source_text[lead["source_url"]] = primary

    source_report = None
    if reviewable:
        source_report = inspect_family_national_preflight(
            catalogue, reviewable, today, catalogue_sha256=pin,
            trusted_official_hosts=[MPT_HOST],
            venue_registry=national_preflight_venue_registry(),
            source_get=lambda url: source_text[url],
        )
    if catalogue != before or canonical_sha256(catalogue) != pin:
        raise ValueError("public_catalogue_modified_in_preview")
    source_reasons = (source_report["blocked_reason_counts"]
                      if source_report else {})
    result = {
        "schema": SCHEMA,
        "mode": "independent_source_geo_review_readonly_no_admission",
        "input_discovery_occurrences": len(leads),
        "curated_geographic_venues_with_live_recheck": sum(checked_geos.values()),
        "eligible_for_independent_source_preflight": len(reviewable),
        "official_source_cues_passed": (
            source_report["official_source_cues_passed"] if source_report else 0),
        "held_before_source_preflight": dict(sorted(held.items())),
        "held_by_independent_source_preflight": dict(sorted(source_reasons.items())),
        "public_catalogue_preserved": len(catalogue["events"]),
        "catalogue_unchanged": True,
        "independent_primary_article_only": True,
        "organizer_person_identity_not_authenticated": True,
        "event_publisher_not_connected": True,
        "approval_granted_to_publisher": False,
        "human_approvals": 0, "published_events": 0, "public_writes": 0,
    }
    if (sum(held.values()) + len(reviewable) != len(leads)
            or result["official_source_cues_passed"] > len(reviewable)):
        raise ValueError("mpt_source_preview_reconciliation_failed")
    return result
