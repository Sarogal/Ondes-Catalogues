"""Synthetic tests: OpenAgenda metadata is a DISCOVERY LEAD only."""
import datetime as dt
import json
import unittest

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
