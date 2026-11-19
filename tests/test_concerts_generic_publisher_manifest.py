"""Independent publisher contract for a data-driven first-party venue manifest.

Only an explicit code-reviewed manifest permits new domain/prefix pairs;
no event name/date/artist appears in the allowlist. A synthetic additional
venue exercises the REAL verifier and REAL publisher with no network or writes.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation/concerts"))
sys.path.insert(0, str(ROOT / "scripts"))
import discover
import generic_music_event as verifier
import published_watch as watcher
import triage
import concerts_cloud_sync as publisher

TODAY = dt.date(2026, 11, 19)


class IndependentGenericPublisherManifestTests(unittest.TestCase):
    def setUp(self):
        self.base = json.loads(verifier.MANIFEST.read_text(encoding="utf-8"))

    def tearDown(self):
        publisher.read_generic_structured_specs.cache_clear()

    def test_publisher_and_verifier_have_independent_matching_reviews(self):
        approved = publisher.read_generic_structured_specs()
        self.assertEqual(set(approved), set(verifier.SPECS))
        for venue_id, spec in verifier.SPECS.items():
            self.assertEqual(approved[venue_id]["host"], spec["host"])
            self.assertEqual(approved[venue_id]["eventPathPrefix"],
                             spec["eventPathPrefix"])
            self.assertIn(venue_id, watcher.SOURCES)
            self.assertEqual(watcher.SOURCES[venue_id][0], spec["host"])
            self.assertTrue(watcher.SOURCES[venue_id][1].fullmatch(
                spec["eventPathPrefix"] + "upcoming-metal-show-2027/"))
            self.assertFalse(watcher.SOURCES[venue_id][1].fullmatch(
                "/other/unknown-show/"))

    def _manifest(self, data):
        folder = tempfile.TemporaryDirectory()
        path = Path(folder.name) / "generic.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return folder, path

    def test_new_reviewed_venue_can_publish_two_unrelated_bills_without_code_patch(self):
        new = {"name": "Salle Autonomie", "city": "Angers",
               "department": "49", "host": "music.example",
               "base": "https://music.example/",
               "eventPathPrefix": "/agenda/concerts/"}
        manifest = copy.deepcopy(self.base)
        manifest["venues"]["salle-autonomie"] = new
        holder, path = self._manifest(manifest)
        try:
            reviewed = verifier.load_specs(path)
            with patch.object(verifier, "SPECS", reviewed), patch.object(
                    publisher, "GENERIC_STRUCTURED_SPECS_PATH", path):
                publisher.read_generic_structured_specs.cache_clear()
                for count, day in ((2, "2027-03-13"), (21, "2027-04-13")):
                    with self.subTest(performers=count):
                        names = ["ARTIST %03d" % i for i in range(count)]
                        url = (new["base"] + "agenda/concerts/" +
                               "show-of-" + day + "/")
                        raw = {
                            "@type": "MusicEvent",
                            "url": url,
                            "name": " + ".join(names),
                            "startDate": day + "T20:00:00+01:00",
                            "genre": ["Death Metal"],
                            "performer": [{"@type": "MusicGroup", "name": n}
                                          for n in names],
                            "location": {
                                "@type": "MusicVenue", "name": new["name"],
                                "address": {"addressLocality": new["city"],
                                            "addressCountry": "FR"}}}
                        html = ('<script type="application/ld+json">' +
                                json.dumps(raw) + '</script>')
                        cand = discover.venue_candidate(
                            raw, {"name": new["name"], "city": new["city"],
                                  "department": new["department"],
                                  "url": new["base"]},
                            url, set(), TODAY.isoformat())
                        cand = triage.triage(cand, catalogue={})
                        cat = {"schemaVersion": 1, "mode": "preview-public-unlisted",
                               "artists": [], "events": [],
                               "venues": [{"id": "salle-autonomie",
                                           "name": new["name"],
                                           "city": new["city"],
                                           "department": new["department"]}]}
                        approval = verifier.verify(cand, html, cat, TODAY)
                        event, new_artists = publisher.validate_approval(
                            approval, {v["id"]: v for v in cat["venues"]},
                            {}, TODAY)
                        self.assertEqual(len(new_artists), count)
                        self.assertEqual(len(event["artistIds"]), count)
                        self.assertEqual(event["organizer"], new["name"])
                        self.assertEqual(event["date"], day)
        finally:
            holder.cleanup()

    def test_wrong_prefix_host_and_venue_cannot_gain_publication_authority(self):
        data = copy.deepcopy(self.base)
        holder, path = self._manifest(data)
        try:
            with patch.object(publisher, "GENERIC_STRUCTURED_SPECS_PATH", path):
                publisher.read_generic_structured_specs.cache_clear()
                specs = publisher.read_generic_structured_specs()
                self.assertNotIn("evil-venue", specs)
                for venue_id, spec in specs.items():
                    candidate = {"venue": spec["name"],
                                 "city": spec["city"],
                                 "department": spec["department"],
                                 "sourceUrl": spec["base"] +
                                     "unreviewed/path/metal-concert/"}
                    self.assertIsNone(verifier.trusted_spec(candidate))
            broken = copy.deepcopy(data)
            broken["venues"]["la-rayonne"]["eventPathPrefix"] = "/../"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.object(publisher, "GENERIC_STRUCTURED_SPECS_PATH", path):
                publisher.read_generic_structured_specs.cache_clear()
                with self.assertRaises(ValueError):
                    publisher.read_generic_structured_specs()
        finally:
            holder.cleanup()


if __name__ == "__main__":
    unittest.main()
