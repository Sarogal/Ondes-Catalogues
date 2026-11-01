import unittest
from scripts.grossesondes_concerts_approved_sync import merge


def fixtures():
    catalog = {"schemaVersion": 1, "mode": "preview-public-unlisted",
               "venues": [{"id": "v", "name": "Venue"}],
               "artists": [{"id": "a", "name": "Band A"}], "events": []}
    approval = {"schema": "grossesondes.concert.approvals.v1", "approvals": [{
        "reviewDecision": "approved", "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-01", "officialEvidence": [{
            "url": "https://official.example/show",
            "proofType": "official-organizer-or-venue",
            "checkedFields": ["artists", "date", "venue"]}],
        "event": {"id": "e1", "title": "Band A", "date": "2026-11-09",
                  "artistIds": ["a"], "venueId": "v", "status": "confirmed",
                  "genres": ["Metal"], "time": None, "officialUrl": "https://official.example/show"}
    }]}
    return catalog, approval


class SyncTests(unittest.TestCase):
    def test_add_and_idempotence(self):
        c, a = fixtures()
        first, report = merge(c, a)
        self.assertEqual(report["added"], ["e1"])
        self.assertEqual(len(c["events"]), 0)
        second, report2 = merge(first, a)
        self.assertEqual(report2["added"], [])
        self.assertEqual(first, second)

    def test_reject_unverified(self):
        c, a = fixtures()
        a["approvals"][0]["officialEvidence"] = []
        with self.assertRaises(ValueError):
            merge(c, a)

    def test_reject_unknown_venue(self):
        c, a = fixtures()
        a["approvals"][0]["event"]["venueId"] = "unknown"
        with self.assertRaises(ValueError):
            merge(c, a)

    def test_reject_conflicting_existing_id(self):
        c, a = fixtures()
        c["events"].append({"id": "e1", "date": "2026-11-10", "venueId": "v", "title": "Another"})
        with self.assertRaisesRegex(ValueError, "collision"):
            merge(c, a)


if __name__ == "__main__":
    unittest.main()
