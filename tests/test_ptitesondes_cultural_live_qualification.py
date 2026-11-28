import unittest
from datetime import date
from ptitesondes_cultural_live_qualification import probe


class CulturalLiveQualificationTests(unittest.TestCase):
    def test_default_rehearsal_matches_both_production_routes(self):
        import inspect
        from ptitesondes_open_world_permanent_place_ban import discover_ban_routes
        self.assertIs(inspect.signature(probe).parameters["qualify"].default,
                      discover_ban_routes)

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
