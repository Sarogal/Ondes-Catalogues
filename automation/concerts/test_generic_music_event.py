"""Fail-closed national structured-venue verifier/publisher integration tests.

No network, no production writes. One reviewed venue accepts many unrelated
concerts with many individually named new acts, without per-concert code.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation/concerts"))
sys.path.insert(0, str(ROOT / "scripts"))
import discover
import generic_music_event as gen
import official_recheck
import triage
from concerts_cloud_sync import validate_approval, merge

TODAY = dt.date(2026, 11, 19)
DATE = "2027-03-13"


def make(venue_id="la-rayonne", names=("ACT ONE", "ACT TWO"),
         kind="MusicEvent", genre=("Death Metal",)):
    spec = gen.SPECS[venue_id]
    url = spec["base"] + "evenement/verified-show-2027/"
    raw = {
        "@type": kind,
        "url": url, "name": " + ".join(names),
        "startDate": DATE + "T20:00:00+01:00",
        "genre": list(genre),
        "performer": [{"@type": "MusicGroup", "name": n} for n in names],
        "location": {"@type": "MusicVenue", "name": spec["name"],
                     "address": {"addressLocality": spec["city"],
                                 "addressCountry": "FR"}},
    }
    source = {"url": spec["base"], "name": spec["name"],
              "city": spec["city"], "department": spec["department"]}
    candidate = discover.venue_candidate(raw, source, url, set(),
                                         TODAY.isoformat())
    candidate = triage.triage(candidate, catalogue={})
    page = '<script type="application/ld+json">' + json.dumps(
        raw, ensure_ascii=False) + "</script>"
    venue = {"id": venue_id, "name": spec["name"],
             "city": spec["city"], "department": spec["department"]}
    catalogue = {"schemaVersion": 1, "mode": "preview-public-unlisted",
                 "venues": [venue], "artists": [], "events": []}
    return candidate, page, catalogue, raw


def publish(approval, catalogue):
    return validate_approval(
        approval, {v["id"]: v for v in catalogue["venues"]},
        {a["id"]: a for a in catalogue["artists"]}, TODAY,
    )


class GenericStructuredNationalContractTests(unittest.TestCase):
    def test_one_two_eight_twenty_and_fifty_two_new_acts_publish(self):
        for venue in gen.SPECS:
            for n in (1, 2, 8, 20, 52):
                with self.subTest(venue=venue, artists=n):
                    names = tuple("ACT %03d" % i for i in range(n))
                    lead, page, cat, _ = make(venue, names)
                    self.assertEqual(lead["reviewBucket"],
                                     "genre_tag_review")
                    app = official_recheck.verify(lead, page, cat, TODAY)
                    self.assertEqual(app["event"]["artistIds"],
                                     ["act-%03d" % i for i in range(n)])
                    self.assertEqual(len(app["newArtists"]), n)
                    self.assertEqual(app["officialEvidence"][0][
                        "officialArtistNames"], list(names))
                    self.assertIsNone(app["event"]["time"])
                    ev, added = publish(app, cat)
                    self.assertEqual(len(ev["artistIds"]), n)
                    self.assertEqual(len(added), n)

    def test_two_unrelated_future_concerts_from_same_venue_publish_without_patch(self):
        # Real publisher merge (not just validate_approval). A source-wide
        # contract admits multiple new first-party concerts across dates.
        base = json.loads((ROOT / "docs/grossesondes/concerts-reference.json")
                          .read_text(encoding="utf-8"))
        lead1, html1, _, _ = make(names=("ACT ONE", "ACT TWO"))
        app1 = official_recheck.verify(lead1, html1, base, TODAY)
        lead2, html2, _, raw2 = make(names=("ACT THREE", "ACT FOUR"))
        raw2["url"] = "https://larayonne.org/evenement/next-month-verified/"
        raw2["startDate"] = "2027-04-13T20:00:00+02:00"
        raw2["name"] = "ACT THREE + ACT FOUR"
        spec = gen.SPECS["la-rayonne"]
        src = {"name": spec["name"], "city": spec["city"],
               "department": spec["department"], "url": spec["base"]}
        lead2 = discover.venue_candidate(raw2, src, raw2["url"],
                                         set(), TODAY.isoformat())
        lead2 = triage.triage(lead2, catalogue=base)
        html2 = '<script type="application/ld+json">' + json.dumps(
            raw2) + '</script>'
        app2 = official_recheck.verify(lead2, html2, base, TODAY)
        queue = {"schema": "grossesondes.concert.approvals.v1",
                 "approvals": [app1, app2]}
        published, stats = merge(base, base, queue, TODAY)
        self.assertEqual(stats["newEvents"], 2)
        self.assertTrue(all(any(
            event["id"] == app["event"]["id"] for event in published["events"])
            for app in queue["approvals"]))
        again, repeated = merge(base, published, queue, TODAY)
        self.assertEqual(repeated["newEvents"], 0)
        self.assertEqual(again, published)

    def test_generic_event_with_explicit_metal_genre_may_pass(self):
        lead, page, cat, _ = make(kind="Event")
        app = official_recheck.verify(lead, page, cat, TODAY)
        self.assertEqual(app["event"]["genres"], ["Death Metal"])
        publish(app, cat)

    def test_known_headliner_new_support_and_unnamed_trailing_guest(self):
        lead, page, cat, _ = make(names=("ACT ONE", "ACT TWO", "Guest"))
        cat["artists"].append({"id": "act-one", "name": "ACT ONE", "aliases": []})
        app = official_recheck.verify(lead, page, cat, TODAY)
        self.assertEqual(app["event"]["title"], "ACT ONE + ACT TWO")
        self.assertEqual(app["newArtists"],
                         [{"id": "act-two", "name": "ACT TWO"}])
        self.assertEqual(app["officialEvidence"][0][
            "unannouncedSupportLabel"], "Guest")
        publish(app, cat)

    def test_mismatched_fresh_first_party_data_fails(self):
        lead, page, cat, raw = make()
        changed = [
            {"startDate": "2027-03-14T20:00:00+01:00"},
            {"performer": [{"@type": "MusicGroup", "name": "ACT ONE"}]},
            {"genre": ["Jazz"]},
            {"genre": ["Rock"]},
            {"eventStatus": "https://schema.org/EventCancelled"},
            {"url": gen.SPECS["la-rayonne"]["base"] + "evenement/other/"},
            {"location": {"name": "Another venue",
                          "address": {"addressLocality": "Paris",
                                      "addressCountry": "FR"}}},
        ]
        for delta in changed:
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                html = '<script type="application/ld+json">' + json.dumps(
                    {**raw, **delta}) + '</script>'
                official_recheck.verify(lead, html, cat, TODAY)

    def test_unknown_host_source_and_misleading_duplicate_event_fail(self):
        lead, page, cat, raw = make()
        for attr, value in (
            ("sourceUrl", "https://evil.example/evenement/verified-show-2027/"),
            ("sourceUrl", "https://larayonne.org/evenement/show/?tracking=1"),
            ("sourcePage", "https://tickets.example/agenda/"),
            ("venue", "Fake Venue"),
            ("city", "Paris"),
            ("department", "75"),
            ("reviewBucket", "genre_unknown"),
            ("publicationAllowed", True),
            ("possibleExistingConcert", True),
            ("source", "unknown_source"),
        ):
            with self.subTest(attr=attr), self.assertRaises(ValueError):
                official_recheck.verify({**lead, attr: value}, page, cat, TODAY)
        doubled = '<script type="application/ld+json">' + json.dumps(
            [raw, {**raw, "name": "Other concert"}]) + "</script>"
        with self.assertRaises(ValueError):
            official_recheck.verify(lead, doubled, cat, TODAY)

    def test_alias_artist_and_exact_event_collision_fail(self):
        lead, page, cat, _ = make()
        cat["artists"] = [{"id": "known", "name": "Elsewhere",
                           "aliases": ["ACT TWO"]}]
        with self.assertRaisesRegex(ValueError, "alias"):
            official_recheck.verify(lead, page, cat, TODAY)
        cat["artists"] = [{"id": "act-one", "name": "ACT ONE", "aliases": []}]
        cat["events"] = [{"id": "old", "date": DATE, "venueId": "la-rayonne",
                          "officialUrl": "https://other.example/previous/",
                          "artistIds": ["act-one"]}]
        with self.assertRaisesRegex(ValueError, "déjà publié"):
            official_recheck.verify(lead, page, cat, TODAY)

    def test_publisher_rejects_forged_artist_place_source_and_proof(self):
        lead, page, cat, _ = make()
        app = official_recheck.verify(lead, page, cat, TODAY)
        wrong = [
            ("event", "venueId", "le-metronum"),
            ("event", "officialUrl", "https://evil.example/other/"),
            ("event", "date", "2027-03-14"),
            ("event", "title", "ACT ONE + INVENTED"),
            ("event", "organizer", "Untrusted organizer"),
            ("event", "time", "20:00"),
            ("event", "genres", ["Jazz"]),
            ("officialEvidence", "officialArtistNames", ["ACT ONE", "FRAUD"]),
            ("officialEvidence", "sourceStructure", "untrusted"),
            ("officialEvidence", "verifiedVenueId", "le-metronum"),
        ]
        for part, key, value in wrong:
            with self.subTest(part=part, key=key), self.assertRaises(ValueError):
                altered = copy.deepcopy(app)
                if part == "event":
                    altered["event"][key] = value
                else:
                    altered["officialEvidence"][0][key] = value
                publish(altered, cat)

    def test_two_day_stability_and_foreign_host_rejected_before_fetch(self):
        lead, page, cat, _ = make()
        row = {"candidate": lead, "status": "pending_review",
               "stableObservations": 1}
        reg = {"items": {"lead": row}}
        empty = {"schema": "grossesondes.concert.approvals.v1",
                 "approvals": []}
        no_network = lambda *_: self.fail("No fetch required")
        out, report = official_recheck.process(
            reg, cat, empty, TODAY, fetch=no_network)
        self.assertEqual(report["evaluated"], 0)
        self.assertEqual(out["approvals"], [])
        row["stableObservations"] = 2
        checked, report = official_recheck.process(
            reg, cat, empty, TODAY, fetch=lambda *_: page)
        self.assertEqual(report["newApprovals"],
                         [checked["approvals"][0]["event"]["id"]])
        publish(checked["approvals"][0], cat)
        row["candidate"] = {**lead,
                            "sourceUrl": "https://evil.example/show/"}
        bad, report = official_recheck.process(
            reg, cat, empty, TODAY, fetch=no_network)
        self.assertEqual(report["newApprovals"], [])
        self.assertEqual(len(report["held"]), 1)
        self.assertEqual(bad["approvals"], [])


if __name__ == "__main__":
    unittest.main()
