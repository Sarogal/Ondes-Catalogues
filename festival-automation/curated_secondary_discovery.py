"""Discover private candidate secondary sources on reviewed regional agenda indexes.

A link printed by a municipal/tourism website is NOT automatically an
independent confirmation. Dynamic links are fetched ONLY if re-discovered in
a fresh index scan AND also appeared in a previous day's private queue.
All output is private, explicitly unverified and never a catalogue patch.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from curated_future_lead_watch import load_leads
from curated_corroboration import inspect_source
from official_watch import get_json, get_page, PAGES, GIT
from regional_festival_discovery import load_indexes, APPROVED
from source_qualification import Anchors, clean_url, normalized

SCHEMA = "grossesondes.secondary-source-discovery.v1"
STATUS = "UNVERIFIED_INSTITUTIONAL_INDEX_CANDIDATE"
MAX_INDEX_CHECKS = 2
MAX_DETAIL_CHECKS = 1
MAX_LINKS_PER_INDEX = 5
MAX_RECORDS_PER_LEAD = 6
MAX_AGE_DAYS = 30
EXCLUDED = re.compile(r"\.(?:pdf|jpe?g|png|svg|zip|webp|gif|ics)$", re.I)
YEAR = re.compile(r"(?<!\d)20[2-4]\d(?!\d)")


def same_host(a, b):
    return urlsplit(a).hostname == urlsplit(b).hostname


def discover_links(html, index_url, leads, approved=APPROVED):
    """Only visible named 2027 anchors with a 2027 detail URL on same host."""
    if index_url not in approved or not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("index regional non approuve")
    parser = Anchors()
    parser.feed(html)
    region = approved[index_url]
    found, seen = [], set()
    for raw, label, _prefix in parser.anchors[:650]:
        if not isinstance(raw, str) or not isinstance(label, str):
            continue
        title = " ".join(label.split())[:160]
        name = normalized(title)
        years = set(YEAR.findall(name))
        if years != {"2027"}:
            continue
        try:
            url = urljoin(index_url, raw)
            parsed = urlsplit(url)
        except (ValueError, TypeError):
            continue
        if (parsed.query or parsed.fragment or not same_host(url, index_url)
                or "2027" not in parsed.path or EXCLUDED.search(parsed.path)
                or parsed.path == urlsplit(index_url).path
                or clean_url(url) != url or len(url) > 500):
            continue
        for lead in leads:
            if region != "FRANCE" and lead["region_hint"] != region:
                continue
            identity = normalized(lead["name"])
            if (not 7 <= len(identity) <= 110
                    or re.search(r"(?<![a-z0-9])" + re.escape(identity)
                                 + r"(?![a-z0-9])", name) is None):
                continue
            pair = lead["id"], url
            if pair not in seen:
                seen.add(pair)
                found.append({"lead_id": lead["id"], "candidate_url": url,
                              "index_url": index_url, "region": region,
                              "label": title})
            if len(found) >= MAX_LINKS_PER_INDEX:
                return found
    return found


def clean_queue(queue, leads, indexes, today, approved=APPROVED):
    """Never trust private JSON as a list of fetch destinations."""
    if not isinstance(queue, dict):
        raise ValueError("file secondaire invalide")
    now = date.fromisoformat(today)
    lead_map = {l["id"]: l for l in leads}
    valid_origins = {s["url"] for s in indexes}
    result = {}
    for key, rows in list(queue.items())[:32]:
        if key not in lead_map or not isinstance(rows, list):
            continue
        kept = []
        for row in rows[:MAX_RECORDS_PER_LEAD * 3]:
            if not isinstance(row, dict) or row.get("lead_id") != key:
                continue
            src, index = row.get("candidate_url"), row.get("index_url")
            if (not isinstance(src, str) or not isinstance(index, str)
                    or index not in valid_origins
                    or (approved.get(index) not in ("FRANCE", lead_map[key]["region_hint"]))
                    or not same_host(src, index)
                    or clean_url(src) != src or len(src) > 500
                    or urlsplit(src).query or urlsplit(src).fragment
                    or "2027" not in urlsplit(src).path
                    or EXCLUDED.search(urlsplit(src).path)
                    or row.get("status") != STATUS
                    or row.get("publication_authorized") is not False
                    or row.get("independence_verified") is not False):
                continue
            try:
                first = date.fromisoformat(row["firstSeen"])
                last = date.fromisoformat(row["lastSeen"])
            except (KeyError, ValueError, TypeError):
                continue
            if not (first <= last <= now and (now - last).days <= MAX_AGE_DAYS):
                continue
            safe = {
                "lead_id": key, "candidate_url": src, "index_url": index,
                "region": approved[index], "firstSeen": first.isoformat(),
                "lastSeen": last.isoformat(), "status": STATUS,
                "publication_authorized": False, "independence_verified": False,
            }
            # Details are never carried as trusted automatically corroborated fields.
            # Even a stored matching claim is only an unverified observation.
            detail_date = row.get("detail_observed_at")
            digest = row.get("detail_text_sha256")
            if (isinstance(detail_date, str) and isinstance(digest, str)
                    and re.fullmatch(r"[0-9a-f]{64}", digest)
                    and all(type(row.get(k)) is bool for k in
                            ("detail_name_seen", "detail_date_seen",
                             "detail_possible_cancellation"))):
                try:
                    checked = date.fromisoformat(detail_date)
                    if first <= checked <= now and (now - checked).days <= 7:
                        safe.update({
                            "detail_observed_at": checked.isoformat(),
                            "detail_text_sha256": digest,
                            "detail_name_seen": row["detail_name_seen"],
                            "detail_date_seen": row["detail_date_seen"],
                            "detail_possible_cancellation": row[
                                "detail_possible_cancellation"],
                        })
                except ValueError:
                    pass
            if src not in {record["candidate_url"] for record in kept}:
                kept.append(safe)
        if kept:
            result[key] = kept[-MAX_RECORDS_PER_LEAD:]
    return result


def choose_indexes(indexes, leads, attempts, today, limit=MAX_INDEX_CHECKS):
    if (not isinstance(attempts, dict)
            or not 0 <= limit <= MAX_INDEX_CHECKS):
        raise ValueError("budget d'index secondaires invalide")
    now = date.fromisoformat(today)
    regions = {lead["region_hint"] for lead in leads}
    possible = []
    for source in indexes:
        if source["region"] not in regions and source["region"] != "FRANCE":
            continue
        checked = attempts.get(source["url"], "")
        if checked:
            try:
                previous = date.fromisoformat(checked)
            except (TypeError, ValueError):
                continue
            if previous >= now:
                continue
        possible.append(((bool(checked), checked, source["region"],
                          source["id"]), source))
    possible.sort(key=lambda x: x[0])
    return [source for _, source in possible[:limit]]


def scan(state, leads, indexes, today, fetch=get_page,
         limit=MAX_INDEX_CHECKS, detail_limit=MAX_DETAIL_CHECKS,
         approved=APPROVED, attempts_key="secondary_index_last_attempted",
         queue_indexes=None):
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or not 0 <= detail_limit <= MAX_DETAIL_CHECKS):
        raise ValueError("etat ou budget de collecte incorrect")
    if attempts_key not in ("secondary_index_last_attempted",
                            "secondary_targeted_index_last_attempted"):
        raise ValueError("historique secondaire non approuve")
    if any(row["url"] not in approved or approved[row["url"]] != row["region"]
           for row in indexes):
        raise ValueError("index hors liste autorisee")
    attempts = state.setdefault(attempts_key, {})
    if not isinstance(attempts, dict):
        raise ValueError("historique secondaire incorrect")
    valid_indexes = {r["url"] for r in indexes}
    for key in list(attempts):
        if key not in valid_indexes:
            del attempts[key]
    queue = clean_queue(state.get("secondary_source_candidates_private", {}),
                        leads, queue_indexes if queue_indexes is not None else indexes,
                        today, approved=approved)
    by_lead = {lead["id"]: lead for lead in leads}
    outcomes, newly_found, details_attempted = [], 0, 0
    for source in choose_indexes(indexes, leads, attempts, today, limit):
        origin = source["url"]
        result = {"index_url": origin, "status": "INACCESSIBLE",
                  "new_candidate_urls": 0, "detail_attempts": 0,
                  "publication_authorized": False}
        try:
            matches = discover_links(fetch(origin), origin, leads, approved=approved)
            result["status"] = "SCANNED"
            for match in matches:
                key, url = match["lead_id"], match["candidate_url"]
                records = queue.setdefault(key, [])
                old = next((rec for rec in records
                            if rec["candidate_url"] == url
                            and rec["index_url"] == origin), None)
                previous_date = old["firstSeen"] if old else today
                row = dict(old or {}, lead_id=key, candidate_url=url,
                           index_url=origin, region=source["region"],
                           firstSeen=previous_date, lastSeen=today,
                           status=STATUS, publication_authorized=False,
                           independence_verified=False)
                if old is None:
                    newly_found += 1
                    result["new_candidate_urls"] += 1
                # Recheck the current live index anchor before EVER requesting
                # the URL. A poisoned queue cannot add a destination by itself.
                if (old is not None and previous_date < today
                        and details_attempted < detail_limit
                        and old.get("detail_observed_at") != today):
                    details_attempted += 1
                    result["detail_attempts"] += 1
                    # Invalidate previous proof before attempting network access.
                    for k in ("detail_observed_at", "detail_text_sha256",
                              "detail_name_seen", "detail_date_seen",
                              "detail_possible_cancellation"):
                        row.pop(k, None)
                    try:
                        evidence = inspect_source(by_lead[key], fetch(url))
                        row.update({
                            "detail_observed_at": today,
                            "detail_text_sha256": evidence["text_sha256"],
                            "detail_name_seen": evidence["name_seen"],
                            "detail_date_seen": evidence["date_seen"],
                            "detail_possible_cancellation": evidence[
                                "possible_cancellation"],
                        })
                    except (OSError, ValueError, UnicodeError, TypeError):
                        result["detail_status"] = "INACCESSIBLE_OR_INVALID"
                if old is None:
                    records.append(row)
                else:
                    records[records.index(old)] = row
                queue[key] = records[-MAX_RECORDS_PER_LEAD:]
        except (OSError, ValueError, UnicodeError, TypeError):
            result["status"] = "INACCESSIBLE"
        attempts[origin] = today
        outcomes.append(result)
    state["secondary_source_candidates_private"] = queue
    return outcomes, newly_found, details_attempted


def build_review(state, leads, indexes, today, approved=APPROVED):
    queue = clean_queue(state.get("secondary_source_candidates_private", {}),
                        leads, indexes, today, approved=approved)
    rows = [dict(record) for lead in leads for record in queue.get(lead["id"], [])]
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "publication_authorized": False, "safe_to_publish": False,
        "independently_verified_count": 0,
        "candidate_sources_count": len(rows),
        "detail_claims_observed_count": sum(
            bool(r.get("detail_date_seen")) for r in rows),
        "sources": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=MAX_INDEX_CHECKS)
    parser.add_argument("--detail-limit", type=int, default=MAX_DETAIL_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    leads = load_leads(json.loads(Path(__file__).with_name(
        "curated_future_leads.json").read_text(encoding="utf-8")))
    config = json.loads(Path(__file__).with_name(
        "regional_festival_indexes.json").read_text(encoding="utf-8"))
    indexes = load_indexes(config)
    # Preserve target media/venue candidates during the preceding regional pass.
    from curated_targeted_secondary import validated_targets, APPROVED_ALL
    all_indexes = list(indexes) + validated_targets()
    pages, git = get_json(PAGES), get_json(GIT)
    if pages != git:
        raise ValueError("catalogues publics divergents : recherche suspendue")
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if (report.get("schema") != "grossesondes.source-watch-report.v1"
            or report.get("date") != today):
        raise ValueError("rapport de veille incompatible")
    outcomes, new, detailed = scan(
        state, leads, indexes, today, limit=args.limit,
        detail_limit=args.detail_limit, approved=APPROVED_ALL,
        queue_indexes=all_indexes)
    review = build_review(state, leads, all_indexes, today,
                          approved=APPROVED_ALL)
    (args.intake / "curated-secondary-sources-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["curated_secondary_indexes_attempted_private"] = len(outcomes)
    report["curated_secondary_candidates_new_private"] = new
    report["curated_secondary_candidates_pending_private"] = review[
        "candidate_sources_count"]
    report["curated_secondary_detail_attempts_private"] = detailed
    report["curated_secondary_independent_sources_verified_private"] = 0
    report["curated_secondary_publications"] = 0
    report["curated_secondary_results_private"] = outcomes
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("SOURCES_SECONDAIRES_FESTIVALS_PRIVEES:", json.dumps({
        "indexes": len(outcomes), "new": new,
        "pending": review["candidate_sources_count"],
        "details_attempted": detailed, "independently_verified": 0,
        "published": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
