"""Safety tests: OSM discovery candidates never become publication evidence."""
import copy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_osm_poi_triage import (
    ENDPOINTS, PINS, SCHEMA, audit, candidates, overpass_query, fetch,
)

NOW = date(2026, 11, 7)


def fixtures():
    backlog, municipal = [], {
        "schema": "ptitesondes.municipal_source_probe.v1",
        "safe_to_publish": False, "proposals": [], "records": [],
    }
    for city, (name, code, postcode, url) in PINS.items():
        backlog.append({
            "city": city, "venue": name, "status": "review_required",
            "public_eligible": False, "gps_verified": False,
            "official_site_verified": False,
            "evidence": [{
                "from": "ministere-bibliotheques-index",
                "historic_postcode_hint_unverified": postcode,
                "historic_street_hint_unverified": "Rue historique",
            }],
        })
        municipal["records"].append({
            "city": city, "venue": name, "status":
            "current_municipal_page_mentions_place_private_only",
            "pinned_current_source": url, "public_eligible": False,
            "gps_verified": False, "official_site_verified": False,
        })
    return municipal, backlog


def fake_overpass(endpoint, code):
    assert endpoint in ENDPOINTS
    assert code in {v[1] for v in PINS.values()}
    postcode = next(item[2] for item in PINS.values() if item[1] == code)
    city = next(city for city, v in PINS.items() if v[1] == code)
    return {"elements": [{
        "type": "node", "id": 20000000 + int(code),
        "lat": 43.123456, "lon": -1.23456,  # Must NEVER be emitted.
        "tags": {"name": "Médiathèque-ludothèque municipale",
                 "amenity": "library", "addr:city": city,
                 "addr:postcode": postcode, "addr:street": "Rue des Jeux",
                 "addr:housenumber": "4"},
    }]}


class PlaceOSMTriagePublicRunnerTests(unittest.TestCase):
    def test_static_admin_area_queries_not_user_injected(self):
        self.assertEqual(len(PINS), 6)
        for name, code, postcode, url in PINS.values():
            self.assertEqual(len(code), 5)
            self.assertIn('["admin_level"="8"]', overpass_query(code))
            self.assertIn(code, overpass_query(code))
            self.assertIn('out tags 120;', overpass_query(code))
            self.assertTrue(url.startswith("https://"))
        for injected in ('53084";out;', "99999", "75001", ""):
            with self.assertRaises(ValueError):
                overpass_query(injected)
        with self.assertRaises(ValueError):
            fetch("https://attacker.example/api/interpreter", "53084")

    def test_two_per_day_and_unverified_ids_only(self):
        municipal, backlog = fixtures()
        queried = []
        def get(endpoint, code):
            queried.append((endpoint, code))
            return fake_overpass(endpoint, code)
        report, stats = audit(municipal, backlog, None, NOW, get=get)
        self.assertEqual(stats["queries_attempted"], 2)
        self.assertEqual(len(queried), 2)
        self.assertEqual(stats["candidates"], 6)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertIs(report["safe_to_publish"], False)
        self.assertEqual(report["proposals"], [])
        self.assertEqual(report["publications"], 0)
        statuses = stats["status_counts"]
        self.assertEqual(statuses.get("single_osm_object_hint_requires_exact_proof"), 2)
        self.assertEqual(statuses.get("not_scanned_yet_or_stale"), 4)
        for record in report["records"]:
            self.assertFalse(record["gps_verified"])
            self.assertFalse(record["mapped_feature_verified"])
            self.assertFalse(record["official_site_verified"])
            self.assertFalse(record["public_eligible"])
            self.assertNotIn("lat", record)
            self.assertNotIn("lng", record)
            self.assertNotIn("address", record)
            for obj in record["osm_candidates_unverified"]:
                self.assertFalse(obj["gps_verified"])
                self.assertFalse(obj["mapped_feature_verified"])
                for sensitive in ("lat", "lon", "lng", "coordinates", "center",
                                  "address", "official_url", "age_min",
                                  "admission", "location_coordinates"):
                    self.assertNotIn(sensitive, obj)

    def test_rotates_six_communes_in_three_days_and_reuses_prior(self):
        municipal, backlog = fixtures()
        previous = None
        used = set()
        for i in range(3):
            day = date.fromordinal(NOW.toordinal() + i)
            called = []
            def get(endpoint, code):
                called.append(code)
                return fake_overpass(endpoint, code)
            previous, stats = audit(municipal, backlog, previous, day, get=get)
            self.assertEqual(len(called), 2)
            used.update(called)
        self.assertEqual(used, {v[1] for v in PINS.values()})
        self.assertEqual(stats["status_counts"],
                         {"single_osm_object_hint_requires_exact_proof": 6})
        self.assertFalse(previous["safe_to_publish"])

    def test_municipal_source_failure_prevents_osm_query(self):
        municipal, backlog = fixtures()
        municipal["records"][0]["status"] = "source_unavailable_or_unmatched"
        report, stats = audit(municipal, backlog, None, NOW, get=fake_overpass)
        self.assertEqual(stats["candidates"], 6)
        failed = next(x for x in report["records"] if x["city"] ==
                      municipal["records"][0]["city"])
        self.assertEqual(failed["status"], "municipal_source_not_confirmed")
        self.assertEqual(failed["osm_candidates_unverified"], [])

    def test_failover_with_unavailable_or_truncated_osm(self):
        municipal, backlog = fixtures()
        calls = []
        def get(endpoint, code):
            calls.append((endpoint, code))
            if endpoint == ENDPOINTS[0]:
                raise OSError("Overpass timeout")
            return fake_overpass(endpoint, code)
        report, stats = audit(municipal, backlog, None, NOW, get=get)
        self.assertEqual(len(calls), 4)
        self.assertEqual(stats["status_counts"].get(
            "single_osm_object_hint_requires_exact_proof"), 2)
        report, stats = audit(municipal, backlog, None, NOW,
                              get=lambda endpoint, code:
                              {"elements": [], "remark": "incomplete"})
        self.assertEqual(stats["status_counts"].get(
            "osm_index_unavailable_or_incomplete"), 2)
        self.assertEqual(report["proposals"], [])

    def test_ambiguous_or_wrong_amenity_city_and_postcode(self):
        elements = [
            {"type": "node", "id": 1, "tags":
             {"amenity": "library", "name": "Médiathèque de Craon",
              "addr:city": "Craon", "addr:postcode": "53400"}},
            {"type": "way", "id": 2, "tags":
             {"amenity": "toy_library", "name": "Ludothèque du Jeu",
              "addr:city": "Craon"}},
            {"type": "node", "id": 3, "tags":
             {"amenity": "library", "name": "Médiathèque de Craon",
              "addr:city": "Paris", "addr:postcode": "53400"}},
            {"type": "node", "id": 4, "tags":
             {"amenity": "library", "name": "Médiathèque de Craon",
              "addr:postcode": "75001"}},
            {"type": "node", "id": 5, "tags":
             {"amenity": "library", "name": "Bibliothèque banale"}},
        ]
        res = candidates({"elements": elements}, "Craon", "53400")
        self.assertEqual({x["osm_object_hint"] for x in res},
                         {"node/1", "way/2"})
        self.assertTrue(all(x["mapped_feature_verified"] is False for x in res))
        for data in ({"elements": [None] * 120},
                     {"remark": "incomplete", "elements": []},
                     {"elements": "not a list"}):
            with self.assertRaises(ValueError):
                candidates(data, "Craon", "53400")

    def test_rejects_wrong_source_and_permissions_before_any_network(self):
        for changes in (
            {"municipal": lambda m: m["records"][0].update(
                {"public_eligible": True})},
            {"municipal": lambda m: m["records"][0].update(
                {"pinned_current_source": "https://localhost/private"})},
            {"backlog": lambda b: b[0].update(
                {"gps_verified": True})},
            {"municipal": lambda m: m["records"].append(
                dict(m["records"][0]))},
            {"backlog": lambda b: b.append(dict(b[0]))},
        ):
            municipal, backlog = fixtures()
            if "municipal" in changes:
                changes["municipal"](municipal)
            else:
                changes["backlog"](backlog)
            with self.assertRaises(ValueError):
                audit(municipal, backlog, None, NOW,
                      get=lambda *_: self.fail("No network"))

    def test_never_trust_old_report_as_publication_permission(self):
        municipal, backlog = fixtures()
        previous, _ = audit(municipal, backlog, None, NOW, get=fake_overpass)
        corrupted = copy.deepcopy(previous)
        corrupted["records"][0]["mapped_feature_verified"] = True
        with self.assertRaises(ValueError):
            audit(municipal, backlog, corrupted,
                  date.fromordinal(NOW.toordinal() + 1),
                  get=lambda *_: self.fail("No network"))


if __name__ == "__main__":
    unittest.main()
