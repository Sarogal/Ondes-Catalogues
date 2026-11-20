from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_sync_summary import render


def report(changed=False):
    return {
        "changed": changed,
        "accepted_additions": ["foo-2027"],
        "accepted_updates": [{"slug": "bar-2027", "fields": ["lineup"]}],
        "held": [{"slug": "pending-2027", "reason": "preuve officielle insuffisante"}],
        "candidate_total": 124,
        "patch_age_days": 0,
        "unchanged_history": True,
        "mode": "publish",
    }


class FestivalSyncSummaryTests(unittest.TestCase):
    def test_already_published_and_future_map_gaps_are_not_approvals(self):
        data=report()
        data["changed"]=False
        data["accepted_additions"]=[]
        data["already_published"]=["festival-666-2027","helixfest-2027"]
        data["future_map_coverage"]={
            "dated_future_editions":64,
            "undated_catalogue_editions":4,
            "coordinates_present":53,
            "coordinates_missing":11,
            "explicitly_hidden":9,
            "explicitly_visible_flag":13,
            "visibility_flag_absent":42,
            "coordinates_present_not_explicitly_hidden":53,
            "city_missing":9,
        }
        output=render(data,False)
        self.assertIn("Déjà présentes dans le catalogue signé : **2**",output)
        self.assertIn("Éditions futures : **64**",output)
        self.assertIn("sans coordonnées : **11**",output)
        self.assertIn("Marqueur explicitement désactivé : **9**",output)
        self.assertIn("Une exécution GitHub Actions réussie ne signifie pas",output)
        self.assertNotIn("Déploiement autorisé par la décision",output)

    def test_report_duplicate_and_map_counter_tampering_refused(self):
        data=report()
        data["accepted_additions"]=["same"]
        data["already_published"]=["same"]
        with self.assertRaises(ValueError):
            render(data)
        data=report()
        data["already_published"]=["same","same"]
        with self.assertRaises(ValueError):
            render(data)
        data=report()
        data["future_map_coverage"]={
            "dated_future_editions":2,
            "undated_catalogue_editions":0,
            "coordinates_present":2,
            "coordinates_missing":1,
            "explicitly_hidden":0,
            "explicitly_visible_flag":0,
            "visibility_flag_absent":2,
            "coordinates_present_not_explicitly_hidden":3,
            "city_missing":1,
        }
        with self.assertRaises(ValueError):
            render(data)
        data["future_map_coverage"]["coordinates_present"]=True
        with self.assertRaises(ValueError):
            render(data)

    def test_no_new_release_despite_validated_historical_candidates(self):
        result=render(report(changed=False), deploy_decision=False)
        self.assertIn("Aucune nouvelle modification du JSON public", result)
        self.assertIn("Propositions différées ou refusées : **1**", result)
        self.assertIn("pending-2027", result)
        self.assertNotIn("Déploiement autorisé par la décision du job", result)

    def test_preview_with_new_candidate_does_not_claim_publication(self):
        result=render(report(changed=True), deploy_decision=False)
        self.assertIn("catalogue candidat seulement", result)
        self.assertIn("confirmation de GitHub Pages", render(report(True), True))
        self.assertIn("ne signifie pas qu'une nouvelle annonce a été publiée", result)

    def test_malformed_reports_fail_closed(self):
        data=report()
        data["changed"]="false"
        with self.assertRaises(ValueError):
            render(data)
        data=report()
        del data["held"]
        with self.assertRaises(ValueError):
            render(data)
        data=report()
        data["candidate_total"]=-1
        with self.assertRaises(ValueError):
            render(data)

    def test_private_reason_cannot_inject_markdown_heading(self):
        data=report()
        data["held"][0]["reason"]="unsafe\n### Fake publication successful"
        result=render(data)
        self.assertNotIn("\n### Fake publication successful", result)


if __name__=="__main__":
    unittest.main()
