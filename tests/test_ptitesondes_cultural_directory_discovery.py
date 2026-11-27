import unittest
from urllib.parse import parse_qs, urlsplit
from ptitesondes_cultural_directory_discovery import scan, PAGE_SIZE

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

    def test_incomplete_response_cannot_advance_cursor(self):
        with self.assertRaises(ValueError):
            scan(fetch=lambda _: {"meta": {"total": 100}, "data": [fixture(1)]})

    def test_generic_culture_not_assumed_family_relevant(self):
        row = dict(fixture(1), nom_du_lieu="Musée municipal")
        result = scan(fetch=lambda _: {"meta": {"total": 1}, "data": [row]})
        self.assertEqual(result["records"], [])
        row["description"] = "Ateliers pour enfants"
        result = scan(fetch=lambda _: {"meta": {"total": 1}, "data": [row]})
        self.assertEqual(len(result["records"]), 1)

if __name__ == "__main__":
    unittest.main()
