"""Explicit non-musical category policy is OFF by default in the publisher."""
from copy import deepcopy
from datetime import date
import inspect
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import merge_policy
from ptitesondes_family_national_scope import FAMILY_TYPES

TODAY = date(2026, 11, 18)
BASE_CATEGORIES = {"concert", "conte-musical", "spectacle-musical",
                   "eveil-musical", "atelier-musical", "cine-concert", "festival"}


def fixture(category="lecture-jeunesse"):
    return {
        "id": "openagenda-1234-2026-12-05", "title": "Lecture du samedi",
        "category": category,
        "category_label": FAMILY_TYPES[category][0] if category in FAMILY_TYPES else "Inconnu",
        "date_start": "2026-12-05", "date_end": "2026-12-05",
        "city": "Montpellier", "department": "Hérault", "region": "Occitanie",
        "venue": "Bibliothèque fictive",
        "source_url": "https://ville-exemple.fr/evenement/lecture-du-samedi",
        "source_label": "Organisateur officiel de test",
        "verified_at": TODAY.isoformat(), "geo_verified_at": TODAY.isoformat(),
        "geo_precision": "venue", "lat": 43.61, "lng": 3.87,
    }


class ExplicitFamilyCategoryPolicy(unittest.TestCase):
    def check(self, event, **kwargs):
        return merge_policy.valid(event, BASE_CATEGORIES, set(event), TODAY, **kwargs)

    def test_all_13_known_familial_categories_valid_only_with_opt_in(self):
        self.assertEqual(len(FAMILY_TYPES), 13)
        allow = tuple(FAMILY_TYPES)
        for kind in FAMILY_TYPES:
            with self.subTest(kind=kind):
                e = fixture(kind)
                self.assertFalse(self.check(e)[0])
                accepted, reason = self.check(e, reviewed_family_categories=allow)
                self.assertTrue(accepted, (kind, reason))

    def test_unknown_or_event_supplied_category_is_never_authority(self):
        c = fixture("custom-category")
        for allow in (None, (), ("custom-category",), tuple(FAMILY_TYPES)):
            with self.subTest(allow=allow):
                self.assertFalse(self.check(c, reviewed_family_categories=allow)[0])
        c["reviewed_family_categories"] = ["custom-category"]
        self.assertFalse(merge_policy.valid(c, BASE_CATEGORIES,
                                            set(fixture()), TODAY,
                                            reviewed_family_categories=tuple(FAMILY_TYPES))[0])

    def test_non_contract_policy_shapes_are_refused(self):
        for allow in ("lecture-jeunesse", ["lecture-jeunesse"],
                      {"lecture-jeunesse": True},
                      ("lecture-jeunesse", "fabricated"),
                      (True,), (7,)):
            with self.subTest(allow=allow):
                self.assertFalse(self.check(fixture(),
                                           reviewed_family_categories=allow)[0])

    def test_approved_labels_must_be_exact_no_guessing(self):
        c = fixture()
        for wrong in ("Lecture", "Atelier", "Concert", "", "Lecture jeunesse "):
            with self.subTest(label=wrong):
                e = dict(c, category_label=wrong)
                self.assertFalse(self.check(e, reviewed_family_categories=tuple(FAMILY_TYPES))[0])

    def test_other_structural_controls_are_unchanged(self):
        allow = tuple(FAMILY_TYPES)
        for alteration in (
            {"date_start": "2025-01-01", "date_end": "2025-01-01"},
            {"lat": 999},
            {"geo_precision": "city"},
            {"source_url": "http://unsafe.test/event"},
            {"verified_at": "2026-09-01"},
        ):
            with self.subTest(alteration=alteration):
                c = dict(fixture(), **alteration)
                self.assertFalse(self.check(c, reviewed_family_categories=allow)[0])

    def test_live_merge_call_never_opts_in(self):
        source = inspect.getsource(merge_policy.merge)
        self.assertIn("valid(ev,categories,fields,today)", source)
        self.assertNotIn("reviewed_family_categories", source)
        self.assertTrue(self.check(dict(fixture("lecture-jeunesse")))[0] is False)

    def test_old_musical_categories_remain_structurally_allowed(self):
        for cat in BASE_CATEGORIES:
            c = fixture()
            c["category"] = cat
            c["category_label"] = "Titre historique"
            ok, why = self.check(c)
            self.assertTrue(ok, (cat, why))


if __name__ == "__main__":
    unittest.main()
