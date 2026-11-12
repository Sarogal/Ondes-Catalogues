"""National private discovery dossier queue, derived from existing reviewed feeds.

No network calls, no URL fetch lists, no public catalogue patch, no source
independence inference. Dynamic regional discoveries do not need to appear in
curated_future_leads.json. All claims remain search hints for editorial review.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from curated_future_lead_watch import load_leads
from historical_future_lead_watch import validated_hints
from targeted_institutional_future_watch import validated_observations as validated_institutional
from targeted_press_edition_watch import (
    SOURCES as APPROVED_PRESS, validated_observations as validated_press,
)
from curated_secondary_discovery import clean_queue
from curated_targeted_secondary import APPROVED_ALL, validated_targets
from regional_festival_discovery import APPROVED
from regional_visible_article_clues import STATUS as VISIBLE_ARTICLE_STATUS
from source_qualification import clean_url, normalized

SCHEMA = "grossesondes.national-festival-discovery-private.v1"
STATE_SCHEMA = "grossesondes.source-watch.v1"
REPORT_SCHEMA = "grossesondes.source-watch-report.v1"
MAX_AGE_DAYS = 60
MAX_CANDIDATES = 200
MAX_SOURCES = 12
MAX_INTAKE_ROWS = 400
YEAR = re.compile(r"(?<!\d)20[2-4]\d(?!\d)")
DANGEROUS_TEXT = re.compile(r"[<>{}\x00-\x1f]")
EXCLUDED_DETAIL = re.compile(r"\.(?:pdf|zip|png|jpe?g|gif|svg|webp|ics)$", re.I)
VALID_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,159}$")


def _recent(first, last, today):
    try:
        a, b, now = date.fromisoformat(first), date.fromisoformat(last), date.fromisoformat(today)
        return a <= b <= now and (now - b).days <= MAX_AGE_DAYS
    except (ValueError, TypeError):
        return False


def _safe_title(title):
    return (isinstance(title, str) and 7 <= len(title) <= 160
            and not DANGEROUS_TEXT.search(title)
            and 7 <= len(normalized(title)) <= 140)


def _safe_origin_link(url, origin):
    """Validate observed provenance only; NEVER use the result as a fetch target."""
    if not isinstance(origin, str) or origin not in APPROVED_ALL:
        return False
    if not isinstance(url, str) or len(url) > 500:
        return False
    try:
        source, target = urlsplit(origin), urlsplit(url)
        return (target.scheme == "https" and target.hostname == source.hostname
                and target.port in (None, 443) and not target.username
                and not target.password and not target.fragment
                and bool(target.path) and target.path != source.path
                and not EXCLUDED_DETAIL.search(target.path)
                and clean_url(url) == url)
    except (ValueError, TypeError):
        return False


def _identity(title, explicit_year=None):
    """Preserve an unknown year; never infer the date of a future edition."""
    if not _safe_title(title):
        return None
    name = normalized(title)
    years = {int(y) for y in YEAR.findall(name)}
    if len(years) > 1:
        return None
    from_title = next(iter(years)) if years else None
    if explicit_year is not None:
        if type(explicit_year) is not int or not 2025 <= explicit_year <= 2049:
            return None
        if from_title is not None and explicit_year != from_title:
            return None
    year = explicit_year if explicit_year is not None else from_title
    clean_name = re.sub(r"\b20[2-4]\d\b", " ", name)
    clean_name = " ".join(clean_name.split()).strip()
    if len(clean_name) < 6:
        return None
    return clean_name, year



def _url_edition_hint(url, title, today):
    """Extract only an unverified research year from a same-name URL slug.

    The caller still validates the first-party source URL independently.
    An URL slug is never a date, organizer proof or publication authority.
    Only an exact normalized festival name followed by -YYYY may supply
    the *private* dossier's missing edition-year hint.
    """
    ident = _identity(title)
    if ident is None or ident[1] is not None or not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        # Even before the caller's origin check, ignore impostor domains.
        if (parsed.scheme != "https" or parsed.port not in (None, 443)
                or parsed.username or parsed.password
                or parsed.hostname not in {urlsplit(seed).hostname for seed in APPROVED}
                or parsed.query or parsed.fragment):
            return None
        slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        match = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*)-(20[2-4]\d)", slug)
        if match is None or normalized(match.group(1).replace("-", " ")) != ident[0]:
            return None
        year = int(match.group(2))
        current = date.fromisoformat(today).year
        return year if current <= year <= current + 2 else None
    except (ValueError, TypeError):
        return None


def _safe_region(value):
    regions = set(APPROVED.values())
    regions.discard("FRANCE")
    if isinstance(value, str) and value in regions:
        return value
    return None


def build_queue(state, report, curated, today):
    """Fold vetted private pipeline observations into a bounded review-only queue."""
    date.fromisoformat(today)
    if (not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA
            or not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA
            or report.get("date") != today
            or not isinstance(curated, list)):
        raise ValueError("entrees de veille nationale invalides")
    validated_targets()  # fixed review of every targeted secondary index
    # Do not let private state or scrape HTML define a domain or a destination.
    by_id = {lead["id"]: lead for lead in curated}
    if len(by_id) != len(curated):
        raise ValueError("doublon de piste editee")
    # A future mention in a reviewed historical homepage is an unverified
    # search lead, never a date, event announcement or authorized publication.
    archive_hints = (validated_hints(state, today)
                     if report.get("historical_future_watch_archive_status_private")
                     == "CONSISTENT" else [])
    approved_archive_urls = {entry["url"] for entry in archive_hints}
    institutional_hints = (validated_institutional(state, today)
                           if report.get("institutional_future_archive_status_private")
                           == "CONSISTENT" else [])
    approved_institutional_urls = {entry["institutional_url"]
                                   for entry in institutional_hints}
    # A validated press article is an independently observed *research lead*,
    # NOT a verified independent publisher or date.  It must not depend on an
    # older homepage hint surviving a stricter date/season validation.
    press_hints = (validated_press(state, today)
                   if report.get("press_edition_archive_integrity_private")
                   == "CONSISTENT" else [])
    approved_press_urls = {
        item["url"] for item in press_hints
        if item["url"] in {cfg["url"] for cfg in APPROVED_PRESS.values()}
    }
    dossiers = {}
    rejected = 0
    observed_sources = 0
    newly_discovered_sources = 0

    def add(title, year, region, url, origin, kind, first, last,
            city=None, archive_slug=None, date_hint=None,
            archive_date_hints=None, institutional_date_hint=None):
        nonlocal rejected, observed_sources, newly_discovered_sources
        ident = _identity(title, year)
        region = _safe_region(region)
        # Curated URLs are separate, fixed, reviewed primary-candidate inputs.
        safe = (isinstance(url, str)
                and kind == "CURATED_PRIMARY_CANDIDATE"
                and url in {lead["source_url"] for lead in curated}
                and origin == url) or (
                    isinstance(url, str)
                    and kind == "HISTORICAL_HOMEPAGE_YEAR_HINT"
                    and url in approved_archive_urls and origin == url) or (
                    isinstance(url, str)
                    and kind == "INSTITUTIONAL_FUTURE_DATE_HINT"
                    and url in approved_institutional_urls and origin == url) or (
                    isinstance(url, str)
                    and kind == "PRESS_ARTICLE_DATE_CLAIM_REVIEW"
                    and url in approved_press_urls and origin == url)
        if (ident is None or not region or not isinstance(url, str)
                or not (safe or _safe_origin_link(url, origin))
                or not _recent(first, last, today)):
            rejected += 1
            return
        name, edition_year = ident
        key = (name, edition_year, region)
        if key not in dossiers and len(dossiers) >= MAX_CANDIDATES:
            rejected += 1
            return
        if key not in dossiers:
            digest = sha256(repr(key).encode("utf-8")).hexdigest()[:20]
            dossiers[key] = {
                "id": "national-" + digest,
                "name_hint": title,
                "normalized_name": name,
                "name_variants": [],
                "edition_year_hint": edition_year,
                "region_hint": region,
                "city_hint": None,
                "archive_slug_hint": None,
                "date_hints": [],
                "historical_homepage_date_hints_review_only": [],
                "institutional_future_date_hints_review_only": [],
                "firstSeen": first, "lastSeen": last,
                "sources": [],
                "source_independence_verified": False,
                "festival_verified": False,
                "edition_dates_verified": False,
                "publication_authorized": False,
                "safe_to_publish": False,
                "status": "DISCOVERED_REVIEW_REQUIRED",
                "missing_checks": [
                    "festival_identity", "edition_year_and_dates",
                    "organizer_identity", "publisher_independence",
                    "place_and_department", "public_duplicate_review",
                    "editorial_signoff",
                ],
            }
        row = dossiers[key]
        row["firstSeen"] = min(row["firstSeen"], first)
        row["lastSeen"] = max(row["lastSeen"], last)
        if title not in row["name_variants"] and len(row["name_variants"]) < 8:
            row["name_variants"].append(title)
        if (isinstance(city, str) and 2 <= len(city) <= 100
                and not DANGEROUS_TEXT.search(city)):
            if row["city_hint"] is None:
                row["city_hint"] = city
            elif row["city_hint"] != city:
                row["missing_checks"].append("conflicting_city_hints")
        if (isinstance(archive_slug, str) and VALID_SLUG.fullmatch(archive_slug)):
            row["archive_slug_hint"] = archive_slug
        if date_hint and date_hint not in row["date_hints"]:
            row["date_hints"].append(date_hint)
        if kind == "HISTORICAL_HOMEPAGE_YEAR_HINT" and archive_date_hints:
            for clue in archive_date_hints:
                if (clue not in row["historical_homepage_date_hints_review_only"]
                        and len(row["historical_homepage_date_hints_review_only"]) < 3):
                    row["historical_homepage_date_hints_review_only"].append(
                        dict(clue))
        if kind == "INSTITUTIONAL_FUTURE_DATE_HINT" and institutional_date_hint:
            if institutional_date_hint not in row["institutional_future_date_hints_review_only"]:
                row["institutional_future_date_hints_review_only"].append(
                    dict(institutional_date_hint))
        witness = {"url": url, "discovered_via": origin, "kind": kind,
                   "firstSeen": first, "lastSeen": last,
                   "independence_verified": False,
                   "publication_authorized": False}
        if any(s["url"] == url and s["discovered_via"] == origin
               for s in row["sources"]):
            return
        if len(row["sources"]) >= MAX_SOURCES:
            rejected += 1
            return
        row["sources"].append(witness)
        observed_sources += 1
        if kind != "CURATED_PRIMARY_CANDIDATE" and first == today:
            newly_discovered_sources += 1

    # The five historical curated investigations remain, but no longer gate
    # registration of completely new festivals from regional indexes.
    for lead in curated:
        year = (int(lead["start_date"][:4]) if lead["start_date"] else
                int(lead["id"][-4:]) if YEAR.search(lead["id"][-4:]) else None)
        hint = ({"start_date": lead["start_date"], "end_date": lead["end_date"],
                 "verified": False} if lead["start_date"] else None)
        add(lead["name"], year, lead["region_hint"], lead["source_url"],
            lead["source_url"], "CURATED_PRIMARY_CANDIDATE",
            today, today, city=lead["city_hint"], date_hint=hint)

    for hint in archive_hints:
        add(hint["name"], hint["year"], hint["region"],
            hint["url"], hint["url"], "HISTORICAL_HOMEPAGE_YEAR_HINT",
            hint["firstSeen"], hint["lastSeen"],
            archive_slug=hint["slug"],
            archive_date_hints=hint["date_hints_review_only"])

    for hint in institutional_hints:
        add(hint["name"], int(hint["start"][:4]), hint["region"],
            hint["institutional_url"], hint["institutional_url"],
            "INSTITUTIONAL_FUTURE_DATE_HINT", hint["first"], hint["last"],
            city=hint["city"], archive_slug=hint["slug"],
            institutional_date_hint={
                "start_date_hint": hint["start"], "end_date_hint": hint["end"],
                "city_name_hint": hint["city"],
                "venue_name_hint": hint["venue"],
                "official_home": hint["official_home"],
                "official_home_future_dates_visible": hint["primary_same_dates"],
                "organizer_name_home_review_only": hint["organizer_name_on_home_review_only"],
                "provider_claim": hint["provider"],
                "institutional_source_url": hint["institutional_url"],
                "observed_at": hint["last"],
                "publication_authorized": False, "review_only": True,
                "independence_verified": False, "edition_dates_verified": False,
            })

    # The publisher's article may keep an existing-edition RESEARCH dossier
    # alive when old, contradictory homepage dates are quarantined.  Only an
    # exact, previously pinned article can seed it, after the public historical
    # archive-integrity gate.  No claim enters `date_hints` or approval fields.
    for article in press_hints:
        years = {int(claim["start_date_hint"][:4]) for claim in article["claims"]}
        if (len(years) != 1
                or any(claim["end_date_hint"][:4] != claim["start_date_hint"][:4]
                       for claim in article["claims"])):
            continue
        year = next(iter(years))
        if not date.fromisoformat(today).year < year <= date.fromisoformat(today).year + 2:
            continue
        add(article["name"], year, article["region"],
            article["url"], article["url"],
            "PRESS_ARTICLE_DATE_CLAIM_REVIEW",
            article["observed_at"], article["observed_at"],
            archive_slug=article["slug"])

    regional = state.get("regional_festival_candidates_review_only", {})
    if not isinstance(regional, dict):
        raise ValueError("file regionale corrompue")
    for url, row in list(regional.items())[:MAX_INTAKE_ROWS]:
        if not isinstance(row, dict) or row.get("publication_authorized") is not False:
            rejected += 1
            continue
        if (row.get("status") != "UNVERIFIED_THEME_LINK"
                or row.get("candidate_url") != url
                or not isinstance(row.get("source_index"), str)
                or row.get("source_index") not in APPROVED
                or row.get("region") != APPROVED.get(row.get("source_index"))):
            rejected += 1
            continue
        # A yearless visible title can keep a strictly matching -YYYY URL
        # as a REVIEW-ONLY edition hint; never treat a slug as event proof.
        year_hint = _url_edition_hint(url, row.get("title"), today)
        add(row.get("title"), year_hint, row["region"], url,
            row["source_index"], "REGIONAL_INDEX_UNVERIFIED",
            row.get("firstSeen"), row.get("lastSeen"),
            archive_slug=row.get("historical_name_slug"))

    # Institutional observations only join already referenced editions. Do not
    # promote unknown slug names into event titles or infer publication.
    originals = report.get("source_reference_leads_review_only", [])
    if not isinstance(originals, list):
        raise ValueError("references sources invalides")
    refs = {row["slug"]: row for row in originals[:MAX_INTAKE_ROWS]
            if isinstance(row, dict) and isinstance(row.get("slug"), str)}
    institutional = state.get("institutional_agenda_candidate_pages", {})
    if not isinstance(institutional, dict):
        raise ValueError("file institutionnelle corrompue")
    for slug, records in list(institutional.items())[:MAX_INTAKE_ROWS]:
        ref = refs.get(slug)
        if not isinstance(ref, dict) or not isinstance(records, list):
            continue
        start = ref.get("start_date")
        try:
            year = date.fromisoformat(start).year
        except (ValueError, TypeError):
            continue
        title = ref.get("name") or ref.get("festival_name")
        region = ref.get("region")
        if not _safe_title(title) or not region:
            continue
        for record in records[:MAX_SOURCES]:
            if (not isinstance(record, dict)
                    or record.get("status") != "UNVERIFIED_INDEX_LINK"
                    or record.get("publication_authorized") is not False):
                rejected += 1
                continue
            add(title, year, region, record.get("candidate_url"),
                record.get("source"), "INSTITUTIONAL_INDEX_UNVERIFIED",
                record.get("lastSeen"), record.get("lastSeen"),
                city=ref.get("city"))

    # Secondary queue is already constrained to pre-approved same-host sources.
    # This does not turn editorial venues/media into independent confirmations.
    from curated_targeted_secondary import APPROVED_ALL
    regional_indexes = json.loads(Path(__file__).with_name(
        "regional_festival_indexes.json").read_text(encoding="utf-8"))
    from regional_festival_discovery import load_indexes
    all_indexes = load_indexes(regional_indexes) + validated_targets()
    secondary = clean_queue(state.get("secondary_source_candidates_private", {}),
                            curated, all_indexes, today, approved=APPROVED_ALL)
    for lead_id, records in secondary.items():
        lead = by_id.get(lead_id)
        if not lead:
            continue
        year = int(lead["start_date"][:4]) if lead["start_date"] else (
            int(lead["id"][-4:]) if YEAR.search(lead["id"][-4:]) else None)
        for record in records:
            add(lead["name"], year, lead["region_hint"],
                record["candidate_url"], record["index_url"],
                "SECONDARY_INDEX_UNVERIFIED", record["firstSeen"],
                record["lastSeen"], city=lead["city_hint"])

    # Visible article observations have no event URL. Keep them separate from
    # visitable dossiers and never manufacture a detail-page fetch target.
    unlinked = []
    private_articles = state.get("regional_festival_article_clues_review_only", {})
    if not isinstance(private_articles, dict):
        raise ValueError("revue nationale des cartes sans lien corrompue")
    for key, record in list(private_articles.items())[:200]:
        if not isinstance(record, dict):
            continue
        origin, title = record.get("source_index"), record.get("title")
        year = record.get("edition_year_hint")
        if (not isinstance(origin, str) or origin not in APPROVED
                or record.get("region") != APPROVED[origin]
                or not _safe_title(title)
                or year is not None and (type(year) is not int
                                         or not today[:4].isdigit()
                                         or not int(today[:4]) - 1 <= year <= int(today[:4]) + 2)
                or record.get("status") != VISIBLE_ARTICLE_STATUS
                or record.get("publication_authorized") is not False
                or record.get("fetch_eligible") is not False
                or not _recent(record.get("firstSeen"), record.get("lastSeen"), today)):
            continue
        name = normalized(title)
        expected_key = sha256((origin + "\n" + name + "\n" + str(year))
                              .encode("utf-8")).hexdigest()[:20]
        if (key != expected_key or _identity(title, year) is None):
            continue
        unlinked.append({
            "title_hint": title, "edition_year_hint": year,
            "region_hint": APPROVED[origin], "source_index": origin,
            "status": "REVIEW_UNLINKED_EVENT_CARD",
            "fetch_eligible": False, "festival_verified": False,
            "publication_authorized": False,
        })
        if len(unlinked) == 100:
            break
    unlinked.sort(key=lambda x: (
        x["region_hint"], x["title_hint"], x["source_index"]))
    rows = sorted(dossiers.values(), key=lambda x: (
        x["edition_year_hint"] or 0, x["normalized_name"], x["region_hint"]))
    for row in rows:
        row["sources"].sort(key=lambda s: (s["url"], s["discovered_via"]))
        row["date_hints"].sort(key=lambda d: (d["start_date"] or ""))
        row["historical_homepage_date_hints_review_only"].sort(
            key=lambda d: (d["start_date_hint"], d["end_date_hint"]))
        row["institutional_future_date_hints_review_only"].sort(
            key=lambda d: (d["start_date_hint"], d["end_date_hint"]))
        row["missing_checks"] = sorted(set(row["missing_checks"]))
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "publication_authorized": False,
        "safe_to_publish": False, "publications": 0,
        "candidate_dossiers_count": len(rows),
        "candidate_sources_count": observed_sources,
        "newly_discovered_sources_count": newly_discovered_sources,
        "historical_homepage_year_hints_private": len(archive_hints),
        "historical_homepage_dossiers_private": sum(
            any(s["kind"] == "HISTORICAL_HOMEPAGE_YEAR_HINT"
                for s in row["sources"]) for row in rows),
        "historical_homepage_date_hints_private": sum(
            len(row["historical_homepage_date_hints_review_only"]) for row in rows),
        "press_article_research_dossiers_private": sum(
            any(source["kind"] == "PRESS_ARTICLE_DATE_CLAIM_REVIEW"
                for source in row["sources"]) for row in rows),
        "institutional_future_date_dossiers_private": sum(
            bool(row["institutional_future_date_hints_review_only"]) for row in rows),
        "non_curated_dossiers_count": sum(
            not any(s["kind"] == "CURATED_PRIMARY_CANDIDATE"
                    for s in row["sources"]) for row in rows),
        "qualified_sources_count": 0,
        "private_review_proposals_count": len(rows),
        "discarded_input_rows": rejected,
        "network_requests": 0,
        "unlinked_visible_article_clues_count": len(unlinked),
        "unlinked_visible_article_clues_review_only": unlinked,
        "dossiers": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state = json.loads((args.intake / "source-watch-state.json").read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    curated = load_leads(json.loads(Path(__file__).with_name(
        "curated_future_leads.json").read_text(encoding="utf-8")))
    review = build_queue(state, report, curated, today)
    (args.intake / "national-festival-discovery-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["national_discovery_dossiers_private"] = review["candidate_dossiers_count"]
    report["national_discovery_historical_homepage_dossiers_private"] = (
        review["historical_homepage_dossiers_private"])
    report["national_discovery_institutional_future_dossiers_private"] = (
        review["institutional_future_date_dossiers_private"])
    report["national_discovery_press_research_dossiers_private"] = (
        review["press_article_research_dossiers_private"])
    report["national_discovery_sources_private"] = review["candidate_sources_count"]
    report["national_discovery_new_sources_private"] = review["newly_discovered_sources_count"]
    report["national_discovery_non_curated_dossiers_private"] = review["non_curated_dossiers_count"]
    report["national_discovery_sources_qualified_private"] = 0
    report["national_discovery_proposals_private"] = review["private_review_proposals_count"]
    report["national_discovery_dropped_private"] = review["discarded_input_rows"]
    report["national_discovery_unlinked_clues_private"] = (
        review["unlinked_visible_article_clues_count"])
    report["national_discovery_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("DECOUVERTE_NATIONALE_PRIVEE:", json.dumps({
        "dossiers": review["candidate_dossiers_count"],
        "sources": review["candidate_sources_count"],
        "new_sources": review["newly_discovered_sources_count"],
        "non_curated_dossiers": review["non_curated_dossiers_count"],
        "qualified": 0, "private_proposals": review["private_review_proposals_count"],
        "unlinked_clues": review["unlinked_visible_article_clues_count"],
        "published": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
