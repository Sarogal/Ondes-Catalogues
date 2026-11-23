"""Publisher must reconcile obsolete ticket notes from current official proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))

from grossesondes_existing_official_updates import (
    apply_independently_verified_updates,
    page,
    reconcile_obsolete_ticket_notes,
)
from grossesondes_cloud_sync import _verified_official_update_delta

SITE = "https://www.motocultor-festival.com/"
CURRENT_PRICE = "Pass 4 jours : 239 € ; Pass 1 jour : 82 € — billetterie officielle ouverte"
OLD_NOTE = (
    "Billetterie officielle 2027 : pass 4 jours Early Bird 1 à 198 € "
    "et Early Bird 2 à 218 € (épuisés); Early Bird 3 à 228 € proposé "
    "à la vente au 9 octobre 2026; palier régulier affiché à 239 € "
    "(non encore disponible à cette vérification). "
    "Ne pas confondre avec les prix 2026 encore présents sur le site."
)
HOME = """<html><head><title>Motocultor Festival 2027</title></head>
<main><h1>Motocultor Festival 2027</h1>
<p>Du jeudi 19 au dimanche 22 août 2027.</p>
<ul><li>Pass 4 jours Tarif normal 239 € En vente</li>
<li>Pass 1 jour Journée au choix 82 € En vente</li></ul>
<article><h2>Les Pass 4J Early Birds sont SOLD OUT !</h2>
<p>Les trois paliers d'Early Birds sont épuisés.</p></article>
</main></html>"""


def signed():
    row = {
        "slug": "motocultor-festival",
        "name": "Motocultor Festival",
        "startDate": "2027-08-19", "endDate": "2027-08-22",
        "city": "Carhaix-Plouguer",
        "department": "29", "officialSite": SITE,
        "lineup": [f"Act {i}" for i in range(57)], "bands": 57,
        "price": CURRENT_PRICE, "notes": OLD_NOTE,
        "lat": 48.2708, "lon": -3.5654, "showOnMap": True,
        "lastVerified": "2026-11-22", "auditSources": [SITE],
    }
    return {"schema": 1, "generatedAt": "2026-11-22", "festivals": [row]}


class OfficialTicketNotesTests(unittest.TestCase):
    def test_current_early_bird_sold_out_disambiguates_historical_notes(self):
        updated = reconcile_obsolete_ticket_notes(
            OLD_NOTE, {4: "239 €", 1: "82 €"}, page(HOME).blocks)
        self.assertIn("198 €", updated)
        self.assertIn("218 €", updated)
        self.assertIn("228 €", updated)
        self.assertNotIn("non encore disponible", updated)
        self.assertNotIn("proposé à la vente", updated)
        self.assertIn("228 € (désormais épuisé", updated)
        self.assertIn("9 octobre 2026", updated)
        self.assertIn("les trois paliers Early Bird", updated)
        self.assertIn("sont épuisés", updated)
        self.assertEqual(
            reconcile_obsolete_ticket_notes(
                updated, {4: "239 €", 1: "82 €"}, page(HOME).blocks),
            updated)

    def test_no_current_first_party_sold_out_proof_preserves_notes(self):
        not_current = HOME.replace(
            "Les trois paliers d'Early Birds sont épuisés.",
            "Les annonces de billetterie arrivent bientôt.")
        self.assertEqual(
            reconcile_obsolete_ticket_notes(
                OLD_NOTE, {4: "239 €"}, page(not_current).blocks),
            OLD_NOTE)
        self.assertIn("non encore disponible",
                      reconcile_obsolete_ticket_notes(
                          OLD_NOTE, {4: "228 €"}, page(HOME).blocks))

    def test_publisher_applies_reconciliation_without_price_or_artist_change(self):
        baseline = signed()
        urls = []
        def first_party(url):
            urls.append(url)
            return HOME
        output, report = apply_independently_verified_updates(
            baseline, deepcopy(baseline), "2026-11-23",
            fetch=first_party, limit=1, tick=0)
        row = output["festivals"][0]
        self.assertEqual(urls, [SITE])
        self.assertIn("motocultor-festival", report["accepted"])
        self.assertIn("notes", report["accepted_changes"][0]["fields"])
        self.assertEqual(row["price"], CURRENT_PRICE)
        self.assertEqual(row["bands"], 57)
        self.assertEqual(row["lineup"], baseline["festivals"][0]["lineup"])
        self.assertNotIn("non encore disponible", row["notes"])
        self.assertTrue(_verified_official_update_delta(
            baseline["festivals"][0], row))
        malicious = dict(row, notes=row["notes"] + " | Prix VIP offert")
        self.assertFalse(_verified_official_update_delta(
            baseline["festivals"][0], malicious))
        malicious_price = dict(row, price="Pass 4 jours : 250 € — billetterie officielle ouverte")
        self.assertFalse(_verified_official_update_delta(
            baseline["festivals"][0], malicious_price))



if __name__ == "__main__":
    unittest.main()
