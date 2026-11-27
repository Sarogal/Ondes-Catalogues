import json
import unittest

from ptitesondes_national_cultural_directory_probe import schema_summary, probe, URL, exact_directory_record


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

    def test_exact_lookup_combines_both_names_without_duplicate_identity(self):
        from urllib.parse import parse_qs, urlsplit
        row = {"__id": 17, "commune": "Cité", "nom_du_lieu": "Ludothèque",
               "nom_usuel_du_lieu": "Ludothèque"}
        calls = []
        def fetch(url):
            calls.append(parse_qs(urlsplit(url).query))
            return {"data": [row], "meta": {"total": 1}}
        self.assertEqual(exact_directory_record("Cité", "Ludothèque", fetch=fetch), row)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["commune__exact"], ["Cité"])
        self.assertEqual(calls[0]["nom_du_lieu__exact"], ["Ludothèque"])
        self.assertEqual(calls[1]["nom_usuel_du_lieu__exact"], ["Ludothèque"])

    def test_lookup_holds_duplicates_wrong_identity_and_partial_results(self):
        row = {"__id": 17, "commune": "Cité", "nom_du_lieu": "Ludothèque"}
        def ambiguous(_):
            return {"data": [row, dict(row, __id=18)], "meta": {"total": 2}}
        self.assertIsNone(exact_directory_record("Cité", "Ludothèque", fetch=ambiguous))
        for data, total in (([row], 9), ([dict(row, commune="Autre")], 1)):
            with self.assertRaises(ValueError):
                exact_directory_record("Cité", "Ludothèque",
                    fetch=lambda _: {"data": data, "meta": {"total": total}})

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
