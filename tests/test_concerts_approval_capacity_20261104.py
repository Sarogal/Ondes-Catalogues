"""Cumulative signed approvals may grow; each publication delta remains bounded."""
import copy
import datetime as dt
from unittest import TestCase, mock
from scripts import concerts_cloud_sync as sync
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=json.loads((ROOT/"docs/grossesondes/concerts-reference.json").read_text(encoding="utf-8"))
DAY=dt.date(2026,11,4)
SCHEMA=sync.SCHEMA

class CumulativeApprovalCapacityTests(TestCase):
    def test_more_than_400_approval_records_are_audited_individually(self):
        self.assertEqual(sync.MAX_NEW_EVENTS_PER_SYNC, 16)
        approved={
            "schema":SCHEMA,
            "approvals":[{"reviewDecision":"rejected",
                          "event":{"id":f"go-c-20270301-rejected-{i:03d}"}}
                         for i in range(151)]
        }
        result, report=sync.merge(BASE, BASE, approved, DAY)
        self.assertEqual(result, BASE)
        self.assertEqual(report["newEvents"],0)
        self.assertEqual(len(report["held"]),151)
        approved["approvals"].extend(
            {"reviewDecision":"rejected","event":{"id":f"go-c-20270302-extra-{i:03d}"}}
            for i in range(250)
        )
        result, report = sync.merge(BASE, BASE, approved, DAY)
        self.assertEqual(result, BASE)
        self.assertEqual(report["newEvents"], 0)
        self.assertEqual(len(report["held"]), 401)

    def test_17_approved_events_publish_in_16_plus_1_idempotent_batches(self):
        self.assertEqual(sync.MAX_NEW_EVENTS_PER_SYNC,16)
        # Stubs isolate the batch guard; production still requires every
        # individually reviewed signature and strict event-specific source.
        sample={
            "schema": SCHEMA,
            "approvals": [{
                "reviewDecision":"approved",
                "event":{
                    "id":f"go-c-202803{i:02d}-test-capacity",
                    "title":f"Capacity dummy {i}",
                    "date":f"2028-03-{i:02d}",
                    "time":None,
                    "artistIds":["kamelot"],
                    "venueId":"la-rayonne",
                    "genres":["Metal"],
                    "status":"confirmed",
                    "sourceType":"salle",
                    "officialUrl":f"https://example.org/concert/{i}"
                }
            } for i in range(1,18)]
        }
        def signed_stub(row, venues, artists, today):
            return row["event"], {}
        with mock.patch.object(sync, "validate_approval", side_effect=signed_stub):
            first, stats = sync.merge(BASE, BASE, sample, DAY)
            self.assertEqual(stats["newEvents"], 16)
            self.assertEqual(stats["deferredUnprocessed"], 1)
            self.assertEqual(len(first["events"]) - len(BASE["events"]), 16)
            self.assertEqual(len(stats["held"]), 0)
            second, next_stats = sync.merge(BASE, first, sample, DAY)
            self.assertEqual(next_stats["newEvents"], 1)
            self.assertEqual(next_stats["deferredUnprocessed"], 0)
            self.assertEqual(len(second["events"]) - len(BASE["events"]), 17)
            self.assertEqual(len(next_stats["held"]), 0)
            again, last_stats = sync.merge(BASE, second, sample, DAY)
            self.assertEqual(again, second)
            self.assertEqual(last_stats["newEvents"], 0)
            self.assertEqual(last_stats["alreadyPublished"], 17)

        # A signed-looking but malformed 17th record is not validated early,
        # nor silently dropped. It is explicitly held when its batch arrives.
        def reject_last(row, venues, artists, today):
            if row["event"]["id"].endswith("17-test-capacity"):
                raise ValueError("Preuve officielle 17 non corroborée")
            return signed_stub(row, venues, artists, today)
        with mock.patch.object(sync, "validate_approval", side_effect=reject_last):
            first, _ = sync.merge(BASE, BASE, sample, DAY)
            blocked, stats = sync.merge(BASE, first, sample, DAY)
            self.assertEqual(blocked, first)
            self.assertEqual(stats["newEvents"], 0)
            self.assertEqual(len(stats["held"]), 1)
            self.assertIn("non corroborée", stats["held"][0]["reason"])

    def test_more_than_100_venues_resume_in_six_at_a_time_batches(self):
        self.assertEqual(sync.MAX_NEW_VENUES_PER_SYNC, 6)
        approved = {
            "schema": SCHEMA, "approvals": [],
            "venueApprovals": [
                {"venue": {"id": f"test-venue-{i:03d}"}}
                for i in range(101)
            ],
        }

        def verified_location(row, today):
            ident = row["venue"]["id"]
            return {
                "id": ident, "name": ident, "city": f"City {ident}",
                "latitude": 43.6, "longitude": 3.88,
                "locationPrecision": "verified-official",
            }

        with mock.patch.object(sync, "validate_venue_approval",
                               side_effect=verified_location):
            first, stats = sync.merge(BASE, BASE, approved, DAY)
            self.assertEqual(stats["newVenues"], 6)
            self.assertEqual(stats["deferredVenues"], 95)
            self.assertEqual(len(first["venues"]) - len(BASE["venues"]), 6)
            self.assertEqual(stats["held"], [])

            second, next_stats = sync.merge(BASE, first, approved, DAY)
            self.assertEqual(next_stats["newVenues"], 6)
            self.assertEqual(next_stats["alreadyRegisteredVenues"], 6)
            self.assertEqual(next_stats["deferredVenues"], 89)
            self.assertEqual(len(second["venues"]) - len(BASE["venues"]), 12)

            current = second
            for _ in range(15):
                current, followup = sync.merge(BASE, current, approved, DAY)
            self.assertEqual(len(current["venues"]) - len(BASE["venues"]), 101)
            self.assertEqual(followup["newVenues"], 5)
            self.assertEqual(followup["deferredVenues"], 0)
            again, final = sync.merge(BASE, current, approved, DAY)
            self.assertEqual(again, current)
            self.assertEqual(final["newVenues"], 0)
            self.assertEqual(final["alreadyRegisteredVenues"], 101)
            self.assertEqual(final["deferredVenues"], 0)

    def test_deferred_venue_evidence_is_checked_only_when_eligible(self):
        signed = {
            "schema": SCHEMA, "approvals": [],
            "venueApprovals": [
                {"venue": {"id": f"v-{i}"}} for i in range(7)
            ],
        }

        def location_stub(row, today):
            ident = row["venue"]["id"]
            if ident == "v-6":
                raise ValueError("Salle non corroborée")
            return {"id": ident, "name": ident, "city": f"City {ident}"}

        with mock.patch.object(sync, "validate_venue_approval",
                               side_effect=location_stub):
            first, stats = sync.merge(BASE, BASE, signed, DAY)
            self.assertEqual(stats["newVenues"], 6)
            self.assertEqual(stats["deferredVenues"], 1)
            self.assertEqual(stats["held"], [])
            second, next_stats = sync.merge(BASE, first, signed, DAY)
            self.assertEqual(second, first)
            self.assertEqual(next_stats["newVenues"], 0)
            self.assertEqual(next_stats["deferredVenues"], 0)
            self.assertEqual(len(next_stats["held"]), 1)
            self.assertIn("non corroborée", next_stats["held"][0]["reason"])

    def test_duplicate_venue_approval_id_still_rejected_without_total_cap(self):
        repeated = {
            "schema": SCHEMA, "approvals": [],
            "venueApprovals": [
                {"venue": {"id": f"v-{i // 2}"}}
                for i in range(101)
            ],
        }
        with self.assertRaisesRegex(ValueError, "Doublon"):
            sync.merge(BASE, BASE, repeated, DAY)

if __name__=="__main__":
    import unittest
    unittest.main()
