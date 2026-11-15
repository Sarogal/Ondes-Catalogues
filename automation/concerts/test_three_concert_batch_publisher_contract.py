"""Offline parity of three independently verified Concerts across one intake.

Fictitious HTML only: this is a protocol regression, NOT real-world proof
of the named concerts or an authorization to publish them. No private data,
network access, approvals or venue-signatures from confidential repositories.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "automation" / "concerts"))

import concerts_cloud_sync as publisher
import approval_preflight as preflight
import official_recheck as engine
from test_rockstore_official_recheck import (
    PAGE as ROCKSTORE_HTML, candidate as rockstore_candidate,
    catalogue as rockstore_catalogue,
)
from test_backstage_recheck import candidate as backstage_candidate

NOW = dt.date(2026, 11, 15)


def catalogue():
    base = rockstore_catalogue()
    base["venues"].append({
        "id": "backstage-by-the-mill-paris",
        "name": "Backstage By The Mill", "city": "Paris",
        "latitude": 48.8842402, "longitude": 2.3321006,
    })
    base["artists"].append({
        "id": "employed-to-serve", "name": "Employed To Serve", "aliases": [],
    })
    return base


def backstage_fixture(artist, date):
    lead = backstage_candidate()
    year, month, day = date.split("-")
    slug = artist.casefold().replace(" ", "-")
    lead.update({
        "candidateId": "backstage:" + date + ":" + slug,
        "sourceUrl": "https://www.backstage-btm.com/agenda/" + slug + "/",
        "name": artist,
        "date": date,
        "classification": ["metalcore"],
    })
    official_page = (
        "<html><body><h1>" + artist + "</h1>"
        "<div>Metalcore</div><div>" + day + "/" + month + "/" + year + "</div>"
        "<div>O’Sullivans By The Mill, 92 bis bd de Clichy - Paris</div>"
        "</body></html>"
    )
    return lead, official_page


def proof_batch():
    rock = rockstore_candidate()
    blackgold, html_blackgold = backstage_fixture("BLACKGOLD", "2026-12-03")
    employed, html_employed = backstage_fixture("Employed To Serve", "2026-12-04")
    sources = {
        rock["sourceUrl"]: ROCKSTORE_HTML,
        blackgold["sourceUrl"]: html_blackgold,
        employed["sourceUrl"]: html_employed,
    }
    registry = {"items": {
        row["candidateId"]: {
            "status": "pending_review", "candidate": row,
            "observations": 2, "stableObservations": 2,
        } for row in (rock, blackgold, employed)
    }}
    return registry, sources


def review(catalog, registry, sources):
    queue = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
    calls = []
    def offline_fetch(url, robots_cache):
        calls.append(url)
        return sources[url]
    out, report = engine.process(registry, catalog, queue, NOW,
                                 fetch=offline_fetch, limit=10)
    return out, report, calls


class ThreeConcertBatchContractTests(unittest.TestCase):
    def test_three_distinct_official_verifiers_pass_real_publisher_validation(self):
        cat = catalogue()
        registry, sources = proof_batch()
        saved = copy.deepcopy((cat, registry))
        approvals, report, fetches = review(cat, registry, sources)
        self.assertEqual(report["evaluated"], 3)
        self.assertEqual(report["held"], [])
        self.assertEqual(len(report["newApprovals"]), 3)
        self.assertEqual(len(fetches), 3)
        self.assertEqual(len(set(fetches)), 3)

        known_venues = {v["id"]: v for v in cat["venues"]}
        known_artists = {a["id"]: a for a in cat["artists"]}
        approved_events = []
        added_artists = []
        for row in approvals["approvals"]:
            event, new = publisher.validate_approval(
                row, known_venues, known_artists, NOW)
            self.assertEqual(event, row["event"])
            self.assertEqual(event["status"], "confirmed")
            self.assertIsNone(event["time"])
            self.assertEqual(len(new), len(row["newArtists"]))
            known_artists.update(new)
            approved_events.append(event["id"])
            added_artists.extend(new)

        self.assertEqual(set(approved_events), {
            "go-c-20270521-montpellier-vulves-assassines",
            "go-c-20261203-paris-blackgold",
            "go-c-20261204-paris-employed-to-serve",
        })
        self.assertEqual(added_artists, ["blackgold"])
        self.assertNotIn("guest", known_artists)
        self.assertEqual((cat, registry), saved)

    def test_entire_three_event_batch_passes_real_merge_and_fail_closed_preflight(self):
        # A modified public fixture is used as BOTH baseline and current.
        # This is not a production snapshot, and it contains NO private
        # approval queue. The Backstage venue is copied from the public
        # catalogue solely to make the fixture's venue structurally complete.
        reference = json.loads(
            (ROOT / "docs" / "grossesondes" /
             "concerts-reference.json").read_text(encoding="utf-8"))
        published = json.loads(
            (ROOT / "docs" / "grossesondes" /
             "concerts.json").read_text(encoding="utf-8"))
        actual_backstage = next(v for v in published["venues"]
                                if v["id"] == "backstage-by-the-mill-paris")
        reference["venues"].append(copy.deepcopy(actual_backstage))
        current = copy.deepcopy(reference)
        registry, sources = proof_batch()
        reviewed, report, _ = review(current, registry, sources)
        self.assertEqual(len(report["newApprovals"]), 3)
        self.assertEqual(report["held"], [])

        before = {"schema": "grossesondes.concert.approvals.v1",
                  "approvals": []}
        current_saved = copy.deepcopy(current)
        ref_saved = copy.deepcopy(reference)
        queued, stats = publisher.merge(reference, current, reviewed, NOW)
        self.assertEqual(stats["held"], [])
        self.assertEqual(stats["newEvents"], 3)
        self.assertEqual(len(queued["events"]) - len(current["events"]), 3)

        preflight_stats = preflight.validate_proposal(
            before, reviewed, reference, current, NOW, publisher.merge)
        self.assertEqual(preflight_stats["publishableEvents"], 3)
        self.assertIs(preflight_stats["validatedByPublisher"], True)
        self.assertEqual(current, current_saved)
        self.assertEqual(reference, ref_saved)

    def test_one_incorrect_publisher_proof_stays_rejected_without_contaminating_others(self):
        cat = catalogue()
        registry, sources = proof_batch()
        approvals, report, _ = review(cat, registry, sources)
        self.assertEqual(report["held"], [])
        venue_ids = {v["id"]: v for v in cat["venues"]}
        artist_ids = {a["id"]: a for a in cat["artists"]}
        for row in approvals["approvals"]:
            if row["event"]["id"].endswith("-blackgold"):
                tampered = copy.deepcopy(row)
                tampered["officialEvidence"][0]["officialArtistNames"] = [
                    "Unverified Support"
                ]
                with self.assertRaises(ValueError):
                    publisher.validate_approval(
                        tampered, venue_ids, artist_ids, NOW)
            else:
                published, _ = publisher.validate_approval(
                    row, venue_ids, artist_ids, NOW)
                self.assertEqual(published, row["event"])

    def test_changed_official_event_detail_blocks_exactly_that_candidate(self):
        cat = catalogue()
        registry, sources = proof_batch()
        target = next(url for url in sources if url.endswith("/blackgold/"))
        sources[target] = sources[target].replace(
            "<div>Metalcore</div>", "<div>Pop</div>")
        approvals, report, _ = review(cat, registry, sources)
        self.assertEqual(len(report["newApprovals"]), 2)
        self.assertEqual(len(report["held"]), 1)
        self.assertIn("Genre", report["held"][0]["reason"])
        self.assertNotIn("go-c-20261203-paris-blackgold", report["newApprovals"])


if __name__ == "__main__":
    unittest.main()
