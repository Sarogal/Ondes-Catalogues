"""Bounded multi-source corroboration for private 2027 festival research.

A different hostname is NOT evidence of an independent publisher. Source
relationships are editorially reviewed in this code, never inferred from HTML.
No public catalogue writer, PR creator, approval or publication hook exists.
"""
import argparse
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from curated_future_lead_watch import load_leads, published_duplicate, visible_text
from curated_future_review import valid_observation
from official_watch import get_page, get_json, PAGES, GIT, permitted_url
from source_qualification import normalized

SCHEMA = "grossesondes.curated-corroboration.v1"
RECORD_STATUS = "UNVERIFIED_SECONDARY_OBSERVATION"
MAX_CHECKS = 2
MAX_AGE_DAYS = 7

# Exact manually inspected destinations, not links extracted from private state.
# A co-organizer, its ticketing page, and a repeat of its own press release
# belong to the SAME publisher even across different domains.
SOURCES = (
    {"id": "mozhell-helloasso", "lead": "mozhell-open-air-2027",
     "url": "https://www.helloasso.com/associations/mozhell-prod/evenements/billetterie-mozhell-2027",
     "role": "ORGANIZER_TICKETING", "publisher": "mozhell-prod",
     "independence_verified": False},
    {"id": "mozhell-aggregator", "lead": "mozhell-open-air-2027",
     "url": "https://www.festivalenfrance.com/festival/mozhell-open-air",
     "role": "UNVERIFIED_AGGREGATOR", "publisher": "festivalenfrance",
     "independence_verified": False},
    {"id": "festibarock-history", "lead": "festibarock-in-2027",
     "url": "https://www.festibarockin.fr/festival/",
     "role": "FESTIVAL_SITE", "publisher": "festibarock-organizer",
     "independence_verified": False},
    {"id": "sainte-practical", "lead": "la-sainte-rock-festival-2027",
     "url": "https://lasainterockfestival.fr/infos-pratiques",
     "role": "FESTIVAL_SITE", "publisher": "la-sainte-organizers",
     "independence_verified": False},
    {"id": "sainte-6mic-history", "lead": "la-sainte-rock-festival-2027",
     "url": "https://www.6mic-aix.fr/evenements/la-sainte-rock-j2/",
     "role": "VENUE_COPRESENTER", "publisher": "la-sainte-organizers",
     "independence_verified": False},
    {"id": "colombin-home", "lead": "colombin-rock-festival-2027",
     "url": "https://www.colombin-rock.fr/",
     "role": "FESTIVAL_SITE", "publisher": "colombin-organizer",
     "independence_verified": False},
)
PRIMARY_PUBLISHERS = {
    "mozhell-open-air-2027": "mozhell-prod",
    "festibarock-in-2027": "festibarock-organizer",
    "la-sainte-rock-festival-2027": "la-sainte-organizers",
    "colombin-rock-festival-2027": "colombin-organizer",
    "esqui-riot-2027": "esqui-riot-organizer",
}
INDEPENDENT_ROLES = {"INSTITUTION", "INDEPENDENT_MEDIA", "INDEPENDENT_VENUE"}
REVIEW_STATUSES = {
    "DISCOVERED", "PRIMARY_CONFIRMED", "INDEPENDENTLY_CORROBORATED",
    "REVIEW_REQUIRED", "READY_FOR_EDITORIAL_VALIDATION", "REJECTED",
}


def validate_sources(sources, leads):
    lead_ids = {l["id"] for l in leads}
    seen, urls = set(), set()
    for item in sources:
        if (set(item) != {"id", "lead", "url", "role", "publisher",
                          "independence_verified"}
                or not isinstance(item["id"], str) or item["id"] in seen
                or item["lead"] not in lead_ids
                or not isinstance(item["publisher"], str)
                or not re.fullmatch(r"[a-z0-9-]{5,70}", item["publisher"])
                or not permitted_url(item["url"])
                or item["url"] in urls
                or not isinstance(item["independence_verified"], bool)):
            raise ValueError("source de corroboration non conforme")
        seen.add(item["id"])
        urls.add(item["url"])
        if item["independence_verified"]:
            if (item["role"] not in INDEPENDENT_ROLES
                    or item["publisher"] == PRIMARY_PUBLISHERS[item["lead"]]):
                raise ValueError("indépendance non démontrée")
    return True


def choose_checks(sources, last_attempted, today, limit=MAX_CHECKS):
    """Oldest attempt first; never retry a source twice on the same day."""
    if not isinstance(last_attempted, dict) or not 0 <= limit <= MAX_CHECKS:
        raise ValueError("budget de vérification invalide")
    now = date.fromisoformat(today)
    possible = []
    for src in sources:
        previous = last_attempted.get(src["id"])
        if previous:
            try:
                when = date.fromisoformat(previous)
            except (ValueError, TypeError):
                when = now
            if when >= now:
                continue
            priority = (1, when.isoformat(), src["id"])
        else:
            priority = (0, "", src["id"])
        possible.append((priority, src))
    return [src for _, src in sorted(possible, key=lambda pair: pair[0])[:limit]]


def inspect_source(lead, html):
    """Explicit same-edition visible claim; a 2026 page proves no 2027 field."""
    text = visible_text(html)  # ignores script/style/hidden content
    identity = normalized(lead["name"])
    name_seen = re.search(r"(?<![a-z0-9])" + re.escape(identity)
                          + r"(?![a-z0-9])", text) is not None
    phrase = normalized(lead["date_phrase"])
    date_seen = (name_seen and lead["start_date"] is not None
                 and re.search(r"(?<![a-z0-9])" + re.escape(phrase)
                               + r"(?![a-z0-9])", text) is not None)
    # A cancellation is a review signal, not an independently verified fact.
    cancelled = bool(name_seen and re.search(
        re.escape(identity) + r".{0,75}\b2027\b.{0,75}\b(?:annule|annulee|reporte|reportee)\b",
        text))
    return {"name_seen": name_seen, "date_seen": bool(date_seen),
            "city_seen": bool(date_seen and normalized(lead["city_hint"]) in text),
            "possible_cancellation": cancelled,
            "text_sha256": sha256(text.encode("utf-8")).hexdigest()}


def valid_secondary(src, row, today):
    """Discard untrusted private state that does not match reviewed metadata."""
    if (not isinstance(row, dict)
            or row.get("status") != RECORD_STATUS
            or row.get("publication_authorized") is not False
            or any(row.get(key) != src[field] for key, field in (
                ("source_id", "id"), ("lead_id", "lead"),
                ("url", "url"), ("publisher", "publisher"),
                ("role", "role"), ("independence_verified", "independence_verified")))
            or not all(isinstance(row.get(k), bool) for k in (
                "name_seen", "date_seen", "city_seen", "possible_cancellation"))
            or (row["date_seen"] and not row["name_seen"])
            or (row["city_seen"] and not row["date_seen"])
            or not isinstance(row.get("text_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["text_sha256"])):
        return False
    try:
        checked = date.fromisoformat(row["observed_at"])
        now = date.fromisoformat(today)
        return 0 <= (now - checked).days <= MAX_AGE_DAYS
    except (KeyError, ValueError, TypeError):
        return False


def scan(state, leads, today, fetch=get_page, limit=MAX_CHECKS, sources=SOURCES):
    validate_sources(sources, leads)
    if not isinstance(state, dict) or state.get("schema") != "grossesondes.source-watch.v1":
        raise ValueError("état privé invalide")
    attempts = state.setdefault("curated_corroboration_last_attempted", {})
    observed = state.setdefault("curated_corroboration_observations", {})
    if not isinstance(attempts, dict) or not isinstance(observed, dict):
        raise ValueError("historique de corroboration invalide")
    allowed = {src["id"] for src in sources}
    for key in list(attempts):
        if key not in allowed:
            del attempts[key]
    for key in list(observed):
        if key not in allowed:
            del observed[key]
    lead_by_id = {row["id"]: row for row in leads}
    outcomes = []
    for source in choose_checks(sources, attempts, today, limit):
        sid = source["id"]
        result = {"source_id": sid, "lead_id": source["lead"], "status": "INACCESSIBLE",
                  "publication_authorized": False}
        try:
            html = fetch(source["url"])
            proof = inspect_source(lead_by_id[source["lead"]], html)
            entry = {
                "status": RECORD_STATUS, "source_id": sid,
                "lead_id": source["lead"], "url": source["url"],
                "role": source["role"], "publisher": source["publisher"],
                "independence_verified": source["independence_verified"],
                "observed_at": today, **proof,
                "publication_authorized": False,
            }
            observed[sid] = entry
            result["status"] = ("DATE_CLAIM_VISIBLE" if proof["date_seen"]
                                else "NO_CURRENT_DATE_CLAIM")
            if proof["possible_cancellation"]:
                result["status"] = "POSSIBLE_CANCELLATION_REVIEW"
        except (OSError, ValueError, UnicodeError, TypeError):
            observed.pop(sid, None)  # failure must not preserve prior positive evidence
        attempts[sid] = today
        outcomes.append(result)
    return outcomes


def build_report(leads, state, published, today, sources=SOURCES):
    """Per-field source attribution, independent publisher groups, no approval."""
    validate_sources(sources, leads)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or not isinstance(published, dict)
            or not isinstance(published.get("festivals"), list)):
        raise ValueError("entrées de corroboration non conformes")
    primary = state.get("curated_future_lead_observations", {})
    secondary = state.get("curated_corroboration_observations", {})
    if not isinstance(primary, dict) or not isinstance(secondary, dict):
        raise ValueError("preuves privées invalides")
    dossiers = []
    for lead in leads:
        pid = lead["id"]
        first = primary.get(pid)
        primary_ok = valid_observation(lead, first, today)
        primary_provenance = ([{"url": lead["source_url"],
                               "publisher": PRIMARY_PUBLISHERS[pid],
                               "observed_at": first["lastSeen"],
                               "kind": "PRIMARY"}] if primary_ok else [])
        dated = lead["start_date"] is not None
        date_evidence = list(primary_provenance) if dated else []
        same_publisher, independent = [], []
        possible_cancellation = False
        checked = 0
        for src in sources:
            if src["lead"] != pid:
                continue
            row = secondary.get(src["id"])
            if not valid_secondary(src, row, today):
                continue
            checked += 1
            possible_cancellation |= row["possible_cancellation"]
            if not row["date_seen"] or not dated:
                continue
            witness = {"url": src["url"], "publisher": src["publisher"],
                       "observed_at": row["observed_at"], "kind": src["role"],
                       "independent_publisher_verified": src["independence_verified"]}
            date_evidence.append(witness)
            if (src["independence_verified"]
                    and src["publisher"] != PRIMARY_PUBLISHERS[pid]
                    and src["role"] in INDEPENDENT_ROLES):
                independent.append(witness)
            else:
                same_publisher.append(witness)
        duplicate = published_duplicate(lead, published)
        if duplicate:
            status = "REVIEW_REQUIRED"
        elif possible_cancellation:
            status = "REVIEW_REQUIRED"
        elif not primary_ok or not dated:
            status = "DISCOVERED"
        elif independent:
            status = "INDEPENDENTLY_CORROBORATED"
        else:
            status = "PRIMARY_CONFIRMED"
        assert status in REVIEW_STATUSES
        blockers = ["editorial_signoff", "venue_for_edition", "organizer_identity",
                    "geographic_coordinates", "duplicate_review"]
        if not primary_ok:
            blockers.append("primary_observation_missing_or_stale")
        if not dated:
            blockers.append("exact_edition_dates_missing")
        if not independent:
            blockers.append("independent_date_corroboration_missing")
        if possible_cancellation:
            blockers.append("possible_cancellation_manual_review")
        if duplicate:
            blockers.append("already_in_public_catalogue")
        dossiers.append({
            "id": pid, "name_hint": lead["name"], "candidate_status": status,
            "publication_authorized": False, "safe_to_publish": False,
            "independent_date_corroboration": bool(primary_ok and dated and independent),
            "same_publisher_date_repeats": len(same_publisher),
            "secondary_sources_observed": checked,
            "potential_cancellation": possible_cancellation,
            "field_provenance": {
                "name": {"status": "PRIMARY_ONLY" if primary_ok else "UNCONFIRMED",
                         "sources": primary_provenance},
                "start_date": {"status": "CORROBORATED" if primary_ok and independent
                               else "PRIMARY_ONLY" if primary_ok and dated else "UNCONFIRMED",
                               "value_hint": lead["start_date"], "sources": date_evidence},
                "end_date": {"status": "CORROBORATED" if primary_ok and independent
                             else "PRIMARY_ONLY" if primary_ok and dated else "UNCONFIRMED",
                             "value_hint": lead["end_date"], "sources": date_evidence},
                "city": {"status": "HINT_ONLY", "value_hint": lead["city_hint"], "sources": []},
                "venue": {"status": "UNCONFIRMED", "sources": []},
                "organizer": {"status": "UNCONFIRMED", "sources": []},
                "lineup": {"status": "UNCONFIRMED", "sources": []},
                "ticketing": {"status": "UNCONFIRMED", "sources": []},
                "coordinates": {"status": "UNCONFIRMED", "sources": []},
            },
            "missing_checks": blockers,
        })
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "safe_to_publish": False, "publication_authorized_count": 0,
        "public_catalogue_editions_at_review": len(published["festivals"]),
        "total": len(dossiers),
        "independently_corroborated_count": sum(
            row["independent_date_corroboration"] for row in dossiers),
        "dossiers": dossiers,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    leads = load_leads(json.loads(Path(__file__).with_name(
        "curated_future_leads.json").read_text(encoding="utf-8")))
    pages, git = get_json(PAGES), get_json(GIT)
    if pages != git:
        raise ValueError("catalogue public divergent, corroboration interrompue")
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if (report.get("schema") != "grossesondes.source-watch-report.v1"
            or report.get("date") != today):
        raise ValueError("rapport d'exécution incohérent")
    outcomes = scan(state, leads, today, limit=args.limit)
    dossier = build_report(leads, state, git, today)
    # Purely private append-only research state; no public catalogue edits.
    (args.intake / "curated-multi-source-review.json").write_text(
        json.dumps(dossier, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["curated_corroboration_attempts_private"] = len(outcomes)
    report["curated_corroboration_independent_private"] = dossier[
        "independently_corroborated_count"]
    report["curated_corroboration_results_private"] = outcomes
    report["curated_corroboration_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("CORROBORATION_FESTIVALS_PRIVEE:", json.dumps({
        "attempts": len(outcomes), "independent": dossier[
            "independently_corroborated_count"], "published": 0,
        "statuses": {r["id"]: r["candidate_status"] for r in dossier["dossiers"]},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
