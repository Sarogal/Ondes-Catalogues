import unittest
from urllib.parse import urlsplit, parse_qs
from ptitesondes_ign_poi_probe import poi_url, summarize, probe, exact_poi_point, verify_admin_point

class IGNPOIProbeTests(unittest.TestCase):
    def test_encoded_query_and_scope(self):
        q = parse_qs(urlsplit(poi_url("Lieu & culture", "2A004")).query)
        self.assertEqual(q["q"], ["Lieu & culture"])
        self.assertEqual(q["index"], ["poi"])
        self.assertEqual(q["citycode"], ["2A004"])
        with self.assertRaises(ValueError):
            poi_url("Lieu", "unknown")

    def test_aggregates_never_reveal_raw_fields(self):
        result = summarize({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"name": "PRIVATE", "type": "poi"},
             "geometry": {"type": "Point", "coordinates": [2, 48]}}]})
        self.assertEqual(result["valid_points"], 1)
        self.assertNotIn("PRIVATE", str(result))
        self.assertFalse(result["publication_ready"])

    def test_exact_named_point_and_reject_ambiguous_or_wrong_commune(self):
        import copy
        row = {"nom_du_lieu": "Ludothèque A", "commune": "Les Bois",
               "code_commune": "01234", "code_postal": "01230"}
        feature = {"type": "Feature", "properties": {"name": "Ludothèque A",
                   "city": "Les Bois", "citycode": "01234", "postcode": "01230",
                   "category": ["culture"], "score": 0.99},
                   "geometry": {"type": "Point", "coordinates": [2, 48]}}
        doc = {"type": "FeatureCollection", "features": [feature]}
        self.assertEqual(exact_poi_point(row, doc), (48, 2))
        for field, value in (("citycode", "99999"), ("score", 0.3),
                             ("type", "municipality"), ("name", "Ludothèque B")):
            wrong = copy.deepcopy(doc)
            wrong["features"][0]["properties"][field] = value
            self.assertIsNone(exact_poi_point(row, wrong))
        self.assertIsNone(exact_poi_point(row, dict(doc, features=[feature, feature])))
        self.assertFalse(verify_admin_point(row, (48, 2), lambda *_: []))

    def test_rejection_reason_does_not_emit_values(self):
        from collections import Counter
        row = {"nom_du_lieu": "Ludothèque A", "commune": "Les Bois",
               "code_commune": "01234", "code_postal": None}
        d = Counter()
        self.assertIsNone(exact_poi_point(row, {}, d))
        self.assertEqual(dict(d), {"directory_postcode_format": 1})
        row["code_postal"] = "01230"
        self.assertIsNone(exact_poi_point(row, {"type": "FeatureCollection", "features": []}, d))
        self.assertEqual(d["poi_exact_name_missing"], 1)
        self.assertNotIn("Ludothèque", str(d))

    def test_probe_selects_discovered_identity(self):
        row = {"nom_du_lieu": "Ludothèque A", "commune": "Les Bois", "code_commune": "01234"}
        seen = []
        def query(name, code):
            seen.append((name, code))
            return {"type": "FeatureCollection", "features": []}
        result = probe(discover=lambda: {"records": [{"city": "Les Bois", "venue": "Ludothèque A"}]},
                       lookup=lambda *_: row, query=query)
        self.assertEqual(seen, [("Ludothèque A", "01234")])
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["public_writes"], 0)

if __name__ == "__main__":
    unittest.main()
