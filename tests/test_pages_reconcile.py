"""Fail-closed regression tests for Pages-only reconciliation."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pages_reconcile import CATALOGUES, event_ids, needs_reconcile


def doc(spec, count=None):
    _name, _path, _url, key, id_key, schema_key, version, minimum = spec
    return {schema_key: version, key: [{id_key: f"event-{i}"} for i in range(count or minimum)]}


class PagesReconcileTests(unittest.TestCase):
    def test_identical_catalogues_do_not_redeploy(self):
        for spec in CATALOGUES:
            with self.subTest(name=spec[0]):
                a = doc(spec)
                self.assertFalse(needs_reconcile(a, copy.deepcopy(a), spec))

    def test_approved_addition_may_redeploy(self):
        for spec in CATALOGUES:
            with self.subTest(name=spec[0]):
                old = doc(spec)
                new = doc(spec, spec[-1] + 1)
                self.assertTrue(needs_reconcile(new, old, spec))

    def test_existing_public_record_never_dropped(self):
        for spec in CATALOGUES:
            with self.subTest(name=spec[0]):
                old = doc(spec, spec[-1] + 1)
                new = doc(spec)
                with self.assertRaisesRegex(ValueError, "absentes de main"):
                    needs_reconcile(new, old, spec)

    def test_change_to_existing_record_can_redeploy_without_changing_ids(self):
        spec = CATALOGUES[0]
        old = doc(spec)
        new = copy.deepcopy(old)
        new[spec[3]][0]["status"] = "Confirmé"
        self.assertTrue(needs_reconcile(new, old, spec))

    def test_duplicate_id_is_blocked(self):
        for spec in CATALOGUES:
            with self.subTest(name=spec[0]):
                a = doc(spec)
                a[spec[3]][1][spec[4]] = a[spec[3]][0][spec[4]]
                with self.assertRaisesRegex(ValueError, "dupliqués"):
                    event_ids(a, spec)

    def test_schema_change_is_blocked(self):
        for spec in CATALOGUES:
            with self.subTest(name=spec[0]):
                a = doc(spec)
                a[spec[5]] = "unknown"
                with self.assertRaisesRegex(ValueError, "schéma"):
                    event_ids(a, spec)


if __name__ == "__main__":
    unittest.main()
