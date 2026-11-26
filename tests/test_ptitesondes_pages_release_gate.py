"""Offline adversarial checks of the one-field historical Pages release gate."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_pages_release_gate import pages_pending_momo_only


def fixture():
    original = {
        "id": "bordeaux-momo-enfant-peche-2027-01-21",
        "source_url": "https://www.opera-bordeaux.com/famille-orchestre-momo-lenfant-peche-86301",
        "date_start": "2027-01-21", "date_end": "2027-01-22",
        "time": "21 janv. 19:00 ; 22 janv. 14:30 (scolaires) et 19:00",
        "title": "Momo, l'enfant pêche",
    }
    after = dict(original, time="21 janv. 19:00 ; 22 janv. 19:00")
    others = [{"id": "old-" + str(i), "title": "unchanged"} for i in range(100)]
    prior = {"sorties.json": {"version": 3, "updated_at": "2026-11-09",
                              "events": [original, *others]},
             "lieux.json": {"version": 1, "places": []}}
    current = copy.deepcopy(prior)
    current["sorties.json"]["events"][0] = after
    return current, prior


class MomoPagesReleaseGateTests(unittest.TestCase):
    def test_approved_single_field_correction_is_only_exception(self):
        git, pages = fixture()
        self.assertTrue(pages_pending_momo_only(git, pages))
        self.assertFalse(pages_pending_momo_only(git, git))
        self.assertFalse(pages_pending_momo_only(pages, git))

    def test_no_arbitrary_history_changes_or_wider_published_differences(self):
        git, pages = fixture()
        variants = []
        alter = copy.deepcopy(pages)
        alter["sorties.json"]["events"][1]["title"] = "unexpected"
        variants.append(alter)
        alter = copy.deepcopy(pages)
        alter["sorties.json"]["events"][0]["title"] = "different"
        variants.append(alter)
        alter = copy.deepcopy(pages)
        alter["sorties.json"]["events"][0]["source_url"] = "https://evil.example"
        variants.append(alter)
        alter = copy.deepcopy(pages)
        alter["sorties.json"]["events"][0]["time"] = "22 janv. 19:00"
        variants.append(alter)
        alter = copy.deepcopy(pages)
        alter["sorties.json"]["updated_at"] = "2026-11-08"
        variants.append(alter)
        alter = copy.deepcopy(pages)
        alter["lieux.json"]["version"] = 2
        variants.append(alter)
        alter = copy.deepcopy(pages)
        alter["sorties.json"]["events"] = alter["sorties.json"]["events"][:-1]
        variants.append(alter)
        alter = copy.deepcopy(pages)
        alter["sorties.json"]["events"].append(copy.deepcopy(
            alter["sorties.json"]["events"][0]))
        variants.append(alter)
        for candidate in variants:
            with self.subTest(variant=variants.index(candidate)):
                self.assertFalse(pages_pending_momo_only(git, candidate))


class GPSPagesReleaseGateTests(unittest.TestCase):
    def setUp(self):
        from ptitesondes_catalogue_geo_correction_preview import digest
        from ptitesondes_historical_gps_ledger import empty_ledger
        from test_ptitesondes_catalogue_geo_correction_preview import DAY, fixture as geo_fixture
        doc, _, _ = geo_fixture()
        self.old = doc["events"][0]
        doc["updated_at"] = "2026-11-26T08:00:00+01:00"
        doc["events"] += [{"id": "other-" + str(i)} for i in range(100)]
        self.pages = {"sorties.json": doc, "lieux.json": {"version": 1, "places": []}}
        self.git = copy.deepcopy(self.pages)
        self.geo = dict(lat=44.5, lng=2.25, geo_precision="venue", geo_verified_at=DAY.isoformat())
        self.new = dict(self.old, **self.geo)
        self.git["sorties.json"]["events"][0] = self.new
        self.git["sorties.json"]["updated_at"] = "2026-11-26T09:00:00+01:00"
        self.ledger = empty_ledger()
        self.ledger["repairs"][self.old["id"]] = dict(
            before_sha256=digest(self.old), after_sha256=digest(self.new), geo=self.geo)

    def test_retry_exact_committed_gps_repair_only(self):
        from ptitesondes_pages_release_gate import pages_pending_gps_only
        self.assertTrue(pages_pending_gps_only(self.git, self.pages, self.ledger))
        self.assertFalse(pages_pending_gps_only(self.git, self.git, self.ledger))
        self.assertFalse(pages_pending_gps_only(self.pages, self.git, self.ledger))

    def test_no_retry_when_ledger_or_other_fields_disagree(self):
        from ptitesondes_pages_release_gate import pages_pending_gps_only
        variants = []
        for key, value in (("title", "Other"), ("lat", 45), ("geo_verified_at", "2026-11-25")):
            git = copy.deepcopy(self.git)
            git["sorties.json"]["events"][0][key] = value
            variants.append(git)
        git = copy.deepcopy(self.git)
        git["sorties.json"]["events"].append({"id":"extra"})
        variants.append(git)
        git = copy.deepcopy(self.git)
        git["lieux.json"]["version"] = 2
        variants.append(git)
        git = copy.deepcopy(self.git)
        git["sorties.json"]["events"].reverse()
        variants.append(git)
        for variant in variants:
            self.assertFalse(pages_pending_gps_only(variant, self.pages, self.ledger))
        ledger = copy.deepcopy(self.ledger)
        ledger["repairs"][self.old["id"]]["before_sha256"] = "0" * 64
        self.assertFalse(pages_pending_gps_only(self.git, self.pages, ledger))
        self.assertFalse(pages_pending_gps_only(self.git, self.pages,
                         {"schema": self.ledger["schema"], "repairs": {}}))


if __name__ == "__main__":
    unittest.main()
