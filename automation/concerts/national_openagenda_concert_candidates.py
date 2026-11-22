#!/usr/bin/env python3
"""Nationwide OpenAgenda discovery; the ORIGINAL public event page is authority.

OpenDataSoft is an INDEX ONLY. Its title, date, genre, venue and coordinates
never sign a public concert. Every private lead is quarantined until a
separately fetched HTTPS openagenda.com page proves the exact Event and the
Publisher repeats the check. No fixed artist, city, room or organizer list.
"""
from __future__ import annotations
import argparse
import datetime as dt
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automation.concerts import openagenda_official_concert as oa
from automation.concerts import source_evidence_probe as probe

SCHEMA = "grossesondes.concert.discovery.v1"
SOURCE = ("https://public.opendatasoft.com/api/explore/v2.1/catalog/"
          "datasets/evenements-publics-openagenda/records")
SELECT = ("uid,originagenda_uid,slug,canonicalurl,title_fr,description_fr,keywords_fr,"
          "firstdate_begin,lastdate_begin,location_name,location_city,"
          "location_postalcode,location_department,location_countrycode,status")
# These are BROAD query seeds, not an exhaustive genre whitelist. Unfamiliar
# artists, styles and venues can be admitted by the actual OpenAgenda Event.
SEEDS = (
    ("title_fr", "concert"),
    ("title_fr", "metal"), ("title_fr", "punk"),
    ("description_fr", "metal"), ("description_fr", "punk"),
    ("description_fr", "hard rock"), ("description_fr", "rock"),
    ("description_fr", "metalcore"), ("description_fr", "hardcore"),
    ("keywords_fr", "concert"),
)
PER_PAGE = 12
PER_CYCLE = 5
# A documented public data API is a bounded JSON client, NOT a general
# website crawler. Every event is independently verified at openagenda.com.
INDEX_HOST = "public.opendatasoft.com"
COUNTRIES = frozenset({"FR","GP","MQ","GF","RE","YT","NC","PF",
                       "WF","PM","BL","MF"})
MUSIC = re.compile(r"\b(metal|punk|hard ?rock|metalcore|thrash|deathcore|"
                   r"black metal|heavy metal|grindcore|stoner|grunge|"
                   r"hardcore|post punk)\b", re.I)
NON_CONCERT = re.compile(r"\b(festival|festi(?:val)?|exposition|"
                         r"conference|visite|atelier|spectacle jeune public)\b",
                         re.I)


def urls(today, slot):
    if (not isinstance(today, dt.date) or isinstance(today, dt.datetime)
            or type(slot) is not int or not 0 <= slot <= 2):
        raise ValueError("OpenAgenda: invalid scan parameters")
    # rotate every cycle across searches AND pages; no fixed first 12 results.
    offset = today.toordinal() * 3 + slot
    end = (today + dt.timedelta(days=366)).isoformat()
    # The public mirror mixes historical and upcoming events. Query future
    # FIRST dates directly so a 2022 exhibition cannot crowd out 2026 shows.
    window = ("firstdate_begin >= date'" + today.isoformat() +
              "' AND firstdate_begin < date'" + end + "'")
    queries = []
    for i in range(PER_CYCLE):
        field, term = SEEDS[(offset + i) % len(SEEDS)]
        queries.append(SOURCE + "?" + urlencode({
            "select": SELECT,
            "where": "(search(" + field + ',\"' + term + '\")) AND ' + window,
            "limit": str(PER_PAGE),
            # Always scan the nearest public page first; additional rotating
            # pages avoid a permanent closed results window over successive
            # runs without starving new events in small regional agendas.
            "offset": str(0 if i < 3 else
                          ((offset // len(SEEDS)) % 20) * PER_PAGE),
        }))
    return queries


def fetch_index_api(url, cache):
    """Only call the public Opendatasoft dataset's documented JSON API.

    Never generalize this exception to arbitrary websites or sources:
    ordinary concert pages still use probe.safe_fetch with robots controls.
    Exactly five bounded, locally assembled API requests per scan.
    DNS pinning, global-IP validation, TLS validation, no redirects and a
    response-size cap remain identical to the general probe.
    """
    if (not isinstance(url, str) or not url.startswith(SOURCE + "?")
            or len(url) > 4000):
        raise ValueError("OpenAgenda index URL outside documented endpoint")
    parsed = urlsplit(url)
    if (parsed.hostname != INDEX_HOST or parsed.username or parsed.password
            or parsed.port or parsed.fragment):
        raise ValueError("OpenAgenda index origin invalid")
    if INDEX_HOST not in cache:
        cache[INDEX_HOST] = probe.public_ip_addresses(INDEX_HOST)[0]
    status, text = probe.request_pinned(
        url, INDEX_HOST, cache[INDEX_HOST], cap=probe.MAX_BYTES)
    if status != 200:
        raise ValueError("OpenAgenda public dataset API unavailable")
    return text


def _day(value):
    if not isinstance(value, str) or not value[:10].startswith("20"):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def candidate(row, today, published):
    if not isinstance(row, dict):
        return None
    url = row.get("canonicalurl")
    title = row.get("title_fr")
    venue = row.get("location_name")
    city = row.get("location_city")
    day = _day(row.get("firstdate_begin"))
    last = _day(row.get("lastdate_begin"))
    # OpendataSoft supplies ONLY a locator. The official OpenAgenda JSON
    # export independently rechecks both numeric IDs before publication.
    event_uid = str(row.get("uid") or "")
    agenda_uid = str(row.get("originagenda_uid") or "")
    if not (event_uid.isascii() and event_uid.isdecimal()
            and agenda_uid.isascii() and agenda_uid.isdecimal()
            and 1 <= len(event_uid) <= 12
            and 1 <= len(agenda_uid) <= 12
            and int(event_uid) and int(agenda_uid)):
        return None
    if (not oa.is_openagenda_event_url(url)
            or not all(isinstance(x, str) and 2 <= len(x.strip()) <= 250
                       for x in (title, venue, city))
            or row.get("location_countrycode") not in COUNTRIES
            or day is None or day < today
            or last is None or last < day
            or (url, day.isoformat()) in published):
        return None
    if NON_CONCERT.search(title):
        return None  # The Festivals engine handles editions separately.
    genre_signal = (title + " " + str(row.get("description_fr") or "")[:500])
    genre_hint = bool(MUSIC.search(genre_signal))
    # An empty hint is research priority only; final source must establish
    # an explicit event-scoped genre and the full artist names.
    ident = "oa:" + sha256(
        (url + "\n" + day.isoformat()).encode("utf-8")).hexdigest()[:24]
    lead = title.split(" + ")[0].strip()
    return {
        "candidateId": ident, "source": "agenda_officiel_openagenda",
        "sourceUrl": url, "sourcePage": url, "eventDetailUrl": url,
        "date": day.isoformat(), "name": title, "leadArtist": lead,
        "openAgendaEventUid": event_uid, "openAgendaUid": agenda_uid,
        "venue": venue.strip(), "city": city.strip(),
        "reviewBucket": ("genre_tag_review" if genre_hint
                         else "genre_unknown"),
        "classification": [],
        "possibleExistingConcert": False,
        "reviewRequired": True, "publicationAllowed": False,
        "officialDetailFound": False, "genreToConfirm": True,
    }


def build(catalogue, today, *, slot=0, fetch=None):
    if (not isinstance(catalogue, dict) or
            not isinstance(catalogue.get("events"), list)):
        raise ValueError("OpenAgenda: missing public catalogue")
    if fetch is None:
        fetch = fetch_index_api
    published = {(e.get("officialUrl"), e.get("date"))
                 for e in catalogue["events"] if isinstance(e, dict)}
    found, failures = {}, 0
    cache = {}
    for url in urls(today, slot):
        try:
            body = fetch(url, cache)
            if not isinstance(body, str) or not 2 <= len(body) <= probe.MAX_BYTES:
                raise ValueError("Invalid ODS read budget")
            data = json.loads(body)
            rows = data.get("results")
            if not isinstance(rows, list) or len(rows) > PER_PAGE:
                raise ValueError("Invalid ODS results")
            for row in rows:
                item = candidate(row, today, published)
                if item is not None:
                    found.setdefault(item["candidateId"], item)
        except (ValueError, OSError, TimeoutError, TypeError):
            failures += 1
            continue
    choices = list(found.values())
    # Discovery is NOT admission; no result may carry an approval.
    return {
        "schema": SCHEMA, "publicationAllowed": False,
        "automaticPublication": False, "asOf": today.isoformat(),
        "source": "OpenAgenda public index - research only",
        "candidates": choices,
        "triageCounts": {"unverified_official_agenda": len(choices)},
        "failedPublicIndexRequests": failures,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--slot", type=int, choices=(0, 1, 2))
    args = parser.parse_args()
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    slot = args.slot if args.slot is not None else (
        dt.datetime.now(ZoneInfo("Europe/Paris")).hour // 8)
    public = json.loads(args.catalogue.read_text(encoding="utf-8"))
    data = build(public, today, slot=slot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "source": "OpenAgenda index", "leads": len(data["candidates"]),
        "failedRequests": data["failedPublicIndexRequests"],
        "publicWrites": 0,
    }))


if __name__ == "__main__":
    main()
