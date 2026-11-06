from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from watch_summary import render


def report():
    return {
        "schema": "grossesondes.source-watch-report.v1",
        "date": "2026-11-04",
        "scanned": [{"slug": "x"}, {"slug": "y"}],
        "unavailable": [{"slug": "helloasso-2027", "reason": "HTTPError: 403 Forbidden"}],
        "coverage": {"catalogue_editions": 124,
                     "official_sources": 93,
                     "editions_without_official_https": 25},
        "candidateUpdateCount": 0, "candidateEditionCount": 0,
        "deferredAdded": 0,
    }


class SummaryTests(unittest.TestCase):
    def test_accurate_no_change_and_failures(self):
        text=render(report())
        self.assertIn("Sources tentées : 3", text)
        self.assertIn("pages exploitables : 2", text)
        self.assertIn("indisponibles : 1", text)
        self.assertIn("124", text)
        self.assertIn("93", text)
        self.assertIn("25", text)
        self.assertIn("Aucun nouveau changement publiable", text)
        self.assertIn("403 Forbidden", text)
        self.assertIn("publiées par cette veille : **0**", text)

    def test_candidate_is_not_confused_with_publication(self):
        data=report()
        data.update(candidateUpdateCount=2, candidateEditionCount=1,
                    deferredAdded=3)
        text=render(data)
        self.assertIn("Nouvelles propositions d'édition : **1**", text)
        self.assertIn("propositions privées ne sont pas des publications", text)
        self.assertNotIn("Aucun nouveau changement publiable", text)
        self.assertIn("publiées par cette veille : **0**", text)

    def test_missing_official_sites_prioritized_without_certification(self):
        data=report()
        data["source_reference_leads_review_only"]=[
            {"slug":"already-over", "start_date":"2026-10-01",
             "candidate_urls":["https://old.example.org"],"official_status":"NOT_VERIFIED",
             "allowed_to_publish":False},
            {"slug":"upcoming-2027", "start_date":"2027-01-15",
             "candidate_urls":["https://reference.example.org/agenda"],"official_status":"NOT_VERIFIED",
             "allowed_to_publish":False},
            {"slug":"near-2026", "start_date":"2026-11-06",
             "candidate_urls":["https://helloasso.example.org/organizer"],"official_status":"NOT_VERIFIED",
             "allowed_to_publish":False},
            {"slug":"not-authorized", "start_date":"2026-11-07",
             "candidate_urls":["https://wrong.example.org"],"official_status":"VERIFIED",
             "allowed_to_publish":True},
        ]
        text=render(data)
        self.assertIn("2 édition(s) avec références à contrôler",text)
        self.assertLess(text.index("near-2026"),text.index("upcoming-2027"))
        self.assertNotIn("already-over",text)
        self.assertNotIn("not-authorized",text)
        self.assertIn("ne sont pas encore des preuves",text)
        self.assertIn("publiées par cette veille : **0**",text)

    def test_regional_pagination_failure_is_not_counted_as_success(self):
        data = report()
        data.update({
            "regional_festival_indexes_review_only": [{
                "region": "Nouvelle-Aquitaine",
                "index_url": "https://sortir.limoges.fr/agenda",
                "checked_url": "https://sortir.limoges.fr/agenda?page=1",
                "page_kind": "PAGINATION",
                "status": "INACCESSIBLE",
                "publication_authorized": False,
            }],
            "regional_festival_inaccessible_this_pass_review_only": 1,
            "regional_festival_pagination_attempted_review_only": 1,
            "regional_festival_pagination_checked_review_only": 0,
            "regional_festival_pagination_inaccessible_review_only": 1,
        })
        result = render(data)
        self.assertIn("1 tentative(s) différée(s)", result)
        self.assertIn("0 page(s) accessibles, 1 indisponible(s)", result)
        self.assertIn("publications : 0", result)
        data["regional_festival_pagination_checked_review_only"] = 1
        with self.assertRaises(ValueError):
            render(data)

    def test_invalid_reference_queue_rejected(self):
        data=report()
        data["source_reference_leads_review_only"]="not a list"
        with self.assertRaises(ValueError):
            render(data)

    def test_qualification_section_is_private_and_rejects_authorized_entries(self):
        data=report()
        data["source_qualification_review_only"]=[
            {"slug":"festival-de-noel-xxxiv-2026",
             "url":"https://www.helloasso.com/associations/execution",
             "role":"TICKETING", "status":"REVIEW_REQUIRED",
             "publication_authorized":False},
            {"slug":"xion-metal-night", "url":"https://example.fr/edition",
             "role":"UNKNOWN", "status":"NOT_VERIFIED",
             "publication_authorized":False},
        ]
        result=render(data)
        self.assertIn("Sources candidates examinées",result)
        self.assertIn("2 URL(s) tentée(s) ; 1 dossier(s)",result)
        self.assertIn("ne modifie jamais",result)
        self.assertIn("publiées par cette veille : **0**",result)
        data["source_qualification_review_only"][0]["publication_authorized"]=True
        with self.assertRaises(ValueError):
            render(data)

    def test_organizer_links_remain_private_review_only(self):
        data=report()
        data["organizer_domain_leads_review_only"]=[
            {"slug":"festival-de-noel-xxxiv-2026",
             "source_url":"https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv-1",
             "candidate_url":"https://execution-mgt.fr/",
             "publication_authorized":False}
        ]
        result=render(data)
        self.assertIn("Liens possibles vers l'organisateur",result)
        self.assertIn("non certifié",result)
        self.assertIn("Aucun domaine n'est authentifié automatiquement",result)
        data["organizer_domain_leads_review_only"][0]["publication_authorized"]=True
        with self.assertRaises(ValueError):
            render(data)

    def test_schema_org_organizer_leads_are_counted_but_never_certified(self):
        data = report()
        data["organizer_domain_leads_review_only"] = [{
            "slug": "dawn-metal-festival-2026",
            "source_url": "https://www.phalempin.fr/agenda/dawn",
            "candidate_url": "https://refuge59.fr/",
            "evidence_format": "SCHEMA_ORG",
            "link_only": True,
            "publication_authorized": False,
        }]
        rendered = render(data)
        self.assertIn("**1** piste(s) schema.org", rendered)
        self.assertIn("SCHEMA_ORG ; non certifié", rendered)
        self.assertIn("Aucun domaine n'est authentifié automatiquement", rendered)
        for field, bad in [
            ("evidence_format", "AUTO_VERIFIED"),
            ("link_only", False), ("publication_authorized", True),
        ]:
            modified = dict(data["organizer_domain_leads_review_only"][0])
            modified[field] = bad
            data["organizer_domain_leads_review_only"] = [modified]
            with self.subTest(field=field), self.assertRaises(ValueError):
                render(data)

    def test_private_qualification_rotation_is_reported_honestly(self):
        data = report()
        data["source_qualification_scheduler_review_only"] = {
            "already_checked_today": 3, "inaccessible_backoff": 4,
            "eligible_editions": 6, "publication_authorized": False}
        result = render(data)
        self.assertIn("Rotation des références non certifiées", result)
        self.assertIn("Éditions éligibles : **6**", result)
        self.assertIn("URL déjà contrôlées aujourd'hui : **3**", result)
        self.assertIn("délai de reprise : **4**", result)
        self.assertIn("aucune publication autorisée", result)
        data["source_qualification_scheduler_review_only"]["publication_authorized"] = True
        with self.assertRaises(ValueError):
            render(data)
        data["source_qualification_scheduler_review_only"]["publication_authorized"] = False
        data["source_qualification_scheduler_review_only"]["eligible_editions"] = -1
        with self.assertRaises(ValueError):
            render(data)

    def test_private_roster_mentions_never_authorize_artists(self):
        data = report()
        data["source_qualification_review_only"] = [{
            "slug": "metal-fest-09-2026",
            "url": "https://backinblackasso.wixsite.com/metalfest09/groupes",
            "role": "ORGANIZER_CANDIDATE", "status": "REVIEW_REQUIRED",
            "publication_authorized": False, "artist_update_authorized": False,
            "roster_evidence_is_complete": False,
            "roster_names_mentioned_review_only": ["Noveria", "Point Mort"],
            "roster_names_unmentioned_review_only": ["Ashed Winter"]
        }]
        summary = render(data)
        self.assertIn("Mentions de groupes du catalogue : **2/3**", summary)
        self.assertIn("ne sont pas des annulations", summary)
        data["source_qualification_review_only"][0]["artist_update_authorized"] = True
        with self.assertRaises(ValueError):
            render(data)
        data["source_qualification_review_only"][0]["artist_update_authorized"] = False
        data["source_qualification_review_only"][0]["roster_evidence_is_complete"] = True
        with self.assertRaises(ValueError):
            render(data)

    def test_consolidated_domain_links_are_explicitly_not_ownership_proof(self):
        data = report()
        dossier = {
            "slug": "festival-de-noel-xxxiv-2026",
            "candidate_domain": "execution-mgt.fr",
            "candidate_urls": ["https://execution-mgt.fr/"],
            "source_count": 2,
            "references": [
                {"source_url": "https://sortir.limoges.fr/a",
                 "source_role": "INSTITUTION"},
                {"source_url": "https://zinor.fr/a",
                 "source_role": "VENUE"}],
            "corroboration_level": "MULTI_SOURCE_LINK_ONLY",
            "link_only": True, "ownership_proven": False,
            "official_site_authorized": False,
            "publication_authorized": False
        }
        data["organizer_domain_evidence_review_only"] = [dossier]
        summary = render(data)
        self.assertIn("liens consolidés, non certifiés", summary)
        self.assertIn("1 avec des liens", summary)
        self.assertIn("Aucun site officiel publié", summary)
        for field in ("link_only", "ownership_proven", "official_site_authorized",
                      "publication_authorized"):
            altered = dict(dossier, **{field: not dossier[field]})
            data["organizer_domain_evidence_review_only"] = [altered]
            with self.subTest(field=field), self.assertRaises(ValueError):
                render(data)

    def test_invalid_report_rejected(self):
        data=report()
        data["schema"]="wrong"
        with self.assertRaises(ValueError):
            render(data)
        data=report()
        data["candidateEditionCount"]=-1
        with self.assertRaises(ValueError):
            render(data)

    def test_untrusted_reason_cannot_inject_markdown_lines(self):
        data=report()
        data["unavailable"][0]["reason"]="error\n## Fake success\nPublished all festivals"
        output=render(data)
        self.assertNotIn("\n## Fake success", output)
        self.assertIn("publiées par cette veille : **0**", output)


if __name__=="__main__":
    unittest.main()
