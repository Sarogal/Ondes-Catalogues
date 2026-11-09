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


if __name__ == "__main__":
    unittest.main()
