"""Independent scheduled *research* budget for venues and specialist agenda indexes.

Three fixed reviewed HTTPS pages only. Any discovered article or event page
remains unverified, regardless of editorial/venue branding. No auto-publish.
This reuses secondary discovery's next-day live-index revalidation.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from curated_future_lead_watch import load_leads
from curated_secondary_discovery import scan, build_review
from official_watch import get_page, get_json, PAGES, GIT
from regional_festival_discovery import load_indexes, APPROVED
from source_qualification import clean_url

TARGETED_INDEXES = (
    {"id": "paca-0-jds-aix-festivals", "region": "Provence-Alpes-Côte d'Azur",
     "url": ("https://www.jds.fr/marseille/aix-en-provence-9088_V/agenda/"
             "manifestations-fetes-festivals-137_B"),
     "role": "THIRD_PARTY_EDITORIAL_AGENDA"},
    {"id": "paca-6mic-agenda", "region": "Provence-Alpes-Côte d'Azur",
     "url": "https://www.6mic-aix.fr/agenda/",
     "role": "VENUE_COPRESENTER"},
    {"id": "fr-soundofbrit-festivals", "region": "FRANCE",
     "url": "https://soundofbrit.fr/festivals/",
     "role": "SPECIALIST_MEDIA_UNVERIFIED"},
)
APPROVED_ALL = {**APPROVED, **{x["url"]: x["region"] for x in TARGETED_INDEXES}}


def validated_targets():
    """Reject changed targets, duplicate hosts and accidental fetch expansion."""
    expected = {
        "paca-0-jds-aix-festivals": ("Provence-Alpes-Côte d'Azur",
            "https://www.jds.fr/marseille/aix-en-provence-9088_V/agenda/manifestations-fetes-festivals-137_B",
            "THIRD_PARTY_EDITORIAL_AGENDA"),
        "paca-6mic-agenda": ("Provence-Alpes-Côte d'Azur",
            "https://www.6mic-aix.fr/agenda/", "VENUE_COPRESENTER"),
        "fr-soundofbrit-festivals": ("FRANCE",
            "https://soundofbrit.fr/festivals/", "SPECIALIST_MEDIA_UNVERIFIED"),
    }
    if len(TARGETED_INDEXES) != len(expected):
        raise ValueError("source cible manquante ou supplementaire")
    for item in TARGETED_INDEXES:
        if (set(item) != {"id", "region", "url", "role"}
                or expected.get(item["id"]) != (
                    item["region"], item["url"], item["role"])
                or clean_url(item["url"]) != item["url"]):
            raise ValueError("source cible non autorisee")
    return [{k: row[k] for k in ("id", "region", "url")}
            for row in TARGETED_INDEXES]


def targeted_scan(state, leads, regionals, today, fetch=get_page,
                  limit=2, detail_limit=1):
    targets = validated_targets()
    all_indexes = list(regionals) + targets
    outcomes, new, details = scan(
        state, leads, targets, today, fetch=fetch, limit=limit,
        detail_limit=detail_limit, approved=APPROVED_ALL,
        attempts_key="secondary_targeted_index_last_attempted",
        queue_indexes=all_indexes)
    return outcomes, new, details, build_review(
        state, leads, all_indexes, today, approved=APPROVED_ALL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--detail-limit", type=int, default=1)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    leads = load_leads(json.loads(Path(__file__).with_name(
        "curated_future_leads.json").read_text(encoding="utf-8")))
    regionals = load_indexes(json.loads(Path(__file__).with_name(
        "regional_festival_indexes.json").read_text(encoding="utf-8")))
    pages, git = get_json(PAGES), get_json(GIT)
    if pages != git:
        raise ValueError("catalogue public divergent : surveillance suspendue")
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if (report.get("schema") != "grossesondes.source-watch-report.v1"
            or report.get("date") != today):
        raise ValueError("rapport de veille incompatible")
    outcomes, new, details, review = targeted_scan(
        state, leads, regionals, today, limit=args.limit,
        detail_limit=args.detail_limit)
    (args.intake / "curated-secondary-sources-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["curated_targeted_indexes_checked_private"] = len(outcomes)
    report["curated_targeted_new_source_candidates_private"] = new
    report["curated_targeted_detail_checks_private"] = details
    report["curated_targeted_sources_pending_private"] = review["candidate_sources_count"]
    report["curated_targeted_results_private"] = outcomes
    report["curated_targeted_independent_confirmations"] = 0
    report["curated_targeted_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("VEILLE_SOURCES_CIBLEES_PRIVEE:", json.dumps({
        "indexes": len(outcomes), "new_candidates": new,
        "detail_attempts": details,
        "pending": review["candidate_sources_count"],
        "independent_verified": 0, "published": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
