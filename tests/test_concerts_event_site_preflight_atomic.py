"""Real publisher + private append-only gate for an outdoor event location.

All event and geography data are synthetic. Nothing is sent to the network or
written to an actual private/public catalogue.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation/concerts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_preflight as gate
from scripts import concerts_cloud_sync as publisher
from test_concerts_event_site_publisher import fixtures, TODAY


class EventSiteAtomicRealPublisherTests(unittest.TestCase):
    def setUp(self):
        self.reference = json.loads(
            publisher.REFERENCE.read_text(encoding="utf-8"))
        self.current = copy.deepcopy(self.reference)
        self.location, self.signed_events = fixtures()
        self.before = {
            "schema": publisher.SCHEMA,
            "approvals": [], "venueApprovals": [],
        }
        self.proposed = {
            "schema": publisher.SCHEMA,
            "approvals": copy.deepcopy(self.signed_events),
            "venueApprovals": [copy.deepcopy(self.location)],
        }

    def test_independent_event_and_location_are_published_atomically(self):
        source = copy.deepcopy((self.before, self.proposed, self.current))
        result = gate.validate_proposal(
            self.before, self.proposed, self.reference,
            self.current, TODAY, publisher.merge)
        self.assertTrue(result["validatedByPublisher"])
        self.assertEqual(result["newApprovals"], 1)
        self.assertEqual(result["publishableEvents"], 1)
        self.assertEqual(source, (self.before, self.proposed, self.current))

    def test_independent_event_without_paired_site_cannot_bypass_normal_gate(self):
        data = copy.deepcopy(self.proposed)
        data["venueApprovals"] = []
        with self.assertRaises(ValueError):
            gate.check_append_only(self.before, data, TODAY)

    def test_wrong_event_or_site_proofs_cannot_be_persisted(self):
        for name, modify in (
            ("music-genre", lambda p: p["approvals"][0]["event"].update(
                genres=["Pop"])),
            ("gps-mismatch", lambda p: p["venueApprovals"][0]["venue"].update(
                latitude=47.1)),
            ("wrong-location-source", lambda p: p["venueApprovals"][0]["officialEvidence"][1].update(
                url="https://www.openstreetmap.org/way/999")),
            ("unsafe-artist-source", lambda p: p["venueApprovals"][0]["eventBinding"].update(
                authoritySourceUrl="https://unverified.example/tour")),
        ):
            with self.subTest(name=name):
                data = copy.deepcopy(self.proposed)
                modify(data)
                with self.assertRaises(ValueError):
                    gate.validate_proposal(self.before, data, self.reference,
                                           self.current, TODAY, publisher.merge)

    def test_private_permanent_venue_cannot_be_smuggled_into_pair(self):
        proposal = copy.deepcopy(self.proposed)
        proposal["venueApprovals"][0]["venueKind"] = "permanent-hall"
        with self.assertRaises(ValueError):
            gate.check_append_only(self.before, proposal, TODAY)


if __name__ == "__main__":
    unittest.main()
