import json
import unittest

from ptitesondes_national_cultural_directory_probe import schema_summary, probe, URL


class CulturalDirectoryProbeTests(unittest.TestCase):
    def test_public_field_names_only(self):
        value = schema_summary({"data": [{"name": "example", "city": "private sample"}]})
        self.assertEqual(value["schema_fields"], ["city", "name"])
        self.assertFalse(value["publication_ready"])
        self.assertNotIn("private sample", json.dumps(value))

    def test_incomplete_or_unexpected_schema_rejected(self):
        for doc in ({}, {"data": []}, {"data": [{}, {}]},
                    {"data": [{"bad\nkey": 1}]}, {"data": ["not a row"]}):
            with self.assertRaises(ValueError):
                schema_summary(doc)

    def test_no_redirect_or_noncanonical_endpoint(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def geturl(self): return "https://other.example/"
            def read(self, *_): return b'{"data":[{"name":"test"}]}'
        def opener(request, timeout):
            self.assertEqual(request.full_url, URL)
            return Response()
        with self.assertRaises(ValueError):
            probe(opener)


if __name__ == "__main__":
    unittest.main()
