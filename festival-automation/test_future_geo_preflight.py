import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from future_geo_preflight import exact_edition_geo, eligible, review


SITE = "https://festival-example.fr/"
ROW = {
    "slug": "festival-exemple-2027",
    "name": "Festival Exemple 2027",
    "startDate": "2027-07-02",
    "endDate": "2027-07-03",
    "officialSite": SITE,
    "city": None,
    "lat": None,
    "lon": None,
    "showOnMap": False,
}


def event(**extra):
    data = {
        "@context": "https://schema.org",
        "@type": "MusicFestival",
        "name": "Festival Exemple 2027",
        "startDate": "2027-07-02",
        "endDate": "2027-07-03",
        "location": {
            "@type": "Place", "name": "Le Champ des Guitares",
            "address": {"@type": "PostalAddress",
                        "addressLocality": "Colonne"},
            "geo": {"@type": "GeoCoordinates",
                    "latitude": 46.8832, "longitude": 5.5577},
        },
    }
    data.update(extra)
    return data


def html(*objects):
    return "<html><head><script type='application/ld+json'>" + json.dumps(
        list(objects) if len(objects) > 1 else objects[0]
    ) + "</script></head><body>festival</body></html>"


def catalogue(*rows):
    return {"schema": 1, "generatedAt": "2026-11-20",
            "festivals": list(rows)}


def state():
    return {"schema": "grossesondes.source-watch.v1"}


class FutureGeoTests(unittest.TestCase):
    def test_exact_edition_requires_full_date_identity_and_place(self):
        claim = exact_edition_geo(html(event()), ROW)
        self.assertEqual(claim["city"], "Colonne")
        self.assertEqual(claim["venue"], "Le Champ des Guitares")
        self.assertEqual((claim["lat"], claim["lon"]), (46.8832, 5.5577))
        self.assertEqual(claim["source"], SITE)
        self.assertNotIn("showOnMap", claim)

    def test_two_independent_days_and_never_publication(self):
        saved = state()
        read = lambda url: html(event())
        first = review(saved, catalogue(ROW), "2026-11-20", read)
        self.assertEqual(first["first_day"], 1)
        self.assertEqual(first["two_day_stable"], 0)
        self.assertFalse(first["publication_authorized"])
        self.assertFalse(first["publisher_geo_sync_connected"])
        repeat = review(saved, catalogue(ROW), "2026-11-20", read)
        self.assertEqual(repeat["two_day_stable"], 0)
        second = review(saved, catalogue(ROW), "2026-11-21", read)
        self.assertEqual(second["two_day_stable"], 1)
        self.assertEqual(second["findings"][0]["status"],
                         "TWO_DAY_STABLE_REVIEW_ONLY")
        self.assertTrue(saved["future_edition_geo_observations_private"]
                        [ROW["slug"]]["stable"])
        self.assertFalse(second["findings"][0]["publication_authorized"])

    def test_old_edition_and_dates_cannot_prove_current(self):
        variants = [
            event(name="Festival Exemple 2026"),
            event(startDate="2027-07-04"),
            event(endDate="2027-07-04"),
            event(eventStatus="https://schema.org/EventCancelled"),
            event(name="Autre Festival 2027"),
        ]
        for raw in variants:
            with self.subTest(raw=raw):
                self.assertIsNone(exact_edition_geo(html(raw), ROW))

    def test_conflicting_same_edition_event_fails_closed(self):
        self.assertIsNone(exact_edition_geo(
            html(event(), event(location={
                **event()["location"], "geo": {
                    "latitude": 46.3, "longitude": 5.5577,
                }})), ROW))
        self.assertIsNone(exact_edition_geo(
            html(event(), event(endDate="2027-07-04")), ROW))

    def test_ambiguous_missing_or_invalid_coordinates_rejected(self):
        original = event()
        variants = [
            {"location": [original["location"], original["location"]]},
            {"location": {"@type": "Place", "name": "Unknown"}},
            {"location": {
                **original["location"], "geo": {
                    "latitude": True, "longitude": 5.5577}}},
            {"location": {
                **original["location"], "geo": {
                    "latitude": "nan", "longitude": 5.5577}}},
            {"location": {
                **original["location"], "geo": {
                    "latitude": 0, "longitude": 0}}},
            {"location": {
                **original["location"], "geo": {
                    "latitude": 91, "longitude": 5.5577}}},
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                self.assertIsNone(exact_edition_geo(
                    html(event(**changes)), ROW))

    def test_city_mismatch_is_not_inferred_from_previous_year(self):
        known_city = {**ROW, "city": "Montpellier"}
        self.assertIsNone(exact_edition_geo(html(event()), known_city))

    def test_prior_geo_and_old_year_do_not_create_eligible_row(self):
        old = {**ROW, "startDate": "2026-10-02", "endDate": "2026-10-03"}
        geocoded = {**ROW, "slug": "geocoded-2027",
                    "lat": 46.8832, "lon": 5.5577}
        self.assertEqual(eligible(catalogue(old, geocoded, ROW),
                                  "2026-11-20"), [ROW])

    def test_no_url_from_private_state_or_untrusted_signed_site(self):
        untrusted = {**ROW, "officialSite": "http://127.0.0.1/admin"}
        saved = state()
        saved["future_edition_geo_observations_private"] = {
            ROW["slug"]: {"url": "http://localhost/internal",
                          "firstSeen": "2026-11-19",
                          "digest": "forged"}}
        calls = []
        result = review(saved, catalogue(untrusted),
                        "2026-11-20", lambda url: calls.append(url))
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["dated_future_without_coordinates"], 1)
        self.assertEqual(calls, [])
        self.assertEqual(saved["future_edition_geo_observations_private"], {})

    def test_changed_coordinates_restart_first_day_and_skip_missed_day(self):
        saved = state()
        review(saved, catalogue(ROW), "2026-11-20",
               lambda url: html(event()))
        changed = event()
        changed["location"]["geo"]["latitude"] = 46.2
        result = review(saved, catalogue(ROW), "2026-11-21",
                        lambda url: html(changed))
        self.assertEqual(result["first_day"], 1)
        self.assertEqual(result["two_day_stable"], 0)
        late = review(saved, catalogue(ROW), "2026-11-23",
                      lambda url: html(changed))
        self.assertEqual(late["two_day_stable"], 0)

    def test_pending_second_day_gets_priority_and_limit_enforced(self):
        first = {**ROW, "slug": "first-2027"}
        second = {**ROW, "slug": "second-2027"}
        saved = state()
        review(saved, catalogue(second), "2026-11-20",
               lambda url: html(event()), limit=1)
        calls = []
        summary = review(saved, catalogue(first, second), "2026-11-21",
                         lambda url: (calls.append(url) or html(event())),
                         limit=1)
        self.assertEqual(summary["findings"][0]["slug"], "second-2027")
        self.assertEqual(summary["two_day_stable"], 1)
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            review(saved, catalogue(ROW), "2026-11-21", limit=5)


if __name__ == "__main__":
    unittest.main()
