"""Regression: a national Concerts discovery batch must never be silently truncated.

All events and sources are synthetic. No network, private approvals or
publication is involved.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover
import intake_archive


class CompleteDiscoveryBatchTests(unittest.TestCase):
    def test_more_than_1000_distinct_candidates_survive_discovery_and_private_archive(self):
        # Above the former 1000-row cap; each candidate must remain quarantined.
        count = 1205
        discovered = [{
            "candidateId": f"synthetic:venue:2027-06-18:band-{i}",
            "source": "agenda_officiel_structuré",
            "sourceUrl": f"https://official.example/events/band-{i}",
            "date": "2027-06-18",
            "name": f"Metal Band {i}",
            "leadArtist": f"Metal Band {i}",
            "venue": "Salle officielle fictive",
            "city": "Rennes",
            "department": "35",
            "classification": ["Metal"],
            "genreToConfirm": False,
            "reviewRequired": True,
            "publicationAllowed": False,
        } for i in range(count)]
        catalogue = {"schemaVersion": 1, "mode": "preview-public-unlisted",
                     "events": [], "artists": [], "venues": []}

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(discover, "today_fr", return_value=dt.date(2026, 11, 18)), \
             mock.patch.object(discover, "json_url", side_effect=lambda url: catalogue if url == discover.CATALOG else {}), \
             mock.patch.object(discover, "scan_venues", return_value=discovered), \
             mock.patch.object(discover, "scan_partner_ics", return_value=[]), \
             mock.patch.object(discover, "scan_ticketmaster", return_value=[]), \
             mock.patch.object(discover.ticketmaster_venue_probes, "probe", return_value=([], [])), \
             mock.patch.object(sys, "argv", ["discover", "--output", tmp]):
            self.assertEqual(discover.main(), 0)
            review = json.loads((Path(tmp) / "candidates.json").read_text(encoding="utf-8"))
            shortlist = json.loads((Path(tmp) / "shortlist.json").read_text(encoding="utf-8"))

        self.assertEqual(len(review["candidates"]), count)
        self.assertEqual(len(shortlist["candidates"]), count)
        self.assertEqual(shortlist["count"], count)
        self.assertEqual(sum(review["triageCounts"].values()), count)
        self.assertEqual(
            len({row["candidateId"] for row in review["candidates"]}), count)
        self.assertTrue(all(row["publicationAllowed"] is False and
                            row["reviewRequired"] is True
                            for row in review["candidates"]))

        # The real private archive requires exactly the reported rows.
        registry, summary = intake_archive.merge(
            None, review, "2026-11-18T18:00:00+00:00")
        self.assertEqual(summary["added"], count)
        self.assertEqual(registry["total"], count)
        self.assertTrue(all(row["status"] == "pending_review"
                            for row in registry["items"].values()))


if __name__ == "__main__":
    unittest.main()
