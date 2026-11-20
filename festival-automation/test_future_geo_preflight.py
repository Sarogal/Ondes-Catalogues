import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from future_geo_preflight import (exact_edition_geo, exact_geo_from_official_site,
                                official_access_links, eligible, review)


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
        same_day = review(saved, catalogue(ROW), "2026-11-21", read)
        self.assertEqual(same_day["two_day_stable"], 1)
        self.assertEqual(saved["future_edition_geo_observations_private"][ROW["slug"]]["firstSeen"], "2026-11-20")
        next_day = review(saved, catalogue(ROW), "2026-11-22", read)
        self.assertEqual(next_day["two_day_stable"], 1)

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
        old = {**ROW, "slug": "old-edition-2026",
               "startDate": "2026-10-02", "endDate": "2026-10-03"}
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


    def test_same_host_access_link_yields_exact_current_edition(self):
        access = SITE + "infos-pratiques/acces"
        home = ("""<html><a href="/infos-pratiques/acces">Accès - Parkings</a>"""
                """<a href="https://evil.example/2027/acces">Accès externe</a>"""
                """<a href="/images">Photos</a></html>""")
        self.assertEqual(official_access_links(home, SITE), [access])
        calls = []
        def fetch(url):
            calls.append(url)
            return home if url == SITE else html(event())
        claim = exact_geo_from_official_site(ROW, fetch)
        self.assertEqual(calls, [SITE, access])
        self.assertEqual(claim["city"], "Colonne")
        self.assertEqual(claim["source"], SITE)

    def test_never_fetch_external_or_unbounded_pages(self):
        home = """<html>
        <a href="https://evil.example/acces">Accès externe</a>
        <a href="//127.0.0.1/acces">Accès réseau local</a>
        <a href="http://festival-example.fr/acces">Accès sans TLS</a>
        <a href="/%2e%2e/admin/acces">Accès trompeur</a>
        <a href="/acces?redirect=https://evil.example">Accès paramétré</a>
        <a href="/2026/acces">Accès édition 2026</a>
        <a href="/venez">Venir au festival</a>
        <a href="/informations-pratiques">Infos pratiques</a>
        <a href="/faq">F.A.Q.</a>
        <a href="/contact">Contact</a>
        </html>"""
        links = official_access_links(home, SITE)
        self.assertEqual(len(links), 2)
        self.assertTrue(all(url.startswith(SITE) for url in links))
        self.assertEqual(links[0], SITE + "venez")
        self.assertNotIn("127.0.0.1", str(links))
        calls = []
        exact_geo_from_official_site(ROW, lambda url: (
            calls.append(url) or home))
        self.assertEqual(calls, [SITE, *links])

    def test_child_page_needs_edition_year_exact_dates_and_coordinates(self):
        child = SITE + "acces/"
        home = '<a href="/acces/">Venir au festival</a>'
        def fetch_unrelated(url):
            return home if url == SITE else html(event(name="Festival Exemple 2026"))
        self.assertIsNone(exact_geo_from_official_site(ROW, fetch_unrelated))
        def fetch_old_date(url):
            return home if url == SITE else html(event(startDate="2027-07-04"))
        self.assertIsNone(exact_geo_from_official_site(ROW, fetch_old_date))

    def test_different_exact_edition_geo_on_two_pages_is_veto(self):
        home = (
            "<html>" + html(event())
            + '<a href="/acces">Accès - Parkings</a></html>')
        other = event()
        other["location"]["geo"]["latitude"] = 44.2
        self.assertIsNone(exact_geo_from_official_site(
            ROW, lambda url: home if url == SITE else html(other)))

    def test_consecutive_daily_report_reuses_same_host_research(self):
        state_value = state()
        child = SITE + "infos-pratiques/"
        home = '<a href="infos-pratiques/">Infos pratiques</a>'
        calls = []
        def fetch(url):
            calls.append(url)
            return home if url == SITE else html(event())
        first = review(state_value, catalogue(ROW), "2026-11-20", fetch)
        second = review(state_value, catalogue(ROW), "2026-11-21", fetch)
        self.assertEqual(first["first_day"], 1)
        self.assertEqual(second["two_day_stable"], 1)
        self.assertEqual(calls, [SITE, child, SITE, child])



if __name__ == "__main__":
    unittest.main()
