"""Offline transport and end-to-end diagnostic tests for GPS fallback."""
from datetime import date
from pathlib import Path
from urllib.parse import quote
import copy
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_geo_fetch import (
    fetch_official_page, ban_query_for_official_address,
    fetch_ban_exact, diagnose_pinned_venue, MAX_GEO_BYTES,
)
from ptitesondes_openagenda_v2_geo_bridge import MAX_HTML

SOURCE = {
    "approved_host": "rouen.fr",
    "exact_url": "https://rouen.fr/jeunesse/bibliotheque",
}
LEAD = {
    "source_url": "https://openagenda.com/fr/rouen-test/events/12345678_lecture",
    "external_id": "12345678", "title": "Lecture pour enfants",
    "city": "Rouen", "venue": "Bibliothèque fictive",
    "date_start": "2026-12-05", "date_end": "2026-12-05",
}
VENUE = {
    "@context": "https://schema.org", "@type": "Library",
    "name": "Bibliothèque fictive",
    "address": {"@type": "PostalAddress",
                "streetAddress": "42 rue Henri II Plantagenet",
                "postalCode": "76100", "addressLocality": "Rouen",
                "addressCountry": "FR"},
}
HTML = ("<html><body><h1>Bibliothèque jeunesse</h1>"
        "<script type='application/ld+json'>" + json.dumps(VENUE)
        + "</script></body></html>")
GEO = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"type": "housenumber", "score": 0.972,
                       "housenumber": "42", "street": "rue Henri II Plantagenet",
                       "postcode": "76100", "city": "Rouen", "citycode": "76540"},
        "geometry": {"type": "Point", "coordinates": [1.09697, 49.42621]},
    }],
}
GEO_URL = ("https://data.geopf.fr/geocodage/search?q=" +
           quote("42 rue Henri II Plantagenet 76100 Rouen") + "&limit=2")
EVENT = {
    "uid": 12345678, "state": 2, "status": 1, "attendanceMode": 1,
    "timezone": "Europe/Paris", "title": {"fr": "Lecture pour enfants"},
    "description": {"fr": "Atelier pour enfants"},
    "rights": {"license": {"id": "etalab-2.0"},
               "licensor": {"name": "Organisateur fictif"}},
    "location": {"name": "Bibliothèque fictive", "adminLevel4": "Rouen",
                 "countryCode": "FR", "latitude": 49.42621,
                 "longitude": 1.09697},
    "timings": [{"begin": "2026-12-05T14:30:00+0100",
                 "end": "2026-12-05T15:30:00+0100"}],
}
AGENDA = {"agenda_slug": "rouen-test", "agenda_uid": "919191",
          "timezone": "Europe/Paris"}


class MockHTTP:
    def __init__(self, body, *, mime="text/html", status=200, redirect=False):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = {"Content-Type": mime}
        self.status = status
        self.redirect = redirect
        self.request = None

    def __call__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.request.full_url + "/redirect" if self.redirect else self.request.full_url

    def read(self, n):
        self.read_limit = n
        return self.body


class GeoHttpReadOnlyTests(unittest.TestCase):
    def test_trusted_official_fetch_is_bounded_and_exact(self):
        mock = MockHTTP(HTML)
        data = fetch_official_page(SOURCE, opener=mock)
        self.assertEqual(data, {"url": SOURCE["exact_url"], "html": HTML})
        self.assertEqual(mock.timeout, 12)
        self.assertEqual(mock.read_limit, MAX_HTML + 1)
        self.assertNotIn("oa_pk_", mock.request.full_url)
        self.assertEqual(mock.request.get_header("Accept"), "text/html")

    def test_trusted_host_and_pin_cannot_be_untrusted_openagenda_or_local(self):
        for source in (
            {}, {"approved_host": "openagenda.com",
                 "exact_url": "https://openagenda.com/fr/foo"},
            {"approved_host": "localhost",
             "exact_url": "https://localhost/lieu"},
            {"approved_host": "rouen.fr",
             "exact_url": "https://rouen.fr.evil.test/lieu"},
            {"approved_host": "rouen.fr",
             "exact_url": "https://rouen.fr/lieu#fragment"},
        ):
            with self.subTest(source=source):
                mock = MockHTTP(HTML)
                with self.assertRaises(ValueError):
                    fetch_official_page(source, opener=mock)
                self.assertIsNone(mock.request)

    def test_301_404_wrong_mime_large_html_and_invalid_utf8_refused(self):
        for mock in (
            MockHTTP(HTML, redirect=True),
            MockHTTP(HTML, status=404),
            MockHTTP(HTML, mime="application/octet-stream"),
            MockHTTP("x" * (MAX_HTML + 1)),
            MockHTTP(b"\xff"),
        ):
            with self.subTest(mime=mock.headers["Content-Type"],
                              status=mock.status, redirect=mock.redirect):
                with self.assertRaises(ValueError):
                    fetch_official_page(SOURCE, opener=mock)

    def test_ign_query_is_derived_from_pinned_official_address_only(self):
        page = {"url": SOURCE["exact_url"], "html": HTML}
        url = ban_query_for_official_address(LEAD, SOURCE, page)
        self.assertEqual(url, GEO_URL)
        not_pinned = dict(page, url="https://rouen.fr/other")
        self.assertIsNone(ban_query_for_official_address(LEAD, SOURCE, not_pinned))
        fake_page = dict(page, html="<h1>Ville sans adresse</h1>")
        self.assertIsNone(ban_query_for_official_address(LEAD, SOURCE, fake_page))
        forged = dict(LEAD, venue="Lieu inventé")
        self.assertIsNone(ban_query_for_official_address(forged, SOURCE, page))

    def test_official_geojson_transport_rejects_redirect_wrong_url_and_size(self):
        for url in (
            GEO_URL.replace("data.geopf.fr", "data.geopf.fr.evil.test"),
            GEO_URL + "&redirect=https://evil.test",
            GEO_URL.replace("limit=2", "limit=500"),
            "http://data.geopf.fr/geocodage/search?q=anything",
        ):
            with self.subTest(url=url):
                self.assertRaises(ValueError, fetch_ban_exact, url,
                                  MockHTTP(json.dumps(GEO), mime="application/json"))
        good = MockHTTP(json.dumps(GEO), mime="application/json")
        self.assertEqual(fetch_ban_exact(GEO_URL, opener=good), GEO)
        self.assertEqual(good.read_limit, MAX_GEO_BYTES + 1)
        for bad in (
            MockHTTP(json.dumps(GEO), mime="text/html"),
            MockHTTP(json.dumps(GEO), mime="application/json", redirect=True),
            MockHTTP(b"not json", mime="application/json"),
            MockHTTP(b"0" * (MAX_GEO_BYTES + 1), mime="application/json"),
        ):
            with self.subTest(mime=bad.headers["Content-Type"]):
                self.assertRaises(ValueError, fetch_ban_exact, GEO_URL, bad)

    def test_full_bounded_diagnostic_only_reports_safe_provenance_decision(self):
        trace = []
        def page_reader(source):
            trace.append("official")
            self.assertEqual(source, SOURCE)
            return {"url": SOURCE["exact_url"], "html": HTML}
        def geo_reader(url):
            trace.append("ign")
            self.assertEqual(url, GEO_URL)
            return copy.deepcopy(GEO)
        result = diagnose_pinned_venue(
            LEAD, EVENT, AGENDA, SOURCE, date(2026, 11, 18),
            official_reader=page_reader, geo_reader=geo_reader)
        self.assertEqual(trace, ["official", "ign"])
        self.assertTrue(result["geography_verified"])
        self.assertTrue(result["direct_source_structurally_valid"])
        self.assertEqual(result["public_writes"], 0)
        self.assertFalse(result["approval_granted"])
        raw = json.dumps(result)
        for private in ("Rouen", "12345678", "rouen.fr", "ao_pk_",
                        "Bibliothèque fictive", "42 rue"):
            self.assertNotIn(private, raw)

    def test_transport_error_never_leaks_private_url_or_credentials(self):
        def bad_reader(_):
            raise RuntimeError("PRIVATE_KEY=oa_pk_secret https://rouen.fr")
        state = diagnose_pinned_venue(
            LEAD, EVENT, AGENDA, SOURCE, date(2026, 11, 18),
            official_reader=bad_reader)
        raw = json.dumps(state)
        self.assertFalse(state["approval_granted"])
        self.assertFalse(state["geography_verified"])
        self.assertNotIn("oa_pk_", raw)
        self.assertNotIn("rouen.fr", raw)

    def test_malformed_ign_payload_is_not_verified_or_published(self):
        bad = dict(GEO, features=[])
        report = diagnose_pinned_venue(
            LEAD, EVENT, AGENDA, SOURCE, date(2026, 11, 18),
            official_reader=lambda src: {"url": SOURCE["exact_url"], "html": HTML},
            geo_reader=lambda url: bad)
        self.assertFalse(report["geography_verified"])
        self.assertFalse(report["direct_source_structurally_valid"])
        self.assertEqual(report["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
