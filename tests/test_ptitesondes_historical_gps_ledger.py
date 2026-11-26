from copy import deepcopy
import unittest

from test_ptitesondes_catalogue_geo_correction_preview import DAY, fixture
from ptitesondes_catalogue_geo_correction_preview import digest
from ptitesondes_historical_gps_ledger import empty_ledger, reconcile


class HistoricalGPSLedgerTests(unittest.TestCase):
    def setUp(self):
        self.ref, _, _ = fixture()
        self.public = deepcopy(self.ref)
        self.old = self.ref["events"][0]
        self.geo = dict(lat=44.5, lng=2.25, geo_precision="venue",
                        geo_verified_at=DAY.isoformat())
        self.new = dict(self.old, **self.geo)
        self.public["events"][0] = self.new
        self.ledger = empty_ledger()
        self.ledger["repairs"][self.old["id"]] = dict(
            before_sha256=digest(self.old), after_sha256=digest(self.new),
            geo=self.geo)

    def test_reconcile_keeps_baseline_metadata_and_other_events(self):
        self.assertEqual(reconcile(self.ref, self.public, self.ledger), self.public)
        self.assertEqual(reconcile(self.ref, self.public, empty_ledger()), self.ref)
        self.assertNotIn("lat", self.old)
        self.assertEqual(self.ref["events"][1:], self.public["events"][1:])

    def test_missing_repair_or_wrong_digest_refused(self):
        with self.assertRaisesRegex(ValueError, "current_record_changed"):
            reconcile(self.ref, self.ref, self.ledger)
        ledger = deepcopy(self.ledger)
        ledger["repairs"][self.old["id"]]["before_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "reference_changed"):
            reconcile(self.ref, self.public, ledger)

    def test_no_other_fields_or_existing_point_allowed(self):
        ledger = deepcopy(self.ledger)
        ledger["repairs"][self.old["id"]]["geo"]["title"] = "Other"
        with self.assertRaisesRegex(ValueError, "invalid_geo"):
            reconcile(self.ref, self.public, ledger)
        old = self.ref["events"][1]
        ledger = empty_ledger()
        ledger["repairs"][old["id"]] = dict(before_sha256=digest(old),
            after_sha256=digest(dict(old, **self.geo)), geo=self.geo)
        with self.assertRaisesRegex(ValueError, "existing_point"):
            reconcile(self.ref, self.public, ledger)

    def test_unrelated_public_edit_is_not_authorized(self):
        public = deepcopy(self.public)
        public["events"][0]["title"] = "Other"
        with self.assertRaisesRegex(ValueError, "current_record_changed"):
            reconcile(self.ref, public, self.ledger)

    def test_unknown_id_and_duplicate_ids_refused(self):
        ledger = deepcopy(self.ledger)
        ledger["repairs"]["unknown"] = ledger["repairs"][self.old["id"]]
        with self.assertRaisesRegex(ValueError, "unknown_or_invalid_repair"):
            reconcile(self.ref, self.public, ledger)
        public = deepcopy(self.public)
        public["events"].append(public["events"][0])
        with self.assertRaisesRegex(ValueError, "duplicate_id"):
            reconcile(self.ref, public, self.ledger)


    def test_record_validated_repair_and_idempotent_reconciliation(self):
        from test_ptitesondes_catalogue_geo_correction_preview import page
        from ptitesondes_historical_gps_apply_guard import prepare_corrections
        from ptitesondes_historical_gps_ledger import record_validated_repairs
        doc, state, proof = fixture()
        corrected, audit, count = prepare_corrections(doc, doc, DAY, state,
            researcher=lambda *_: proof, source_reader=lambda _: page())
        self.assertEqual(count, 1)
        old_ledger = empty_ledger()
        ledger = record_validated_repairs(doc, doc, corrected, old_ledger, audit, DAY)
        self.assertEqual(old_ledger, empty_ledger())
        self.assertEqual(reconcile(doc, corrected, ledger), corrected)
        unchanged, second, count = prepare_corrections(corrected, corrected, DAY, state,
            researcher=lambda *_: self.fail("valid point rechecked"))
        self.assertEqual(count, 0)
        self.assertEqual(record_validated_repairs(doc, corrected, unchanged,
                         ledger, second, DAY), ledger)

    def test_record_refuses_forged_non_geo_mutation(self):
        from test_ptitesondes_catalogue_geo_correction_preview import page
        from ptitesondes_historical_gps_apply_guard import prepare_corrections
        from ptitesondes_historical_gps_ledger import record_validated_repairs
        doc, state, proof = fixture()
        corrected, audit, _ = prepare_corrections(doc, doc, DAY, state,
            researcher=lambda *_: proof, source_reader=lambda _: page())
        corrected["events"][0]["title"] = "Other"
        audit["after_sha256"] = digest(corrected)
        audit["proposals"][0]["after_sha256"] = digest(corrected["events"][0])
        with self.assertRaisesRegex(ValueError, "non_geo_change"):
            record_validated_repairs(doc, doc, corrected, empty_ledger(), audit, DAY)
