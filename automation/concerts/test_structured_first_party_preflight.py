"""Offline contract tests: generic first-party structural recheck never signs."""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover
import structured_first_party_preflight as module
import triage

TODAY = dt.date(2026, 11, 18)
URL = "https://venue.example/concerts/metal-surface-2027/"
SOURCE = {"name": "La Salle", "city": "Nîmes", "department": "30",
          "url": "https://venue.example/agenda/", "priority": "P1"}
SOURCES = {"schema": "grossesondes.concert.sourcelist.v1",
           "venues": [SOURCE]}
CATALOGUE = {"schemaVersion": 1, "mode": "preview-public-unlisted",
             "events": [], "artists": [], "venues": []}
APPROVALS = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}


def event_data(**changes):
    e = {"@type": "MusicEvent", "name": "Metal Surface + Nouveau Groupe",
         "url": URL, "startDate": "2027-03-20T20:00:00+01:00",
         "genre": ["Death Metal"],
         "performer": [
             {"@type": "MusicGroup", "name": "Metal Surface"},
             {"@type": "MusicGroup", "name": "Nouveau Groupe"},
         ],
         "location": {"@type": "MusicVenue", "name": SOURCE["name"],
                      "address": {"addressLocality": SOURCE["city"],
                                  "addressCountry": "FR"}}}
    e.update(changes)
    return e


def page(**changes):
    return ('<html><script type="application/ld+json">'
            + json.dumps(event_data(**changes), ensure_ascii=False)
            + '</script></html>')


def candidate():
    row = discover.venue_candidate(
        event_data(), SOURCE, SOURCE["url"], set(), TODAY.isoformat())
    return triage.triage(row, catalogue=CATALOGUE)


def registry(rows=None):
    rows = rows or [candidate()]
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {
                str(i): {"candidate": row, "status": "pending_review",
                         "stableObservations": 2}
                for i, row in enumerate(rows)
            }}


def run(reg=None, source_list=None, catalogue=None, approved=None,
        fetch=None, robots=None, limit=8):
    return module.build(
        reg if reg is not None else registry(),
        source_list if source_list is not None else SOURCES,
        catalogue if catalogue is not None else CATALOGUE,
        approved if approved is not None else APPROVALS, TODAY,
        fetch=fetch if fetch is not None else (
            lambda url, **kwargs: (page(), url)),
        robots=robots if robots is not None else (
            lambda url, cache: True),
        limit=limit)


class StructuredIndependentPreflightTests(unittest.TestCase):
    def test_valid_official_structure_is_only_evidence_not_approval(self):
        original = registry()
        before = json.dumps(original, ensure_ascii=False, sort_keys=True)
        result = run(reg=original)
        self.assertEqual(result["eligible"], 1)
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["structureMatched"], 1)
        self.assertEqual(result["results"][0]["status"],
                         "independent_structure_matched")
        self.assertEqual(result["approvalsProposed"], 0)
        self.assertFalse(result["publicationAllowed"])
        self.assertFalse(result["results"][0]["publicationAllowed"])
        self.assertEqual(json.dumps(original, ensure_ascii=False,
                                    sort_keys=True), before)

    def test_changed_official_performer_date_or_venue_is_held(self):
        variants = [
            {"performer": [
                {"@type": "MusicGroup", "name": "Metal Surface"},
                {"@type": "MusicGroup", "name": "Autre Groupe"}]},
            {"startDate": "2027-03-21T20:00:00+01:00"},
            {"location": {"name": "Autre salle",
                           "address": {"addressLocality": "Nîmes"}}},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                result = run(fetch=lambda url, **kw: (page(**changes), url))
                self.assertEqual(result["structureMatched"], 0)
                self.assertEqual(result["results"][0]["status"], "held")

    def test_unknown_venue_or_cross_origin_is_never_fetched(self):
        fail_fetch = lambda url, **kw: self.fail("Must not request untrusted source")
        unmatched = {**SOURCES, "venues": []}
        report = run(source_list=unmatched, fetch=fail_fetch)
        self.assertEqual(report["reasonCounts"],
                         {"source_not_independently_mapped": 1})
        moved = candidate()
        moved["sourceUrl"] = "https://attacker.example/concerts/metal/"
        report = run(reg=registry([moved]), fetch=fail_fetch)
        self.assertEqual(report["structureMatched"], 0)

    def test_robots_and_redirect_are_fail_closed(self):
        blocked = run(robots=lambda url, cache: False,
                      fetch=lambda url, **kw: self.fail("Robots disallow"))
        self.assertEqual(blocked["reasonCounts"], {"robots_restricted": 1})
        redirected = run(fetch=lambda url, **kw: (
            page(), "https://attacker.example/events/bad"))
        self.assertEqual(redirected["structureMatched"], 0)
        self.assertEqual(redirected["reasonCounts"],
                         {"structured_event_proof_missing_or_ambiguous": 1})

    def test_preflight_excludes_unstable_expired_decided_and_published(self):
        original = candidate()
        row = registry([original])
        row["items"]["0"]["stableObservations"] = 1
        self.assertEqual(run(reg=row)["attempted"], 0)
        row["items"]["0"]["stableObservations"] = 2
        row["items"]["0"]["status"] = "rejected"
        self.assertEqual(run(reg=row)["attempted"], 0)
        existing = {
            "officialUrl": URL, "date": original["date"]}
        published = {**CATALOGUE, "events": [existing]}
        self.assertEqual(run(catalogue=published)["attempted"], 0)
        approved = {**APPROVALS, "approvals": [{
            "reviewDecision": "approved", "event": existing}]}
        self.assertEqual(run(approved=approved)["attempted"], 0)

    def test_generic_rock_never_claims_genre_confirmed(self):
        original = candidate()
        original["classification"] = ["Rock"]
        original["reviewBucket"] = "genre_unknown"
        self.assertEqual(run(reg=registry([original]))["attempted"], 0)

    def test_budget_and_rotation_examine_distinct_candidates(self):
        originals = []
        for i in range(20):
            row = candidate()
            row["candidateId"] = f"synthetic-{i:02d}"
            row["sourceUrl"] = f"https://venue.example/concerts/show-{i:02d}/"
            originals.append(row)
        fetched = []
        def fetch(url, **kwargs):
            fetched.append(url)
            return "<html>NO MUSIC EVENT</html>", url
        report = run(reg=registry(originals), fetch=fetch, limit=8)
        self.assertEqual(report["attempted"], 8)
        self.assertEqual(len(fetched), 8)
        self.assertEqual(report["structureMatched"], 0)
        with self.assertRaises(ValueError):
            run(limit=13)

    def test_corrupt_schema_fails_closed(self):
        for bad in ({"schema": "something-else", "items": {}},
                    {"schema": "grossesondes.concert.intake.v1",
                     "items": []}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    run(reg=bad)


if __name__ == "__main__":
    unittest.main()
