"""Security and real-format regressions for signed tourism archive renewals."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "festival-automation"))

from grossesondes_signed_institutional_renewal import (
    PROOF_MODE, signed_tourism_urls, candidates_from_signed_history,
    current_edition_dates, private_proposal, validate_verified_row,
)

DAY = "2026-11-23"
OFFICE = "https://www.osezmauges.fr/agenda/mauges-pit-fest/occ/1/"
ORGANIZER = "https://maugespitfest.fr/"
HIST = {
    "slug": "mauges-pit-fest",
    "name": "Mauges Pit Fest",
    "lastKnownYear": 2026,
    "startDate": "2026-10-02", "endDate": "2026-10-03",
    "styles": "Metal / Hardcore / Punk / Rock",
    "sourceConfidence": "Site officiel de l'organisateur et office de tourisme",
    "officialSite": ORGANIZER,
    "source": "https://info-festival.net/festivals-par-genre-musical/metal/",
    "auditSources": [ORGANIZER, OFFICE],
    "city": "Saint-Macaire-en-Mauges", "lat": 47.0878, "lon": -1.0968,
    "venue": "Salle Thomas Dupouet",
    "lineup": ["Old Group A", "Old Group B"], "bands": 2,
    "price": "2026 : 48 €",
}
# The tourism page's lead card shows the first date; the detailed schedule
# explicitly shows TWO days with no repeated 2027 in its day subheadings.
OFFICIAL_2027 = (
    "<html><body><header>Ôsez Mauges - tourisme d'affaires</header>"
    "<main><h1>Mauges Pit Fest</h1>"
    "<p>Agenda, SÈVREMOINE</p><p>Le 08 octobre 2027</p>"
    "<p>Festival</p><p>Salle Thomas Dupouet, 49450 SÈVREMOINE</p>"
    "<p>Programmation en cours du MAUGES PIT FEST VI.</p>"
    "<p>Programmation 2027 en cours, pass 2 jours = 48 €.</p>"
    "<h2>Date</h2><p>Le 08 octobre</p><p>Vendredi 18h30 à 2h</p>"
    "<p>Le 09 octobre</p><p>Samedi 15h30 à 2h</p>"
    "<h2>Situation</h2><p>Saint-Macaire-en-Mauges</p></main>"
    "</body></html>"
)


def history(*rows):
    return {"schema": 2, "knownFestivals": list(rows)}


def published(*rows):
    return {"schema": 1, "festivals": list(rows)}


class SignedTourismRenewalTests(unittest.TestCase):
    def test_2027_two_days_from_same_event_visible_schedule(self):
        self.assertEqual(
            tuple(x.isoformat() for x in current_edition_dates(
                OFFICIAL_2027, HIST, 2027)),
            ("2027-10-08", "2027-10-09"))
        row = private_proposal(HIST, OFFICE, 2027, OFFICIAL_2027, DAY)
        self.assertIsNotNone(row)
        self.assertEqual(row["slug"], "mauges-pit-fest-2027")
        self.assertEqual(row["proofMode"], PROOF_MODE)
        actual = validate_verified_row(row, HIST, OFFICIAL_2027, DAY)
        self.assertEqual(actual["startDate"], "2027-10-08")
        self.assertEqual(actual["endDate"], "2027-10-09")
        for field in ("city", "department", "region", "venue", "lat",
                      "lon", "price"):
            self.assertIsNone(actual[field], field)
        self.assertEqual(actual["lineup"], [])
        self.assertEqual(actual["bands"], 0)
        self.assertFalse(actual["showOnMap"])
        self.assertNotIn("Old Group A", str(actual))
        self.assertNotIn("2026 : 48", str(actual))

    def test_only_existing_signed_tourism_origin_is_contacted(self):
        self.assertEqual(signed_tourism_urls(HIST), [OFFICE])
        self.assertEqual(
            [(r["slug"], u, year) for r, u, year in
             candidates_from_signed_history(
                history(HIST), published(), DAY)],
            [("mauges-pit-fest", OFFICE, 2027)])
        forged = deepcopy(HIST)
        forged["auditSources"].append("http://127.0.0.1/private")
        self.assertEqual(signed_tourism_urls(forged), [OFFICE])
        unreviewed = deepcopy(HIST)
        unreviewed["sourceConfidence"] = "Unknown third-party festival list"
        self.assertEqual(signed_tourism_urls(unreviewed), [])
        published_next = published({"slug": "mauges-pit-fest-2027"})
        self.assertEqual(candidates_from_signed_history(
            history(HIST), published_next, DAY), [])

    def test_private_proposal_cannot_promote_new_url_or_forge_fields(self):
        row = private_proposal(HIST, OFFICE, 2027, OFFICIAL_2027, DAY)
        forged = deepcopy(row)
        forged["officialSite"] = "https://untrusted.example.net/"
        self.assertIsNone(validate_verified_row(forged, HIST, OFFICIAL_2027, DAY))
        forged = deepcopy(row)
        forged["lineup"] = ["Old Group A"]
        self.assertIsNone(validate_verified_row(forged, HIST, OFFICIAL_2027, DAY))
        forged = deepcopy(row)
        forged["price"] = "2026 : 48 €"
        self.assertIsNone(validate_verified_row(forged, HIST, OFFICIAL_2027, DAY))
        forged = deepcopy(row)
        forged["startDate"] = "2027-10-03"
        self.assertIsNone(validate_verified_row(forged, HIST, OFFICIAL_2027, DAY))

    def test_2026_only_or_incomplete_weekend_cannot_create_2027(self):
        older = OFFICIAL_2027.replace("2027", "2026")
        self.assertIsNone(current_edition_dates(older, HIST, 2027))
        incomplete = OFFICIAL_2027.replace(
            "<p>Le 09 octobre</p><p>Samedi 15h30 à 2h</p>", "")
        self.assertIsNone(current_edition_dates(incomplete, HIST, 2027))
        contradictory = OFFICIAL_2027.replace(
            "<p>Le 09 octobre</p>", "<p>Le 09 novembre</p>")
        self.assertIsNone(current_edition_dates(contradictory, HIST, 2027))

    def test_publisher_collects_only_signed_source_and_stage_reproves(self):
        from grossesondes_cloud_sync import collect_signed_tourism_renewals
        from grossesondes_stage import stage
        from test_grosses_stage import fixtures

        cal, hist, patch = fixtures()
        # Substitute one historical archive record but keep immutable count
        # and the ordinary source manifest in this isolated fixture.
        hist["knownFestivals"][0] = deepcopy(HIST)
        probe_urls = []

        def signed_fetch(url):
            probe_urls.append(url)
            self.assertEqual(url, OFFICE)
            return OFFICIAL_2027

        additions, sources, checks = collect_signed_tourism_renewals(
            hist, cal, DAY, fetcher=signed_fetch, tick=0)
        self.assertEqual(checks, 1)
        self.assertEqual(probe_urls, [OFFICE])
        self.assertEqual(len(additions), 1)
        proposal = additions[0]
        patch["additions"] = [proposal]
        patch["updates"] = []
        out, report = stage(
            cal, hist, patch, sources, DAY,
            published_calendar=cal, published_history=hist)
        self.assertEqual(report["accepted_additions"],
                         ["mauges-pit-fest-2027"])
        row = out["festivals"][-1]
        self.assertEqual(row["lineup"], [])
        self.assertIsNone(row["city"])
        self.assertIsNone(row["price"])
        self.assertEqual(len(out["festivals"]), len(cal["festivals"]) + 1)

        # A private patch cannot manufacture the publisher's trust marker.
        untrusted, held = stage(
            cal, hist, patch, {}, DAY,
            published_calendar=cal, published_history=hist)
        self.assertEqual(held["accepted_additions"], [])
        self.assertEqual(len(untrusted["festivals"]), len(cal["festivals"]))

    def test_not_an_open_registry(self):
        rows = []
        for i in range(9):
            r = deepcopy(HIST)
            r["slug"] = f"archive-{i}"
            r["name"] = f"Festival {i} Rock"
            rows.append(r)
        refs = candidates_from_signed_history(
            history(*rows), published(), DAY, limit=4, tick=1)
        self.assertEqual(len(refs), 4)
        self.assertEqual(len(set(x[0]["slug"] for x in refs)), 4)
        with self.assertRaises(ValueError):
            candidates_from_signed_history(history(*rows),
                                           published(), DAY, limit=100)


if __name__ == "__main__":
    unittest.main()
