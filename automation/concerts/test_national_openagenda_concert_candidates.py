"""Synthetic tests: OpenAgenda metadata is a DISCOVERY LEAD only."""
import datetime as dt
import json
import unittest
from unittest import mock

from automation.concerts import national_openagenda_concert_candidates as scan
from automation.concerts import openagenda_official_concert as source

TODAY = dt.date(2026, 11, 22)
EXACT = ("https://openagenda.com/fr/metal-tour/events/"
         "8675309-metalcore-deathcore")
FUTURE = "2027-03-05T19:30:00+01:00"


def row(**changes):
    val = {
        "uid": 8675309, "originagenda_uid": 9969608,
        "canonicalurl": EXACT,
        "title_fr": "UNKNOWN GROUP A + UNKNOWN GROUP B",
        "description_fr": "Concert metalcore rock",
        "firstdate_begin": FUTURE,
        "lastdate_begin": FUTURE,
        "location_name": "Salle Nouvelle", "location_city": "Tours",
        "location_postalcode": "37000", "location_countrycode": "FR",
    }
    val.update(changes)
    return val


class NationalOpenAgendaResearchTests(unittest.TestCase):
    def test_national_scan_never_creates_an_approval_from_index_metadata(self):
        seen = []
        def get(url, cache):
            seen.append(url)
            self.assertTrue(url.startswith(
                "https://public.opendatasoft.com/api/explore/v2.1/"))
            return json.dumps({"results": [
                row(), row(), row(canonicalurl="https://evil.example/"),
                row(title_fr="Festival métallurgique"),
                row(firstdate_begin="2024-03-05T19:30:00+01:00"),
            ]})
        report = scan.build({"events": []}, TODAY, slot=0, fetch=get)
        self.assertEqual(len(report["candidates"]), 1, report)
        first = report["candidates"][0]
        self.assertEqual(first["source"], "agenda_officiel_openagenda")
        self.assertEqual(first["eventDetailUrl"], EXACT)
        self.assertEqual(first["leadArtist"], "UNKNOWN GROUP A")
        self.assertEqual(first["openAgendaEventUid"], "8675309")
        self.assertEqual(first["openAgendaUid"], "9969608")
        self.assertFalse(first["publicationAllowed"])
        self.assertTrue(first["reviewRequired"])
        self.assertEqual(report["triageCounts"],
                         {"unverified_official_agenda": 1})
        self.assertEqual(len(seen), scan.PER_CYCLE)
        # ODS has no power to attest genre or grant any publisher signature.
        self.assertNotIn("officialEvidence", first)
        self.assertNotIn("reviewDecision", first)

    def test_documented_index_client_remains_pinned_to_exact_api(self):
        url = scan.urls(TODAY, 0)[0]
        with mock.patch.object(scan.probe, "public_ip_addresses",
                               return_value=["1.1.1.1"]) as lookup, \
             mock.patch.object(scan.probe, "request_pinned",
                               return_value=(200, '{"results":[]}')) as read:
            data = scan.fetch_index_api(url, {})
            self.assertEqual(json.loads(data), {"results": []})
            lookup.assert_called_once_with("public.opendatasoft.com")
            self.assertEqual(read.call_args.args[1:],
                             ("public.opendatasoft.com", "1.1.1.1"))
        for bad in (
            "https://evil.example/api/search?q=concert",
            "https://public.opendatasoft.com/login",
            "https://public.opendatasoft.com/api/other?hack=1",
            "http://public.opendatasoft.com/api/explore/v2.1/catalog/",
        ):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                scan.fetch_index_api(bad, {})

    def test_openagenda_url_is_bounded_to_real_individual_event(self):
        self.assertTrue(source.is_openagenda_event_url(EXACT))
        for incorrect in (
            "https://fake.openagenda.com/fr/metal-tour/events/abc-123",
            "http://openagenda.com/fr/metal-tour/events/abc-123",
            "https://openagenda.com/fr/metal-tour/",
            "https://openagenda.com/fr/metal-tour/events/",
            EXACT + "?ticket=1",
            "https://openagenda.com@evil.com/fr/metal-tour/events/abc-123",
            "https://openagenda.com/fr/metal-tour/events/../admin",
        ):
            with self.subTest(url=incorrect):
                self.assertFalse(source.is_openagenda_event_url(incorrect))

    def test_invalid_metadata_does_not_become_an_event(self):
        for field in (
            {"location_countrycode": "US"},
            {"canonicalurl": "https://tickets.example/event/"},
            {"title_fr": "Festival metalcore 2027"},
            {"firstdate_begin": "2025-01-01T19:00:00+01:00"},
            {"location_name": None},
        ):
            with self.subTest(field=field):
                self.assertIsNone(scan.candidate(row(**field), TODAY, set()))

    def test_metadata_failure_cannot_block_other_official_source_cycles(self):
        def nope(url, cache):
            raise TimeoutError("Open-data public index unavailable")
        report = scan.build({"events": []}, TODAY, slot=1, fetch=nope)
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["failedPublicIndexRequests"],
                         scan.PER_CYCLE)
        self.assertEqual(report["triageCounts"],
                         {"unverified_official_agenda": 0})


if __name__ == "__main__":
    unittest.main()
