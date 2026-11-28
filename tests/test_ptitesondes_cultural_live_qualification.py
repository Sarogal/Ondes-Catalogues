import unittest
from datetime import date
from ptitesondes_cultural_live_qualification import probe


class CulturalLiveQualificationTests(unittest.TestCase):
    def test_default_rehearsal_matches_both_production_routes(self):
        import inspect
        from ptitesondes_open_world_permanent_place_ban import discover_ban_routes
        self.assertIs(inspect.signature(probe).parameters["qualify"].default,
                      discover_ban_routes)

    def test_administration_probe_bounded_and_independent(self):
        from unittest.mock import patch
        from ptitesondes_cultural_live_qualification import probe_administration
        calls = []
        leads = [{"city": f"Private city {i}", "code_commune": "99999"} for i in range(9)]
        leads.insert(1, dict(leads[0]))
        def communes(city):
            calls.append(city)
            if city.endswith("1"):
                return [{"nom": city, "code": "12345"}, {"nom": city, "code": "54321"}]
            return [{"nom": city, "code": "12345"}]
        def directory(city, code):
            self.assertEqual(code, "12345")
            return {}
        with patch("ptitesondes_dila_municipal_domains.municipal_site_hosts",
                   return_value={"mairie.example"}):
            result = probe_administration(leads, commune_fetch=communes, directory_fetch=directory)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["counts"], {"attempted": 4, "unique_commune_code": 3,
                         "dila_authority_found": 3, "commune_not_unique": 1})
        self.assertNotIn("Private", str(result))
        self.assertEqual(result["public_writes"], 0)

    def test_bounded_sample_redacts_facts_and_isolates_failures(self):
        rows = [{"city": "Private city", "venue": str(i)} for i in range(12)]
        def qualify(row):
            if row["venue"] == "0":
                raise OSError("Private URL")
            if row["venue"] == "1":
                return {"private": "Private GPS"}
            return None
        result = probe(discover=lambda: {"records": rows, "rows_examined": 240},
                       qualify=qualify, build=lambda *_: {"private": "Private draft"},
                       today=date(2026, 11, 27))
        self.assertEqual(result["counts"], {"attempted": 8, "candidate_unavailable": 1,
                         "proof_found": 1, "valid_draft": 1, "not_qualified": 6})
        self.assertNotIn("Private", str(result))
        self.assertIn("read_failures", result)
        self.assertEqual(result["public_writes"], 0)
        self.assertFalse(result["publication_ready"])

if __name__ == "__main__":
    unittest.main()
