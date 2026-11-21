"""Independent, private-only Concerts review of municipal music leads from Festivals.

A private Festival report may nominate a name and URL, but NEVER grant HTTP
authority. Concerts independently rederives the town's official HTTPS website
from Geo -> DILA, re-fetches its homepage, re-proves the same-host agenda link,
and confirms the exact visible event link + named detail. Unknown bands, music
events, and official municipal domains need no closed catalog.

No concert date, place, performer, genre, festival status or publication
approval is inherited from Festivals. All outputs stay within the private
Concerts intake registry on PUBLIC GitHub Actions runners.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for local in (str(ROOT / "festival-automation"), str(ROOT / "scripts")):
    if local not in sys.path:
        sys.path.insert(0, local)

from dns_pinned_https import fetch_public_html
from national_municipal_source_research import (
    SCHEMA as MUNICIPAL_SCHEMA, verified_commune, delegated_municipal_commune,
    fetch_dila_records,
)
from national_municipal_pages_preflight import (
    SCHEMA as PAGES_SCHEMA, QUEUE_SCHEMA, MAX_UNKNOWN_MUSIC_LINKS,
    _rederive_municipal_site, _candidate_links, _visible,
    unknown_municipal_music_links, ACCESS_CHALLENGE,
)
from source_qualification import normalized
import triage

SCHEMA = "grossesondes.concert.discovery.v1"
SOURCE = "festival_municipal_music_handoff"
MAX_RECHECK = 4
MAX_PRIVATE_ROWS = 3
MAX_AGE_DAYS = 2
INELIGIBLE_TYPES = frozenset({"POSSIBLE_FESTIVAL_REVIEW_ONLY"})
MUSIC_RESEARCH_TYPES = frozenset({
    "UNCLASSIFIED_MUSIC_EVENT_REVIEW_ONLY",
    "POSSIBLE_CONCERT_OR_TOUR_REVIEW_ONLY",
})


def _trusted_dossiers(queue, municipal, pages, today):
    """Only a current, non-publishing, bounded source report is considered."""
    now = date.fromisoformat(today)
    if (not isinstance(queue, dict) or queue.get("schema") != QUEUE_SCHEMA
            or not isinstance(queue.get("dossiers"), list)
            or len(queue["dossiers"]) > 500
            or not isinstance(municipal, dict)
            or municipal.get("schema") != MUNICIPAL_SCHEMA
            or municipal.get("publication_authorized") is not False
            or municipal.get("publications") != 0
            or municipal.get("review_only") is not True
            or not isinstance(municipal.get("rows"), list)
            or len(municipal["rows"]) > MAX_PRIVATE_ROWS
            or not isinstance(pages, dict)
            or pages.get("schema") != PAGES_SCHEMA
            or pages.get("publication_authorized") is not False
            or pages.get("publications") != 0
            or pages.get("safe_to_publish") is not False
            or pages.get("review_only") is not True
            or pages.get("unknown_music_links_publications") != 0
            or not isinstance(pages.get("rows"), list)
            or len(pages["rows"]) > MAX_PRIVATE_ROWS
            or pages.get("as_of") != municipal.get("as_of")):
        raise ValueError("Unsafe or inconsistent private municipal reports")
    try:
        observed = date.fromisoformat(pages["as_of"])
        if not timedelta(0) <= (now-observed) <= timedelta(days=MAX_AGE_DAYS):
            raise ValueError("Stale municipal observation")
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Invalid municipal research date") from exc
    dossiers = {
        row["id"]: row for row in queue["dossiers"][:200]
        if isinstance(row, dict) and isinstance(row.get("id"), str)
        and re.fullmatch(r"national-[a-f0-9]{20}", row["id"])
        and isinstance(row.get("name_hint"), str)
        and isinstance(row.get("city_hint"), str)
    }
    municipal_by_id = {}
    for row in municipal["rows"]:
        if not isinstance(row, dict) or row.get("dossier_id") in municipal_by_id:
            raise ValueError("Duplicate municipal source identity")
        municipal_by_id[row.get("dossier_id")] = row

    eligible = []
    for row in pages["rows"]:
        if not isinstance(row, dict):
            raise ValueError("Malformed private municipal page")
        dossier = dossiers.get(row.get("dossier_id"))
        municipal_row = municipal_by_id.get(row.get("dossier_id"))
        suggestions = row.get("unknown_music_links_review_only", [])
        if (dossier is None or municipal_row is None
                or row.get("site_rederived") is not True
                or not isinstance(suggestions, list)
                or len(suggestions) > MAX_UNKNOWN_MUSIC_LINKS):
            continue
        if row.get("municipal_website") != municipal_row.get("municipal_website"):
            continue
        for suggestion in suggestions:
            if (not isinstance(suggestion, dict)
                    or suggestion.get("classification") not in MUSIC_RESEARCH_TYPES
                    or suggestion.get("review_only") is not True
                    or suggestion.get("publication_authorized") is not False
                    or suggestion.get("festival_verified") is not False
                    or suggestion.get("concert_verified") is not False
                    or suggestion.get("date_verified") is not False
                    or not isinstance(suggestion.get("title_hint"), str)
                    or not 7 <= len(suggestion["title_hint"]) <= 160
                    or not isinstance(suggestion.get("index_url_review_only"), str)
                    or not isinstance(suggestion.get("detail_url_review_only"), str)):
                continue
            eligible.append((municipal_row, dossier, suggestion))
    eligible.sort(key=lambda x: (
        x[0]["dossier_id"], x[2]["detail_url_review_only"],
        x[2]["title_hint"]))
    return eligible


def _recheck_event(municipal_row, dossier, hint, today,
                   fetch=fetch_public_html,
                   commune_lookup=verified_commune,
                   delegated_lookup=delegated_municipal_commune,
                   directory_fetch=fetch_dila_records):
    """Fresh government website -> LIVE index link -> named event detail."""
    site = _rederive_municipal_site(
        municipal_row, dossier, commune_lookup, delegated_lookup, directory_fetch)
    if site is None:
        return None
    index_url = hint["index_url_review_only"]
    claimed_detail = hint["detail_url_review_only"]
    try:
        homepage = fetch(site)
        if ACCESS_CHALLENGE.search(_visible(homepage)):
            return None
        if index_url == site:
            index_html = homepage
        else:
            # The page URL from the PRIVATE report may not authorize a fetch.
            # It must appear in a fresh same-origin visible homepage anchor.
            discovered = _candidate_links(
                homepage, site, site, dossier["name_hint"],
                dossier["edition_year_hint"], today)
            if index_url not in discovered:
                return None
            index_html = fetch(index_url)
        if ACCESS_CHALLENGE.search(_visible(index_html)):
            return None
        links = unknown_municipal_music_links(index_html, index_url, site)
        if not any(
            row["detail_url_review_only"] == claimed_detail
            and normalized(row["title_hint"]) == normalized(hint["title_hint"])
            and row["classification"] in MUSIC_RESEARCH_TYPES
            for row in links
        ):
            return None
        # Only the freshly attributed, visibly linked same-host detail may
        # be downloaded; no URL from a forged report is a fetch grant.
        detail = fetch(claimed_detail)
        visible = _visible(detail)
        if (ACCESS_CHALLENGE.search(visible)
                or re.search(r"(?<![a-z0-9])" +
                             re.escape(normalized(hint["title_hint"])) +
                             r"(?![a-z0-9])", visible) is None):
            return None
        return site, index_url, claimed_detail
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        return None


def reverify(queue, municipal, pages, today, *,
             fetch=fetch_public_html, commune_lookup=verified_commune,
             delegated_lookup=delegated_municipal_commune,
             directory_fetch=fetch_dila_records, limit=MAX_RECHECK):
    """Archive private search candidates; never approve unknown music by genre."""
    if type(limit) is not int or not 0 <= limit <= MAX_RECHECK:
        raise ValueError("Unsafe municipal Concerts check budget")
    eligible = _trusted_dossiers(queue, municipal, pages, today)
    if eligible and limit:
        offset = (date.fromisoformat(today).toordinal()*limit) % len(eligible)
        selected = [eligible[(offset+i) % len(eligible)]
                    for i in range(min(limit, len(eligible)))]
    else:
        selected = []
    candidates = []
    for municipal_row, dossier, hint in selected:
        independently_checked = _recheck_event(
            municipal_row, dossier, hint, today, fetch,
            commune_lookup, delegated_lookup, directory_fetch)
        if independently_checked is None:
            continue
        _, index_url, detail_url = independently_checked
        digest = sha256((detail_url + "\n" +
                         normalized(hint["title_hint"])).encode("utf-8")).hexdigest()[:24]
        # The event may be musical, but its artist, genre, venue, precise date
        # and classification remain for independent Concerts evidence review.
        proposed = {
            "candidateId": "concert-municipal-" + digest,
            "source": SOURCE, "sourceUrl": detail_url,
            "sourcePage": index_url, "date": None,
            "name": hint["title_hint"], "leadArtist": None,
            "venue": None, "city": None, "department": None,
            "venueCatalogueId": None, "classification": [],
            "genreToConfirm": True, "officialDetailFound": True,
            "newlyDiscoveredMunicipalSource": True,
            "requiresArtistAndVenueReproof": True,
            "municipalMusicResearchOnly": True,
            "sourceAuthorityVerified": False,
            "publicationAllowed": False, "reviewRequired": True,
        }
        candidate = triage.triage(proposed)
        if (candidate["reviewBucket"] != "undated_lead"
                or candidate["publicationAllowed"] is not False):
            raise ValueError("Unknown municipal music source bypassed quarantine")
        candidates.append(candidate)
    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "publicationAllowed": False, "automaticPublication": False,
        "candidates": candidates,
        "triageCounts": {"undated_lead": len(candidates)},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True, type=Path)
    parser.add_argument("--municipal", required=True, type=Path)
    parser.add_argument("--pages", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=MAX_RECHECK)
    args = parser.parse_args()
    now = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    if all(x.is_file() for x in (args.queue, args.municipal, args.pages)):
        result = reverify(
            json.loads(args.queue.read_text(encoding="utf-8")),
            json.loads(args.municipal.read_text(encoding="utf-8")),
            json.loads(args.pages.read_text(encoding="utf-8")),
            now, limit=args.limit)
    else:
        result = {
            "schema": SCHEMA,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "publicationAllowed": False, "automaticPublication": False,
            "candidates": [], "triageCounts": {"undated_lead": 0},
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Municipal music hints rechecked by Concerts: candidates=" +
          str(len(result["candidates"])) + ", publications=0, approvals=0")


if __name__ == "__main__":
    main()
