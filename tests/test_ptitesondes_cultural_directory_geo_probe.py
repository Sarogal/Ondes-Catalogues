import unittest
from ptitesondes_cultural_directory_geo_probe import classify, pair, point, distance


class CulturalDirectoryGeoProbeTests(unittest.TestCase):
    def test_distinct_points_are_not_publication_proof(self):
        row = {"latitude": "48.5", "longitude": "2.2",
               "coordonnees_geographiques_lieu": "48.5,2.2",
               "coordonnees_geographiques_commune_lieu": "48.6,2.2"}
        self.assertEqual(classify(row), "distinct_directory_point_unverified")
        self.assertEqual(classify(dict(row, coordonnees_geographiques_commune_lieu="48.5,2.2")),
                         "near_municipality_reference")
        self.assertEqual(classify(dict(row, coordonnees_geographiques_lieu="48.6,2.2")),
                         "place_fields_disagree")
        self.assertEqual(classify(dict(row, coordonnees_geographiques_commune_lieu=[2.2,48.5])),
                         "municipality_pair_unparsed")

    def test_nearby_exact_node_requires_named_place_not_centroid(self):
        from ptitesondes_cultural_directory_geo_probe import nearby_exact_node
        row = {"latitude": 48.5, "longitude": 2.2,
               "coordonnees_geographiques_lieu": "48.5,2.2",
               "coordonnees_geographiques_commune_lieu": "48.6,2.2",
               "nom_du_lieu": "Ludothèque A", "commune": "Les Bois",
               "code_postal": "01230"}
        obj = {"type": "node", "id": 123, "lat": 48.5, "lon": 2.2,
               "tags": {"name": "Ludothèque A", "addr:city": "Les Bois",
                        "addr:postcode": "01230", "amenity": "toy_library"}}
        self.assertEqual(nearby_exact_node(row, {"elements": [obj]}), (48.5, 2.2))
        for bad in (dict(obj, type="way"), dict(obj, lat=48.51),
                    dict(obj, tags=dict(obj["tags"], name="Autre")),
                    dict(obj, tags=dict(obj["tags"], **{"addr:city": "Autre"})),
                    dict(obj, tags=dict(obj["tags"], access="private"))):
            self.assertIsNone(nearby_exact_node(row, {"elements": [bad]}))
        self.assertIsNone(nearby_exact_node(row, {"elements": [obj, obj]}))
        self.assertIsNone(nearby_exact_node(row, {"elements": [obj], "remark": "partial"}))

    def test_invalid_coordinate_rejected(self):
        for lat, lng in ((0, 0), (91, 1), (float("nan"), 1), (True, 2), (1, 181)):
            self.assertIsNone(point(lat, lng))
        self.assertIsNone(pair([1, 2]))
        self.assertEqual(pair({"lat": 48, "lon": 2}), (48, 2))
        self.assertAlmostEqual(distance((48, 2), (48, 2)), 0)


if __name__ == "__main__":
    unittest.main()
