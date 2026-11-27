import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from ptitesondes_cultural_directory_discovery import scan, PAGE_SIZE, MAX_PAGES, MAX_ROWS_PER_SCAN, format_counts

def fixture(i):
    return {"commune": "Les Bois", "nom_du_lieu": f"Ludothèque {i}",
            "code_commune": "01234", "latitude": 0, "longitude": 0}

class CulturalDiscoveryTests(unittest.TestCase):
    def test_rotation_and_wrap_no_gps_or_permission(self):
        calls = []
        def get(url):
            page = int(parse_qs(urlsplit(url).query)["page"][0])
            calls.append(page)
            return {"meta": {"total": PAGE_SIZE + 1},
                    "data": [fixture(i) for i in range((page-1)*PAGE_SIZE,
                        min(page*PAGE_SIZE, PAGE_SIZE+1))]}
        result = scan(fetch=get)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(result["next_page"], 1)
        self.assertEqual(result["rows_examined"], PAGE_SIZE + 1)
        self.assertEqual(len(result["records"]), PAGE_SIZE + 1)
        self.assertTrue(all(not r["public_eligible"] and not r["gps_verified"]
                            and "latitude" not in r for r in result["records"]))

    def test_bounded_throughput_and_cursor_continuity(self):
        def get(url):
            page = int(parse_qs(urlsplit(url).query)["page"][0])
            return {"meta": {"total": 2000},
                    "data": [fixture(i) for i in range((page-1)*PAGE_SIZE, page*PAGE_SIZE)]}
        with patch("ptitesondes_cultural_directory_discovery.monotonic", return_value=0):
            result = scan(9, fetch=get)
        self.assertEqual(result["rows_examined"], MAX_ROWS_PER_SCAN)
        self.assertEqual(result["next_page"], 9 + MAX_PAGES)
        self.assertEqual(len(result["records"]), MAX_ROWS_PER_SCAN)
        with patch("ptitesondes_cultural_directory_discovery.monotonic", side_effect=[0, 31]):
            result = scan(9, fetch=get)
        self.assertEqual(result["rows_examined"], PAGE_SIZE)
        self.assertEqual(result["next_page"], 10)

    def test_incomplete_response_cannot_advance_cursor(self):
        with self.assertRaises(ValueError):
            scan(fetch=lambda _: {"meta": {"total": 100}, "data": [fixture(1)]})

    def test_cursor_recovers_only_if_directory_shrank(self):
        calls = []
        def get(url):
            n = int(parse_qs(urlsplit(url).query)["page"][0])
            calls.append(n)
            return {"meta": {"total": 1}, "data": [fixture(1)] if n == 1 else []}
        result = scan(17, fetch=get)
        self.assertEqual(calls, [17, 1])
        self.assertEqual(result["next_page"], 1)
        self.assertEqual(len(result["records"]), 1)

    def test_in_range_bad_page_is_not_skipped(self):
        def get(url):
            n = int(parse_qs(urlsplit(url).query)["page"][0])
            return {"meta": {"total": 100},
                    "data": [fixture(i) for i in range(20)] if n == 1 else []}
        with self.assertRaises(ValueError):
            scan(3, fetch=get)

    def test_format_diagnostics_only_emit_shapes(self):
        counts = format_counts([{"site_internet_et_autres_liens": '["https://secret.example"]',
                                 "accessible_au_public": "oui", "code_commune": "01234"},
                                {"accessible_au_public": True, "code_commune": None}])
        self.assertEqual(counts["site_internet_et_autres_liens"], {"json_list_text": 1, "missing": 1})
        self.assertEqual(counts["accessible_au_public"], {"boolean_text": 1, "boolean": 1})
        self.assertNotIn("secret", str(counts))

    def test_structured_descriptions_and_json_domain_labels(self):
        for value in ([{"lang": "fr", "value": "Ateliers pour enfants"}],
                      '[{"libelle": "Éveil musical"}]',
                      {"fr": {"texte": "Spectacles jeune public"}}):
            row = dict(fixture(1), nom_du_lieu="Musée municipal", description=value)
            result = scan(fetch=lambda _: {"meta": {"total": 1}, "data": [row]})
            self.assertEqual(len(result["records"]), 1)
            self.assertFalse(result["records"][0]["public_eligible"])

    def test_structured_metadata_is_not_family_evidence(self):
        row = dict(fixture(1), nom_du_lieu="Musée municipal",
                   description=[{"url": "https://example.org/enfants", "enfants": True,
                                 "value": "Expositions temporaires"}])
        result = scan(fetch=lambda _: {"meta": {"total": 1}, "data": [row]})
        self.assertEqual(result["records"], [])

    def test_generic_culture_not_assumed_family_relevant(self):
        row = dict(fixture(1), nom_du_lieu="Musée municipal")
        result = scan(fetch=lambda _: {"meta": {"total": 1}, "data": [row]})
        self.assertEqual(result["records"], [])
        row["description"] = "Ateliers pour enfants"
        result = scan(fetch=lambda _: {"meta": {"total": 1}, "data": [row]})
        self.assertEqual(len(result["records"]), 1)

if __name__ == "__main__":
    unittest.main()
