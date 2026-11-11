"""Bounded checks of two editorial articles relevant to 2027 festivals.

This is an article CLAIM watch, not a publisher-independence certification.
The articles may quote organizers or other newspapers. A different domain
does not establish independent reporting, and no observation can publish.
All state remains on the private intake branch, using existing public runners.
"""
import argparse
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from historical_future_lead_watch import _archive_visible_text
from official_watch import get_json, get_page, permitted_url
from regional_festival_discovery import HISTORY_PAGES, HISTORY_GIT
from source_qualification import normalized

STATE_SCHEMA = "grossesondes.source-watch.v1"
REPORT_SCHEMA = "grossesondes.source-watch-report.v1"
STATUS = "PRESS_DATE_CLAIM_REVIEW_ONLY"
MAX_CHECKS = 2
MAX_HISTORY = 500
MAX_AGE_DAYS = 7

# These immutable source identities and exact article paths were inspected
# editorially on 2026-11-11. Scraped links and private state never add URLs.
SOURCES = {
    "gueules-progres": {
        "slug": "les-gueules-de-bois",
        "name": "Les Gueules de Bois",
        "region": "Bourgogne-Franche-Comté",
        "old_year": 2026,
        "official_home": "https://festivalgueulesdebois.com/",
        "url": (
            "https://www.leprogres.fr/culture-loisirs/2026/11/06/"
            "la-billetterie-du-festival-des-gueules-de-bois-de-l-ete-2027-est-ouverte"
        ),
        "publisher": "Le Progrès",
        "claims": {
            "winter": {
                "start": "2027-02-13", "end": "2027-02-13",
                "season": "winter",
                "phrase": r"\bpremier rendez vous le samedi 13 fevrier 2027\b",
            },
            "summer": {
                "start": "2027-08-19", "end": "2027-08-21",
                "season": "summer",
                "phrase": (
                    r"\b(?:septieme edition du festival|edition estivale)"
                    r".{0,125}\b19 20 et 21 aout 2027\b"
                ),
            },
        },
    },
    "mauges-angers": {
        "slug": "mauges-pit-fest",
        "name": "Mauges Pit Fest",
        "region": "Pays de la Loire",
        "old_year": 2026,
        "official_home": "https://maugespitfest.fr/",
        "url": (
            "https://my-angers.info/10/26/"
            "le-mauges-pit-fest-dresse-un-bilan-positif-pour-sa-cinquieme-edition/199913"
        ),
        "publisher": "Angers Info",
        "claims": {
            "next-edition": {
                "start": "2027-10-08", "end": "2027-10-09",
                "season": None,
                "phrase": (
                    r"\bprochaine edition du festival est d ores et deja"
                    r" programmee pour les 8 et 9 octobre 2027\b"
                ),
            },
        },
    },
}


def approved_roster(history, today):
    """Two public archive snapshots must match pinned identities exactly."""
    now = date.fromisoformat(today)
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)
            or len(history["knownFestivals"]) > MAX_HISTORY):
        raise ValueError("archive source shape invalid")
    found = set()
    for row in history["knownFestivals"]:
        if not isinstance(row, dict):
            raise ValueError("invalid archived row")
        slug = row.get("slug")
        if slug not in {x["slug"] for x in SOURCES.values()}:
            continue
        if slug in found:
            raise ValueError("duplicate approved festival in archive")
        config = next(x for x in SOURCES.values() if x["slug"] == slug)
        try:
            start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid archived dates") from None
        if (row.get("name") != config["name"]
                or row.get("region") != config["region"]
                or row.get("officialSite") != config["official_home"]
                or row.get("lastKnownYear") != config["old_year"]
                or not start <= end < now or end.year != config["old_year"]):
            raise ValueError("pinned archive identity changed")
        found.add(slug)
    if found != {x["slug"] for x in SOURCES.values()}:
        raise ValueError("missing pinned archived festival")
    if any(not permitted_url(x["url"]) for x in SOURCES.values()):
        raise ValueError("unapproved article URL")
    return SOURCES


def load_sources(today, fetch_json=get_json):
    """Reject divergent archives *before* reading any press articles."""
    try:
        pages, git = fetch_json(HISTORY_PAGES), fetch_json(HISTORY_GIT)
        if pages != git:
            return {}, "DIVERGENT"
        return approved_roster(pages, today), "CONSISTENT"
    except (OSError, TypeError, ValueError, UnicodeError, KeyError):
        return {}, "UNAVAILABLE_OR_INVALID"


def inspect_article(html, source):
    """Recognize only pinned, explicit edition phrases in visible article text.

    The article title/identity alone is insufficient. A 2026 write-up with a
    generic reference to next year is not an exact future-edition date claim.
    """
    text = _archive_visible_text(html)
    name = normalized(source["name"])
    if not re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", text):
        return [], sha256(text.encode("utf-8")).hexdigest()
    claims = []
    for cid, claim in source["claims"].items():
        # Pin the date, range and season in code; matching alone is review.
        if re.search(claim["phrase"], text):
            claims.append(cid)
    return sorted(claims), sha256(text.encode("utf-8")).hexdigest()


def _recent(value, today):
    try:
        delta = (date.fromisoformat(today) - date.fromisoformat(value)).days
        return 0 <= delta <= MAX_AGE_DAYS
    except (ValueError, TypeError):
        return False


def validated_observations(state, today):
    """No untrusted private row may change a URL, date, status or approval."""
    raw = state.get("press_edition_observations_private", {})
    if not isinstance(raw, dict) or len(raw) > len(SOURCES):
        raise ValueError("invalid press observation registry")
    accepted = []
    for key, row in raw.items():
        if key not in SOURCES or not isinstance(row, dict):
            continue
        cfg = SOURCES[key]
        ids = row.get("observed_claim_ids")
        if (row.get("status") != STATUS
                or row.get("slug") != cfg["slug"]
                or row.get("article_url") != cfg["url"]
                or row.get("publisher") != cfg["publisher"]
                or row.get("review_only") is not True
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False
                or row.get("edition_dates_verified") is not False
                or row.get("independence_verified") is not False
                or not _recent(row.get("observed_at"), today)
                or not isinstance(row.get("text_sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", row["text_sha256"]) is None
                or not isinstance(ids, list) or not ids
                or ids != sorted(set(ids))
                or any(cid not in cfg["claims"] for cid in ids)):
            continue
        accepted.append({
            "slug": cfg["slug"],
            "name": cfg["name"],
            "region": cfg["region"],
            "url": cfg["url"],
            "publisher": cfg["publisher"],
            "observed_at": row["observed_at"],
            "claims": [
                {"claim_id": cid,
                 "start_date_hint": cfg["claims"][cid]["start"],
                 "end_date_hint": cfg["claims"][cid]["end"],
                 "season_hint": cfg["claims"][cid]["season"],
                 "review_only": True, "independence_verified": False,
                 "edition_dates_verified": False,
                 "publication_authorized": False}
                for cid in ids
            ],
            "review_only": True, "publication_authorized": False,
            "independence_verified": False,
            "publisher_origin_assessed": False,
        })
    return sorted(accepted, key=lambda x: x["slug"])


def scan(state, approved, today, fetch=get_page, limit=MAX_CHECKS):
    if (not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA
            or not isinstance(approved, dict)
            or any(k not in SOURCES or v != SOURCES[k] for k, v in approved.items())
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("invalid press watch configuration")
    checks = state.setdefault("press_edition_checks_private", {})
    observations = state.setdefault("press_edition_observations_private", {})
    if not isinstance(checks, dict) or not isinstance(observations, dict):
        raise ValueError("invalid private press state")
    outcomes = []
    for key, cfg in sorted(approved.items())[:limit]:
        last = checks.get(key)
        if last is not None:
            if not isinstance(last, str) or date.fromisoformat(last) > date.fromisoformat(today):
                raise ValueError("invalid press check time")
            if last == today:
                continue
        observations.pop(key, None)
        status = "UNAVAILABLE_OR_INCONCLUSIVE"
        try:
            ids, digest = inspect_article(fetch(cfg["url"]), cfg)
            if ids:
                observations[key] = {
                    "status": STATUS, "slug": cfg["slug"],
                    "article_url": cfg["url"], "publisher": cfg["publisher"],
                    "observed_at": today, "text_sha256": digest,
                    "observed_claim_ids": ids, "review_only": True,
                    "safe_to_publish": False, "publication_authorized": False,
                    "edition_dates_verified": False,
                    "independence_verified": False,
                }
                status = "VISIBLE_DATE_CLAIM_REVIEW"
            else:
                status = "NO_EXACT_DATE_CLAIM"
        except (OSError, ValueError, UnicodeError, TypeError):
            pass  # no stale positive observation survives a fetch failure
        checks[key] = today
        outcomes.append({"source_id": key, "status": status,
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
        raise ValueError("invalid private daily report")
    approved, integrity = load_sources(today)
    results = scan(state, approved, today, limit=args.limit) if approved else []
    current = validated_observations(state, today)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["press_edition_archive_integrity_private"] = integrity
    report["press_edition_attempts_private"] = len(results)
    report["press_edition_date_claim_sources_private"] = len(current)
    report["press_edition_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("PRESS_EDITION_REVIEW:", json.dumps({
        "archive": integrity, "checks": len(results),
        "review_only_sources": len(current), "publications": 0
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
