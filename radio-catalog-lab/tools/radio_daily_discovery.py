#!/usr/bin/env python3
"""Non-publishing daily Radio Browser discovery for Grosses Ondes.

No fixed station UUID admission list. The discovery output is an untrusted
candidate report; neither an APK nor a signed catalog is ever changed.
Only read-only GET to official Radio Browser mirrors. No stream probes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# Search terms are intentionally extensible and NOT station admission rules.
# The daily planner always searches broad families, then rotates deeper subgenres.
# Variants like 'thrash/trash' and 'nu/nü/nu-metal' are separate API queries.
DEFAULT_TAGS = (
    "metal", "heavy metal", "hard rock", "rock",
    "punk", "punk rock", "black metal", "death metal",
    "thrash metal", "trash metal", "nu metal", "nü metal",
    "pagan metal", "folk metal", "power metal", "doom metal",
    "symphonic metal", "progressive metal", "speed metal", "glam metal",
    "hair metal", "traditional metal", "classic metal", "nwobhm",
    "new wave of british heavy metal", "melodic metal", "melodic death metal", "melodic black metal",
    "technical death metal", "brutal death metal", "symphonic death metal", "technical metal",
    "blackened death metal", "atmospheric black metal", "depressive black metal", "dsbm",
    "raw black metal", "war metal", "blackgaze", "post black metal",
    "blackened thrash metal", "viking metal", "celtic metal", "medieval metal",
    "pirate metal", "epic metal", "fantasy metal", "battle metal",
    "gothic metal", "goth metal", "industrial metal", "groove metal",
    "alternative metal", "avant garde metal", "experimental metal", "funk metal",
    "rap metal", "crossover thrash", "crossover metal", "christian metal",
    "white metal", "unblack metal", "neoclassical metal", "orchestral metal",
    "metalcore", "melodic metalcore", "progressive metalcore", "deathcore",
    "blackened deathcore", "symphonic deathcore", "mathcore", "grindcore",
    "deathgrind", "goregrind", "pornogrind", "cybergrind",
    "sludge", "sludge metal", "stoner", "stoner metal",
    "stoner rock", "desert rock", "drone metal", "drone doom",
    "funeral doom", "death doom", "gothic doom", "epic doom",
    "stoner doom", "post metal", "djent", "thall",
    "nu metalcore", "nü metal", "nu-metal", "post hardcore",
    "hardcore", "hardcore punk", "beatdown hardcore", "metallic hardcore",
    "melodic hardcore", "punk hardcore", "street punk", "oi punk",
    "oi!", "anarcho punk", "crust punk", "crust",
    "d beat", "d-beat", "skate punk", "pop punk",
    "folk punk", "celtic punk", "horror punk", "psychobilly",
    "garage punk", "post punk", "post-punk", "art punk",
    "egg punk", "proto punk", "grind punk", "screamo",
    "emoviolence", "emo", "alternative rock", "progressive rock",
    "hard blues rock", "blues rock", "classic rock", "southern rock",
    "psychedelic rock", "garage rock", "post rock", "post-rock",
    "industrial rock", "gothic rock", "grunge", "noise rock",
    "math rock", "space rock", "desert rock", "new wave of traditional heavy metal",
    "n w o t h m", "sleaze rock", "glam rock",
)

DEFAULT_NAMES = (
    "metal", "hard rock", "punk", "rock",
    "black metal", "death metal", "thrash metal", "trash metal",
    "pagan metal", "nu metal", "nü metal", "viking metal",
    "folk metal", "metalcore", "deathcore", "grindcore",
    "doom metal", "stoner", "djent", "hardcore",
    "crust punk", "gothic metal", "industrial metal", "power metal",
    "symphonic metal", "progressive metal", "NWOBHM", "post metal",
)

CORE_TAGS = (
    "metal", "heavy metal", "hard rock", "rock",
    "punk", "punk rock", "black metal", "death metal",
    "thrash metal", "trash metal", "nu metal", "pagan metal",
)

CORE_NAMES = (
    "metal", "punk", "hard rock", "rock",
)

STRONG_GENRES = (
    "metallic hardcore", "nü metal", "nu-metal", "d beat",
    "d-beat", "djent", "thrash", "trash",
    "crust", "grind", "stoner", "punkrock",
    "hardcore", "nwobhm", "dsbm", "goregrind",
    "screamo", "grunge",
)


MAX_JSON_BYTES = 3_000_000
USER_AGENT = "GrossesOndesDailyDiscovery/0.1 (https://grosses-ondes.fr/)"
API_HOST_SUFFIX = ".api.radio-browser.info"


def normalize(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()

# Include future labels added by the scanner's vocabulary: new stations can
# be considered relevant without an old UUID or a fixed list of *radios*.
GENRE_TERMS = tuple(sorted({normalize(x) for x in DEFAULT_TAGS + STRONG_GENRES
                            if normalize(x)}, key=lambda x: (len(x), x)))


def is_public_stream(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return False
        if parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.hostname.lower() == "localhost" or parsed.hostname.lower().endswith(
            (".localhost", ".local", ".internal")
        ):
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            return ip.is_global
        except ValueError:
            return "." in parsed.hostname
    except (ValueError, TypeError):
        return False


def _uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None


def genre_evidence(name: str, tags: str) -> list[str]:
    text = " " + normalize(name + " " + tags) + " "
    return sorted({
        genre for genre in GENRE_TERMS
        if " " + genre + " " in text
    })


def candidate(raw: object, known_ids: set[str]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    station_id = _uuid(raw.get("stationuuid"))
    name = str(raw.get("name") or "").strip()[:240]
    if not station_id or not name:
        return None
    tags = str(raw.get("tags") or "")[:1000]
    matches = genre_evidence(name, tags)
    if not matches:
        return None

    stream = str(raw.get("url_resolved") or raw.get("url") or "").strip()
    safe_stream = is_public_stream(stream)
    last_ok = raw.get("lastcheckok") in (True, 1, "1")
    code = str(raw.get("countrycode") or "").strip().upper()[:2]
    if not re.fullmatch(r"[A-Z]{2}", code):
        code = ""
    status = (
        "already_known" if station_id in known_ids
        else "needs_stream_check" if not safe_stream or not last_ok
        else "candidate_requires_qualification"
    )
    # Values are public-source observations, NOT proof of station ownership,
    # distinct identity, actual format, live connectivity or editorial approval.
    return {
        "stationuuid": station_id,
        "name": name,
        "countrycode": code,
        "tags": tags,
        "genreEvidence": matches,
        "streamUrl": stream if safe_stream else None,
        "homepage": str(raw.get("homepage") or "")[:1500],
        "favicon": str(raw.get("favicon") or "")[:1500],
        "lastcheckok": last_ok,
        "status": status,
        "source": "Radio Browser (unverified candidate)",
    }


def annotate_duplicate_risks(rows: list[dict]) -> None:
    identities: dict[tuple[str, str], set[str]] = {}
    urls: dict[str, set[str]] = {}
    for row in rows:
        station_id = row["stationuuid"]
        identities.setdefault((row["countrycode"], normalize(row["name"])), set()).add(station_id)
        if row["streamUrl"]:
            urls.setdefault(row["streamUrl"].strip(), set()).add(station_id)
    for row in rows:
        key = (row["countrycode"], normalize(row["name"]))
        row["duplicateIdentityRisk"] = (
            len(identities[key]) > 1
            or bool(row["streamUrl"] and len(urls[row["streamUrl"].strip()]) > 1)
        )
        if row["duplicateIdentityRisk"] and row["status"] != "already_known":
            row["status"] = "needs_duplicate_review"


def known_uuids(path: Path | None) -> set[str]:
    """Optional dynamic known-UUID export; NEVER source-of-truth approval gate."""
    if path is None:
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = payload if isinstance(payload, list) else (
        payload.get("known_station_uuids") if isinstance(payload, dict) else None
    )
    if not isinstance(ids, list):
        raise ValueError("Known station UUID input must be an array")
    result = set()
    for value in ids:
        parsed = _uuid(value)
        if parsed is None:
            raise ValueError("Invalid UUID in known station input")
        result.add(parsed)
    return result


MAX_DAILY_QUERIES = 40


def plan_daily_queries(day: dt.date, tags: list[str] | tuple[str, ...],
                       names: list[str] | tuple[str, ...],
                       max_queries: int = MAX_DAILY_QUERIES
                       ) -> tuple[list[str], list[str]]:
    """Core families every day; rotate every specialist term over subsequent days.

    The fixed limit is a per-run *request budget*, not a permanent catalogue
    ceiling. Appending a genre never requires adding any particular radio UUID.
    """
    if not 1 <= max_queries <= MAX_DAILY_QUERIES:
        raise ValueError("Daily query budget out of bounds")
    used: set[tuple[str, str]] = set()
    def uniq(field: str, terms) -> list[tuple[str, str]]:
        result = []
        for raw in terms:
            if not isinstance(raw, str):
                raise ValueError("Invalid genre term")
            term = raw.strip()
            if not term or len(term) > 60 or not re.fullmatch(r"[\w !&+/\-]+", term, re.UNICODE):
                raise ValueError("Unsafe genre query")
            identity = (field, term.casefold())
            if identity not in used:
                used.add(identity)
                result.append((field, term))
        return result

    all_queries = uniq("tag", tags) + uniq("name", names)
    known = set(all_queries)
    core = [(field, term) for field, sources in (
        ("tag", CORE_TAGS), ("name", CORE_NAMES),
    ) for term in sources if (field, term) in known]
    core_ids = set(core)
    rest = [query for query in all_queries if query not in core_ids]
    if len(core) > max_queries:
        raise ValueError("Insufficient budget for mandatory core genres")
    places = max_queries - len(core)
    # Consecutive daily windows traverse all remaining tags, without hiding
    # deep subgenres forever behind a popularity-ordered first page.
    if rest and places:
        start = (day.toordinal() * places) % len(rest)
        rotated = [rest[(start + i) % len(rest)] for i in range(min(places, len(rest)))]
    else:
        rotated = []
    selected = core + rotated
    return ([value for field, value in selected if field == "tag"],
            [value for field, value in selected if field == "name"])


def suggest_related_tags(rows: list[dict], *, limit: int = 100) -> list[str]:
    """Metadata-driven hints for *future searches*, never station approvals."""
    if not 0 <= limit <= 200:
        raise ValueError("Invalid tag suggestion budget")
    known = {normalize(term) for term in DEFAULT_TAGS}
    suggestions: dict[str, str] = {}
    for row in rows:
        for tag in str(row.get("tags") or "").split(",")[:80]:
            raw = tag.strip()
            key = normalize(raw)
            if (not 3 <= len(raw) <= 60 or key in known or
                    not re.fullmatch(r"[\w &+!/\-]+", raw, re.UNICODE)):
                continue
            if not genre_evidence("", raw):
                continue
            suggestions.setdefault(key, raw)
    return sorted(suggestions.values(), key=lambda term: normalize(term))[:limit]


def previous_genre_hints(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return []
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Previous genre report too large")
    prior = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(prior, dict) or prior.get("schemaVersion") != 1 or (
        prior.get("publicationAllowed") is not False
    ):
        raise ValueError("Untrusted previous discovery report")
    hints = prior.get("suggestedGenreTags", [])
    if not isinstance(hints, list) or len(hints) > 200:
        raise ValueError("Unbounded discovered genre list")
    return suggest_related_tags([{"tags": ",".join(hints)}], limit=100)


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_api_mirrors() -> list[str]:
    """Use official DNS mirror discovery, not a permanent single-server pin."""
    addresses = socket.getaddrinfo("all.api.radio-browser.info", 443, type=socket.SOCK_STREAM)
    found = set()
    for entry in addresses:
        address = entry[4][0]
        try:
            host = socket.gethostbyaddr(address)[0].lower().rstrip(".")
            if host.endswith(API_HOST_SUFFIX) and host != "all.api.radio-browser.info":
                found.add(host)
        except OSError:
            continue
    if not found:
        raise RuntimeError("Radio Browser DNS mirror discovery failed; do not report a clean scan")
    return sorted(found)


def fetch_page(hosts: list[str], field: str, term: str,
               offset: int, limit: int) -> list[dict]:
    if field not in {"tag", "name"} or not term or not hosts:
        raise ValueError("Invalid discovery query")
    opener = urllib.request.build_opener(NoRedirects())
    query = urllib.parse.urlencode({
        field: term, "hidebroken": "false",
        "order": "changetimestamp", "reverse": "true",
        "limit": str(limit), "offset": str(offset),
    })
    last_error: Exception | None = None
    for host in hosts:
        if not (host.endswith(API_HOST_SUFFIX) and host != "all.api.radio-browser.info"):
            continue
        url = f"https://{host}/json/stations/search?{query}"
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json",
        })
        try:
            with opener.open(req, timeout=18) as response:
                if response.status != 200:
                    raise RuntimeError(f"Radio Browser HTTP {response.status}")
                payload = response.read(MAX_JSON_BYTES + 1)
                if len(payload) > MAX_JSON_BYTES:
                    raise RuntimeError("Radio Browser response too large")
            decoded = json.loads(payload)
            if not isinstance(decoded, list) or any(not isinstance(r, dict) for r in decoded):
                raise ValueError("Invalid Radio Browser response shape")
            return decoded
        except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as error:
            last_error = error
    raise RuntimeError(f"Radio Browser query failed: {field}={term}; {last_error}")


def page_offsets(day: dt.date, page_size: int, max_pages: int) -> list[int]:
    """Always inspect latest, rotate deeper pages so old blind spots get seen."""
    if not 1 <= max_pages <= 20 or not 1 <= page_size <= 250:
        raise ValueError("Scan budget exceeded")
    if max_pages == 1:
        return [0]
    slot = day.toordinal() % 7
    return [0] + [page_size * (1 + slot * (max_pages - 1) + i)
                  for i in range(max_pages - 1)]


def discover(*, fetch, tags: list[str], names: list[str],
             day: dt.date, page_size: int, max_pages: int,
             known_ids: set[str], sleep_seconds: float = 0.0) -> dict:
    queries = [("tag", x) for x in tags] + [("name", x) for x in names]
    if not queries or len(queries) > 40 or any(not q[1].strip() for q in queries):
        raise ValueError("Discovery query list must be bounded, nonempty and valid")
    if not 0 <= sleep_seconds <= 3:
        raise ValueError("Invalid crawl delay")
    offsets = page_offsets(day, page_size, max_pages)
    observed: dict[str, dict] = {}
    scan_log = []
    # Missing results are never a deletion signal; a failed query fails
    # the whole report rather than publishing an apparent empty catalog.
    for field, term in queries:
        seen_pages = 0
        for offset in offsets:
            records = fetch(field, term, offset, page_size)
            if not isinstance(records, list):
                raise ValueError("Bad discovery page")
            seen_pages += 1
            for raw in records:
                row = candidate(raw, known_ids)
                if row is None:
                    continue
                uid = row["stationuuid"]
                previous = observed.get(uid)
                if previous is None or (
                    previous["status"] == "needs_stream_check"
                    and row["status"] == "candidate_requires_qualification"
                ):
                    observed[uid] = row
            if len(records) < page_size:
                break
            if sleep_seconds:
                time.sleep(sleep_seconds)
        scan_log.append({"field": field, "term": term, "pagesRead": seen_pages})
    rows = sorted(observed.values(), key=lambda row: row["stationuuid"])
    annotate_duplicate_risks(rows)
    new = [r for r in rows if r["status"] != "already_known"]
    return {
        "schemaVersion": 1,
        "scanDate": day.isoformat(),
        "source": "Radio Browser",
        "suggestedGenreTags": suggest_related_tags(rows),
        "publicationAllowed": False,
        "qualifiedStreamCount": 0,
        "knownUuidInputCount": len(known_ids),
        "observedUniqueUuidCount": len(rows),
        "unrecognizedCandidateCount": len(new),
        "queries": scan_log,
        "candidates": new,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--known-uuids-file", type=Path)
    parser.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    parser.add_argument("--tags", help="Explicit diagnostic tag override; no rotation")
    parser.add_argument("--names", help="Explicit diagnostic name override; no rotation")
    parser.add_argument("--previous-report", type=Path,
                        help="Optional last candidate report for emerging genre tags")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--crawl-delay", type=float, default=0.15)
    args = parser.parse_args(argv)
    day = dt.date.fromisoformat(args.date)
    known = known_uuids(args.known_uuids_file)
    if args.tags is None and args.names is None:
        new_terms = previous_genre_hints(args.previous_report)
        selected_tags, selected_names = plan_daily_queries(
            day, list(DEFAULT_TAGS) + new_terms, list(DEFAULT_NAMES))
    else:
        selected_tags = [x.strip() for x in (args.tags or "").split(",") if x.strip()]
        selected_names = [x.strip() for x in (args.names or "").split(",") if x.strip()]
    hosts = resolve_api_mirrors()
    def remote(field: str, term: str, offset: int, limit: int) -> list[dict]:
        return fetch_page(hosts, field, term, offset, limit)
    report = discover(
        fetch=remote, tags=selected_tags, names=selected_names,
        day=day, page_size=args.page_size, max_pages=args.max_pages,
        known_ids=known, sleep_seconds=args.crawl_delay,
    )
    report["configuredGenreQueries"] = len(DEFAULT_TAGS) + len(DEFAULT_NAMES)
    report["selectedDailyQueries"] = len(selected_tags) + len(selected_names)
    report["coreQueries"] = len(CORE_TAGS) + len(CORE_NAMES)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"DISCOVERY_PREVIEW_ONLY date={day} unique={report['observedUniqueUuidCount']} "
          f"unrecognized={report['unrecognizedCandidateCount']} "
          f"published=false queries={len(report['queries'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
