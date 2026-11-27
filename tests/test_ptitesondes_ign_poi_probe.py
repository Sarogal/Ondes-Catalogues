import unittest
from urllib.parse import urlsplit, parse_qs
from ptitesondes_ign_poi_probe import poi_url, summarize, probe

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
