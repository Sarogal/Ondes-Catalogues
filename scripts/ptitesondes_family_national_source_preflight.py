"""Independent national source-evidence PREFLIGHT for family outings.

STRICTLY READ-ONLY: neither a new publisher nor private approval, and not
connected to historical OpenAgenda or municipal Gosier admission. Review of
organiser hosts and venue registers happens OUTSIDE this program. All fetched
source cues are rechecked, but this module cannot authenticate the author of a
site, recheck an external GPS provider, or attest human approval.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
from html.parser import HTMLParser
import hashlib
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit

from ptitesondes_family_national_scope import (
    FAMILY_TYPES, audit_family_scope,
)
from merge_policy import byid
from proof import meters

SCHEMA = "ptitesondes.family_independent_source_preflight.v1"


def canonical_sha256(document):
    """Versioned canonical JSON pin; no dependency on the draft municipal PR."""
    return hashlib.sha256(json.dumps(
        document, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
MAX_BATCH = 100
SOURCE_FIELDS = frozenset({
    "official_url", "start_local", "lat", "lng", "venue_key",
    "region", "department",
})
BUNDLE_FIELDS = frozenset({"scope", "source"})
REGISTRY_FIELDS = frozenset({
    "venue_key", "city", "venue", "region", "department",
    "lat", "lng", "institutional_url", "geo_source_url",
})
BAD_STATUS = re.compile(
    r"\b(?:annul(?:e|ee|es|ees)|complet|report(?:e|ee|es|ees))\b"
)
AGE_PHRASE = re.compile(
    r"\b(?:(?:pour|destine|reserve)\s+(?:les |aux |a |la )?"
    r"(?:enfants?|familles?|bebes?|tout.petit[s]?)"
    r"|public\s+(?:enfants?|familles?)|en\s+famille)\b"
)
TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.words = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden_depth = max(0, self.hidden_depth - 1)

    def handle_data(self, data):
        if not self.hidden_depth:
            self.words.append(data)


class _SessionBlocks(HTMLParser):
    """Smallest self-contained dated/time block in a publisher's HTML.

    A global page may contain several dates and several unrelated clocks.
    Only pair cues contained in one <time>, <li> or <p> block can prove
    a precise session on a shared programme URL. No inferred recurrence.
    """
    TAGS = frozenset({"time", "li", "p"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.blocks = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        elif not self.hidden and tag in self.TAGS:
            self.stack.append((tag, []))

    def handle_data(self, data):
        if not self.hidden:
            for _, parts in self.stack:
                parts.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in self.TAGS and self.stack and self.stack[-1][0] == tag:
            _, words = self.stack.pop()
            self.blocks.append(norm_text(" ".join(words)))


def _session_pair_on_official_page(html, scope, clock):
    if not isinstance(html, str) or not TIME_PATTERN.fullmatch(clock):
        return False
    try:
        day = date.fromisoformat(scope["date_start"])
    except (TypeError, ValueError, KeyError):
        return False
    month = (
        "janvier", "fevrier", "mars", "avril", "mai", "juin",
        "juillet", "aout", "septembre", "octobre", "novembre", "decembre"
    )[day.month - 1]
    dates = tuple(norm_text(x) for x in (
        day.isoformat(), f"{day.day:02d}/{day.month:02d}/{day.year}",
        f"{day.day} {month} {day.year}",
    ))
    hh, mm = clock.split(":")
    times = tuple(norm_text(x) for x in (clock, f"{int(hh)}h{mm}"))
    parser = _SessionBlocks()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return False
    return any(
        any(d in block for d in dates)
        and any(t in block for t in times)
        for block in parser.blocks
    )


def norm_text(text):
    if not isinstance(text, str):
        return ""
    decomp = unicodedata.normalize("NFKD", text).casefold()
    clean = "".join(c for c in decomp if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", clean).split())


def official_host(url):
    if not isinstance(url, str):
        return None
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username
                or u.password or u.port not in (None, 443)
                or u.fragment or u.hostname.endswith(".example")):
            return None
        return u.hostname.casefold()
    except ValueError:
        return None


def _source_cues(scope, source, html):
    if not isinstance(html, str) or not 50 <= len(html) <= 2_000_000:
        return {"official_html_unreadable"}
    parser = _VisibleText()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return {"official_html_unreadable"}
    visible = norm_text(" ".join(parser.words))
    if not visible:
        return {"official_html_unreadable"}
    fail = set()
    if (norm_text(scope["title"]) not in visible
            or norm_text(scope["venue"]) not in visible
            or norm_text(scope["city"]) not in visible):
        fail.add("official_title_venue_city_mismatch")
    try:
        day = date.fromisoformat(scope["date_start"])
        # Most official pages use either ISO, numeric French, or spelled-out
        # French dates. No recurring session is inferred from a vague month.
        dmy = f"{day.day:02d}/{day.month:02d}/{day.year}"
        month = (
            "janvier", "fevrier", "mars", "avril", "mai", "juin",
            "juillet", "aout", "septembre", "octobre", "novembre",
            "decembre",
        )[day.month - 1]
        dates = (
            norm_text(day.isoformat()), norm_text(dmy),
            norm_text(f"{day.day} {month} {day.year}"),
        )
        if not any(k in visible for k in dates):
            fail.add("official_dated_occurrence_not_confirmed")
    except (ValueError, TypeError, KeyError):
        fail.add("official_dated_occurrence_not_confirmed")
    hhmm = source["start_local"]
    h, m = hhmm.split(":")
    cues = (norm_text(hhmm), norm_text(f"{int(h)}h{m}"))
    if not any(cue in visible for cue in cues):
        fail.add("official_local_start_time_not_confirmed")
    if BAD_STATUS.search(visible):
        fail.add("cancelled_full_or_postponed")
    if not AGE_PHRASE.search(visible):
        fail.add("official_family_audience_not_confirmed")
    for bound in (scope.get("age_min"), scope.get("age_max")):
        if type(bound) is int and not re.search(
            rf"\b{bound}\s*ans?\b", visible
        ):
            # A source saying "enfants" is not sufficient to invent an age.
            fail.add("exact_age_bounds_not_confirmed")
    price = scope["price_evidence"]
    registration = scope["registration_evidence"]
    if price == "explicit_free" and "gratuit" not in visible:
        fail.add("explicit_free_claim_not_on_official_page")
    if price == "explicit_price" and not re.search(r"\b(?:euros?|eur)\b", visible):
        # A currency symbol can be present in raw text prior to normalization.
        if "€" not in " ".join(parser.words):
            fail.add("explicit_price_claim_not_on_official_page")
    if registration == "explicit_required" and not any(
        term in visible for term in ("inscription obligatoire", "sur inscription")
    ):
        fail.add("registration_required_claim_not_on_official_page")
    if registration == "explicit_not_required" and not any(
        term in visible for term in ("sans inscription", "inscription non obligatoire")
    ):
        fail.add("no_registration_claim_not_on_official_page")
    # These conditions require a separate SOURCE_ONLY editorial decision; this
    # stage cannot infer a price or waive contradictory registration details.
    if price in ("ambiguous", "contradictory") or registration in (
        "ambiguous", "contradictory"
    ):
        fail.add("unresolved_access_contradiction")
    return fail


def _venue_match(scope, source, registry):
    if not isinstance(registry, (list, tuple)):
        return False
    records = [
        v for v in registry if isinstance(v, dict)
        and set(v) == REGISTRY_FIELDS
        and v.get("venue_key") == source.get("venue_key")
    ]
    if len(records) != 1:
        return False
    v = records[0]
    if (norm_text(v["venue"]) != norm_text(scope["venue"])
            or norm_text(v["city"]) != norm_text(scope["city"])
            or norm_text(v["region"]) != norm_text(source["region"])
            or norm_text(v["department"]) != norm_text(source["department"])):
        return False
    institutional = official_host(v["institutional_url"])
    geo = official_host(v["geo_source_url"])
    if not institutional or not geo or institutional == geo:
        return False
    try:
        a = (float(source["lat"]), float(source["lng"]))
        b = (float(v["lat"]), float(v["lng"]))
        if (not all(math.isfinite(x) for x in a + b)
                or not -90 <= a[0] <= 90 or not -180 <= a[1] <= 180
                or not -90 <= b[0] <= 90 or not -180 <= b[1] <= 180):
            return False
        return meters(a, b) <= 65
    except (ValueError, TypeError, OverflowError, KeyError):
        return False


def inspect_family_national_preflight(
    catalogue, bundles, today, *, catalogue_sha256, trusted_official_hosts,
    venue_registry, source_get,
):
    """Preflight actual candidate source evidence, never authorize a release.

    Trust-list / registry must be independently curated and immutable at call
    time, not copied from candidates. A successful preflight is still only a
    diagnostic pending private GitHub approvals, external geographic checks,
    anti-source authenticity review and a separate publisher.
    """
    if type(today) is not date:
        raise ValueError("invalid_preflight_date")
    if not isinstance(bundles, list) or not 1 <= len(bundles) <= MAX_BATCH:
        raise ValueError("invalid_preflight_batch")
    if (not isinstance(catalogue_sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", catalogue_sha256)
            or canonical_sha256(catalogue) != catalogue_sha256):
        raise ValueError("catalogue_sha_pin_mismatch")
    byid(catalogue)
    before = deepcopy(catalogue)
    if (not isinstance(trusted_official_hosts, (list, tuple))
            or not trusted_official_hosts
            or any(not isinstance(h, str) or not h or h != h.casefold()
                   or h.startswith(".") or "/" in h
                   for h in trusted_official_hosts)):
        raise ValueError("independent_host_registry_invalid")
    if not isinstance(venue_registry, (list, tuple)):
        raise ValueError("independent_venue_registry_invalid")
    if not callable(source_get):
        raise ValueError("official_reader_required")

    blocked = Counter()
    validated_source_count = 0
    signatures = set()
    shared_urls = Counter(
        b["source"].get("official_url")
        for b in bundles
        if isinstance(b, dict) and isinstance(b.get("source"), dict)
        and isinstance(b["source"].get("official_url"), str)
    )
    for bundle in bundles:
        reasons = set()
        if not isinstance(bundle, dict) or set(bundle) != BUNDLE_FIELDS:
            reasons.add("invalid_proof_bundle")
            blocked.update(reasons)
            continue
        scope, source = bundle["scope"], bundle["source"]
        if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
            reasons.add("invalid_source_evidence_shape")
            blocked.update(reasons)
            continue

        scope_check = audit_family_scope([scope], today)
        if scope_check["structurally_plausible_for_independent_review"] != 1:
            reasons.add("national_scope_not_plausible")
            reasons.update(scope_check["blocked_reason_counts"])
        if not isinstance(scope, dict) or scope.get("record_kind") != "dated_event":
            reasons.add("permanent_place_requires_independent_place_pipeline")
        if reasons:
            blocked.update(sorted(reasons))
            continue

        source_url = source["official_url"]
        host = official_host(source_url)
        if (not host or host not in trusted_official_hosts
                or scope.get("source_url") != source_url):
            reasons.add("official_organizer_host_not_trusted_or_url_changed")
        start = source["start_local"]
        if not isinstance(start, str) or not TIME_PATTERN.fullmatch(start):
            reasons.add("invalid_local_start_time")
        if not all(isinstance(source.get(k), str) and source[k].strip()
                   for k in ("venue_key", "region", "department")):
            reasons.add("source_location_not_identified")
        if not _venue_match(scope, source, venue_registry):
            reasons.add("venue_point_or_independent_provenance_unverified")

        raw = None
        if not reasons:
            try:
                raw = source_get(source_url)
                reasons.update(_source_cues(scope, source, raw))
            except (OSError, UnicodeError, ValueError, TypeError, KeyError):
                reasons.add("official_source_unavailable_or_unverifiable")

        # A programme URL is often shared by *different proven sessions*.
        # Never deduplicate merely by URL; the exact local start is part of
        # the occurrence identity. Ambiguous historical time fails closed.
        title = norm_text(scope["title"])
        city = norm_text(scope["city"])
        venue = norm_text(scope["venue"])
        day = scope["date_start"]
        signature = (title, city, venue, day, start)
        if (source_url, signature) in signatures:
            reasons.add("duplicate_within_candidate_batch")
        # Distinct sessions on a shared page need one SAME-BLOCK date/time
        # pair. Otherwise separately mentioned dates and times could combine
        # into an invented session.
        historical_same_url = any(
            isinstance(old, dict) and old.get("source_url") == source_url
            for old in catalogue["events"]
        )
        if (shared_urls[source_url] > 1 or historical_same_url) and not (
            isinstance(raw, str)
            and _session_pair_on_official_page(raw, scope, start)
        ):
            reasons.add("shared_page_exact_session_pair_unverified")
        signatures.add((source_url, signature))
        for old in catalogue["events"]:
            if (not isinstance(old, dict)
                    or not isinstance(old.get("date_start"), str)):
                continue
            same_page = old.get("source_url") == source_url
            same_identity = (
                norm_text(old.get("title")) == title
                and norm_text(old.get("city")) == city
                and norm_text(old.get("venue")) == venue
            )
            start_day = old.get("date_start")
            end_day = old.get("date_end") or start_day
            if not isinstance(end_day, str):
                continue
            overlaps = start_day <= day <= end_day
            if not overlaps:
                continue
            if same_identity:
                prior_clock = old.get("time")
                if (not isinstance(prior_clock, str)
                        or not TIME_PATTERN.fullmatch(prior_clock)
                        or prior_clock == start):
                    reasons.add("already_published_from_any_source")
                    break
                # Distinct exact clock on the SAME date is allowed only
                # when separately paired on an official session block.
                if not (
                    isinstance(raw, str)
                    and _session_pair_on_official_page(raw, scope, start)
                ):
                    reasons.add("shared_page_exact_session_pair_unverified")
            elif same_page:
                # One publisher page with conflicting identity on the same
                # day is not a reason to auto-pass an uncertain collision.
                reasons.add("shared_page_event_identity_ambiguous")
                break

        if reasons:
            blocked.update(sorted(reasons))
        else:
            validated_source_count += 1
        if catalogue != before or canonical_sha256(catalogue) != catalogue_sha256:
            raise ValueError("catalogue_mutated_during_national_preflight")

    if catalogue != before or canonical_sha256(catalogue) != catalogue_sha256:
        raise ValueError("catalogue_mutated_during_national_preflight")
    return {
        "schema": SCHEMA,
        "mode": "national_source_preflight_readonly_not_admission",
        "catalogue_sha256": catalogue_sha256,
        "catalogue_events_preserved": len(catalogue["events"]),
        "input_count": len(bundles),
        "official_source_cues_passed": validated_source_count,
        "source_preflight_batch_passed": (
            validated_source_count == len(bundles) and not blocked
        ),
        "blocked_occurrences": len(bundles) - validated_source_count,
        "blocked_reason_counts": dict(sorted(blocked.items())),
        "independent_official_host_and_venue_provenance_required": True,
        "geo_provider_not_refetched": True,
        "official_author_identity_not_cryptographically_authenticated": True,
        "human_approvals_not_checked": True,
        "catalogue_unchanged": True,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "municipal_gosier_and_openagenda_paths_unchanged": True,
        "publisher_not_connected": True,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "public_writes": 0,
    }
