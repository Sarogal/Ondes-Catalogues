"""One reviewed institution/organizer comparison on existing *public* runners.

Editorially pinned URLs, historical identity and exact future event dates are
immutable code configuration. Scraped HTML or private state NEVER selects HTTP
destinations. Institutional syndication is not proof of independent reporting.
All output is review-only, confined to the existing private intake branch.
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
from regional_festival_discovery import HISTORY_GIT, HISTORY_PAGES
from source_qualification import matches_date, normalized

STATE_SCHEMA = "grossesondes.source-watch.v1"
REPORT_SCHEMA = "grossesondes.source-watch-report.v1"
STATUS = "INSTITUTIONAL_DATE_CLAIM_UNVERIFIED"
MAX_CHECKS = 1
MAX_AGE_DAYS = 7
MAX_HISTORY = 500

# Exact event, source and archived-identity pairing reviewed on 2026-11-09.
# Separate hostnames alone do not mean independent journalism; infolocale
# reports the same DATAtourisme provider used by multiple syndication sites.
SOURCES = {
    "mauges-pit-fest": {
        "name": "Mauges Pit Fest",
        "region": "Pays de la Loire",
        "archive_year": 2026,
        "official_home": "https://maugespitfest.fr/",
        "institutional_url": (
            "https://www.infolocale.fr/evenements/"
            "evenement-sevremoine-festival-mauges-pit-fest-2006186681"
        ),
        "start": "2027-10-08",
        "end": "2027-10-09",
        "city": "Saint-Macaire-en-Mauges",
        "venue": "Salle Thomas Dupouet",
        "provider": "Pôle Tourisme ôsezMauges",
        "organizer": "Association Mac’N’Roll Metallicus",
    },
}


def _approved_history(history, today):
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)
            or len(history["knownFestivals"]) > MAX_HISTORY):
        raise ValueError("historique de festivals non conforme")
    now = date.fromisoformat(today)
    found = {}
    for row in history["knownFestivals"]:
        if not isinstance(row, dict):
            raise ValueError("archive historique non conforme")
        slug = row.get("slug")
        if slug not in SOURCES:
            continue
        if slug in found:
            raise ValueError("identité historique dupliquée")
        expected = SOURCES[slug]
        try:
            first = date.fromisoformat(row["startDate"])
            end = date.fromisoformat(row["endDate"])
        except (TypeError, KeyError, ValueError):
            raise ValueError("dates historiques altérées") from None
        if (row.get("name") != expected["name"]
                or row.get("region") != expected["region"]
                or row.get("officialSite") != expected["official_home"]
                or normalized(row.get("organizer")) != normalized(expected["organizer"])
                or type(row.get("lastKnownYear")) is not int
                or row["lastKnownYear"] != expected["archive_year"]
                or not first <= end < now or end.year != expected["archive_year"]):
            raise ValueError("référence historique divergente")
        found[slug] = expected
    if set(found) != set(SOURCES):
        raise ValueError("référence historique absente")
    for source in found.values():
        if (not permitted_url(source["institutional_url"])
                or not permitted_url(source["official_home"])
                or date.fromisoformat(source["start"]).year <= now.year
                or date.fromisoformat(source["end"]).year
                != date.fromisoformat(source["start"]).year):
            raise ValueError("source ou calendrier cible non autorisé")
    return found


def load_sources(today, fetch_json=get_json):
    """If Pages and raw Git differ, refuse network requests to any sources."""
    try:
        one, two = fetch_json(HISTORY_PAGES), fetch_json(HISTORY_GIT)
        if one != two:
            return {}, "DIVERGENT"
        return _approved_history(one, today), "CONSISTENT"
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {}, "UNAVAILABLE_OR_INVALID"


def _exact_dates_near_name(html, source):
    """Visible named-event matching, with a strict bounded grammar for two dates.

    Supports '08/10/2027', '8 octobre 2027', and compact range
    'vendredi 8, samedi 9 octobre 2027'. Never lifts other 2027 events' dates.
    """
    text = _archive_visible_text(html)
    name = normalized(source["name"])
    dates = (date.fromisoformat(source["start"]),
             date.fromisoformat(source["end"]))
    hits = []
    # Date headers may be directly *above* the event title.
    for occurrence in list(re.finditer(
            r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", text))[:20]:
        local = text[max(0, occurrence.start()-170):occurrence.end()+1100]
        trailing = text[occurrence.end():occurrence.end()+250]
        first_year = re.search(r"(?<![0-9])20[2-4][0-9](?![0-9])", trailing)
        if first_year and int(first_year.group(0)) != dates[0].year:
            # Mauges Pit Fest 2026 followed by *another* festival's 2027
            # programme is not Mauges Pit Fest VI corroboration.
            continue
        if first_year and re.search(
                r"\b(?:autre festival|another festival|autre evenement)\b",
                trailing[:first_year.start()]):
            continue
        start = matches_date(local, dates[0].isoformat())
        end = matches_date(local, dates[1].isoformat())
        # Date range with a shared month and year plus weekday labels.
        span = (rf"(?<![0-9])0?{dates[0].day}"
                rf"(?: (?:et|au|a|vendredi|samedi|dimanche|lundi|mardi|mercredi|jeudi))*"
                rf" 0?{dates[1].day} octobre {dates[1].year}(?![0-9])")
        shared = re.search(span, local) is not None
        if (start and end) or shared:
            hits.append(local)
            break
    if not hits:
        return None
    context = hits[0]
    city = normalized(source["city"]) in context
    venue = normalized(source["venue"]) in context
    # Page content supports a *claim*, never location/ownership verification.
    return {
        "start_date_hint": dates[0].isoformat(),
        "end_date_hint": dates[1].isoformat(),
        "city_name_hint": source["city"] if city else None,
        "venue_name_hint": source["venue"] if venue else None,
        "visible_text_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


def _organizer_visible_on_home(html, source):
    """Explicit current-site organizer phrase; never proof of the 2027 edition.

    Read only the visible body of the already fetched, pinned first-party URL.
    Exact expected wording is manually reviewed, not supplied by private state.
    """
    if source != SOURCES["mauges-pit-fest"]:
        return False
    text = _archive_visible_text(html)
    expected = "association mac n roll metallicus presente le mauges pit fest"
    return re.search(r"(?<![a-z0-9])" + re.escape(expected) +
                     r"(?![a-z0-9])", text) is not None


def _recent(start, end, today):
    try:
        first, last, now = (
            date.fromisoformat(start), date.fromisoformat(end),
            date.fromisoformat(today))
        return first <= last <= now and (now-last).days <= MAX_AGE_DAYS
    except (TypeError, ValueError):
        return False


def validated_observations(state, today):
    """Treat persisted observations as untrusted; constrain every field."""
    raw = state.get("institutional_future_date_observations_private", {})
    if not isinstance(raw, dict) or len(raw) > 50:
        raise ValueError("état des pistes institutionnelles altéré")
    result = []
    for slug, row in raw.items():
        if slug not in SOURCES or not isinstance(row, dict):
            continue
        source = SOURCES[slug]
        if (row.get("name_hint") != source["name"]
                or row.get("region_hint") != source["region"]
                or row.get("institutional_url") != source["institutional_url"]
                or row.get("official_home") != source["official_home"]
                or row.get("start_date_hint") != source["start"]
                or row.get("end_date_hint") != source["end"]
                or row.get("city_name_hint") not in (None, source["city"])
                or row.get("venue_name_hint") not in (None, source["venue"])
                or row.get("status") != STATUS
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False
                or row.get("festival_verified") is not False
                or row.get("edition_dates_verified") is not False
                or row.get("independence_verified") is not False
                or row.get("organizer_verified") is not False
                or type(row.get("first_party_current_date_match")) is not bool
                or type(row.get("organizer_name_visible_on_home_review_only", False)) is not bool
                or row.get("provider_claim") != source["provider"]
                or not _recent(row.get("firstSeen"), row.get("lastSeen"), today)
                or not isinstance(row.get("visible_text_sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}",
                                row["visible_text_sha256"]) is None):
            continue
        result.append({
            "slug": slug, "name": source["name"],
            "region": source["region"],
            "institutional_url": source["institutional_url"],
            "official_home": source["official_home"],
            "start": source["start"], "end": source["end"],
            "city": row["city_name_hint"],
            "venue": row["venue_name_hint"],
            "first": row["firstSeen"], "last": row["lastSeen"],
            "primary_same_dates": row["first_party_current_date_match"],
            "organizer_name_on_home_review_only": (
                source["organizer"] if row.get("organizer_name_visible_on_home_review_only", False)
                else None),
            "provider": source["provider"],
        })
    return sorted(result, key=lambda x: x["slug"])


def scan(state, sources, today, fetch=get_page, limit=MAX_CHECKS):
    if (not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA
            or not isinstance(sources, dict) or len(sources) > MAX_CHECKS
            or any(slug not in SOURCES or value != SOURCES[slug]
                   for slug, value in sources.items())
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("configuration de surveillance non conforme")
    checks = state.setdefault("institutional_future_checks_private", {})
    observations = state.setdefault("institutional_future_date_observations_private", {})
    if not isinstance(checks, dict) or not isinstance(observations, dict):
        raise ValueError("historique institutionnel altéré")
    outcomes = []
    for slug, source in sorted(sources.items())[:limit]:
        previous = checks.get(slug, {})
        if not isinstance(previous, dict):
            raise ValueError("historique de passage invalide")
        when = previous.get("lastAttempted")
        if when:
            try:
                checked = date.fromisoformat(when)
            except (TypeError, ValueError):
                raise ValueError("date de passage invalide") from None
            if checked >= date.fromisoformat(today):
                if checked > date.fromisoformat(today):
                    raise ValueError("horodatage futur")
                continue  # one attempt per festival per day
        observations.pop(slug, None)
        first_party = False
        organizer_visible = False
        official_status = "NOT_FETCHED"
        inst_status = "UNAVAILABLE"
        try:
            # First-party site is *allowed* but may still advertise 2026.
            primary_html = fetch(source["official_home"])
            first_party = _exact_dates_near_name(primary_html, source) is not None
            organizer_visible = _organizer_visible_on_home(primary_html, source)
            official_status = ("SAME_DATE_VISIBLE_UNVERIFIED"
                               if first_party else "FUTURE_DATE_NOT_VISIBLE")
        except (OSError, ValueError, UnicodeError, TypeError):
            official_status = "UNAVAILABLE"
        candidate = None
        try:
            candidate = _exact_dates_near_name(
                fetch(source["institutional_url"]), source)
            inst_status = ("FUTURE_DATE_VISIBLE_UNVERIFIED"
                           if candidate else "DATE_NOT_VISIBLE")
        except (OSError, ValueError, UnicodeError, TypeError):
            inst_status = "UNAVAILABLE"
        if candidate:
            previous_first = (previous.get("firstSeen")
                              if previous.get("candidate_seen") is True
                              else None)
            first = previous_first if _recent(
                previous_first, today, today) else today
            observations[slug] = {
                "name_hint": source["name"],
                "region_hint": source["region"],
                "institutional_url": source["institutional_url"],
                "official_home": source["official_home"],
                "start_date_hint": candidate["start_date_hint"],
                "end_date_hint": candidate["end_date_hint"],
                "city_name_hint": candidate["city_name_hint"],
                "venue_name_hint": candidate["venue_name_hint"],
                "visible_text_sha256": candidate["visible_text_sha256"],
                "firstSeen": first, "lastSeen": today,
                "first_party_current_date_match": first_party,
                "organizer_name_visible_on_home_review_only": organizer_visible,
                "provider_claim": source["provider"],
                "status": STATUS, "publication_authorized": False,
                "safe_to_publish": False, "festival_verified": False,
                "edition_dates_verified": False,
                "organizer_verified": False,
                "independence_verified": False,
            }
        checks[slug] = {
            "lastAttempted": today,
            "firstSeen": observations[slug]["firstSeen"] if candidate else today,
            "candidate_seen": bool(candidate),
            "institutional_status": inst_status,
            "first_party_status": official_status,
        }
        outcomes.append({
            "slug": slug, "institutional_status": inst_status,
            "first_party_status": official_status,
            "candidate_seen": bool(candidate),
            "publication_authorized": False,
        })
    state["institutional_future_date_observations_private"] = {
        x["slug"]: observations[x["slug"]]
        for x in validated_observations(state, today)}
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("schema") != REPORT_SCHEMA or report.get("date") != today:
        raise ValueError("rapport quotidien invalide")
    sources, quality = load_sources(today)
    outcomes = scan(state, sources, today, limit=args.limit) if sources else []
    accepted = validated_observations(state, today)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["institutional_future_archive_status_private"] = quality
    report["institutional_future_sources_checked_private"] = len(outcomes)
    report["institutional_future_candidates_private"] = len(accepted)
    report["institutional_future_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("TARGETED_INSTITUTIONAL_FUTURE:", json.dumps({
        "archive": quality, "checked": len(outcomes),
        "review_only": len(accepted), "publications": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
