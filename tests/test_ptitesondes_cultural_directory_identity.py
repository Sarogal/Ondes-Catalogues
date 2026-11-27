import unittest
from ptitesondes_cultural_directory_identity import directory_identity, same_official_address

ROW = {"commune": "Les Bois", "nom_du_lieu": "Bibliothèque des enfants",
       "nom_usuel_du_lieu": "Ludothèque du parc", "code_commune": "01234",
       "code_postal": "01230", "numero_et_libelle_voie": "12 bis rue des Jeux",
       "adresse_complete": "12 bis rue des Jeux, 01230 Les Bois",
       "latitude": 0, "longitude": 0}


class CulturalIdentityTests(unittest.TestCase):
    def test_exact_alias_address_no_gps_or_permission(self):
        facts = directory_identity("Les Bois", "Ludothèque du parc", ROW)
        self.assertIsNotNone(facts)
        self.assertEqual(facts["insee"], "01234")
        self.assertEqual(facts["housenumber"], "12 bis")
        self.assertFalse(facts["public_eligible"])
        self.assertNotIn("latitude", facts)
        self.assertNotIn("longitude", facts)
        self.assertTrue(same_official_address(facts, dict(facts)))
        self.assertFalse(same_official_address(facts, dict(facts, street="rue voisine")))

    def test_conflicting_identity_address_or_entrance_is_held(self):
        for changes in (
            {"commune": "Autre ville"},
            {"code_commune": "1234"},
            {"code_postal": 1230},
            {"nom_usuel_du_lieu": "Autre lieu"},
            {"adresse_complete": "14 rue des Jeux, 01230 Les Bois"},
            {"adresse_entree_public": "14 rue des Jeux, 01230 Les Bois"},
            {"numero_et_libelle_voie": "rue des Jeux"},
        ):
            self.assertIsNone(directory_identity("Les Bois", "Ludothèque du parc",
                                                 dict(ROW, **changes)), changes)

    def test_exact_component_variants_without_conflicting_information(self):
        for value in ("12 bis rue des Jeux", "12 bis rue des Jeux 01230",
                      "12 bis rue des Jeux Les Bois",
                      "12 bis rue des Jeux Les Bois 01230",
                      "12 bis rue des Jeux 01230 Les Bois France"):
            row = dict(ROW, adresse_complete=value, adresse_entree_public=value)
            facts = directory_identity("Les Bois", "Ludothèque du parc", row)
            self.assertIsNotNone(facts, value)
            self.assertEqual(facts["address_query"], "12 bis rue des jeux 01230 Les Bois")
            self.assertFalse(facts["public_eligible"])
            self.assertIsNone(directory_identity("Les Bois", "Ludothèque du parc", row,
                                                 equivalent_formats=False))
        for value in ("14 rue des Jeux", "12 bis rue des Jeux 99999 Les Bois",
                      "12 bis rue des Jeux Autre ville", "12 bis rue des Jeux 01230 Les Bois autre bâtiment"):
            self.assertIsNone(directory_identity("Les Bois", "Ludothèque du parc",
                                                 dict(ROW, adresse_complete=value)), value)

    def test_diagnostics_distinguish_missing_number_and_conflict(self):
        from collections import Counter
        counts = Counter()
        for changes in ({"numero_et_libelle_voie": "rue des Jeux"},
                        {"adresse_complete": "14 rue des Jeux, 01230 Les Bois"},
                        {"adresse_entree_public": "14 rue des Jeux, 01230 Les Bois"}):
            self.assertIsNone(directory_identity("Les Bois", "Ludothèque du parc",
                                                 dict(ROW, **changes), counts))
        self.assertEqual(dict(counts), {"numbered_street_missing": 1,
                                       "complete_address_mismatch": 1,
                                       "entrance_address_mismatch": 1})
        self.assertNotIn("Les Bois", str(counts))

    def test_no_guessed_address_or_partial_comparison(self):
        self.assertIsNone(directory_identity("Les Bois", "Ludothèque du parc",
                                             dict(ROW, adresse_complete=None)))
        self.assertFalse(same_official_address({}, {}))
        facts = directory_identity("Les Bois", "Bibliothèque des enfants", ROW)
        self.assertFalse(same_official_address(facts, dict(facts, postcode="99999")))


if __name__ == "__main__":
    unittest.main()
