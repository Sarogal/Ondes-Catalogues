"""Bounded, next-day qualification probes for dynamic national festival leads.

Only a live anchor on a reviewed regional index can authorize ONE same-host
detail request. State, previous JSON, arbitrary metadata, and page body links
cannot themselves authorize destinations. Never certifies dates, independence,
organizers or publications.
"""
import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from curated_future_lead_watch import visible_text
from national_discovery_queue import _identity, _recent, _safe_origin_link
from national_structured_clues import detail_event_clues, valid_clues
from official_watch import get_page
from regional_festival_discovery import (
    APPROVED, RegionalEventAnchors, municipal_event_title,
)
from source_qualification import normalized

SCHEMA = "grossesondes.national-detail-qualification-private.v1"
STATE_SCHEMA = "grossesondes.source-watch.v1"
QUEUE_SCHEMA = "grossesondes.national-festival-discovery-private.v1"
REPORT_SCHEMA = "grossesondes.source-watch-report.v1"
MAX_CHECKS = 1
MAX_DOSSIERS = 200
MAX_SOURCES_PER_DOSSIER = 12
MAX_AGE_DAYS = 30
MAX_OBSERVATION_DAYS = 7
MAX_ANCHORS = 650
YEAR_RE = re.compile(r"(?<![0-9])20[2-4][0-9](?![0-9])")


def _safe_queue(queue, today):
    if (not isinstance(queue, dict) or queue.get("schema") != QUEUE_SCHEMA
            or queue.get("as_of") != today
            or queue.get("publication_authorized") is not False
            or queue.get("safe_to_publish") is not False
            or queue.get("review_only") is not True
            or not isinstance(queue.get("dossiers"), list)
            or len(queue["dossiers"]) > MAX_DOSSIERS):
        raise ValueError("file nationale invalide")
    return queue["dossiers"]


def _eligible_sources(state, queue, today, due_only=True):
    dossiers = _safe_queue(queue, today)
    private_rows = state.get("regional_festival_candidates_review_only")
    attempts = state.get("national_detail_last_attempted_private", {})
    if not isinstance(private_rows, dict) or not isinstance(attempts, dict):
        raise ValueError("etats de qualification non conformes")
    now = date.fromisoformat(today)
    eligible, seen = [], set()
    for dossier in dossiers:
        if (not isinstance(dossier, dict)
                or dossier.get("publication_authorized") is not False
                or dossier.get("safe_to_publish") is not False
                or not isinstance(dossier.get("id"), str)
                or not isinstance(dossier.get("sources"), list)
                or len(dossier["sources"]) > MAX_SOURCES_PER_DOSSIER):
            continue
        year = dossier.get("edition_year_hint")
        if type(year) is not int or year < now.year or year > now.year + 2:
            continue  # Unknown edition years are NOT guessed.
        for source in dossier["sources"]:
            if (not isinstance(source, dict)
                    or source.get("kind") != "REGIONAL_INDEX_UNVERIFIED"
                    or source.get("publication_authorized") is not False):
                continue
            url, index = source.get("url"), source.get("discovered_via")
            if (not isinstance(url, str) or url in seen
                    or not isinstance(index, str) or index not in APPROVED
                    or not _safe_origin_link(url, index)
                    or dossier.get("region_hint") != APPROVED[index]):
                continue
            row = private_rows.get(url)
            if (not isinstance(row, dict)
                    or row.get("status") != "UNVERIFIED_THEME_LINK"
                    or row.get("publication_authorized") is not False
                    or row.get("candidate_url") != url
                    or row.get("source_index") != index
                    or row.get("region") != APPROVED[index]
                    or not isinstance(row.get("title"), str)
                    or not _recent(row.get("firstSeen"), row.get("lastSeen"), today)
                    or row["firstSeen"] >= today
                    or row["lastSeen"] < (now - timedelta(days=MAX_AGE_DAYS)).isoformat()):
                continue
            ident = _identity(row["title"])
            if (ident is None or ident[1] != year
                    or ident[0] != dossier.get("normalized_name")):
                continue
            # The index link cannot be changed by private state alone.
            if (source.get("firstSeen") != row["firstSeen"]
                    or source.get("lastSeen") != row["lastSeen"]):
                continue
            last = attempts.get(url, {})
            if not isinstance(last, dict):
                continue
            previous = last.get("lastAttempted")
            if previous is not None:
                try:
                    day = date.fromisoformat(previous)
                except (ValueError, TypeError):
                    continue
                if day > now:
                    continue
                if due_only and day == now:
                    continue
                if (due_only and last.get("status") in (
                    "INDEX_UNAVAILABLE", "DETAIL_UNAVAILABLE",
                    "INDEX_LINK_NOT_FOUND") and (now - day).days < 2):
                    continue
            seen.add(url)
            priority = ((previous is not None), previous or "", dossier["id"], url)
            eligible.append((priority, {
                "dossier_id": dossier["id"], "url": url, "index_url": index,
                "title": row["title"], "year": year,
            }))
    eligible.sort(key=lambda x: x[0])
    return [source for _, source in eligible]


def _seen_again(index_html, source):
    """The exact destination and identity must reappear in today's live index.

    Reuse the regional discovery parser: municipality event titles may be
    carried by a strictly recognized aria-label while the anchor is a generic
    "En savoir plus". A different visible title must never be overridden.
    """
    if not isinstance(index_html, str) or len(index_html) > 650_000:
        raise ValueError("index HTML inexploitable")
    parser = RegionalEventAnchors()
    parser.feed(index_html)
    expected = normalized(source["title"])
    for href, label, _prefix in parser.anchors[:MAX_ANCHORS]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        # The discovery step strips this *exact* municipal navigation prefix.
        # Do the same here; a specific visible title never gets overridden.
        event_title = municipal_event_title(label)
        title = event_title if event_title is not None else " ".join(label.split())[:160]
        if normalized(title) != expected:
            continue
        try:
            url = urljoin(source["index_url"], href)
        except (TypeError, ValueError):
            continue
        if url == source["url"] and _safe_origin_link(url, source["index_url"]):
            return True
    return False


def _inspect_detail(html, source, today):
    """Detect visible same-edition clues, never extract certified event fields."""
    text = visible_text(html)
    identity = _identity(source["title"])[0]
    matched = re.search(r"(?<![a-z0-9])" + re.escape(identity)
                        + r"(?![a-z0-9])", text)
    name_seen = matched is not None
    year_near_name = False
    cancellation_hint = False
    if name_seen:
        local = text[max(0, matched.start()-85):matched.end()+180]
        year_near_name = str(source["year"]) in set(YEAR_RE.findall(local))
        cancellation_hint = bool(year_near_name and re.search(
            r"\b(?:annule|annulee|report|reporte|reportee|decale)\b", local))
    return {
        "dossier_id": source["dossier_id"],
        "candidate_url": source["url"], "index_url": source["index_url"],
        "name_hint": source["title"], "edition_year_hint": source["year"],
        "observed_at": today, "name_seen": name_seen,
        "edition_year_near_name": year_near_name,
        "possible_cancellation_review_only": cancellation_hint,
        "visible_text_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "structured_event_clues_private": detail_event_clues(html, source, text),
        "date_claim_verified": False,
        "festival_verified": False, "organizer_verified": False,
        "independence_verified": False,
        "publication_authorized": False,
        "status": ("NAME_YEAR_VISIBLE_REVIEW_ONLY" if name_seen and year_near_name
                   else "DETAIL_INCONCLUSIVE_REVIEW_ONLY"),
    }


def _valid_observation(source, row, today):
    if (not isinstance(row, dict) or row.get("dossier_id") != source["dossier_id"]
            or row.get("candidate_url") != source["url"]
            or row.get("index_url") != source["index_url"]
            or row.get("name_hint") != source["title"]
            or row.get("edition_year_hint") != source["year"]
            or row.get("status") not in (
                "NAME_YEAR_VISIBLE_REVIEW_ONLY", "DETAIL_INCONCLUSIVE_REVIEW_ONLY")
            or row.get("date_claim_verified") is not False
            or row.get("festival_verified") is not False
            or row.get("organizer_verified") is not False
            or row.get("independence_verified") is not False
            or row.get("publication_authorized") is not False
            or type(row.get("name_seen")) is not bool
            or type(row.get("edition_year_near_name")) is not bool
            or type(row.get("possible_cancellation_review_only")) is not bool
            or (row["edition_year_near_name"] and not row["name_seen"])
            or row.get("status") != (
                "NAME_YEAR_VISIBLE_REVIEW_ONLY" if
                row["name_seen"] and row["edition_year_near_name"]
                else "DETAIL_INCONCLUSIVE_REVIEW_ONLY")
            or not isinstance(row.get("visible_text_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["visible_text_sha256"])
            or not valid_clues(row.get("structured_event_clues_private", []),
                               source, row["name_seen"])):
        return False
    try:
        when, now = date.fromisoformat(row["observed_at"]), date.fromisoformat(today)
        return 0 <= (now-when).days <= MAX_OBSERVATION_DAYS
    except (TypeError, ValueError):
        return False


def scan(state, queue, today, fetch=get_page, limit=MAX_CHECKS):
    if (not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("etat ou budget national invalide")
    sources = _eligible_sources(state, queue, today)
    history = state.setdefault("national_detail_last_attempted_private", {})
    observations = state.setdefault("national_detail_observations_private", {})
    if not isinstance(observations, dict):
        raise ValueError("observations nationales invalides")
    # Never turn persisted URLs into network targets, even when stored previously.
    live_keys = {entry["url"] for entry in _eligible_sources(
        state, queue, today, due_only=False)}
    for url in list(observations):
        if url not in live_keys or not isinstance(observations[url], dict):
            del observations[url]
    outcomes = []
    for source in sources[:limit]:
        url = source["url"]
        status = "INDEX_UNAVAILABLE"
        observations.pop(url, None)  # Failed rechecks cannot preserve positives.
        try:
            html = fetch(source["index_url"])
            if not _seen_again(html, source):
                status = "INDEX_LINK_NOT_FOUND"
            else:
                status = "DETAIL_UNAVAILABLE"
                try:
                    details = fetch(url)
                    observation = _inspect_detail(details, source, today)
                    observations[url] = observation
                    status = observation["status"]
                except (OSError, ValueError, UnicodeError, TypeError):
                    pass
        except (OSError, ValueError, UnicodeError, TypeError):
            pass
        history[url] = {"lastAttempted": today, "status": status}
        outcomes.append({
            "candidate_url": url, "index_url": source["index_url"],
            "dossier_id": source["dossier_id"], "status": status,
            "publication_authorized": False,
        })
    return outcomes


def build_review(state, queue, today):
    """Only recent matching observations can enter a report, never an approval."""
    _safe_queue(queue, today)
    observations = state.get("national_detail_observations_private", {})
    if not isinstance(observations, dict):
        raise ValueError("preuves details corrompues")
    valid_sources = _eligible_sources(state, queue, today, due_only=False)
    rows = []
    for source in valid_sources:
        proof = observations.get(source["url"])
        if _valid_observation(source, proof, today):
            rows.append(dict(proof))
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "publication_authorized": False, "safe_to_publish": False,
        "network_budget_index_and_detail_pairs": MAX_CHECKS,
        "observations_count": len(rows),
        "name_year_visible_count": sum(
            x["status"] == "NAME_YEAR_VISIBLE_REVIEW_ONLY" for x in rows),
        "structured_event_clues_count": sum(
            len(x.get("structured_event_clues_private", [])) for x in rows),
        "structured_event_visible_start_count": sum(
            h["start_date_visible_near_name"] for x in rows
            for h in x.get("structured_event_clues_private", [])),
        "qualified_source_count": 0, "publications": 0,
        "observations": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    queue = json.loads((args.intake / "national-festival-discovery-review.json")
                       .read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("schema") != REPORT_SCHEMA or report.get("date") != today:
        raise ValueError("rapport national incompatible")
    outcomes = scan(state, queue, today, limit=args.limit)
    review = build_review(state, queue, today)
    (args.intake / "national-festival-detail-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["national_detail_attempts_private"] = len(outcomes)
    report["national_detail_name_year_clues_private"] = review["name_year_visible_count"]
    report["national_detail_observations_private"] = review["observations_count"]
    report["national_detail_sources_qualified_private"] = 0
    report["national_detail_structured_clues_private"] = review["structured_event_clues_count"]
    report["national_detail_visible_date_clues_private"] = review["structured_event_visible_start_count"]
    report["national_detail_publications"] = 0
    report["national_detail_outcomes_private"] = outcomes
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("QUALIFICATION_NATIONALE_PRIVEE:", json.dumps({
        "index_detail_pairs_attempted": len(outcomes),
        "observations": review["observations_count"],
        "name_year_visible": review["name_year_visible_count"],
        "structured_clues": review["structured_event_clues_count"],
        "visible_start_clues": review["structured_event_visible_start_count"],
        "qualified": 0, "published": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
