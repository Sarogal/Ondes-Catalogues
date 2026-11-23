"""Bounded independent named-venue geometry, never an OpenAgenda town pin."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_candidate_promotion import base
from test_ptitesondes_open_world_release_rehearsal import (
    AGENDA, DAY, TODAY, KEY, oa_event, lead,
)
from test_ptitesondes_open_world_patch_bridge import private_patch
from ptitesondes_named_venue_geo_resolver import (
    resolve_named_city_only_venue, _page_pin, read_source_cache, SCHEMA,
)
from ptitesondes_open_world_patch_bridge import merge_verified_open_world

URL = ("https://www.tourisme-exemple.fr/visiter/centre-culturel-nouveau/")
VENUE = "Centre Culturel Antoine Tangamen dit Zwazo"
CITY = "Basse-Pointe"
CENTER = (14.868227, -61.113506)
POINT = (14.86740401, -61.11625135)
SOURCE = {"city": CITY, "region": "Martinique",
          "venue_name": VENUE, "official_url": URL}


def live_event():
    event = deepcopy(oa_event())
    event["title"] = {"fr": "ATELIER D'EVEIL MUSICAL"}
    event["description"] = {
        "fr": "Éveil musical pour les enfants jusqu'à 11 ans au Centre Culturel Antoine Tangamen"
    }
    event["timezone"] = "America/Martinique"
    event["location"] = {
        "name": CITY, "adminLevel4": CITY, "adminLevel2": "Martinique",
        "adminLevel1": "Martinique", "countryCode": "MQ",
        "latitude": CENTER[0], "longitude": CENTER[1],
    }
    event["timings"] = [{
        "begin": DAY.isoformat() + "T09:00:00-04:00",
        "end": DAY.isoformat() + "T11:00:00-04:00",
    }]
    return event


def official_html(*, latitude=POINT[0], longitude=POINT[1],
                  venue=VENUE, city=CITY, two_points=False):
    extra = ("<a href='https://www.google.com/maps/dir/?api=1&amp;destination=14.1%2C-61.0'>Bad second pin</a>"
             if two_points else "")
    return (
        "<html><head><title>" + venue + "</title></head><body>"
        "<h1>" + venue + "</h1><p>Rue Marcé Bedouin, 97218 " + city + "</p>"
        "<a href='https://www.google.com/maps/dir/?api=1&amp;destination="
        + str(latitude) + "%2C" + str(longitude) + "'>Itinéraire</a>"
        + extra + "</body></html>"
    )


class LiveNamedVenueTests(unittest.TestCase):
    def test_cache_is_an_evidence_hint_not_an_approval_list(self):
        rows = read_source_cache()
        self.assertTrue(rows)
        self.assertTrue(all("lat" not in row and "lng" not in row for row in rows))
        self.assertEqual(
            resolve_named_city_only_venue(
                live_event(), sources=[], source_reader=lambda url: self.fail("No source")),
            None)

    def test_independent_exact_page_geo_and_incomplete_oa_venue_name(self):
        result = resolve_named_city_only_venue(
            live_event(), sources=[SOURCE],
            source_reader=lambda url: official_html() if url == URL else self.fail("bad url"))
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], VENUE)
        self.assertEqual((result["latitude"], result["longitude"]), POINT)
        self.assertEqual(result["official_url"], URL)

    def test_refuse_ambiguity_disagreement_and_missing_expressed_venue(self):
        event = live_event()
        tests = [
            (event, [SOURCE, SOURCE], official_html()),
            (event, [SOURCE], official_html(city="Autreville")),
            (event, [SOURCE], official_html(venue="Centre fictif non attesté")),
            (event, [SOURCE], official_html(latitude=13.1)),
            (event, [SOURCE], official_html(two_points=True)),
            (event, [dict(SOURCE, city="Fort-de-France")], official_html()),
            (dict(event, description={"fr": "Atelier musical pour enfants en ville"}),
             [SOURCE], official_html()),
            (dict(event, location=dict(event["location"], name=VENUE)),
             [SOURCE], official_html()),
        ]
        for event_input, sources, html in tests:
            with self.subTest(sources=sources, html=html[:60]):
                self.assertIsNone(resolve_named_city_only_venue(
                    event_input, sources=sources, source_reader=lambda url: html))

    def test_unsupported_map_links_are_not_coordinates(self):
        html = ("<html><body><h1>" + VENUE + "</h1>" + CITY +
                "<a href='https://www.google.com/maps/search/?api=1&query=" +
                "Centre%20Culturel%20Antoine%20Tangamen'>Search only</a></body></html>")
        self.assertIsNone(_page_pin(html, SOURCE))

    def test_city_only_venue_reaches_actual_append_only_merge_without_event_corrob(self):
        baseline = base()
        baseline["events"][0]["category"] = "eveil-musical"
        baseline["events"][0]["category_label"] = "Éveil musical"
        event = live_event()
        original = dict(lead(), title="ATELIER D'EVEIL MUSICAL",
                        city_unverified=CITY, venue_unverified=CITY,
                        explicit_source_session_intervals=event["timings"])
        url = ("https://openagenda.com/" + AGENDA["slug"] +
               "/events/" + str(event["uid"]))
        dossier = {"lead": original, "date_start": DAY.isoformat(),
                   "official_event_url": url, "official_venue_url": url}
        checked = []
        def official_reader(url):
            checked.append(url)
            self.assertEqual(url, URL)
            return official_html()
        def verifier(event, source_reader):
            return resolve_named_city_only_venue(
                event, sources=[SOURCE], source_reader=source_reader)
        result, audit, report = merge_verified_open_world(
            baseline, baseline, private_patch(baseline, queue=[dossier]),
            TODAY, KEY,
            agenda_reader=lambda uid, key: AGENDA,
            event_reader=lambda uid, eid, key: event,
            official_reader=official_reader,
            named_venue_resolver=verifier,
            directory_reader=lambda *_: self.fail("No second event source"),
            ign_reader=lambda *_: self.fail("BAN not a venue pin"),
            osm_reader=lambda *_: self.fail("Do not replace pin by town centroid"),
            legacy_checker=lambda *_: (False, "legacy_fails"),
        )
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(report["publisher_accepted_new"], 1)
        self.assertEqual(checked, [URL])
        row = result["events"][-1]
        self.assertEqual(row["venue"], VENUE)
        self.assertEqual((row["lat"], row["lng"]), POINT)
        self.assertEqual(row["geo_precision"], "venue")
        self.assertEqual(row["source_url"], url + "_" + event["slug"])
        self.assertEqual(row["time"], "09:00")
        self.assertEqual(result["events"][:-1], baseline["events"])

    def test_missing_independent_place_evidence_keeps_existing_catalogue(self):
        baseline = base()
        event = live_event()
        original = dict(lead(), title="ATELIER D'EVEIL MUSICAL",
                        city_unverified=CITY, venue_unverified=CITY,
                        explicit_source_session_intervals=event["timings"])
        url = "https://openagenda.com/" + AGENDA["slug"] + "/events/999401"
        dossier = {"lead": original, "date_start": DAY.isoformat(),
                   "official_event_url": url, "official_venue_url": url}
        result, audit, report = merge_verified_open_world(
            baseline, baseline, private_patch(baseline, queue=[dossier]),
            TODAY, KEY, agenda_reader=lambda uid, key: AGENDA,
            event_reader=lambda uid, eid, key: event,
            named_venue_resolver=lambda event, source_reader: None,
            official_reader=lambda url: self.fail("No official source found"),
            directory_reader=lambda *_: self.fail("No DILA fallback"),
            ign_reader=lambda *_: self.fail("No guessed pin"),
            osm_reader=lambda *_: self.fail("No guessed pin"),
            legacy_checker=lambda *_: (False, "legacy_fails"),
        )
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(report["held_reason_counts"],
                         {"oa_direct_city_only_location": 1})
        self.assertEqual(result, baseline)


if __name__ == "__main__":
    unittest.main()
