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
    def test_capacity_extends_beyond_150_but_not_beyond_400(self):
        self.assertEqual(sync.MAX_CUMULATIVE_EVENT_APPROVALS,400)
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
        with self.assertRaisesRegex(ValueError,"Trop d.approbations"):
            sync.merge(BASE, BASE, approved, DAY)

    def test_new_event_delta_fails_closed_instead_of_truncating(self):
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
        with mock.patch.object(sync,"validate_approval",side_effect=signed_stub):
            with self.assertRaisesRegex(ValueError,"Trop de nouveaux concerts"):
                sync.merge(BASE, BASE, sample, DAY)

    def test_venue_total_capacity_and_delta_guard(self):
        self.assertEqual(sync.MAX_CUMULATIVE_VENUE_APPROVALS,100)
        self.assertEqual(sync.MAX_NEW_VENUES_PER_SYNC,6)
        approved={"schema": SCHEMA,"approvals":[],
            "venueApprovals":[{"venue":{"id":f"v-{i}"}}
                              for i in range(101)]}
        with self.assertRaisesRegex(ValueError,"Liste d.approbations de salles"):
            sync.merge(BASE, BASE, approved, DAY)
        signed={"schema":SCHEMA,"approvals":[],
            "venueApprovals":[{"venue":{"id":f"v-{i}"}} for i in range(7)]}
        def location_stub(row, today):
            ident=row["venue"]["id"]
            return {"id":ident,"name":ident,"city":f"Ville {ident}"}
        with mock.patch.object(sync,"validate_venue_approval",side_effect=location_stub):
            with self.assertRaisesRegex(ValueError,"Trop de nouvelles salles"):
                sync.merge(BASE, BASE, signed, DAY)

if __name__=="__main__":
    import unittest
    unittest.main()
