import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from official_admin_communes import (
    HOST, fetch_admin_communes, search_url, search_url_from_existing,
    verified_commune,
)


def feature(name="Colonne", code="39161", dep="39",
            lon=5.5577, lat=46.8832):
    return {"type": "Feature", "properties": {
                "nom": name, "code": code, "codeDepartement": dep},
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def response(*items):
    return {"type": "FeatureCollection", "features": list(items)}


class AdminCommuneTests(unittest.TestCase):
    def test_fixed_canonical_api_search_with_zone_overseas(self):
        url = search_url("Colonne")
        self.assertTrue(url.startswith("https://geo.api.gouv.fr/communes?"))
        self.assertIn("nom=Colonne", url)
        self.assertIn("zone=metro%2Cdrom%2Ccom", url)
        self.assertEqual(search_url_from_existing(url), url)
        for city in ("https://127.0.0.1", "Colonne?admin=yes",
                     "Colonne&evil=1", "../Colonne", "Colonne#x",
                     "A" * 120):
            with self.subTest(city=city):
                with self.assertRaises(ValueError):
                    search_url(city)

    def test_fixed_host_rejects_extra_queries_and_userinfo(self):
        url = search_url("Colonne")
        for candidate in (
            url + "&remote=http://127.0.0.1",
            url.replace("geo.api.gouv.fr", "geo.api.gouv.fr.evil.test"),
            url.replace("https://", "http://"),
            url + "&nom=Other",
            url + "#frag",
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    search_url_from_existing(candidate)

    def test_one_exact_commune_and_department_accepted(self):
        data = response(feature())
        calls = []
        def reader(url):
            calls.append(url)
            return data
        got = verified_commune("Colonne", "39", reader)
        self.assertEqual(len(calls), 1)
        self.assertEqual(got["codeInsee"], "39161")
        self.assertEqual((got["lat"], got["lon"]), (46.8832, 5.5577))
        self.assertEqual(got["geoPrecision"], "commune")
        self.assertEqual(got["markerMeaning"], "centre_indicatif_de_commune")
        self.assertEqual(got["geoSource"], calls[0])

    def test_corsica_and_overseas_allowed_without_mainland_bbox(self):
        for name, code, dep, lon, lat in (
            ("Ajaccio", "2A004", "2A", 8.7386, 41.9220),
            ("Saint-Pierre", "97502", "975", -56.17, 46.78),
            ("Papeete", "98735", "987", -149.56, -17.53),
        ):
            with self.subTest(city=name):
                hit = verified_commune(
                    name, dep,
                    lambda _: response(feature(name, code, dep, lon, lat)))
                self.assertIsNotNone(hit)
                self.assertEqual(hit["city"], name)

    def test_homonyms_and_wrong_department_are_never_guessed(self):
        duplicate = response(feature(), feature(code="39162", dep="69"))
        self.assertIsNone(verified_commune("Colonne", None, lambda _: duplicate))
        self.assertIsNone(verified_commune("Colonne", "75",
                                            lambda _: response(feature())))
        got = verified_commune("Colonne", "39", lambda _: duplicate)
        self.assertEqual(got["codeInsee"], "39161")
        # A label is not a code; the duplicate result remains ambiguous.
        self.assertIsNone(verified_commune("Colonne", "Jura",
                                            lambda _: duplicate))

    def test_reject_nonexact_or_unbounded_untrusted_responses(self):
        variants = [
            response(feature(name="Colombes")),
            response(feature(code="nonsense")),
            response(feature(lon=float("nan"))),
            response(feature(lat=90.1)),
            response(feature(lon=0, lat=0)),
            response(feature(lon=True)),
            response(*[feature() for _ in range(51)]),
            {"features": [feature()]},
            [],
        ]
        for raw in variants:
            with self.subTest(raw=str(raw)[:30]):
                self.assertIsNone(verified_commune(
                    "Colonne", "39", lambda _: raw))

    def test_transport_has_no_redirect_fallback_and_bounded_bytes(self):
        from unittest.mock import patch
        class Response:
            status = 302
            def getheader(self, key, default=""):
                return {"Content-Type": "application/geo+json",
                        "Content-Encoding": "identity"}.get(key, default)
            def read(self, maximum):
                return b"{}"
        class Connection:
            def __init__(self, *args, **kwargs):
                self.target = None
            def request(self, method, target, headers):
                self.target = target
                self.assert_local_request(method, target, headers)
            def assert_local_request(self, method, target, headers):
                if method != "GET" or not target.startswith("/communes?"):
                    raise AssertionError("Unpinned request")
            def getresponse(self):
                return Response()
            def close(self):
                return None
        with patch("official_admin_communes.DNSPinnedHTTPSConnection", Connection):
            with self.assertRaises(ValueError):
                fetch_admin_communes(search_url("Colonne"))


if __name__ == "__main__":
    unittest.main()
