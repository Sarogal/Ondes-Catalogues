#!/usr/bin/env python3
"""Open-world concert proposals from independently OSM-attributed venue sites.

This is NOT admission from an untrusted registry source name. A candidate
must be stable across distinct days, and the published venue's named OSM
node must freshly attribute the event's HTTPS domain to the venue.
The exact event must freshly contain a single full MusicEvent with a
matching date, named performers, individually/event-scoped relevant genres,
French location and exact address. The independent Publisher re-fetches
the OSM node and event page AGAIN before persisting any private approval.

A second event on another website is not required. Other venue/organizer
discoveries remain in research until independently tied to their real sites.
"""
from __future__ import annotations

import argparse
import time
import copy
import datetime as dt
import json
import hashlib
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.concerts import discover
from automation.concerts import event_site_pair_recheck as pairs
from automation.concerts import official_rss_jsonld_bridge as bridge
from automation.concerts import source_admission_intake as intake
from automation.concerts import source_cross_domain_corroboration as cross
from automation.concerts import dynamic_first_party_venue_proposals as official
from automation.concerts import venue_address_osm_source as address_osm
from automation.concerts import official_venue_single_source as official_source
from automation.concerts import openagenda_official_concert as openagenda
from scripts import concert_dynamic_existing_venue as verified

SCHEMA = "grossesondes.concert.single-official-osm-proposals.v1"
MAX_CHECKS = 16  # default for standalone callers
MAX_REVIEW_CHECKS = 48  # bounded network rechecks, never a cap on sources or bands
MAX_REVIEW_SECONDS = 240  # soft elapsed-time budget between complete candidates
MAX_REVIEW_MEMORY = 4096
REVIEW_BUCKETS = frozenset({"genre_tag_review", "genre_unknown"})


def require(ok, reason):
    if not ok:
        raise ValueError("OSM official concert: " + reason)


def _site(catalogue, c):
    matching = [venue for venue in catalogue["venues"]
                if isinstance(venue, dict)
                and cross.clean_venue(venue.get("name")) ==
                    cross.clean_venue(c.get("venue"))
                and intake.normalized(venue.get("city")) ==
                    intake.normalized(c.get("city"))
                and (not c.get("department") or
                     str(venue.get("department")) == str(c["department"]))
                and (verified.OSM_NODE.fullmatch(
                    str(venue.get("geoSource", "")))
                    or address_osm.eligible_address(venue)
                    or openagenda.is_openagenda_event_url(
                        c.get("eventDetailUrl") or c.get("sourceUrl"))
                    # An EXISTING venue can have only indicative historical
                    # geolocation. Its separately registered first-party
                    # agenda remains a valid source-identity anchor, with the
                    # whole bill independently re-fetched by the Publisher.
                    # Never derive this trust from the candidate itself.
                    or official_source.official_origin(
                        venue, c.get("eventDetailUrl") or
                        c.get("sourceUrl")) is not None)]
    require(len(matching) == 1,
            "exact published venue with independently verifiable geography required")
    return matching[0]


def _detail(c):
    url = c.get("eventDetailUrl") or c.get("sourceUrl")
    host = intake.valid_https(url)
    require(host and bridge.official_event_url(url, "https://" + host + "/"),
            "individual first-party HTTPS event page required")
    # A discovery page on a different host is not a first-party attribution.
    page = c.get("sourcePage") or c.get("sourceUrl")
    require(intake.valid_https(page) == host,
            "event and discovery page must be on the same HTTPS origin")
    return url


def eligible(registry, catalogue, today, *, diagnostics=None):
    require(isinstance(today, dt.date) and not isinstance(today, dt.datetime),
            "invalid day")
    require(isinstance(registry, dict)
            and registry.get("schema") == intake.REGISTRY_SCHEMA
            and isinstance(registry.get("items"), dict),
            "untrusted private registry")
    require(isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and all(isinstance(catalogue.get(k), list)
                    for k in ("venues", "events", "artists")),
            "invalid public catalogue")
    published = {(e.get("officialUrl"), e.get("date"))
                 for e in catalogue["events"] if isinstance(e, dict)}
    leads = []
    # Diagnostic-only counts: never grant authority based on this report.
    def held(reason):
        if diagnostics is not None:
            diagnostics[reason] += 1

    for entry in registry["items"].values():
        if not isinstance(entry, dict) or not isinstance(
                entry.get("candidate"), dict):
            held("malformed_candidate")
            continue
        c = entry["candidate"]
        if entry.get("status") != "pending_review":
            held("not_pending_review")
            continue
        if (type(entry.get("stableObservations")) is not int
                or entry["stableObservations"] < 1):
            held("invalid_observation_stability")
            continue
        if (c.get("publicationAllowed") is not False
                or c.get("reviewRequired") is not True):
            held("unsafe_discovery_flags")
            continue
        if c.get("possibleExistingConcert") is not False:
            held("possible_duplicate")
            continue
        if c.get("reviewBucket") not in REVIEW_BUCKETS:
            held("other_review_bucket")
            continue
        if not intake.official_claim(c.get("source")):
            held("not_official_source_claim")
            continue
        try:
            date = dt.date.fromisoformat(c.get("date"))
        except (TypeError, ValueError):
            held("invalid_date")
            continue
        if date < today:
            held("past_event")
            continue
        try:
            url = _detail(c)
        except (TypeError, ValueError, KeyError):
            held("not_individual_first_party_url")
            continue
        try:
            venue = _site(catalogue, c)
        except (TypeError, ValueError, KeyError):
            held("no_unique_published_venue")
            continue
        # ONE live read of a legitimate official venue agenda or of the OA
        # platform is enough to propose a show. Independent publisher replay
        # supplies the second *verification*, not a second *source* or a
        # mandatory second calendar day. Unknown unowned domains retain the
        # original two-day stability barrier.
        if (entry["stableObservations"] < 2
                and not openagenda.is_openagenda_event_url(url)
                and official_source.official_origin(venue, url) is None):
            held("insufficient_stability")
            continue
        if (url, date.isoformat()) in published:
            held("already_published")
            continue
        leads.append((url, date.isoformat(), venue["id"], c))
    # Rotate across distinct ACTUAL published venues, not contiguous
    # alphabetical URL cohorts. An agenda with fifty undated/pop events
    # must never consume eight consecutive rechecks while a verified rock
    # show from another room is still waiting. Every candidate stays in
    # the queue and the daily/slot offset eventually rechecks them all.
    # Only network workload is bounded, not the number of venues or bands.
    # Spend the first checks on candidates with an explicit genre signal,
    # while retaining unknown-genre leads for later independent rechecks.
    # A "genre_unknown" observation is NOT a rejection; first-party event
    # or artist proof may still establish an eligible concert.
    leads.sort(key=lambda row: (
        row[3].get("reviewBucket") != "genre_tag_review",
        row[0], row[1], row[2]))
    queues = defaultdict(deque)
    for item in leads:
        queues[item[2]].append(item)
    venue_ids = sorted(queues)
    ordered = []
    while len(ordered) < len(leads):
        for venue_id in venue_ids:
            if queues[venue_id]:
                ordered.append(queues[venue_id].popleft())
    return ordered


def propose(row, catalogue, today, *, fetch=verified.safe_fetch):
    url, date, vid, candidate = row
    venue = next((v for v in catalogue["venues"] if v["id"] == vid), None)
    require(isinstance(venue, dict), "published venue disappeared")
    require(_detail(candidate) == url
            and _site(catalogue, candidate)["id"] == vid,
            "source or physical venue changed")
    cache = {}
    # Official sites already attached to the published venue need ONE
    # dated show announcement, not fresh OSM ownership before every show.
    # Other unlisted sites still take the generic BAN/OSM route.
    official_home = official_source.official_origin(venue, url)
    openagenda_page = openagenda.is_openagenda_event_url(url)
    has_named_node = bool(verified.OSM_NODE.fullmatch(
        str(venue.get("geoSource", ""))))
    if openagenda_page:
        feature, website = None, None
    elif official_home is not None:
        feature, website = None, official_home
    else:
        try:
            if has_named_node:
                feature = verified.osm_identity(venue, url, fetch, cache)
                website = None
            else:
                feature, website = verified.address_identity(
                    venue, url, fetch, cache)
        except (ValueError, OSError, TimeoutError) as exc:
            raise ValueError("osm_identity: " + str(exc)) from exc
    # New OpenAgenda observations include two research-only numeric locators.
    # They never grant an approval: a fresh first-party OpenAgenda export
    # independently verifies event, agenda ownership, date, room and genre.
    export_ids = (candidate.get("openAgendaUid"),
                  candidate.get("openAgendaEventUid"))
    official_export = openagenda_page and all(export_ids)
    try:
        if official_export:
            body = fetch(openagenda.official_export_url(*export_ids), cache)
        else:
            body = fetch(url, cache)
    except (ValueError, OSError, TimeoutError) as exc:
        raise ValueError("official_event_fetch: " + str(exc)) from exc
    require(isinstance(body, str) and 20 <= len(body) <= 400_000,
            "missing individual official OpenAgenda evidence")
    try:
        if official_export:
            # The national index can link to a municipality's syndicated
            # OpenAgenda page while the immutable event UID belongs to the
            # venue's originating agenda. Derive the actual published URL
            # only from a freshly fetched, UID-bound official export.
            # The independent verifier and Publisher then validate that
            # original URL, never the discovery alias.
            url = openagenda.original_event_url_from_export(
                body, url, agenda_uid=export_ids[0],
                event_uid=export_ids[1])
            names, genres = openagenda.verified_export(
                body, url, date, venue, agenda_uid=export_ids[0],
                event_uid=export_ids[1])
        elif openagenda_page:
            names, genres = openagenda.verified_bill(
                body, url, date, venue)
        else:
            names, genres = official._individual_event(
                body, url, date, venue, accept_generic=True,
                fetch=fetch, cache=cache, profile_scan_day=today)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("official_event_content: " + str(exc)) from exc
    lead = candidate.get("leadArtist")
    require(isinstance(lead, str) and bool(lead.strip()),
            "missing named lead in original observation")
    # Discovery may list just the headliner while the official page carries
    # the complete multi-artist bill. Never assume the whole event shares
    # the same genre or that a musician is already known.
    observed = lead.split(" + ")[0]
    initial = intake.normalized(observed)
    # For OpenAgenda only, compare the observed commercial headline's
    # candidate name with the name already VERIFIED from the fresh export.
    # This is a discovery correlation, not artist or publication evidence.
    if official_export:
        candidate_name = openagenda.promotional_artist_candidate(observed)
        if candidate_name is not None:
            initial = intake.normalized(candidate_name)
    named_lead = initial in {intake.normalized(name) for name in names}
    if official_export and not named_lead:
        named_lead = openagenda.observed_export_bill_matches(observed, names, body, city=venue.get("city"))
    tour_correlated = False
    if not named_lead and not openagenda_page:
        nodes = verified.individual_event_nodes(body, accept_generic=True)
        # Only an exact originally observed tour title, rechecked by the
        # same independently authenticated visible tour verifier, may stand
        # in for a named discovery headliner. Never register that title.
        if len(nodes) == 1 and intake.normalized(nodes[0].get("name")) == initial:
            detail = verified.sparse_visible_event_detail(
                body, nodes, url, date, venue, tour_only=True)
            tour_correlated = detail == (names, genres)
    require(named_lead or tour_correlated,
            "fresh bill does not contain the observed headliner or verified tour title")
    artists, newly_named = pairs._artists(names, catalogue)
    eid = ("go-c-" + date.replace("-", "") + "-" +
           intake.normalized(venue["city"]).replace(" ", "-")[:72] + "-" +
           intake.normalized(names[0]).replace(" ", "-")[:72])
    require(len(eid) <= 150 and len(artists) == len(names),
            "invalid or colliding artist identities")
    require(not any(
        e.get("id") == eid or e.get("officialUrl") == url or
        (e.get("date") == date and e.get("venueId") == vid and
         bool(set(e.get("artistIds") or []) & set(artists)))
        for e in catalogue["events"] if isinstance(e, dict)),
        "already published or overlapping concert")
    now = today.isoformat()
    proof = {
        "url": url,
        "proofType": (verified.OPENAGENDA_PROFILE if openagenda_page else
                      verified.OFFICIAL_SOURCE_PROFILE if official_home else
                      verified.OSM_SINGLE_PROFILE if has_named_node else
                      verified.OSM_ADDRESS_PROFILE),
        "checkedAt": now,
        "checkedFields": (list(verified.OPENAGENDA_CHECKED)
                          if openagenda_page else
                          list(verified.CHECKED) if official_home or
                          has_named_node else list(verified.ADDRESS_CHECKED)),
        "officialArtistNames": names,
        "officialGenreLabels": genres,
    }
    if openagenda_page:
        proof["officialOpenAgendaEventUrl"] = url
        if official_export:
            proof["officialOpenAgendaUid"] = str(export_ids[0])
            proof["officialOpenAgendaEventUid"] = str(export_ids[1])
    elif official_home:
        proof["officialVenueSourceUrl"] = official_home
    else:
        proof["namedOsmUrl"] = feature
        if not has_named_node:
            proof.update({
                "publishedVenueGeoSource": venue["geoSource"],
                "sourceWebsite": website,
            })
    approval = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": now,
        "officialEvidence": [proof],
        "event": {
            "id": eid, "title": " + ".join(names),
            "date": date, "time": None, "artistIds": artists,
            "venueId": vid, "genres": genres,
            "status": "confirmed", "officialUrl": url,
            "sourceType": "salle",
        },
        "newArtists": newly_named,
    }
    # A second full replay here plus a third one inside approval_preflight
    # prevent discovery claims or a stale source from becoming a signature.
    try:
        verified.validate(
            approval, {v["id"]: v for v in catalogue["venues"]},
            {a["id"]: a for a in catalogue["artists"]}, today, fetch=fetch)
    except (ValueError, OSError, TimeoutError, KeyError, TypeError) as exc:
        raise ValueError("publisher_recheck: " + str(exc)) from exc
    return approval


def _review_key(row):
    # Exact source identity; private scheduling only, never evidence.
    return hashlib.sha256(json.dumps(
        [row[0], row[1], row[2], row[3].get("candidateId")],
        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _review_memory(prior, selected):
    if (not isinstance(prior, dict) or prior.get("schema") != SCHEMA
            or prior.get("publicationAllowed") is not False
            or prior.get("privateApprovalApplied") is not False):
        return []
    active = {_review_key(row) for row in selected}
    history = prior.get("recentReviewKeys")
    if isinstance(history, list):
        return list(dict.fromkeys(k for k in history[-MAX_REVIEW_MEMORY:]
                                  if isinstance(k, str) and k in active))
    # Upgrade the previous private report without mistaking truncated IDs
    # for identities: only an unambiguous prior check can seed memory.
    index = defaultdict(list)
    for row in selected:
        index[(str(row[3].get("candidateId", ""))[:120], row[1], row[2])].append(
            _review_key(row))
    result = []
    checks = prior.get("candidateChecks", [])
    if not isinstance(checks, list):
        return []
    for check in checks:
        if not isinstance(check, dict):
            continue
        identity = (check.get("candidateId"), check.get("date"),
                    check.get("venueId"))
        if not all(isinstance(part, str) for part in identity):
            continue
        matches = index.get(identity, [])
        if len(matches) == 1:
            result.append(matches[0])
    return list(dict.fromkeys(result))[-MAX_REVIEW_MEMORY:]


# Fingerprint only the event extraction and proof modules that can repair
# these specific failures. Unrelated radio/festival/catalogue commits do
# not invalidate this memory. No GitHub network request or SHA lookup.
EXTRACTOR_FILES = (
    "scripts/concert_dynamic_existing_venue.py",
    "automation/concerts/dynamic_first_party_venue_proposals.py",
    "automation/concerts/event_site_pair_recheck.py",
    "automation/concerts/event_site_microdata.py",
    "automation/concerts/discover.py",
    "automation/concerts/official_rss_jsonld_bridge.py",
    "automation/concerts/official_html_evidence.py",
    "automation/concerts/open_world_visible_cards.py",
    "automation/concerts/official_visible_tour_bill.py",
    "automation/concerts/open_world_artist_genre.py",
    "automation/concerts/artist_official_bio.py",
    "automation/concerts/first_party_tec_event.py",
    "automation/concerts/triage.py",
)
_MISSING_ADDRESS_REPLAY = (
    "publisher_recheck: Unlisted official source: no unique exact first-party MusicEvent: venue_address_missing")
_GEO_REPLAY_REASONS = frozenset({
    "publisher_recheck: Unlisted official source: no unique exact first-party MusicEvent: venue_postal_identity_mismatch",
    "publisher_recheck: Unlisted official source: no unique exact first-party MusicEvent: venue_street_mismatch",
})
# These failures may be repaired either by a verified venue update or by
# a new Publisher address parser/contract. Both paths share the existing
# bounded retry quota; neither turns prior failure into evidence.
_VENUE_IDENTITY_REPLAY_REASONS = frozenset({
    "official_event_content: Source admission: unique first-party music event not found: venue_name_or_location_mismatch",
    "publisher_recheck: Unlisted official source: no unique exact first-party MusicEvent: venue_name_mismatch",
})
_EXTRACTION_REASONS = _GEO_REPLAY_REASONS | _VENUE_IDENTITY_REPLAY_REASONS | frozenset({
    _MISSING_ADDRESS_REPLAY,
    "official_event_content: Source admission: unique first-party music event not found: named_bill_missing_or_ambiguous",
    "official_event_content: Source admission: unique first-party music event not found: relevant_artist_or_event_genre_missing",
})


def _extractor_revision():
    digest = hashlib.sha256()
    try:
        for path in EXTRACTOR_FILES:
            digest.update(path.encode("utf-8") + b"\0")
            digest.update(hashlib.sha256((ROOT / path).read_bytes()).digest())
    except OSError:
        return None  # No inferred version if the deployed code is incomplete.
    return digest.hexdigest()


def _valid_revision(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[a-f0-9]{64}", value))


def _retry_memory(prior, selected):
    """Private scheduling state only; an old failure never grants trust."""
    if (not isinstance(prior, dict) or prior.get("schema") != SCHEMA
            or prior.get("publicationAllowed") is not False
            or prior.get("privateApprovalApplied") is not False):
        return {}
    active = {_review_key(row) for row in selected
              if row[3].get("source") != "agenda_officiel_openagenda"}
    history = prior.get("extractionRetryMemory")
    if isinstance(history, dict):
        result = {key: revision for key, revision in
                  list(history.items())[-MAX_REVIEW_MEMORY:]
                  if key in active and (revision == "legacy" or _valid_revision(revision))}
        # The previous release did not remember this diagnostic. Recover it
        # from the last exact correlated window, without resetting other holds.
        migration_reasons = ({_MISSING_ADDRESS_REPLAY} | _GEO_REPLAY_REASONS |
                             _VENUE_IDENTITY_REPLAY_REASONS)
    elif "extractionRetryMemory" in prior:
        return {}
    else:
        result = {}
        migration_reasons = _EXTRACTION_REASONS
    # Upgrade reports using only uniquely correlated exact identities.
    # Older reports contain only the last window's failure reasons.
    index = defaultdict(list)
    for row in selected:
        key = _review_key(row)
        if key in active:
            identity = (str(row[3].get("candidateId", ""))[:120], row[1], row[2])
            index[identity].append(key)
    checks = prior.get("candidateChecks")
    if not isinstance(checks, list):
        return result
    revision = prior.get("extractorRevision")
    revision = revision if _valid_revision(revision) else "legacy"
    for check in checks[-MAX_REVIEW_CHECKS:]:
        if (not isinstance(check, dict)
                or check.get("state") != "held_event_or_source_not_verified"
                or not isinstance(check.get("reason"), str)
                or check["reason"] not in migration_reasons):
            continue
        identity = (check.get("candidateId"), check.get("date"), check.get("venueId"))
        if not all(isinstance(part, str) for part in identity):
            continue
        matches = index.get(identity, [])
        if len(matches) == 1:
            result.setdefault(matches[0], revision)
    return result


def _venue_fingerprints(catalogue, selected):
    venues = {v["id"]: v for v in catalogue["venues"]
              if isinstance(v, dict) and isinstance(v.get("id"), str)}
    fields = ("name", "city", "address", "postalCode", "latitude", "longitude",
              "geoPrecision", "geoSource")
    result = {}
    exact = set()
    for row in selected:
        v = venues.get(row[2])
        if v is None or row[3].get("source") == "agenda_officiel_openagenda":
            continue
        key = _review_key(row)
        result[key] = hashlib.sha256(json.dumps(
            [v.get(field) for field in fields], ensure_ascii=False,
            separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
        if (isinstance(v.get("postalCode"), str)
                and re.fullmatch(r"\d{5}", v["postalCode"])
                and v.get("geoPrecision") in {"named-site-point", "named-site-area"}):
            exact.add(key)
    return result, exact


def _geo_retry_memory(prior, selected, fingerprints, exact):
    if (not isinstance(prior, dict) or prior.get("schema") != SCHEMA
            or prior.get("publicationAllowed") is not False
            or prior.get("privateApprovalApplied") is not False):
        return {}
    saved = prior.get("venueGeoRetryMemory")
    if isinstance(saved, dict):
        return {key: value for key, value in list(saved.items())[-MAX_REVIEW_MEMORY:]
                if key in fingerprints and (value == "legacy" or _valid_revision(value))}
    if "venueGeoRetryMemory" in prior:
        return {}
    # Migrate the last exact correlated diagnostic from the previous release.
    index = defaultdict(list)
    for row in selected:
        key = _review_key(row)
        if key in fingerprints:
            index[(str(row[3].get("candidateId", ""))[:120], row[1], row[2])].append(key)
    result = {}
    checks = prior.get("candidateChecks")
    if not isinstance(checks, list):
        return result
    for check in checks[-MAX_REVIEW_CHECKS:]:
        if (not isinstance(check, dict)
                or check.get("state") != "held_event_or_source_not_verified"
                or not isinstance(check.get("reason"), str)
                or check["reason"] not in _GEO_REPLAY_REASONS):
            continue
        identity = (check.get("candidateId"), check.get("date"), check.get("venueId"))
        if not all(isinstance(part, str) for part in identity):
            continue
        keys = index.get(identity, [])
        if len(keys) == 1:
            key = keys[0]
            # If the corrected venue is already present during deployment,
            # allow a single legacy recheck; otherwise wait for its change.
            result[key] = "legacy" if key in exact else fingerprints[key]
    return result


def _prioritize_extraction_retries(window, selected, failures, revision, limit,
                                   geo_stale=(), recency=None):
    """Use at most one quarter of the budget on changed-code retries.

    Replace only rows from the SAME non-OpenAgenda lane; preserve its
    allocation and at least one ordinary rotation pick. Never retry a
    failure with unchanged extraction code merely because it was tagged.
    """
    extraction_stale = ({key for key, previous in failures.items() if previous != revision}
                        if _valid_revision(revision) else set())
    geo_stale = set(geo_stale)
    stale = extraction_stale | geo_stale
    pending = len(extraction_stale)
    budget = limit // 4
    if not stale or not budget:
        return window, set(), pending
    picked = {_review_key(row) for row in window}
    window = list(window)
    prioritized = set()
    # Newly repaired venues get first use of the shared retry quota.
    # Within each priority, least recently examined wins. Successive code
    # revisions must not keep favoring the first rows of a static registry.
    recency = {} if recency is None else recency
    for row in sorted(selected, key=lambda row: (
            _review_key(row) not in geo_stale,
            recency.get(_review_key(row), -1))):
        key = _review_key(row)
        if len(prioritized) >= budget:
            break
        if key not in stale or key in picked:
            continue
        # Both genre-tagged and unknown queues retain their existing shares.
        lane = row[3].get("reviewBucket") == "genre_tag_review"
        replaceable = [i for i, current in enumerate(window)
                       if current[3].get("source") != "agenda_officiel_openagenda"
                       and (current[3].get("reviewBucket") == "genre_tag_review") == lane
                       and _review_key(current) not in stale]
        if len(replaceable) < 2:
            continue  # Preserve at least one ordinary pick in each lane.
        i = replaceable[-1]
        picked.remove(_review_key(window[i]))
        window[i] = row
        picked.add(key)
        prioritized.add(key)
    return window, prioritized, pending


def build(registry, catalogue, before, today, *, slot=0, limit=MAX_CHECKS,
          fetch=verified.safe_fetch, prior=None, max_seconds=MAX_REVIEW_SECONDS):
    require(type(max_seconds) is int and 1 <= max_seconds <= MAX_REVIEW_SECONDS,
            "invalid bounded review time")
    require(type(slot) is int and slot in (0, 1, 2)
            and type(limit) is int and 1 <= limit <= MAX_REVIEW_CHECKS,
            "invalid bounded scan")
    require(isinstance(before, dict)
            and before.get("schema") == "grossesondes.concert.approvals.v1"
            and isinstance(before.get("approvals"), list),
            "invalid private approval preview")
    eligibility_rejections = Counter()
    selected = eligible(registry, catalogue, today,
                        diagnostics=eligibility_rejections)
    memory = _review_memory(prior, selected)
    recency = {key: i for i, key in enumerate(memory)}

    def ranked(pool, start):
        if not pool:
            return []
        rotated = pool[start:] + pool[:start]
        # Unseen first, then least recently checked. The original rotation
        # breaks ties, and remains identical when there is no memory.
        return sorted(rotated, key=lambda row: recency.get(_review_key(row), -1))

    # Rotate BOTH pools without leaving unvisited holes between scan slots.
    # OpenAgenda receives a proportional share (at most half whenever there
    # are other sources), while first-party venue pages keep the remainder.
    # An unknown artist/venue is never excluded by this scheduling choice.
    # When one lane is short, use the remaining network budget on the other.
    fast = [row for row in selected
            if row[3].get("source") == "agenda_officiel_openagenda"
            and row[3].get("openAgendaUid")
            and row[3].get("openAgendaEventUid")]
    regular = [row for row in selected if row not in fast]
    tick = (today - dt.date(2026, 11, 21)).days * 3 + slot
    reserved = (
        min(len(fast), limit if not regular else max(
            1, min(limit // 2, round(limit * len(fast) / len(selected)))))
        if fast else 0)
    fstart = (tick * reserved) % len(fast) if fast else 0
    fast_ranked = ranked(fast, fstart)
    window = fast_ranked[:reserved]
    # A venue with one explicitly labelled first-party metal/punk show
    # should not wait through dozens of unrelated genre-unknown cards.
    # Reserve a bounded share for genre-tagged official leads, scaled to
    # the available budget. The rest still rotates across EVERY other venue and
    # previously unknown group; registry tags are NAVIGATION ONLY.
    tagged = [row for row in regular
              if row[3].get("reviewBucket") == "genre_tag_review"]
    other = [row for row in regular
             if row[3].get("reviewBucket") != "genre_tag_review"]
    spare = limit - len(window)
    tagged_budget = max(2, 4 * (limit // 16))
    take_tagged = min(len(tagged), spare if not other else min(tagged_budget, max(1, spare // 3), spare))
    tstart = (tick * take_tagged) % len(tagged) if tagged else 0
    tagged_ranked = ranked(tagged, tstart)
    window.extend(tagged_ranked[:take_tagged])
    take_regular = min(len(other), limit - len(window))
    # Rotating by the ACTUAL per-lane number read avoids holes across slots.
    rstart = (tick * take_regular) % len(other) if other else 0
    other_ranked = ranked(other, rstart)
    window.extend(other_ranked[:take_regular])
    # Return any unused capacity to the other pools without repeating a lead.
    # This preserves the existing all-OpenAgenda or all-venue budgets.
    picked = {id(row) for row in window}
    for pool in (fast_ranked, tagged_ranked, other_ranked):
        if len(window) >= min(limit, len(selected)):
            break
        for lead in pool:
            if len(window) >= min(limit, len(selected)):
                break
            if id(lead) not in picked:
                window.append(lead)
                picked.add(id(lead))
    # Once a priority lane has exhausted its unseen candidates, its
    # reserved capacity should not repeatedly fetch the same pages while
    # another lane still contains unvisited leads. Keep the lane allocation
    # for first visits; then spend unused capacity on unseen leads globally.
    # When the entire queue has been visited, resume least-recent review
    # within the original lane quotas. This is scheduling, never evidence.
    repeated = [row for row in window if _review_key(row) in recency]
    window = [row for row in window if _review_key(row) not in recency]
    picked = {_review_key(row) for row in window}
    target = min(limit, len(selected))
    for pool in (fast_ranked, tagged_ranked, other_ranked):
        for row in pool:
            if len(window) >= target:
                break
            key = _review_key(row)
            if key not in recency and key not in picked:
                window.append(row)
                picked.add(key)
    for row in repeated:
        if len(window) >= target:
            break
        key = _review_key(row)
        if key not in picked:
            window.append(row)
            picked.add(key)
    # Defensive refill if repeated identities were present in the registry.
    for pool in (fast_ranked, tagged_ranked, other_ranked):
        for row in pool:
            if len(window) >= target:
                break
            key = _review_key(row)
            if key not in picked:
                window.append(row)
                picked.add(key)
    revision = _extractor_revision()
    retry_memory = _retry_memory(prior, selected)
    fingerprints, exact_geo = _venue_fingerprints(catalogue, selected)
    geo_memory = _geo_retry_memory(prior, selected, fingerprints, exact_geo)
    geo_stale = {key for key, previous in geo_memory.items()
                 if key in exact_geo and fingerprints[key] != previous}
    window, prioritized, pending_retries = _prioritize_extraction_retries(
        window, selected, retry_memory, revision, limit,
        geo_stale=geo_stale, recency=recency)
    geo_prioritized = prioritized & geo_stale
    output = copy.deepcopy(before)
    working = copy.deepcopy(catalogue)
    known = {row["event"]["id"] for row in output["approvals"]
             if isinstance(row, dict) and isinstance(row.get("event"), dict)}
    counts = Counter()
    reason_counts = Counter()
    address_replay_diagnostics = Counter()
    checks = []
    started = time.monotonic()
    examined = []
    for row in window:
        # Do not interrupt a candidate halfway through independent proof.
        # Deferred rows retain their original recency and pending retry.
        if time.monotonic() - started >= max_seconds:
            break
        examined.append(row)
        candidate = row[3]
        identifier = str(candidate.get("candidateId", ""))[:120]
        check = {"candidateId": identifier, "date": row[1],
                 "venueId": row[2]}
        key = _review_key(row)
        # Re-evaluation consumes the pending retry regardless of outcome.
        # The unchanged code must not repeatedly get priority for one failure.
        if _valid_revision(revision):
            retry_memory.pop(key, None)
        geo_memory.pop(key, None)
        try:
            approval = propose(row, working, today, fetch=fetch)
            require(approval["event"]["id"] not in known,
                    "already privately approved")
            output["approvals"].append(approval)
            known.add(approval["event"]["id"])
            working["events"].append(approval["event"])
            working["artists"].extend(
                {"id": a["id"], "name": a["name"], "aliases": []}
                for a in approval["newArtists"])
            counts["independently_verified_proposal"] += 1
            check["state"] = "independently_verified_proposal"
        except (ValueError, KeyError, TypeError, IndexError, OSError,
                TimeoutError) as exc:
            counts["held_event_or_source_not_verified"] += 1
            # Exception messages may embed hostile input. Do not expose URLs
            # or multiline payloads; private, bounded diagnostics only.
            detail = " ".join(str(exc).split()) if isinstance(
                exc, ValueError) else type(exc).__name__
            detail = re.sub(r"https?://\S+", "[url]", detail)[:180]
            reason = detail or type(exc).__name__
            check.update(state="held_event_or_source_not_verified",
                         reason=reason)
            reason_counts[reason] += 1
            # Only fixed codes from the exact Publisher replay; never HTML,
            # URLs, untrusted exception attributes or new approval authority.
            cause = exc
            for _ in range(4):
                if isinstance(cause, verified.AddressReplayHeld):
                    codes = sorted(set(cause.address_replay_diagnostics) &
                                   verified.AddressReplayHeld.CODES)
                    if codes:
                        check["addressReplayDiagnostics"] = codes
                        address_replay_diagnostics.update(codes)
                    break
                cause = cause.__cause__
                if cause is None:
                    break
            if (reason in _EXTRACTION_REASONS and _valid_revision(revision)
                    and candidate.get("source") != "agenda_officiel_openagenda"):
                retry_memory[key] = revision
            if reason in _GEO_REPLAY_REASONS and key in fingerprints:
                geo_memory[key] = fingerprints[key]
        checks.append(check)
    checked_keys = [_review_key(row) for row in examined]
    checked_set = set(checked_keys)
    next_memory = [k for k in memory if k not in checked_set] + checked_keys
    return output, {
        "schema": SCHEMA,
        "extractorRevision": revision,
        "extractionRetryMemory": dict(list(retry_memory.items())[-MAX_REVIEW_MEMORY:]),
        "changedExtractorRetryPendingBefore": pending_retries,
        "changedExtractorPriorityChecks": len((prioritized - geo_prioritized) & checked_set),
        "venueGeoRetryMemory": dict(list(geo_memory.items())[-MAX_REVIEW_MEMORY:]),
        "changedVenueGeoRetryPendingBefore": len(geo_stale),
        "changedVenueGeoPriorityChecks": len(geo_prioritized & checked_set),
        "changedVenueGeoRetryPendingAfter": sum(
            key in exact_geo and fingerprints[key] != previous
            for key, previous in geo_memory.items()),
        "changedExtractorRetryPendingAfter": sum(
            previous != revision for previous in retry_memory.values())
            if _valid_revision(revision) else 0,
        "recentReviewKeys": next_memory[-MAX_REVIEW_MEMORY:],
        "previouslyReviewed": sum(k in recency for k in checked_keys),
        "firstReviewInMemory": sum(k not in recency for k in checked_keys),
        "asOf": today.isoformat(),
        "scanSlot": slot,
        "eligibleQueue": len(selected),
        "examined": len(examined),
        "reviewBudget": limit,
        "reviewTimeBudgetSeconds": max_seconds,
        "reviewDeferredByTimeBudget": len(window) - len(examined),
        "reviewElapsedSeconds": round(time.monotonic() - started, 2),
        "openAgendaExamined": sum(
            row[3].get("source") == "agenda_officiel_openagenda"
            for row in examined),
        "officialGenreTaggedExamined": sum(
            row[3].get("source") != "agenda_officiel_openagenda"
            and row[3].get("reviewBucket") == "genre_tag_review"
            for row in examined),
        "otherOfficialExamined": sum(
            row[3].get("source") != "agenda_officiel_openagenda"
            for row in examined),
        "stateCounts": dict(sorted(counts.items())),
        "eligibilityRejections": dict(sorted(eligibility_rejections.items())),
        "candidateChecks": checks,
        "rejectionReasons": dict(sorted(reason_counts.items())),
        "addressReplayDiagnostics": dict(sorted(address_replay_diagnostics.items())),
        "privateApprovalApplied": False,
        "publicationAllowed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--scan-slot", choices=(0, 1, 2), type=int, default=0)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    parser.add_argument("--max-seconds", type=int, default=MAX_REVIEW_SECONDS)
    opts = parser.parse_args()
    data = lambda p: json.loads(p.read_text(encoding="utf-8"))
    proposal, summary = build(
        data(opts.registry), data(opts.catalogue),
        data(opts.candidate),
        dt.datetime.now(ZoneInfo("Europe/Paris")).date(),
        slot=opts.scan_slot, limit=opts.limit, max_seconds=opts.max_seconds,
        prior=data(opts.report) if opts.report.exists() else None)
    opts.output.write_text(json.dumps(
        proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    opts.report.write_text(json.dumps(
        summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("OSM first-party official concert proposals kept private; "
          "Publisher recheck required.")


if __name__ == "__main__":
    main()
