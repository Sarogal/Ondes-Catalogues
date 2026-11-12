"""Observe exact 2027 date claims on two approved festival homepages.

A published official-site URL in the old public archive is a RESEARCH
identity anchor, not proof of organizer ownership or the new edition.
We never infer publisher independence or authorize any publication here.
No dynamic URLs, extra scheduled workflows, public artifacts or PR creation.
"""
import argparse
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from historical_future_lead_watch import (
    APPROVED, _archive_visible_text, load_verified_roster,
)
from official_watch import get_page, permitted_url
from source_qualification import normalized

STATE_SCHEMA = "grossesondes.source-watch.v1"
REPORT_SCHEMA = "grossesondes.source-watch-report.v1"
STATUS = "FIRST_PARTY_VISIBLE_DATE_CLAIM_REVIEW"
MAX_CHECKS = 2
MAX_AGE_DAYS = 7

# Exact official homepages, validated against two public historical
# snapshots. These must NOT be supplied or extended from private state.
SOURCES = {
    "les-gueules-de-bois": {
        "name": "Les Gueules de Bois",
        "region": "Bourgogne-Franche-Comté",
        "url": "https://festivalgueulesdebois.com/",
        "year": 2027,
        "claims": {
            "summer": {
                "start": "2027-08-19", "end": "2027-08-21",
                "season": "summer",
                # Heading and explicit dates MUST belong to the visible
                # current-edition zone preceding the retrospective section.
                "pattern": r"\bete 2027\b.{0,190}\b19 20 21 aout(?: 2027)?\b",
            },
            "winter": {
                "start": "2027-02-13", "end": "2027-02-13",
                "season": "winter",
                "pattern": r"\bhiver 2027\b.{0,150}\b(?:samedi )?13 fevrier(?: 2027)?\b",
            },
        },
    },
    "le-gros-tonneau": {
        "name": "Le Gros Tonneau",
        "region": "Auvergne-Rhône-Alpes",
        "url": "https://legrostonneau-festival.fr/",
        "year": 2027,
        "claims": {
            "may": {
                "start": "2027-05-07", "end": "2027-05-08",
                "season": None,
                # On the current homepage the poster-style date PRECEDES
                # "GROS TONNEAU", while text below still describes 2026.
                # Bind that exact leading poster to the brand on this page.
                "pattern": (
                    r"\b0?7 0?8 mai 2027\b.{0,150}"
                    r"\breplonge dans le millesime 2026 du gros tonneau\b"
                ),
            },
        },
    },
}


def roster(today, fetch_archive=load_verified_roster):
    """Refuse requests unless both historical snapshots and pinned URLs agree."""
    approved, state = fetch_archive(today)
    if state != "CONSISTENT":
        return {}, state
    selected = {}
    try:
        for slug, source in SOURCES.items():
            reference = approved[slug]
            if (tuple(reference[key] for key in ("name", "region", "url"))
                    != (source["name"], source["region"], source["url"])
                    or not permitted_url(source["url"])
                    or not any(date.fromisoformat(spec["end"]) >= date.fromisoformat(today)
                               for spec in source["claims"].values())):
                raise ValueError("festival identity no longer approved")
            selected[slug] = source
    except (KeyError, ValueError, TypeError):
        return {}, "UNAVAILABLE_OR_INVALID"
    return selected, "CONSISTENT"


def inspect_homepage(html, config):
    """Read only the current-edition visible section, never archive or footer.

    Returns fixed claim IDs only; no dates, venues, musicians or URLs are
    generated from the HTML. A date on another event/section is not borrowed.
    """
    text = _archive_visible_text(html)
    identity = normalized(config["name"])
    if re.search(r"(?<![a-z0-9])" + re.escape(identity)
                 + r"(?![a-z0-9])", text) is None:
        return [], sha256(text.encode("utf-8")).hexdigest()
    # The bottom of these homepages contains past lineups, archived editions,
    # embeds or global footer content. Only the visible event hero is read.
    hero = re.split(r"\b(?:retour sur l edition 2026|dans le retro|"
                    r"les editions precedentes|ils nous soutiennent)\b",
                    text, maxsplit=1)[0][:1250]
    # A brand only present in the retrospective section must not validate
    # another event's future dates displayed above it.
    if (" ".join(normalized(config["name"]).split()[1:]) not in hero
            or re.search(r"\b(?:autre festival|another festival|"
                         r"autre evenement)\b", hero)):
        return [], sha256(text.encode("utf-8")).hexdigest()
    matched = sorted(cid for cid, spec in config["claims"].items()
                     if re.search(spec["pattern"], hero))
    return matched, sha256(text.encode("utf-8")).hexdigest()


def _recent(value, today):
    try:
        difference = (date.fromisoformat(today) - date.fromisoformat(value)).days
        return 0 <= difference <= MAX_AGE_DAYS
    except (ValueError, TypeError):
        return False


def validated_observations(state, today):
    """Persisted private claims are untrusted even when originally self-written."""
    raw = state.get("first_party_edition_observations_private", {})
    if not isinstance(raw, dict) or len(raw) > len(SOURCES):
        raise ValueError("invalid private first-party register")
    result = []
    for slug, row in raw.items():
        if slug not in SOURCES or not isinstance(row, dict):
            continue
        source = SOURCES[slug]
        ids = row.get("claim_ids")
        if (row.get("status") != STATUS
                or row.get("url") != source["url"]
                or row.get("slug") != slug
                or row.get("name") != source["name"]
                or row.get("region") != source["region"]
                or row.get("year") != source["year"]
                or not _recent(row.get("observed_at"), today)
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False
                or row.get("edition_dates_verified") is not False
                or row.get("independence_verified") is not False
                or row.get("organizer_verified") is not False
                or row.get("review_only") is not True
                or not isinstance(row.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
                or not isinstance(ids, list) or not ids
                or ids != sorted(set(ids))
                or any(cid not in source["claims"] or
                       date.fromisoformat(source["claims"][cid]["end"])
                       < date.fromisoformat(today) for cid in ids)):
            continue
        result.append({
            "slug": slug, "name": source["name"], "region": source["region"],
            "year": source["year"], "url": source["url"],
            "observed_at": row["observed_at"],
            "claims": [
                {"claim_id": cid,
                 "start_date_hint": source["claims"][cid]["start"],
                 "end_date_hint": source["claims"][cid]["end"],
                 "season_hint": source["claims"][cid]["season"],
                 "review_only": True, "edition_dates_verified": False,
                 "organizer_verified": False, "independence_verified": False,
                 "publication_authorized": False}
                for cid in ids
            ],
            "review_only": True, "edition_dates_verified": False,
            "organizer_verified": False, "independence_verified": False,
            "publication_authorized": False,
        })
    return sorted(result, key=lambda row: row["slug"])


def scan(state, approved, today, fetch=get_page, limit=MAX_CHECKS):
    if (not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA
            or not isinstance(approved, dict)
            or any(slug not in SOURCES or source != SOURCES[slug]
                   for slug, source in approved.items())
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("unauthorized first-party watch")
    checks = state.setdefault("first_party_edition_checks_private", {})
    observations = state.setdefault("first_party_edition_observations_private", {})
    if not isinstance(checks, dict) or not isinstance(observations, dict):
        raise ValueError("invalid private first-party watch state")
    outcomes = []
    for slug, source in sorted(approved.items())[:limit]:
        previous = checks.get(slug)
        if previous is not None:
            try:
                previous_date = date.fromisoformat(previous)
            except (ValueError, TypeError):
                raise ValueError("invalid last first-party attempt") from None
            if previous_date > date.fromisoformat(today):
                raise ValueError("future first-party attempt")
            if previous_date == date.fromisoformat(today):
                continue
        # A failed fetch or changed page invalidates a previous positive.
        observations.pop(slug, None)
        result = "UNAVAILABLE_OR_INCONCLUSIVE"
        try:
            claim_ids, digest = inspect_homepage(fetch(source["url"]), source)
            claim_ids = [cid for cid in claim_ids if
                         date.fromisoformat(source["claims"][cid]["end"])
                         >= date.fromisoformat(today)]
            if claim_ids:
                observations[slug] = {
                    "status": STATUS, "url": source["url"], "slug": slug,
                    "name": source["name"], "region": source["region"],
                    "year": source["year"], "observed_at": today,
                    "claim_ids": claim_ids, "sha256": digest,
                    "review_only": True, "publication_authorized": False,
                    "safe_to_publish": False, "edition_dates_verified": False,
                    "organizer_verified": False, "independence_verified": False,
                }
                result = "VISIBLE_FIRST_PARTY_DATE_REVIEW_ONLY"
            else:
                result = "NO_APPROVED_2027_DATE_CLAIM"
        except (ValueError, TypeError, UnicodeError, OSError):
            pass
        checks[slug] = today
        outcomes.append({"slug": slug, "status": result,
                         "publication_authorized": False})
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("schema") != REPORT_SCHEMA or report.get("date") != today:
        raise ValueError("inconsistent first-party daily report")
    approved, integrity = roster(today)
    if not approved:
        state["first_party_edition_observations_private"] = {}
    results = scan(state, approved, today, limit=args.limit) if approved else []
    current = validated_observations(state, today)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["first_party_edition_archive_integrity_private"] = integrity
    report["first_party_edition_attempts_private"] = len(results)
    report["first_party_edition_claim_sources_private"] = len(current)
    report["first_party_edition_date_claims_private"] = sum(
        len(row["claims"]) for row in current)
    report["first_party_edition_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("FIRST_PARTY_EDITION_REVIEW:", json.dumps({
        "archive": integrity, "checks": len(results),
        "claims": report["first_party_edition_date_claims_private"],
        "published": 0
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
