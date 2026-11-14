"""Offline, fail-closed Cernunnos 2027 proof tests; never infer days."""
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
    def test_accepted_five_new_artists_without_unverified_days(self):
        old = published()
        updated = revalidate(old, running(), groups(), TODAY)
        self.assertIsNotNone(updated)
        self.assertEqual(updated["lineup"][:20], old["lineup"])
        self.assertEqual(updated["lineup"][20:], list(NEW_LINEUP))
        self.assertEqual(updated["bands"], 25)
        self.assertNotIn("lineupByDate", updated)
        self.assertNotIn("surprise", updated["lineup"])
        self.assertIn("jours discordants", updated["notes"])
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


    def test_cloud_candidate_stamps_real_change_but_not_noop(self):
        from copy import deepcopy
        from unittest.mock import patch
        from grossesondes_cloud_sync import build_candidate

        initial = {
            "schema": 1,
            "generatedAt": "2026-11-05",
            "festivals": [published()],
        }
        history = {"schema": 2, "knownFestivals": []}
        records = {"festivals.json": initial,
                   "festival-history.json": history}
        report = {"accepted_additions": [], "accepted_updates": [],
                  "held": [], "source_proofs": [],
                  "automatic_publication": False}
        def altered(reference, candidate, live):
            return candidate["festivals"] != live["festivals"]
        with patch("grossesondes_cloud_sync.stage",
                   return_value=(deepcopy(initial), report)), \
             patch("grossesondes_cloud_sync.validate_history_extension"), \
             patch("grossesondes_cloud_sync.merge_staged_with_approved",
                   side_effect=lambda *args: deepcopy(initial)), \
             patch("grossesondes_cloud_sync.safe_target",
                   side_effect=altered):
            changed, changed_report = build_candidate(
                records, records, {},
                {"cernunnos_running_order": running(),
                 "cernunnos_groups": groups()},
                TODAY, trusted_published=True
            )
            self.assertTrue(changed_report["changed"])
            self.assertEqual(changed["generatedAt"], TODAY)
            self.assertEqual(changed["festivals"][0]["bands"], 25)
            unmodified, old_report = build_candidate(
                records, records, {}, {}, TODAY, trusted_published=True
            )
            self.assertFalse(old_report["changed"])
            self.assertEqual(unmodified["generatedAt"], "2026-11-05")
            self.assertEqual(unmodified["festivals"][0]["bands"], 20)


if __name__ == "__main__":
    unittest.main()
