import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from grossesondes_official_status import explicit_statuses, CANCELLED, POSTPONED
from grossesondes_existing_official_updates import page, apply_independently_verified_updates
from grossesondes_cloud_sync import _verified_official_update_delta, safe_target

SITE = "https://festival-example.fr/"
ROW = {"name": "Festival Exemple 2027", "slug": "festival-exemple-2027",
       "startDate": "2027-07-10", "endDate": "2027-07-11",
       "status": "Annoncé", "officialSite": SITE, "showOnMap": True,
       "city": "Paris", "lat": 48.85, "lon": 2.35,
       "lineup": ["Groupe A", "Groupe B"], "bands": 2,
       "price": "20 €", "lastVerified": "2026-11-22", "auditSources": [SITE]}

class FestivalStatusTests(unittest.TestCase):
    def test_current_edition_not_artist(self):
        for text in ("Festival Exemple 2027 est annulé",
                     "L’édition 2027 du Festival Exemple est annulée",
                     "Annulation du Festival Exemple 2027"):
            self.assertEqual(explicit_statuses(page("<h1>"+text+"</h1>").blocks, ROW),
                             {CANCELLED})
        for text in ("Groupe A annule sa venue au Festival Exemple 2027",
                     "Festival Exemple 2026 est annulé",
                     "Festival Exemple 2027 : Groupe A annulé",
                     "Festival Exemple 2027 pourrait être annulé",
                     "Autre Festival Exemple 2027 est annulé"):
            self.assertEqual(explicit_statuses(page("<p>"+text+"</p>").blocks, ROW), set())

    def scan(self, html, row=ROW):
        doc = {"schema": 1, "generatedAt": "2026-11-22", "festivals": [row]}
        return apply_independently_verified_updates(doc, doc, "2026-11-25",
                  fetch=lambda _: html, limit=1, tick=0)

    def test_cancelled_preserves_history_and_removes_active_marker(self):
        doc, report = self.scan("<main><h1>Festival Exemple 2027 est annulé</h1></main>")
        new = doc["festivals"][0]
        self.assertEqual(report["accepted"], [ROW["slug"]])
        self.assertEqual(new["status"], CANCELLED)
        self.assertTrue(new["cancelled"])
        self.assertFalse(new["showOnMap"])
        for key in ("startDate", "endDate", "lineup", "price", "lat", "lon"):
            self.assertEqual(new[key], ROW[key])
        self.assertTrue(_verified_official_update_delta(ROW, new))
        self.assertFalse(_verified_official_update_delta(ROW, dict(new, lineup=[])))
        self.assertFalse(_verified_official_update_delta(ROW, dict(new, showOnMap=True)))
        old = {"schema": 1, "festivals": [ROW]}
        with self.assertRaises(ValueError):
            safe_target(old, doc, old)
        self.assertTrue(safe_target(old, doc, old,
                        verified_official_updates=frozenset({ROW["slug"]})))

    def test_postponed_and_conflicting_status(self):
        doc, report = self.scan("<h1>Festival Exemple 2027 est reporté</h1>")
        new = doc["festivals"][0]
        self.assertEqual(report["accepted"], [ROW["slug"]])
        self.assertEqual(new["status"], POSTPONED)
        self.assertFalse(new["showOnMap"])
        self.assertNotEqual(new.get("cancelled"), True)
        self.assertTrue(_verified_official_update_delta(ROW, new))
        doc, report = self.scan("<h1>Festival Exemple 2027 est annulé</h1>"
                                "<p>Festival Exemple 2027 est maintenu</p>")
        self.assertEqual(report["accepted"], [])
        self.assertEqual(doc["festivals"][0], ROW)
        doc, report = self.scan("<p hidden>Festival Exemple 2027 est annulé</p>")
        self.assertEqual(report["accepted"], [])

    def test_status_is_idempotent(self):
        doc, _ = self.scan("<h1>Festival Exemple 2027 est annulé</h1>")
        cancelled = doc["festivals"][0]
        out, report = self.scan("<h1>Festival Exemple 2027 est annulé</h1>", cancelled)
        self.assertEqual(report["accepted"], [])
        self.assertEqual(out["festivals"][0], cancelled)

if __name__ == "__main__":
    unittest.main()
