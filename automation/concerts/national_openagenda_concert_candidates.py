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
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import openagenda_official_concert as oa
import source_evidence_probe as probe

SCHEMA = "grossesondes.concert.discovery.v1"
SOURCE = ("https://public.opendatasoft.com/api/explore/v2.1/catalog/"
          "datasets/evenements-publics-openagenda/records")
SELECT = ("uid,canonicalurl,title_fr,description_fr,keywords_fr,"
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
    window = ("lastdate_begin >= date'" + today.isoformat() +
              "' AND firstdate_begin < date'" + end + "'")
    return [
        SOURCE + "?" + urlencode({
            "select": SELECT,
            "where": "(" + "search(" + field + ",\"" + term + "\")" +
                     ") AND " + window,
            "limit": str(PER_PAGE),
            "offset": str(((offset // len(SEEDS)) % 20) * PER_PAGE),
        })
        for field,term in (SEEDS[(offset + i) % len(SEEDS)]
                           for i in range(PER_CYCLE))
    ]


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
        fetch = probe.safe_fetch
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
