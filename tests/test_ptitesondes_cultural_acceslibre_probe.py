import unittest
from ptitesondes_cultural_acceslibre_probe import compare


class CulturalAcceslibreProbeTests(unittest.TestCase):
    def test_numberless_official_content_requires_visible_exact_facts(self):
        from ptitesondes_cultural_acceslibre_probe import inspect_official_content
        lead = {"nom_du_lieu": "Ludothèque A", "commune": "Les Bois",
                "code_commune": "01234", "code_postal": "01230",
                "numero_et_libelle_voie": "Rue des Jeux", "adresse_complete": "Rue des Jeux"}
        html = "<main><h1>Ludothèque A</h1><address>Rue des Jeux 01230 Les Bois</address><p>Jeux pour enfants</p><p>Accès libre</p></main>"
        self.assertEqual(inspect_official_content(lead, html), "page_content_concordant_unverified")
        self.assertEqual(inspect_official_content(lead, html.replace("Ludothèque A", "Autre lieu")), "page_identity_unconfirmed")
        self.assertEqual(inspect_official_content(lead, html.replace("Rue des Jeux", "Rue Autre")), "page_address_unconfirmed")
        self.assertEqual(inspect_official_content(lead, html.replace("Jeux pour enfants", "Activités")), "page_family_service_unconfirmed")
        self.assertEqual(inspect_official_content(lead, html.replace("Accès libre", "Accès réservé")), "page_access_restricted")

    def test_identity_diagnostics_do_not_relax_gate(self):
        from collections import Counter
        from ptitesondes_cultural_acceslibre_probe import inspect_official_content
        lead = {"nom_du_lieu": "Ludothèque A", "commune": "Les Bois"}
        cases = {
            "main_missing": "<div><h1>Ludothèque A</h1><p>Jeux pour enfants et accès libre</p></div>",
            "heading_missing": "<main><p>Ludothèque A, jeux pour enfants et accès libre</p></main>",
            "headings_multiple": "<main><h1>Ludothèque A</h1><h1>Autre lieu</h1><p>Jeux pour enfants</p></main>",
            "heading_different": "<main><h1>Autre lieu</h1><p>Ludothèque A, jeux pour enfants</p></main>",
        }
        for detail, html in cases.items():
            with self.subTest(detail=detail):
                counts = Counter()
                self.assertEqual(inspect_official_content(lead, html, diagnostics=counts),
                                 "page_identity_unconfirmed")
                self.assertEqual(counts, {"identity_" + detail: 1})
                self.assertNotIn("Ludothèque", str(counts))

    def test_exact_identity_and_concordance_are_only_hints(self):
        lead = {"nom_du_lieu": "Ludothèque A", "commune": "Les Bois",
                "code_commune": "01234", "code_postal": "01230",
                "numero_et_libelle_voie": "Rue des Jeux", "adresse_complete": "Rue des Jeux",
                "latitude": 48.5, "longitude": 2.2}
        erp = {"id": "unique", "name": "Ludothèque A", "commune": "Les Bois",
               "code_insee": "01234", "postal_code": "01230", "latitude": "48.5",
               "longitude": "2.2", "voie": "Rue des Jeux", "site_internet": ""}
        out = compare([lead], [erp])
        self.assertEqual(out["counts"], {"concordant_directory_hint": 1})
        self.assertEqual(out["numberless_counts"], {"concordant_directory_hint": 1})
        self.assertFalse(out["publication_ready"])
        self.assertNotIn("Ludothèque", str(out))
        self.assertEqual(compare([lead], [erp, dict(erp, id="other")])["counts"], {"ambiguous": 1})
        self.assertEqual(compare([lead], [dict(erp, code_insee="99999")])["counts"], {"no_exact_match": 1})
        self.assertEqual(compare([lead], [dict(erp, latitude="49")])["counts"], {"point_conflict": 1})


if __name__ == "__main__":
    unittest.main()
