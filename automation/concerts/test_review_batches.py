"""No-publication and fairness tests for the national batch review queue."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_batches import build_batches, region_of, markdown


def lead(n, dept, city, venue, tier="genre_documented"):
    return {
        "name": n, "date": "2026-11-25", "department": dept,
        "city": city, "venue": venue,
        "sourceUrl": "https://official.example/concert/" + n.lower(),
        "sourceKind": "agenda_officiel_structuré",
        "tier": tier,
        "individualOfficialLead": True,
        "publicationAllowed": False, "reviewRequired": True,
    }


def report(items):
    return {
        "schema": "grossesondes.concert.coverage-gaps.v1",
        "asOf": "2026-11-02",
        "publicationAllowed": False,
        "discovery": {"potentialMissing": len(items)},
        "priorityLeads": items,
    }


class ReviewBatchTests(unittest.TestCase):
    def test_geographic_balance_and_venue_cap_and_quarantine(self):
        items = ([lead(f"Paris {i}", "75", "Paris", "Le Club") for i in range(9)] +
                 [lead("Brest", "29", "Brest", "Cabaret Vauban"),
                  lead("Bordeaux", "33", "Bordeaux", "Salem"),
                  lead("Lille", "59", "Lille", "Brat Cave")])
        result = build_batches(report(items), batch_size=10, per_venue=2)
        self.assertEqual(result["selected"], 5)
        self.assertEqual(result["regionCounts"].get("Bretagne"), 1)
        self.assertEqual(result["regionCounts"].get("Nouvelle-Aquitaine"), 1)
        self.assertEqual(result["regionCounts"].get("Hauts-de-France"), 1)
        self.assertEqual(result["regionCounts"].get("Île-de-France"), 2)
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["reviewedOrApproved"], 0)
        self.assertTrue(all(x["approvalDecision"] == "not_reviewed"
                            and x["publicationAllowed"] is False for x in result["items"]))

    def test_dynamic_order_prioritizes_undercounted_regions(self):
        data = report([
            lead("Paris", "75", "Paris", "Big Club"),
            lead("Normandie", "14", "Caen", "Petit Club"),
            lead("Centre", "45", "Orléans", "Astrolabe"),
            lead("Corse", "2A", "Ajaccio", "Aghja"),
        ])
        data["catalogue"] = {"regions": {
            "Île-de-France": 42, "Normandie": 8, "Centre-Val de Loire": 1,
            "Corse": 0,
        }}
        results = build_batches(data, batch_size=2)
        self.assertEqual([x["region"] for x in results["items"]],
                         ["Corse", "Centre-Val de Loire"])
        order = results["regionPriorityOrder"]
        self.assertLess(order.index("Corse"), order.index("Centre-Val de Loire"))
        self.assertLess(order.index("Centre-Val de Loire"), order.index("Normandie"))
        self.assertLess(order.index("Normandie"), order.index("Île-de-France"))
        self.assertFalse(results["publicationAllowed"])
        self.assertEqual(region_of("45"), "Centre-Val de Loire")
        self.assertEqual(region_of("14"), "Normandie")
        self.assertEqual(region_of("2A"), "Corse")
        self.assertEqual(region_of("971"), "Guadeloupe")

    def test_unknown_genre_duplicate_and_missing_source_never_enter_review(self):
        a = lead("One", "59", "Lille", "Salle")
        b = copy.deepcopy(a)
        c = lead("Unknown", "35", "Rennes", "Salle", tier="genre_to_verify")
        d = lead("No source", "33", "Bordeaux", "Salle")
        d["sourceUrl"] = None
        result = build_batches(report([a, b, c, d]))
        self.assertEqual(result["selected"], 1)

    def test_invalid_inputs_fail_closed(self):
        for variant in ("wrong-schema", "not-quarantined", "bad-row"):
            x = report([lead("One", "29", "Brest", "Vauban")])
            if variant == "wrong-schema":
                x["schema"] = "unknown"
            elif variant == "not-quarantined":
                x["publicationAllowed"] = True
            else:
                x["priorityLeads"][0]["publicationAllowed"] = True
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                build_batches(x)
        self.assertEqual(region_of("02"), "Hauts-de-France")
        self.assertEqual(region_of("29"), "Bretagne")
        self.assertEqual(region_of("33"), "Nouvelle-Aquitaine")
        self.assertIn("Aucune date approuvée", markdown(build_batches(report([]))))


if __name__ == "__main__":
    unittest.main()
