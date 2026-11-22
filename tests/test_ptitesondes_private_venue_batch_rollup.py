"""Offline adversarial tests for private-only seven-batch venue rollup."""
from copy import deepcopy
from datetime import date
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_generic_venue_osm_preflight import audit
from ptitesondes_private_venue_batch_rollup import rollup_private_batches

DAY = date(2026,11,20)


def lead(i, uid=None):
    uid = str(uid if uid is not None else 100000 + i)
    return {"title":"Une sortie familiale", "city":"Ville test",
            "venue":"Lieu privé "+str(i), "collector":"openagenda-v2",
            "external_id":uid,
            "source_url":"https://openagenda.com/demo/events/"+uid+"_sortie",
            "date_start":"2026-12-12", "date_end":"2026-12-12"}


def reports():
    backlog=[lead(i) for i in range(25)]
    # The second copy is precisely one duplicate collector entry, not a
    # second child session. The snapshot stays synthetic/offline.
    backlog.append({**lead(0),"collector":"opendatasoft-index"})
    return [audit(backlog,DAY,live=False,batch_index=i)
            for i in range(3)]


class PrivateBatchRollupTests(unittest.TestCase):
    def test_three_batches_complete_and_names_never_leave_rollup(self):
        data=reports()
        summary=rollup_private_batches(data)
        self.assertTrue(summary["batches_complete"])
        self.assertFalse(summary["full_live_scan"])
        self.assertEqual(summary["batches_examined"],3)
        self.assertEqual(summary["unknown_venue_entries"],26)
        self.assertEqual(summary["unknown_distinct_candidate_sessions"],25)
        self.assertEqual(summary["unknown_unique_venues"],25)
        self.assertEqual(summary["duplicate_or_repeated_entries"],1)
        self.assertEqual(summary["live_venues_queried"],0)
        self.assertEqual(summary["public_writes"],0)
        self.assertFalse(summary["publication_ready"])
        serialized=json.dumps(summary,ensure_ascii=False)
        for secret in ("Lieu privé", "Ville test", "openagenda.com",
                       "source_url", "uid", "records", "lat", "lng"):
            self.assertNotIn(secret,serialized)

    def test_missing_duplicate_and_mismatched_batches_fail_closed(self):
        data=reports()
        with self.assertRaises(ValueError):
            rollup_private_batches(data[:2])
        with self.assertRaises(ValueError):
            rollup_private_batches([data[0],data[1],data[1]])
        wrong_day=deepcopy(data)
        wrong_day[1]["day"]="2026-11-21"
        with self.assertRaises(ValueError):
            rollup_private_batches(wrong_day)
        wrong_backlog=deepcopy(data)
        wrong_backlog[1]["total_backlog"]+=1
        with self.assertRaises(ValueError):
            rollup_private_batches(wrong_backlog)
        repeated=deepcopy(data)
        repeated[1]["records"][0]["city"]=data[0]["records"][0]["city"]
        repeated[1]["records"][0]["venue"]=data[0]["records"][0]["venue"]
        with self.assertRaises(ValueError):
            rollup_private_batches(repeated)

    def test_private_publisher_or_evidence_flag_cannot_pass(self):
        originals=reports()
        for patch in (
            {"public_writes":1},
            {"publication_ready":True},
            {"gps_verified":True},
            {"verified_venue_leads":1},
            {"schema":"other"},
            {"selected_venues":99},
            {"queried_venues":5},
        ):
            with self.subTest(patch=patch):
                items=deepcopy(originals)
                items[0].update(patch)
                with self.assertRaises(ValueError):
                    rollup_private_batches(items)
        for nested in ("official_page","official_geocode",
                       "unnumbered_named_venue_hint"):
            items=deepcopy(originals)
            items[0]["records"][0][nested]={"public_writes":1}
            with self.assertRaises(ValueError):
                rollup_private_batches(items)

    def test_private_geo_hints_and_reusable_proofs_do_not_double_count(self):
        data=reports()
        row=data[0]["records"][0]
        row["shared_location_proof_private_review"]=True
        row["unnumbered_named_venue_hint"]={
            "official_name_correlated":True,
            "osm_geometry_correlated":True,
            "gps_verified":False, "publication_ready":False,
            "public_writes":0,
        }
        data[0]["private_reusable_location_proofs"]=1
        data[0]["candidate_sessions_with_private_reusable_proof"]=1
        data[0]["unnumbered_named_venue_private_hints"]=1
        data[0]["candidate_sessions_with_unnumbered_private_hint"]=1
        summary=rollup_private_batches(data)
        self.assertEqual(summary["reusable_location_proof_venues_private"],1)
        self.assertEqual(summary["unnumbered_named_venue_hints_private"],1)
        self.assertEqual(summary[
            "candidate_sessions_with_any_geo_signal_not_published"],1)
        self.assertFalse(summary["publication_ready"])
        bad=deepcopy(data)
        bad[0]["candidate_sessions_with_unnumbered_private_hint"]=2
        with self.assertRaises(ValueError):
            rollup_private_batches(bad)

    def test_invalid_types_and_no_reports_fail_closed(self):
        for x in ([],[{}],[None], "not-a-list"):
            with self.assertRaises(ValueError):
                rollup_private_batches(x)
        data=reports()
        bad=deepcopy(data)
        bad[0]["batch_index"]=True
        with self.assertRaises(ValueError):
            rollup_private_batches(bad)


if __name__ == "__main__":
    unittest.main()
