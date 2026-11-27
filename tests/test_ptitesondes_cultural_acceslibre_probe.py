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
                self.assertEqual(counts, {"identity_" + detail: 1, "structured_absent": 1})
                self.assertNotIn("Ludothèque", str(counts))

    def test_structured_place_hint_never_bypasses_visible_content(self):
        import json
        from collections import Counter
        from ptitesondes_cultural_acceslibre_probe import structured_place_hint, inspect_official_content
        lead = {"nom_du_lieu": "Ludothèque A", "commune": "Les Bois",
                "code_postal": "01230", "numero_et_libelle_voie": "Rue des Jeux"}
        node = {"@type": "Library", "name": "Ludothèque A",
                "address": {"streetAddress": "Rue des Jeux", "postalCode": "01230",
                            "addressLocality": "Les Bois"}}
        def html(data):
            return '<script type="application/ld+json">' + json.dumps(data) + '</script>'
        self.assertEqual(structured_place_hint(lead, html({"@graph": [node]})),
                         "structured_address_concordant_hint")
        self.assertEqual(structured_place_hint(lead, html([node, node])),
                         "structured_identity_ambiguous")
        self.assertEqual(structured_place_hint(lead, html(dict(node, address={}))),
                         "structured_address_unconfirmed")
        self.assertEqual(structured_place_hint(lead, html(dict(node, name="Autre"))),
                         "structured_identity_unconfirmed")
        self.assertEqual(structured_place_hint(lead, html(dict(node, **{"@type": "Event"}))),
                         "structured_identity_unconfirmed")
        self.assertEqual(structured_place_hint(lead, html(node) * 9),
                         "structured_budget_exceeded")
        counts = Counter()
        self.assertEqual(inspect_official_content(lead, html(node), diagnostics=counts),
                         "page_identity_unconfirmed")
        self.assertEqual(counts["structured_address_concordant_hint"], 1)

    def test_broader_sample_is_bounded_and_stops_at_directory_end(self):
        from urllib.parse import parse_qs, urlsplit
        from ptitesondes_cultural_acceslibre_probe import candidates, MAX_PROBE_PAGES
        from ptitesondes_cultural_directory_discovery import PAGE_SIZE
        calls = []
        def fetch(url):
            page = int(parse_qs(urlsplit(url).query)["page"][0])
            calls.append(page)
            return {"meta": {"total": PAGE_SIZE + 1},
                    "data": [{} for _ in range(PAGE_SIZE if page == 1 else 1)]}
        self.assertEqual(candidates(fetch), [])
        self.assertEqual(calls, [1, 2])
        for invalid in (0, MAX_PROBE_PAGES + 1, True):
            with self.assertRaises(ValueError):
                candidates(fetch, pages=invalid)
        self.assertEqual(calls, [1, 2])

    def test_broader_sample_rejects_directory_drift(self):
        from ptitesondes_cultural_acceslibre_probe import candidates
        from ptitesondes_cultural_directory_discovery import PAGE_SIZE
        responses = iter([
            {"meta": {"total": PAGE_SIZE * 3}, "data": [{} for _ in range(PAGE_SIZE)]},
            {"meta": {"total": PAGE_SIZE * 4}, "data": [{} for _ in range(PAGE_SIZE)]},
        ])
        with self.assertRaisesRegex(ValueError, "directory_changed_during_scan"):
            candidates(lambda _: next(responses), pages=2)

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
