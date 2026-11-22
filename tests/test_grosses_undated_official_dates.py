"""Offline checks: promote exact future dates from one signed official homepage."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from grossesondes_existing_official_updates import (
    apply_independently_verified_updates, signed_rotation,
)
from grossesondes_cloud_sync import _verified_official_update_delta, safe_target

DAY = "2026-11-22"
SITE = "https://www.sylakopenair.com/"


def festival():
    return {"slug": "sylak-open-air-2027", "name": "Sylak Open Air 2027",
            "officialSite": SITE, "startDate": None, "endDate": None,
            "status": "Dates à venir", "verificationStatus": "Dates à confirmer",
            "lineup": [], "bands": 0, "days": None, "lastVerified": "2026-11-18",
            "auditSources": [SITE], "showOnMap": False, "lat": None, "lon": None}


def signed(*rows):
    return {"schema": 1, "generatedAt": DAY,
            "festivals": [deepcopy(x) for x in rows]}


GOOD_HTML = ("<main><h1>Sylak Open Air 2027</h1>"
             "<p>Sylak Open Air 2027 : 30 au 31 juillet 2027.</p></main>")


class UndatedOfficialDateTests(unittest.TestCase):
    def updated(self, html, row=None):
        row = row or festival()
        original = signed(row)
        result, report = apply_independently_verified_updates(
            original, original, DAY, limit=1, tick=0, fetch=lambda url: html)
        return result["festivals"][0], report

    def test_future_date_exact_official_single_source_publishes(self):
        old = festival()
        self.assertEqual(signed_rotation(signed(old), DAY, 1, 0)[0][0], SITE)
        new, report = self.updated(GOOD_HTML, old)
        self.assertEqual((new["startDate"], new["endDate"]),
                         ("2027-07-30", "2027-07-31"))
        self.assertEqual(new["days"], "2")
        self.assertEqual(new["status"], "Annoncé")
        self.assertEqual(new["verificationStatus"],
                         "Dates confirmées sur le site officiel")
        self.assertTrue(_verified_official_update_delta(old, new))
        self.assertEqual(report["accepted"], [old["slug"]])
        self.assertEqual(new["auditSources"], [SITE])

    def test_publisher_requires_its_own_recheck_and_allows_no_other_change(self):
        old = festival()
        new, report = self.updated(GOOD_HTML, old)
        foundation = [{"slug": f"base-{i}", "name": f"Base {i}"}
                      for i in range(90)]
        before = signed(*foundation, old)
        after = signed(*foundation, new)
        with self.assertRaises(Exception):
            safe_target(before, after, before)
        self.assertTrue(safe_target(
            before, after, before,
            verified_official_updates=frozenset(report["accepted"])))
        for key, bad in (("venue", "Wrong location"),
                         ("startDate", "2026-07-30"),
                         ("endDate", "2027-08-15"),
                         ("status", "Annulé"),
                         ("lat", 46.0)):
            altered = deepcopy(new)
            altered[key] = bad
            with self.subTest(key=key):
                self.assertFalse(_verified_official_update_delta(old, altered))

    def test_old_edition_single_opening_day_and_conflicting_ranges_rejected(self):
        sources = (
            "<main><h1>Sylak Open Air 2026</h1><p>30 au 31 juillet 2026</p></main>",
            "<main><h1>Sylak Open Air 2027</h1><p>30 juillet 2027</p></main>",
            ("<main><p>Sylak Open Air 2027 : 30 au 31 juillet 2027</p>"
             "<p>Sylak Open Air 2027 : 15 au 16 août 2027</p></main>"),
            "<script>Sylak Open Air 2027 : 30 au 31 juillet 2027</script>",
        )
        for source in sources:
            with self.subTest(source=source[:80]):
                new, report = self.updated(source)
                self.assertEqual(report["accepted"], [])
                self.assertEqual(new, festival())

    def test_future_rotation_rejects_previous_year_or_unpinned_identity(self):
        old = festival()
        old["name"], old["slug"] = "Sylak Open Air 2026", "sylak-open-air-2026"
        self.assertEqual(signed_rotation(signed(old), DAY, 1, 0), [])
        forged = festival()
        forged["name"] = "An unrelated series 2027"
        self.assertEqual(signed_rotation(signed(forged), DAY, 1, 0)[0][0], SITE)
        # The publisher still needs exact edition/site proof. A forged
        # year-matching name alone never authorizes mutation.
        new, report = self.updated(GOOD_HTML, forged)
        self.assertEqual(report["accepted"], [])
        self.assertEqual(new, forged)


if __name__ == "__main__":
    unittest.main()
