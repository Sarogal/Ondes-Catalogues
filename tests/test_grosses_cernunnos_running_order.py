"""Offline, fail-closed Cernunnos 2027 official two-page evidence tests."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from grossesondes_cernunnos_running_order import (
    OLD_LINEUP, NEW_LINEUP, DAYS, revalidate,
)

TODAY = "2026-11-14"


def published():
    return {
        "slug": "cernunnos-pagan-fest",
        "officialSite": "https://www.cernunnospaganfest.fr/",
        "startDate": "2027-02-12",
        "endDate": "2027-02-14",
        "status": "Confirmé",
        "lineup": list(OLD_LINEUP),
        "bands": 20,
        "notes": "ancienne information",
        "auditSources": [],
        "lastVerified": "2026-10-30",
    }


def running():
    return (
        '<main><h1>REPARTITION DES GROUPES POUR 2027</h1>'
        '<p>Running Order #cernunnos2027 à suivre</p>'
        '<h2>VENDREDI 12 FEVRIER</h2>'
        '<p>' + " ".join(DAYS["2027-02-12"]) + '</p>'
        '<h2>SAMEDI 13 FEVRIER</h2>'
        '<p>' + " ".join(DAYS["2027-02-13"]) + '</p>'
        '<h2>DIMANCHE 14 FEVRIER</h2>'
        '<p>' + " ".join(DAYS["2027-02-14"]) + '</p>'
        '</main>'
    )


def groups():
    return ("LES GROUPES DE L'EDITION 2027 lineup #cernunnos2027 "
            + " ".join(NEW_LINEUP))


class OfficialRunningOrderTests(unittest.TestCase):
    def test_accepted_five_new_artists_and_25_dated_slots(self):
        old = published()
        updated = revalidate(old, running(), groups(), TODAY)
        self.assertIsNotNone(updated)
        self.assertEqual(updated["lineup"][:20], old["lineup"])
        self.assertEqual(updated["lineup"][20:], list(NEW_LINEUP))
        self.assertEqual(updated["bands"], 25)
        self.assertEqual(updated["lineupByDate"], {
            day: list(names) for day, names in DAYS.items()
        })
        self.assertNotIn("surprise", updated["lineup"])
        self.assertNotIn("lineupByDate", old)
        self.assertIsNone(revalidate(updated, running(), groups(), TODAY))

    def test_missing_names_or_year_in_either_page_block(self):
        old = published()
        for html, group_text in (
            (running().replace("Waldkauz", "Unknown"), groups()),
            (running(), groups().replace("Fianna Bán", "Unknown")),
            (running().replace("POUR 2027", "POUR 2026"), groups()),
            (running(), groups().replace("EDITION 2027", "EDITION 2026")),
            (running().replace("VENDREDI 12 FEVRIER", "VENDREDI 13 FEVRIER"), groups()),
        ):
            with self.subTest(html=html[-50:], group=group_text[-20:]):
                self.assertIsNone(revalidate(old, html, group_text, TODAY))

    def test_hidden_scripts_and_forged_day_cannot_qualify(self):
        text = running().replace("Albaluna", "Unknown")
        text += "<script>ALBALUNA VENDREDI 12 FEVRIER</script>"
        self.assertIsNone(revalidate(published(), text, groups(), TODAY))
        duplicate = running().replace("</main>", "<p>VENDREDI 12 FEVRIER</p></main>")
        self.assertIsNone(revalidate(published(), duplicate, groups(), TODAY))

    def test_wrong_identity_date_and_unknown_future_lineup_refused(self):
        old = published()
        for changed in (
            dict(old, slug="other-festival"),
            dict(old, startDate="2026-02-12"),
            dict(old, lineup=list(OLD_LINEUP)+["Undocumented"], bands=21),
            dict(old, officialSite="https://evil.example"),
        ):
            self.assertIsNone(revalidate(changed, running(), groups(), TODAY))
        self.assertIsNone(revalidate(old, running(), groups(), "2027-04-01"))


if __name__ == "__main__":
    unittest.main()
