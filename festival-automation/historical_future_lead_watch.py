"""Bounded archive-homepage watch: future-year *research hints*, never editions.

Only twelve exact, reviewed homepage URLs are eligible for a network request.
The URLs MUST still match both identical public historical snapshots. Nothing
from HTML, historical free text or private state becomes a request destination.
An edition year near the visible name is not a verified date or organizer.
"""
import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from curated_future_lead_watch import _VisibleBody
from official_watch import get_json, get_page, permitted_url
from regional_festival_discovery import HISTORY_PAGES, HISTORY_GIT
from source_qualification import normalized

STATE_SCHEMA = "grossesondes.source-watch.v1"
REPORT_SCHEMA = "grossesondes.source-watch-report.v1"
STATUS = "UNVERIFIED_ARCHIVE_HOMEPAGE_YEAR_MENTION"
MAX_CHECKS = 2
MAX_ARCHIVE_ROWS = 500
MAX_AGE_DAYS = 7

# Curated exact URL/identity tuples derived from the historical catalogue.
# These are *research* pages, not certified official ownership.
# Every new entry requires an explicit code review and tests.
APPROVED = {
    "as-one-fest": ("As One Fest", "Nouvelle-Aquitaine",
                    "https://www.asonefest.fr/"),
    "barbeuk-metal-fest": ("Barbeuk Metal Fest", "Pays de la Loire",
                          "https://www.barbeukmetalfest.fr/"),
    "betizfest": ("BetiZFest", "Hauts-de-France",
                  "https://betizfest.info/"),
    "les-lunatiques": ("Les Lunatiques", "Bretagne",
                       "https://lunatiques-festival.fr/"),
    "le-gros-tonneau": ("Le Gros Tonneau", "Auvergne-Rhône-Alpes",
                        "https://legrostonneau-festival.fr/"),
    "riip-fest": ("RIIP Fest", "Centre-Val de Loire",
                  "https://www.riipfest.com/"),
    "metal-hunting-open-air": ("Metal Hunting Open Air", "Grand Est",
                               "https://metalhunting.fr/"),
    "xtreme-fest": ("Xtreme Fest", "Occitanie",
                    "https://xtremefest.fr/"),
    "graf-zeppelin-festival": ("Graf Zeppelin Festival", "Normandie",
                               "https://festivalgrafzeppelin.com/"),
    "helixfest": ("HelixFest", "Provence-Alpes-Côte d'Azur",
                  "https://helixfest.fr/"),
    "les-gueules-de-bois": ("Les Gueules de Bois", "Bourgogne-Franche-Comté",
                            "https://festivalgueulesdebois.com/"),
    "mennecy-metal-fest": ("Mennecy Metal Fest", "Île-de-France",
                           "https://mennecy-metal-fest.fr/"),
}


def validated_roster(history, today):
    """Fail closed on any incorrect approved historical source."""
    now = date.fromisoformat(today)
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)
            or len(history["knownFestivals"]) > MAX_ARCHIVE_ROWS):
        raise ValueError("historique incompatible")
    rows = {}
    for row in history["knownFestivals"]:
        if not isinstance(row, dict):
            raise ValueError("archive malformée")
        slug = row.get("slug")
        if slug not in APPROVED:
            continue
        if slug in rows:
            raise ValueError("doublon dans les archives approuvées")
        name, region, url = APPROVED[slug]
        try:
            first = date.fromisoformat(row["startDate"])
            last = date.fromisoformat(row["endDate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("édition historique invalide") from None
        if (row.get("name") != name or
                normalized(row.get("region")) != normalized(region)
                or row.get("officialSite") != url or not permitted_url(url)
                or type(row.get("lastKnownYear")) is not int
                or not first <= last < now or
                last.year != row["lastKnownYear"]):
            raise ValueError("source historique modifiée ou édition non passée")
        rows[slug] = {"slug": slug, "name": name, "region": region, "url": url,
                      "last_known_year": row["lastKnownYear"]}
    if set(rows) != set(APPROVED):
        raise ValueError("sélection historique incomplète")
    return rows


def load_verified_roster(today, fetch_json=get_json):
    """A divergent Pages/raw archive disables all homepage fetches."""
    try:
        first = fetch_json(HISTORY_PAGES)
        second = fetch_json(HISTORY_GIT)
        if first != second:
            return {}, "DIVERGENT"
        return validated_roster(first, today), "CONSISTENT"
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {}, "UNAVAILABLE_OR_INVALID"



class _ArchiveVisibleBody(_VisibleBody):
    # <title> is page metadata, not visible evidence. Navigation and footers
    # can mention unrelated events or copyright years.
    HIDDEN = _VisibleBody.HIDDEN | {"head", "title", "nav", "footer"}


def _archive_visible_text(html):
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("HTML historique non conforme")
    parser = _ArchiveVisibleBody()
    parser.feed(html)
    result = normalized(" ".join(parser.parts))
    if len(result) < 30:
        raise ValueError("texte historique visible insuffisant")
    return result


def visible_future_years(name, html, today):
    """Only bounded adjacent visible wording; no schema, metadata or date claim."""
    text = _archive_visible_text(html)  # excludes document head and hidden HTML
    identity = normalized(name)
    now = date.fromisoformat(today).year
    years = set()
    for occurrence in re.finditer(
            r"(?<![a-z0-9])" + re.escape(identity) + r"(?![a-z0-9])", text):
        # The year must FOLLOW the *same* visible identity locally.
        # A preceding year may belong to a different event on the page;
        # a later year may belong to another named festival or a footer.
        nearby = text[occurrence.end():occurrence.end() + 64]
        mentions = list(re.finditer(r"(?<!\d)(20[2-4]\d)(?!\d)", nearby))
        if not mentions:
            continue
        mention = mentions[0]  # never skip an older year to borrow a newer one
        preceding = nearby[:mention.start()]
        if (len(preceding) > 45
                or re.search(r"\b(?:autre festival|autre fest|prochain festival)\b",
                             preceding)
                or re.search(r"(?:copyright|droits reserves|tous droits reserves)\s*$",
                             preceding[-24:])):
            continue
        year = int(mention.group(1))
        if now < year <= now + 2:
            years.add(year)
    return sorted(years), sha256(text.encode("utf-8")).hexdigest()



# Extract conservative, syntactic FR date hints from the very same page already
# fetched by the archive watch. These are NEVER verified dates or public fields.
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
}
MONTH_PATTERN = "|".join(MONTHS)
# Accept "13 fevrier 2027", "19 au 21 aout 2027", and "2027 19-21 aout"
# after HTML text normalization; no cross-month or unstated-year inference.
FR_DATE_AFTER = re.compile(
    rf"(?<!\d)(?P<start>[1-9]|[12]\d|3[01])"
    rf"(?: (?:au |a |et )?(?P<end>[1-9]|[12]\d|3[01]))?"
    rf" (?P<month>{MONTH_PATTERN}) (?P<year>20[2-4]\d)(?!\d)")
FR_YEAR_BEFORE = re.compile(
    rf"(?<!\d)(?P<year>20[2-4]\d) "
    rf"(?P<start>[1-9]|[12]\d|3[01])"
    rf"(?: (?:au |a |et )?(?P<end>[1-9]|[12]\d|3[01]))?"
    rf" (?P<month>{MONTH_PATTERN})(?![a-z])")
# Three explicitly printed days (e.g. "19, 20 & 21 aout 2027") must not
# be shortened into the last two days by the two-day date grammar.
DAY = r"(?:[1-9]|[12]\d|3[01])"
FR_DATE_AFTER_THREE = re.compile(
    rf"(?<!\d)(?P<start>{DAY}) (?:et )?(?P<middle>{DAY}) (?:et |au |a )?(?P<end>{DAY})"
    rf" (?P<month>{MONTH_PATTERN}) (?P<year>20[2-4]\d)(?!\d)")
FR_YEAR_BEFORE_THREE = re.compile(
    rf"(?<!\d)(?P<year>20[2-4]\d) (?P<start>{DAY})"
    rf" (?:et )?(?P<middle>{DAY}) (?:et |au |a )?(?P<end>{DAY})"
    rf" (?P<month>{MONTH_PATTERN})(?![a-z])")


def _season_matches_dates(season, first, last):
    """Reject obvious season/date contradictions, never infer a season."""
    months = {first.month, last.month}
    if season == "summer" and months.intersection({12, 1, 2, 3}):
        return False
    if season == "winter" and months.intersection({6, 7, 8}):
        return False
    return True


MAX_DATE_HINTS = 3
PILOT_PRIORITY = {"les-gueules-de-bois"}  # known public 2027 programme; still unverified


def visible_future_date_hints(name, html, today, target_year):
    """Bounded date phrases from one displayed edition context, not proof.

    Stop before another mention of the festival or a new winter/summer
    heading. A summer heading cannot borrow dates from a later winter
    heading, even when both belong to the same festival and year.
    """
    if (type(target_year) is not int
            or not date.fromisoformat(today).year < target_year
            <= date.fromisoformat(today).year + 2):
        return []
    text = _archive_visible_text(html)
    identity = normalized(name)
    identity_pattern = r"(?<![a-z0-9])" + re.escape(identity) + r"(?![a-z0-9])"
    output = {}
    for occurrence in re.finditer(identity_pattern, text):
        local = text[occurrence.end():occurrence.end() + 200]
        first_year = re.search(r"(?<!\d)(20[2-4]\d)(?!\d)", local[:65])
        if not first_year or int(first_year.group(1)) != target_year:
            continue
        before_year = local[:first_year.end()]
        labels = re.findall(r"\b(hiver|winter|ete|summer)\b", before_year)
        season_names = {"hiver": "winter", "winter": "winter",
                        "ete": "summer", "summer": "summer"}
        seasons = {season_names[label] for label in labels}
        if len(seasons) > 1:
            continue  # even the section label is ambiguous
        season = next(iter(seasons)) if seasons else None

        # The HTML has already been flattened to visible text. A small
        # fixed window alone can accidentally cross a subsequent section.
        # Bound BOTH date grammars at the earliest new edition/event header.
        after_year = first_year.end()
        boundaries = [len(local)]
        for pattern in (identity_pattern,
                        r"\b(?:hiver|winter|ete|summer) 20[2-4]\d\b",
                        r"\b(?:autre festival|autre evenement|prochain festival)\b"):
            new_section = re.search(pattern, local[after_year:])
            if new_section:
                boundaries.append(after_year + new_section.start())
        bound = min(boundaries)
        after_window = local[after_year:min(bound, after_year + 100)]
        before_window = local[first_year.start():min(bound, first_year.start() + 120)]
        matches, three_day_spans = [], []
        for pattern, text_window, offset, triple in (
                (FR_DATE_AFTER_THREE, after_window, after_year, True),
                (FR_YEAR_BEFORE_THREE, before_window, first_year.start(), True),
                (FR_DATE_AFTER, after_window, after_year, False),
                (FR_YEAR_BEFORE, before_window, first_year.start(), False)):
            for match in pattern.finditer(text_window):
                start_at = offset + match.start()
                stop_at = offset + match.end()
                if triple:
                    three_day_spans.append((start_at, stop_at))
                matches.append((start_at, not triple, stop_at, match, triple))
        # A two-day submatch inside a three-day phrase is not a separate date.
        for absolute_start, _, _, match, triple in sorted(matches, key=lambda x: x[:3]):
            if not triple and any(a <= absolute_start < b
                                  for a, b in three_day_spans):
                continue
            if int(match.group("year")) != target_year:
                continue
            try:
                start_day = int(match.group("start"))
                end_day = int(match.group("end") or match.group("start"))
                if triple and not (int(match.group("middle")) == start_day + 1
                                   and end_day == start_day + 2):
                    continue
                start = date(target_year, MONTHS[match.group("month")], start_day)
                end = date(target_year, MONTHS[match.group("month")], end_day)
            except ValueError:
                continue
            if (not date.fromisoformat(today) < start <= end
                    or (end - start).days > 14
                    or not _season_matches_dates(season, start, end)):
                continue
            output[(start.isoformat(), end.isoformat())] = {
                "start_date_hint": start.isoformat(),
                "end_date_hint": end.isoformat(),
                "season_hint": season,
                "status": "UNVERIFIED_VISIBLE_DATE_PHRASE",
                "edition_dates_verified": False,
                "organizer_verified": False,
                "independence_verified": False,
                "publication_authorized": False,
                "review_only": True,
            }
            break  # one date per explicit name/year occurrence
        if len(output) >= MAX_DATE_HINTS:
            break
    return [output[key] for key in sorted(output)][:MAX_DATE_HINTS]


def _valid_private_date_hints(value, year, today):
    if not isinstance(value, list) or len(value) > MAX_DATE_HINTS:
        return None
    output = []
    for hint in value:
        if not isinstance(hint, dict):
            return None
        try:
            first = date.fromisoformat(hint["start_date_hint"])
            last = date.fromisoformat(hint["end_date_hint"])
        except (ValueError, KeyError, TypeError):
            return None
        if (first.year != year or last.year != year
                or not date.fromisoformat(today) < first <= last
                or (last - first).days > 14
                or hint.get("season_hint") not in (None, "winter", "summer")
                or not _season_matches_dates(hint.get("season_hint"), first, last)
                or hint.get("status") != "UNVERIFIED_VISIBLE_DATE_PHRASE"
                or hint.get("edition_dates_verified") is not False
                or hint.get("organizer_verified") is not False
                or hint.get("independence_verified") is not False
                or hint.get("publication_authorized") is not False
                or hint.get("review_only") is not True):
            return None
        output.append({
            "start_date_hint": first.isoformat(),
            "end_date_hint": last.isoformat(),
            "season_hint": hint.get("season_hint"),
            "status": "UNVERIFIED_VISIBLE_DATE_PHRASE",
            "edition_dates_verified": False,
            "organizer_verified": False,
            "independence_verified": False,
            "publication_authorized": False,
            "review_only": True,
        })
    return output


def choose_roster(roster, attempted, today, limit=MAX_CHECKS):
    if type(limit) is not int or not 0 <= limit <= MAX_CHECKS:
        raise ValueError("budget homepage non conforme")
    if not isinstance(attempted, dict):
        raise ValueError("rotations historiques invalides")
    now = date.fromisoformat(today)
    choices = []
    for slug in sorted(roster):
        prior = attempted.get(slug, {})
        if not isinstance(prior, dict):
            raise ValueError("état de rotation altéré")
        when = prior.get("lastAttempted", "")
        if when:
            try:
                previous = date.fromisoformat(when)
            except (TypeError, ValueError):
                raise ValueError("date de rotation altérée") from None
            if previous > now:
                raise ValueError("rotation dans le futur")
            if previous == now:
                continue
        choices.append((when != "", when, slug not in PILOT_PRIORITY, slug))
    choices.sort()
    return [roster[slug] for _, _, _, slug in choices[:limit]]


def validated_hints(state, today):
    """Read only recent, untrusted REVIEW hints on a fixed approved roster."""
    rows = state.get("historical_future_edition_hints_private", {})
    if not isinstance(rows, dict):
        raise ValueError("pistes historiques privées invalides")
    now = date.fromisoformat(today)
    result = []
    for slug, row in rows.items():
        if slug not in APPROVED or not isinstance(row, dict):
            continue
        name, region, url = APPROVED[slug]
        try:
            first = date.fromisoformat(row["firstSeen"])
            last = date.fromisoformat(row["lastSeen"])
        except (KeyError, ValueError, TypeError):
            continue
        year = row.get("edition_year_hint")
        if (not first <= last <= now
                or (now - last).days > MAX_AGE_DAYS
                or type(year) is not int or not now.year < year <= now.year + 2
                or row.get("name_hint") != name
                or row.get("source_url") != url
                or row.get("region_hint") != region
                or row.get("status") != STATUS
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False
                or row.get("edition_dates_verified") is not False
                or row.get("organizer_verified") is not False
                or row.get("independence_verified") is not False
                or not isinstance(row.get("visible_text_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["visible_text_sha256"]) is None):
            continue
        date_hints = _valid_private_date_hints(
            row.get("date_hints_review_only", []), year, today)
        if date_hints is None:
            continue  # untrusted private date claims may not join this dossier
        result.append({
            "slug": slug, "name": name, "region": region, "url": url,
            "year": year, "firstSeen": first.isoformat(),
            "lastSeen": last.isoformat(),
            "date_hints_review_only": date_hints,
        })
    return sorted(result, key=lambda x: (x["slug"], x["year"]))


def scan(state, roster, today, fetch=get_page, limit=MAX_CHECKS):
    if state.get("schema") != STATE_SCHEMA:
        raise ValueError("état privé incompatible")
    if (not isinstance(roster, dict) or len(roster) > len(APPROVED)
            or any(slug not in APPROVED or not isinstance(source, dict)
                   or source.get("slug") != slug
                   or (source.get("name"), source.get("region"),
                       source.get("url")) != APPROVED[slug]
                   for slug, source in roster.items())):
        raise ValueError("sélection de surveillance non approuvée")
    attempts = state.setdefault("historical_future_source_checks_private", {})
    pending = state.setdefault("historical_future_edition_hints_private", {})
    if not isinstance(pending, dict):
        raise ValueError("observations historiques invalides")
    choices = choose_roster(roster, attempts, today, limit)
    outcomes = []
    for source in choices:
        slug = source["slug"]
        # A failed recheck MUST NOT leave yesterday's positive observation.
        pending.pop(slug, None)
        found = []
        status = "UNAVAILABLE"
        try:
            html = fetch(source["url"])
            found, digest = visible_future_years(source["name"], html, today)
            status = "YEAR_MENTION_REVIEW_ONLY" if found else "NO_FUTURE_YEAR_MENTION"
            if found:
                # Multiple different years on one page are ambiguous.
                # Never construct a dossier from ambiguity.
                if len(found) == 1:
                    previous = attempts.get(slug, {})
                    first_seen = today
                    if (isinstance(previous, dict)
                            and previous.get("candidate_year") == found[0]
                            and previous.get("firstSeen") is not None):
                        first_seen = previous["firstSeen"]
                    pending[slug] = {
                        "name_hint": source["name"],
                        "source_url": source["url"], "region_hint": source["region"],
                        "edition_year_hint": found[0],
                        "firstSeen": first_seen, "lastSeen": today,
                        "status": STATUS, "visible_text_sha256": digest,
                        "date_hints_review_only": visible_future_date_hints(
                            source["name"], html, today, found[0]),
                        "safe_to_publish": False, "publication_authorized": False,
                        "edition_dates_verified": False,
                        "organizer_verified": False,
                        "independence_verified": False,
                    }
                else:
                    status = "AMBIGUOUS_YEARS_REVIEW_ONLY"
        except (OSError, ValueError, UnicodeError, TypeError):
            pass
        old = attempts.get(slug, {})
        first = old.get("firstSeen", today) if (
            isinstance(old, dict) and old.get("candidate_year") in found
            and old.get("firstSeen")) else today
        attempts[slug] = {
            "lastAttempted": today,
            "status": status,
            "candidate_year": found[0] if len(found) == 1 else None,
            "firstSeen": first if len(found) == 1 else today,
        }
        outcomes.append({"status": status, "publication_authorized": False})
    # Keep only bounded, strictly validated, recent hints.
    state["historical_future_edition_hints_private"] = {
        item["slug"]: pending[item["slug"]]
        for item in validated_hints(state, today)
    }
    return outcomes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--intake", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = p.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("schema") != REPORT_SCHEMA or report.get("date") != today:
        raise ValueError("rapport du jour absent")
    state_path = args.intake / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    roster, quality = load_verified_roster(today)
    outcomes = scan(state, roster, today, limit=args.limit) if roster else []
    hints = validated_hints(state, today)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    report["historical_future_watch_archive_status_private"] = quality
    report["historical_future_watch_sources_configured_private"] = len(APPROVED)
    report["historical_future_watch_sources_checked_private"] = len(outcomes)
    report["historical_future_watch_year_mentions_private"] = sum(
        r["status"] == "YEAR_MENTION_REVIEW_ONLY" for r in outcomes)
    report["historical_future_watch_pending_hints_private"] = len(hints)
    report["historical_future_watch_visible_date_hints_private"] = sum(
        len(row["date_hints_review_only"]) for row in hints)
    report["historical_future_watch_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("ARCHIVE_HOMEPAGE_WATCH:", json.dumps({
        "archive": quality, "checked": len(outcomes),
        "year_mentions": report["historical_future_watch_year_mentions_private"],
        "pending_review": len(hints), "published": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
