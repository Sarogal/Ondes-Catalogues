#!/usr/bin/env python3
"""One-off PUBLIC and READ-ONLY live rehearsal of three venue-wide verifiers.

The three public show URLs below are regression examples, not allowlists for
production. No private inputs, approvals, ledger writes or publication.
An official live page is fetched *again* and independently rechecked with
the exact publisher gate against the existing public catalogue.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "concerts"))
sys.path.insert(0, str(ROOT / "scripts"))

import bbc_adapter
import bonjour_minuit_adapter
import cave_poetes_adapter
import official_recheck
from concerts_cloud_sync import validate_approval


def one_case(kind, url, spec, html, today):
    if kind == "bbc":
        source = {"name": "Big Band Café", "city": "Hérouville-Saint-Clair",
                  "department": "14", "url": bbc_adapter.AGENDA}
        candidate = bbc_adapter.candidate(html, url, source, today.isoformat())
    elif kind == "cave":
        source = {"name": "La Cave aux Poètes", "city": "Roubaix",
                  "department": "59", "url": "https://caveauxpoetes.com/agenda/"}
        original_card = {
            "date": spec["date"], "artists": ["Dewaere", "DALAÏDRAMA"],
            "venue": "La Cave aux Poètes", "status": "",
        }
        candidate = cave_poetes_adapter.candidate(
            html, url, original_card, source, today.isoformat())
    elif kind == "bonjour":
        source = {"name": "Bonjour Minuit", "city": "Saint-Brieuc",
                  "department": "22", "url": bonjour_minuit_adapter.AGENDA}
        candidate = bonjour_minuit_adapter.candidate(
            html, url, source, today.isoformat())
    else:
        raise ValueError("Unrecognized rehearsal venue")

    # Independently enforce the publicly verified expected fixture.
    if candidate["date"] != spec["date"]:
        raise ValueError(kind + ": official date is different")
    if candidate.get("classification") != spec["genres"]:
        raise ValueError(kind + ": first-party genre is different")
    if candidate.get("sourceUrl") != url:
        raise ValueError(kind + ": first-party URL was substituted")
    candidate.update({"reviewBucket": "genre_tag_review",
                      "possibleExistingConcert": False})
    return candidate


def run():
    today = dt.date.today()
    catalogue = json.loads(
        (ROOT / "docs" / "grossesondes" / "concerts.json").read_text(
            encoding="utf-8"))
    if catalogue.get("schemaVersion") != 1:
        raise ValueError("Unexpected public catalogue schema")

    cases = [
        ("bbc", "https://bigbandcafe.com/svinkels-family-friends/",
         {"date": "2026-12-12", "genres": ["Punk"],
          "title": "Svinkels + DOMINIQUE FÉVRIER", "artists": 2, "time": None}),
        ("cave", "https://caveauxpoetes.com/evenement/dalaidrama-dewaere/",
         {"date": "2027-02-12", "genres": ["Punk"],
          "title": "Dewaere + DALAÏDRAMA", "artists": 2, "time": "20:00"}),
        ("bonjour", "https://bonjour-minuit.fr/evenement/novodata-12fev27/",
         {"date": "2027-02-12", "genres": ["Rock"],
          "title": "Novö Data + Barre à Mine", "artists": 2, "time": None}),
    ]
    cache = {}
    results = []
    for kind, url, expected in cases:
        if dt.date.fromisoformat(expected["date"]) <= today:
            raise ValueError(kind + ": a historical live fixture expired")
        try:
            # The existing official downloader enforces robots, HTTPS, host and size.
            html = official_recheck.download_official(url, cache)
            candidate = one_case(kind, url, expected, html, today)
            approval = official_recheck.verify(
                candidate, html, copy.deepcopy(catalogue), today)
            event, new_artists = validate_approval(
                approval,
                {v["id"]: v for v in catalogue["venues"]},
                {a["id"]: a for a in catalogue["artists"]}, today)
            if len(event["artistIds"]) != expected["artists"]:
                raise ValueError(kind + ": incomplete named lineup")
            if event.get("time") != expected["time"]:
                raise ValueError(kind + ": unproved musical start")
            if event.get("date") != expected["date"] or event.get("genres") != expected["genres"]:
                raise ValueError(kind + ": publisher modified verified date or genre")
            if event["title"].casefold() != expected["title"].casefold():
                raise ValueError(kind + ": published act names do not match expected lineup")
            if any(e["id"] == event["id"] or e.get("officialUrl") == url
                   for e in catalogue["events"]):
                raise ValueError(kind + ": duplicate already published")
            results.append({"venue": kind, "publisherAccepts": True,
                            "eventId": event["id"],
                            "lineupArtistCount": len(event["artistIds"]),
                            "newArtistCount": len(new_artists),
                            "time": event["time"]})
        except Exception as exc:
            results.append({"venue": kind, "publisherAccepts": False,
                            "failure": type(exc).__name__ + ": " + str(exc)[:160]})
    print(json.dumps({"mode": "live-read-only-no-private-ledger",
                      "asOf": today.isoformat(), "results": results},
                     ensure_ascii=False, sort_keys=True), flush=True)
    if len(results) != 3 or not all(x["publisherAccepts"] for x in results):
        raise RuntimeError("Live rehearsal incomplete; no approval or publication")


if __name__ == "__main__":
    run()
