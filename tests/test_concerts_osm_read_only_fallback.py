"""Closed-form, safe OSM data transport queries; never arbitrary OverpassQL."""
import math
import unittest
from urllib.parse import parse_qs, urlsplit

from automation.concerts import osm_read_only_fallback as api


class ReadOnlyOsmQueryTests(unittest.TestCase):
    def test_single_named_feature_has_fixed_read_only_query(self):
        for kind in ("node", "way"):
            for format_ in ("xml", "json"):
                url = api.element(kind, "912345678", fmt=format_)
                self.assertEqual(urlsplit(url).scheme, "https")
                self.assertEqual(urlsplit(url).hostname,
                                 "overpass.private.coffee")
                data = parse_qs(urlsplit(url).query)["data"][0]
                self.assertEqual(data,
                    "[out:" + format_ + "][timeout:12];" +
                    kind + "(912345678);out body;")
                self.assertNotIn("http", data)

    def test_untrusted_osm_expression_or_wrong_kind_rejected_before_network(self):
        for kind, ident in (
            ("node", "0"), ("node", "-1"), ("node", "9123);out;node(1"),
            ("node", "912345678\n"), ("node", "912345678" * 4),
            ("relation", "912345678"), ("way", "1.2"),
            ("way", "http://unsafe.invalid"),
        ):
            with self.subTest(kind=kind, ident=ident):
                with self.assertRaises(ValueError):
                    api.element(kind, ident)

    def test_small_french_bbox_no_user_query_code(self):
        url = api.nearby(47.39435, 0.68690, 47.39565, 0.68910)
        q = parse_qs(urlsplit(url).query)["data"][0]
        self.assertIn("node(47.394350,0.686900,47.395650,0.689100)", q)
        self.assertIn("way(47.394350,0.686900,47.395650,0.689100)", q)
        self.assertIn("(._;>;);out body;", q)
        self.assertNotIn("https", q)

    def test_large_foreign_inverted_or_nonfinite_bbox_fails(self):
        invalid = (
            (47, 0, 50, 1),
            (47, 0, 47, 0.001),
            (47, 0.001, 47.001, -0.01),
            (55, 0, 55.001, 0.01),
            (47, math.inf, 47.001, 0.01),
            (47, 0, 47.012, 0.01),
        )
        for bounds in invalid:
            with self.subTest(bounds=bounds):
                with self.assertRaises(ValueError):
                    api.nearby(*bounds)


if __name__ == "__main__":
    unittest.main()
