"""Bounded rechecks of five editorially curated future-festival announcements.

All records and page observations remain on the private intake branch.
A repeated primary-site claim is not independent verification and never
authorizes an addition, ticket status, lineup, map pin or public patch.
"""
import argparse
from datetime import date, timedelta, datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from official_watch import get_page, get_json, PAGES, GIT, permitted_url
from source_qualification import normalized

SCHEMA = "grossesondes.curated-future-leads.v1"
MAX_CHECKS = 2
MAX_LEADS = 5
# Both the exact hostname AND path have been reviewed. Private state and
# scraped HTML never supply destinations to the HTTP client.
ALLOWED = {
    "mozhell-open-air-2027":
        ("https://www.mozhell.fr/fr/le-mozhell-est-de-retour-pour-une-nouvelle-edition-en-2027",
         "https://www.mozhell.fr/fr/"),
    "festibarock-in-2027":
        ("https://www.festibarockin.fr/", "https://www.festibarockin.fr/"),
    "la-sainte-rock-festival-2027":
        ("https://lasainterockfestival.fr/", "https://lasainterockfestival.fr/"),
    "colombin-rock-festival-2027":
        ("https://www.colombin-rock.fr/programmation/", "https://www.colombin-rock.fr/"),
    "esqui-riot-2027":
        ("https://esquiriot.fr/", "https://esquiriot.fr/"),
}
FIELDS = {
    "id", "name", "source_url", "official_home_candidate", "date_phrase",
    "start_date", "end_date", "city_hint", "region_hint", "genre_hint",
}
PRIVATE_STATUS = "UNVERIFIED_PRIMARY_EDITION"


def load_leads(data):
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA
            or not isinstance(data.get("leads"), list)
            or not 1 <= len(data["leads"]) <= MAX_LEADS):
        raise ValueError("configuration de recherche de festivals invalide")
    seen, result = set(), []
    for row in data["leads"]:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError("champs d'une piste de recherche invalides")
        key = row["id"]
        if (not isinstance(key, str) or key not in ALLOWED or key in seen
                or (row["source_url"], row["official_home_candidate"]) != ALLOWED[key]
                or not permitted_url(row["source_url"])
                or not permitted_url(row["official_home_candidate"])):
            raise ValueError("source de festival non autorisee")
        seen.add(key)
        for field in ("name", "city_hint", "region_hint", "genre_hint", "date_phrase"):
            if not isinstance(row[field], str) or not 3 <= len(row[field]) <= 160:
                raise ValueError("indication de festival invalide")
        if (normalized(row["date_phrase"]) != row["date_phrase"]
                or "2027" not in row["date_phrase"]
                or len(normalized(row["name"])) < 7):
            raise ValueError("preuve textuelle non canonique")
        start, end = row["start_date"], row["end_date"]
        if (start is None) != (end is None):
            raise ValueError("dates partielles interdites")
        if start is not None:
            try:
                begin, finish = date.fromisoformat(start), date.fromisoformat(end)
            except (TypeError, ValueError) as exc:
                raise ValueError("dates invalides") from exc
            if not (begin.year == finish.year == 2027
                    and begin <= finish and (finish - begin).days <= 7):
                raise ValueError("edition datee incoherente")
        result.append(dict(row))
    return result


def published_duplicate(lead, published):
    """Existing 2027 edition wins even if a prospective slug differs."""
    if not isinstance(published, dict) or not isinstance(published.get("festivals"), list):
        raise ValueError("catalogue de reference invalide")
    expected = normalized(lead["name"])
    for row in published["festivals"]:
        if not isinstance(row, dict):
            raise ValueError("ligne de catalogue invalide")
        if row.get("slug") == lead["id"]:
            return True
        first = row.get("startDate")
        if not isinstance(first, str) or not first.startswith("2027-"):
            continue
        title = re.sub(r"\s+2027$", "", normalized(row.get("name", "")))
        if title == expected:
            return True
        if (row.get("officialSite") == lead["official_home_candidate"]
                and title and expected in title):
            return True
    return False


def select_leads(leads, checked, today, limit):
    if (not 0 <= limit <= MAX_CHECKS or not isinstance(checked, dict)):
        raise ValueError("budget de collecte invalide")
    current = date.fromisoformat(today)
    choices = []
    for lead in leads:
        previous = checked.get(lead["id"])
        if previous:
            if not isinstance(previous, str):
                raise ValueError("historique de passage non conforme")
            checked_at = date.fromisoformat(previous)
            if checked_at > current:
                raise ValueError("historique de passage futur")
            if checked_at == current:
                continue
            key = (1, checked_at.isoformat(), lead["id"])
        else:
            key = (0, "", lead["id"])
        choices.append((key, lead))
    return [lead for _, lead in sorted(choices, key=lambda x: x[0])[:limit]]


class _VisibleBody(HTMLParser):
    """Exclude hidden attribute blocks and scripts, including nested markup."""
    HIDDEN = {"script", "style", "svg", "noscript", "template", "iframe"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img",
            "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        attributes = dict(attrs)
        style = (attributes.get("style") or "").replace(" ", "").lower()
        hidden = (tag in self.HIDDEN or "hidden" in attributes
                  or (attributes.get("aria-hidden") or "").lower() == "true"
                  or "display:none" in style or "visibility:hidden" in style
                  or (self.stack and self.stack[-1][1]))
        self.stack.append((tag, bool(hidden)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, value):
        if (not self.stack or not self.stack[-1][1]) and len(self.parts) < 16000:
            self.parts.append(value)


def visible_text(html):
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("HTML non exploitable")
    parser = _VisibleBody()
    parser.feed(html)
    text = normalized(" ".join(parser.parts))
    if len(text) < 30:
        raise ValueError("texte visible insuffisant")
    return text


def inspect_primary(lead, html):
    """Visible exact identity plus manually curated 2027 date words."""
    try:
        text = visible_text(html)
    except (ValueError, TypeError):
        return False, False, ""
    identity = normalized(lead["name"])
    matched_name = bool(re.search(
        r"(?<![a-z0-9])" + re.escape(identity) + r"(?![a-z0-9])", text))
    matched_date = bool(re.search(
        r"(?<![a-z0-9])" + re.escape(lead["date_phrase"]) + r"(?![a-z0-9])", text))
    return matched_name, matched_date, sha256(text.encode("utf-8")).hexdigest()


def scan(report, state, leads, published, today, fetch=get_page, limit=MAX_CHECKS):
    if (not isinstance(report, dict)
            or report.get("schema") != "grossesondes.source-watch-report.v1"
            or report.get("date") != today
            or not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"):
        raise ValueError("rapport ou etat de veille non conforme")
    checked = state.setdefault("curated_future_lead_last_checked", {})
    observations = state.setdefault("curated_future_lead_observations", {})
    if not isinstance(checked, dict) or not isinstance(observations, dict):
        raise ValueError("observations privees non conformes")
    # Private state is never trusted as a fetch list or public data source.
    for key in list(checked):
        if key not in ALLOWED:
            del checked[key]
    for key in list(observations):
        if key not in ALLOWED or not isinstance(observations[key], dict):
            del observations[key]
    outcomes = []
    for lead in select_leads(leads, checked, today, limit):
        key, url = lead["id"], lead["source_url"]
        entry = {"id": key, "source_url": url, "observed_at": today,
                 "status": "SOURCE_UNAVAILABLE", "name_seen": False,
                 "date_seen": False, "publication_authorized": False,
                 "editor_review_required": True}
        if published_duplicate(lead, published):
            entry["status"] = "ALREADY_PUBLISHED"
            checked[key] = today
            outcomes.append(entry)
            continue
        try:
            html = fetch(url)
            name_seen, date_seen, digest = inspect_primary(lead, html)
        except (OSError, ValueError, UnicodeError, TypeError):
            name_seen = date_seen = False
            digest = ""
        entry["name_seen"], entry["date_seen"] = name_seen, date_seen
        if name_seen and date_seen:
            before = observations.get(key, {})
            was_previous_day = before.get("lastSeen") == (
                date.fromisoformat(today) - timedelta(days=1)).isoformat()
            same_claim = (before.get("claim") ==
                          [lead["name"], lead["start_date"], lead["end_date"],
                           lead["date_phrase"], url])
            stable = was_previous_day and same_claim and (
                before.get("status") == PRIVATE_STATUS)
            entry["status"] = (
                "TWO_DAYS_PRIMARY_OBSERVATION_PRIVATE" if stable
                else "FIRST_PRIMARY_OBSERVATION_PRIVATE")
            entry["dated_edition"] = lead["start_date"] is not None
            observations[key] = {
                "status": PRIVATE_STATUS, "firstSeen": (
                    before["firstSeen"] if stable else today),
                "lastSeen": today, "lastVisibleDigest": digest,
                "claim": [lead["name"], lead["start_date"], lead["end_date"],
                          lead["date_phrase"], url],
                "publication_authorized": False,
            }
        else:
            if digest:
                entry["status"] = "VISIBLE_EVIDENCE_INSUFFICIENT"
            # Fail closed: network failures and truncated/incomplete HTML are
            # inconclusive, not proof that an old positive claim still holds.
            # Never carry stale positive evidence into editorial proposals.
            observations.pop(key, None)
        checked[key] = today
        outcomes.append(entry)
    report["curated_future_leads_configured_review_only"] = len(leads)
    report["curated_future_leads_checked_review_only"] = len(outcomes)
    report["curated_future_leads_two_day_review_only"] = sum(
        x["status"] == "TWO_DAYS_PRIMARY_OBSERVATION_PRIVATE" for x in outcomes)
    report["curated_future_leads_review_only"] = outcomes
    report["curated_future_leads_publications"] = 0
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    config = json.loads(Path(__file__).with_name(
        "curated_future_leads.json").read_text(encoding="utf-8"))
    leads = load_leads(config)
    pages, git = get_json(PAGES), get_json(GIT)
    if pages != git:
        raise ValueError("divergence du catalogue public : aucune qualification")
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = scan(report, state, leads, git, today, limit=args.limit)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("PISTES_FESTIVALS_2027:", json.dumps({
        "configured": len(leads), "checked": len(result),
        "two_day_private": report["curated_future_leads_two_day_review_only"],
        "results": [{k: row[k] for k in ("id", "status")} for row in result],
        "published": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
