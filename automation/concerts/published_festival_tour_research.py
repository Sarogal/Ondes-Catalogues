"""Find concert-tour stops already published in the Festivals catalogue.

This is a retrospective, purely PRIVATE research handoff: never mutate a
signed Festival row and never approve a Concert. The source is the independently
committed public festival catalogue, but its old artist/venue/source fields are
only nomination hints and MUST be re-proven by Concerts' own first-party
verification. No network requests and no event-specific allowlists.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from ipaddress import ip_address
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import triage

SCHEMA = "grossesondes.concert.discovery.v1"
SOURCE = "festival_published_tour_research"
MAX_INPUT_BYTES = 64 * 1024 * 1024  # Technical file/resource bound.
MAX_LINEUP_TEXT_BYTES = 64 * 1024  # Technical payload bound, not an artist count.
MIN_DISTINCT_CITIES = 2
MIN_DISTINCT_DATES = 2
TOUR_WORDS = re.compile(
    r"\b(?:etape(?:s)?\s+francais(?:e|es|es)?\s+du\s+"
    r"festival\s+itinerant|(?:tournee|tourn[eé]e)\s+de\s+concerts?|"
    r"concerts?\s+d'une\s+tournee|tournee\s+europeenne|"
    r"touring\s+festival\s+concert\s+stop)\b"
)


def _public_https_home(url):
    if not isinstance(url, str) or len(url) > 180:
        return None
    try:
        s = urlsplit(url)
        if (s.scheme != "https" or not s.hostname
                or s.username or s.password
                or s.port not in (None, 443)
                or s.path not in ("", "/") or s.query or s.fragment):
            return None
        host = s.hostname.lower()
        if (not re.fullmatch(r"[a-z0-9.-]+", host)
                or host in {"localhost", "local", "example.com", "test"}
                or host.endswith((".localhost", ".local", ".test", ".invalid"))
                or "." not in host):
            return None
        try:
            ip_address(host)
            return None  # No literal IPs in a public catalogue -> Concerts
        except ValueError:
            pass
        return "https://" + host + "/"
    except (ValueError, TypeError):
        return None


def _one_day_future(row, today):
    try:
        first = date.fromisoformat(row["startDate"])
        last = date.fromisoformat(row["endDate"])
        return first if first == last and first >= today else None
    except (KeyError, ValueError, TypeError):
        return None


def valid_artist_names(names, *, minimum=2):
    """Validate the entire roster without an editorial maximum artist count."""
    if not isinstance(names, list) or len(names) < minimum:
        return False
    # Each nonempty name costs at least one byte; bound work before iteration.
    if len(names) > MAX_LINEUP_TEXT_BYTES:
        return False
    if not all(isinstance(n, str) and 2 <= len(n.strip()) <= 130
               and len(n) <= 130 for n in names):
        return False
    if sum(len(n.encode("utf-8", errors="surrogatepass")) + 1
           for n in names) > MAX_LINEUP_TEXT_BYTES:
        return False
    normalized_names = tuple(triage.words(n) for n in names)
    return (all(normalized_names)
            and len(set(normalized_names)) == len(names))


def _named_lineup(row):
    names = row.get("lineup")
    if not valid_artist_names(names):
        return None
    return tuple(sorted(triage.words(n) for n in names))


def _qualifies_row(row, today):
    if not isinstance(row, dict):
        return None
    mandatory = ("slug", "name", "city", "department", "venue",
                 "officialSite", "notes")
    if not all(isinstance(row.get(k), str) and
               2 <= len(row[k].strip()) <= 1200 for k in mandatory):
        return None
    if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", row["slug"])
            or len(row["slug"]) > 130
            or not re.fullmatch(r"[0-9]{2,3}|2A|2B", row["department"])
            or len(row["venue"]) > 300
            or len(row["name"]) > 200
            or len(row["city"]) > 160):
        return None
    when = _one_day_future(row, today)
    site = _public_https_home(row["officialSite"])
    lineup = _named_lineup(row)
    notes = triage.words(row["notes"])
    if (when is None or site is None or lineup is None
            or not TOUR_WORDS.search(notes)):
        return None
    return {
        "row": row, "day": when.isoformat(), "site": site,
        "lineup": lineup, "cityKey": triage.words(row["city"]),
    }


def correction_research(corrections, today):
    """Reviewed retractions nominate a tour without reviving its festival row."""
    if not isinstance(corrections, list):
        raise ValueError("Invalid festival corrections")
    selected = {}
    for correction in corrections:
        if (not isinstance(correction, dict) or correction.get("schema") != 1
                or correction.get("action") != "retract_false_edition_only"
                or correction.get("retainHistoricalFestival") is not True
                or correction.get("continueEditionWatch") is not True):
            continue
        previous = correction.get("previousRow")
        lead = correction.get("concertLead")
        if not isinstance(previous, dict) or not isinstance(lead, dict):
            continue
        if lead.get("publicationAuthorized") is not False:
            continue
        site = _public_https_home(previous.get("officialSite"))
        day = _one_day_future(previous, today)
        slug = previous.get("slug")
        if (site is None or day is None or day.isoformat() != lead.get("date")
                or not isinstance(slug, str) or len(slug) > 130
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)):
            continue
        if not all(isinstance(lead.get(k), str) and 2 <= len(lead[k]) <= 200
                   for k in ("title", "venue", "city", "department", "officialUrl")):
            continue
        if not re.fullmatch(r"[0-9]{2,3}|2A|2B", lead["department"]):
            continue
        lineup = lead.get("artists")
        if _named_lineup({"lineup": lineup}) is None:
            continue
        # Same-origin detail is a research hint, never permission to fetch.
        try:
            url = urlsplit(lead["officialUrl"])
            if (url.scheme != "https" or url.netloc != urlsplit(site).netloc
                    or url.path in ("", "/") or url.query or url.fragment
                    or lead["officialUrl"] not in correction.get("evidence", [])):
                continue
        except (ValueError, TypeError):
            continue
        stable = sha256(json.dumps({
            "slug": slug, "date": day.isoformat(), "site": site,
            "city": triage.words(lead["city"]),
        }, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        candidate = triage.triage({
            "candidateId": "concert-from-festival-" + stable,
            "source": SOURCE, "sourceUrl": lead["officialUrl"], "sourcePage": site,
            "date": day.isoformat(), "name": lead["title"],
            "leadArtist": lineup[0], "venue": lead["venue"],
            "city": lead["city"], "department": lead["department"],
            "venueCatalogueId": None, "artistNamesFromFestivalOnly": list(lineup),
            "festivalReferenceSlug": slug, "classification": [],
            "genreToConfirm": True, "officialDetailFound": False,
            "publishedFestivalTourFlag": True, "requiresArtistAndVenueReproof": True,
            "festivalCatalogueHintsOnly": True,
            "publicationAllowed": False, "reviewRequired": True,
        })
        if candidate["reviewBucket"] != "tour_source_research":
            raise ValueError("Retraction research cannot enter publisher source")
        selected[candidate["candidateId"]] = candidate
    return list(selected.values())


def _tour_title(source):
    # Only remove an exact terminal city label, not arbitrary title words.
    title = triage.words(source["row"]["name"])
    city = source["cityKey"]
    if city and title.endswith(" " + city):
        title = title[:-(len(city) + 1)]
    return title


def _different_stages(a, b):
    return a["day"] != b["day"] and a["cityKey"] != b["cityKey"]


def _tour_sources(sources):
    """Nominate exact recurring bills or explicitly named variable tours.

    A variable bill needs a same-origin, same-title, different-date/city
    witness sharing at least two exact artist names. Never merge rosters or
    propagate a match transitively to a third unrelated stage.
    """
    exact, titled = defaultdict(list), defaultdict(list)
    for i, source in enumerate(sources):
        exact[(source["site"], source["lineup"])].append(i)
        title = _tour_title(source)
        if len(title.split()) >= 2:
            titled[(source["site"], title)].append(i)
    selected = set()
    for members in exact.values():
        if (len({sources[i]["cityKey"] for i in members}) >= MIN_DISTINCT_CITIES
                and len({sources[i]["day"] for i in members}) >= MIN_DISTINCT_DATES):
            selected.update(members)
    for members in titled.values():
        # Index only the named artists on this exact organizer/title cohort.
        by_artist = defaultdict(list)
        for i in members:
            for artist in sources[i]["lineup"]:
                by_artist[artist].append(i)
        for i in members:
            if i in selected:
                continue
            overlap = defaultdict(int)
            for artist in sources[i]["lineup"]:
                for j in by_artist[artist]:
                    if j == i or not _different_stages(sources[i], sources[j]):
                        continue
                    overlap[j] += 1
                    if overlap[j] == 2:
                        selected.add(i)
                        selected.add(j)
                if i in selected:
                    break
    return [source for i, source in enumerate(sources) if i in selected]


def find_research(catalogue, today, concert_catalogue=None, corrections=None):
    if (not isinstance(catalogue, dict) or catalogue.get("schema") != 1
            or not isinstance(catalogue.get("festivals"), list)
            or not isinstance(today, date)):
        raise ValueError("Unsafe signed public festival catalogue")
    sources = [source for row in catalogue["festivals"]
               if (source := _qualifies_row(row, today)) is not None]
    selected = []
    for source in _tour_sources(sources):
        site = source["site"]
        r = source["row"]
        stable_id = sha256(json.dumps({
            "slug": r["slug"], "date": source["day"], "site": site,
            "city": source["cityKey"],
        }, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        # The festival catalogue is nomination evidence ONLY. It neither
        # establishes an approved concert source nor a verified concert
        # artist, place, date or genre. Preserve exact visible hints
        # while explicitly requiring fresh independent concert proof.
        row = {
            "candidateId": "concert-from-festival-" + stable_id,
            "source": SOURCE,
            "sourceUrl": site, "sourcePage": site,
            # Signed catalogue is nomination provenance, NOT the official
            # source host. Separate the two so the independent source
            # admission queue can research the real organizer domain.
            "festivalCatalogueSource": (
                "https://sarogal.github.io/Ondes-Catalogues/"
                "grossesondes/festivals.json"),
            "date": source["day"], "name": r["name"],
            "leadArtist": r["lineup"][0], "venue": r["venue"],
            "city": r["city"], "department": r["department"],
            "venueCatalogueId": None,
            "artistNamesFromFestivalOnly": list(r["lineup"]),
            "festivalReferenceSlug": r["slug"],
            "classification": [],
            "genreToConfirm": True,
            "officialDetailFound": False,
            "publishedFestivalTourFlag": True,
            "requiresArtistAndVenueReproof": True,
            "festivalCatalogueHintsOnly": True,
            "publicationAllowed": False, "reviewRequired": True,
        }
        classified = triage.triage(row)
        if classified["reviewBucket"] != "tour_source_research":
            raise ValueError("Tour review cannot enter publisher source")
        selected.append(classified)
    # This offline nomination pass archives every eligible lead. Network
    # verification budgets and fair rotation belong to the downstream review.
    by_id = {row["candidateId"]: row for row in selected}
    for row in correction_research(corrections if corrections is not None else [], today):
        by_id.setdefault(row["candidateId"], row)
    selected = list(by_id.values())
    selected.sort(key=lambda row: (row["date"], row["candidateId"]))
    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "publicationAllowed": False, "automaticPublication": False,
        "candidates": selected,
        "triageCounts": {"tour_source_research": len(selected)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--festivals", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    # Bound actual input bytes rather than the number of festivals or leads.
    # Never silently truncate the catalogue or split a touring cohort.
    remaining = MAX_INPUT_BYTES

    def read_bounded(path):
        nonlocal remaining
        with path.open("rb") as stream:
            payload = stream.read(remaining + 1)
        if len(payload) > remaining:
            raise ValueError("Festival tour research input exceeds byte budget")
        remaining -= len(payload)
        return json.loads(payload.decode("utf-8"))

    data = read_bounded(args.festivals)
    correction_dir = args.festivals.parent / "festival-corrections"
    corrections = [read_bounded(p) for p in sorted(correction_dir.glob("*.json"))]
    report = find_research(data, datetime.now(ZoneInfo("Europe/Paris")).date(),
                           corrections=corrections)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Touring concert stops nominated by signed Festival catalogue=" +
          str(len(report["candidates"])) +
          "; private research only, no approvals or map mutations")


if __name__ == "__main__":
    main()
