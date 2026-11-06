"""Tests de l'archive cumulative privée des concerts."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import intake_archive as a


def candidate(cid="venue:x"):
    return {
        "candidateId": cid, "name": "Groupe",
        "date": "2027-03-04", "city": "Nantes",
        "sourceUrl": "https://example.org/events/1",
        "reviewRequired": True, "publicationAllowed": False
    }


def discovery(*rows):
    return {"schema": a.DISCOVERY_SCHEMA, "candidates": list(rows),
            "triageCounts": {"genre_unknown": len(rows)}}


class ArchiveTests(unittest.TestCase):
    def test_new_discovery_kept(self):
        data, stats = a.merge(None, discovery(candidate()), "2026-11-01T20:00:00Z")
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["total"], 1)
        self.assertEqual(data["items"]["venue:x"]["status"], "pending_review")

    def test_repeat_keeps_first_seen_and_decision(self):
        t0 = "2026-11-01T20:00:00Z"
        data, _ = a.merge(None, discovery(candidate()), t0)
        data["items"]["venue:x"]["status"] = "rejected"
        data2, stats = a.merge(data, discovery(candidate()), "2026-11-02T20:00:00Z")
        self.assertEqual(stats["seenAgain"], 1)
        self.assertEqual(data2["items"]["venue:x"]["status"], "rejected")
        self.assertEqual(data2["items"]["venue:x"]["firstSeenAt"], t0)
        self.assertEqual(data2["items"]["venue:x"]["observations"], 2)

    def test_missing_today_is_not_deleted(self):
        d, _ = a.merge(None, discovery(candidate()), "2026-11-01")
        d2, _ = a.merge(d, discovery(), "2026-11-02")
        self.assertIn("venue:x", d2["items"])
        self.assertEqual(d2["total"], 1)

    def test_reject_implicit_publication(self):
        bad = candidate()
        bad["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            a.merge(None, discovery(bad), "2026-11-01")

    def test_reject_duplicate_ids_or_truncated_result(self):
        with self.assertRaises(ValueError):
            a.merge(None, discovery(candidate(), candidate()), "2026-11-01")
        d = discovery(candidate())
        d["triageCounts"] = {"genre_unknown": 3}
        with self.assertRaises(ValueError):
            a.merge(None, d, "2026-11-01")

    def test_reject_unknown_registry(self):
        with self.assertRaises(ValueError):
            a.merge({"schema": "unknown", "items": {}}, discovery(), "2026-11-01")


if __name__ == "__main__":
    unittest.main()
