"""Adversarial OFFLINE tests of the independent multi-place public gate."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_place_preflight import (
    evaluate, source_index, pinned_proposal, official_proof,
    mapped_proof, safe_host, verify_envelope,
)
from ptitesondes_places import validate, assert_append_only

TODAY = date(2026, 11, 6)
REGISTRY = json.loads((ROOT / "scripts/ptitesondes_place_sources.json").read_text(encoding="utf-8"))
CURRENT = json.loads((ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))
BELLEVUE = next(s for s in REGISTRY["sources"] if s["id"] == "nantes-ludotheque-bellevue")
TOTEMS = next(s for s in REGISTRY["sources"] if s["id"] == "pace-totems")


def historical(*omitted):
    output = deepcopy(CURRENT)
    output["places"] = [p for p in output["places"] if p["id"] not in omitted]
    return output


def proposal(src):
    return dict(src["facts"], lat=src["osm"]["lat"],
                lng=src["osm"]["lng"], reviewed_at="2026-11-06")


def private(*sources):
    return {
        "schema": "ptitesondes.place_release_review.v1",
        "date": "2026-11-06",
        "safe_to_publish": False,
        "mode": "private_proposal_only",
        "records": [{
            "city": s["facts"]["city"], "venue": s["facts"]["name"],
            "status": "requires_independent_public_preflight"
        } for s in sources],
        "proposals": [proposal(s) for s in sources],
    }


def page(src):
    return "<html><body>" + "".join(
        "<p>" + phrase + "</p>" for phrase in src["official_anchors"]
    ) + "</body></html>"


def node():
    return ('<osm version="0.6"><node id="2810810943" lat="47.2035757" '
            'lon="-1.6073739"><tag k="name" v="La ludothèque de la Meta"/>'
            '<tag k="amenity" v="toy_library"/><tag k="addr:city" v="Nantes"/>'
            '<tag k="addr:street" v="Rue Firmin Colas"/>'
            '<tag k="addr:housenumber" v="20"/><tag k="addr:postcode" v="44100"/>'
            '</node></osm>')


def way():
    coords = [(48.14625, -1.7740082), (48.14625, -1.7739482),
              (48.1463116, -1.7739482), (48.1463116, -1.7740082)]
    nodes = "".join(
        '<node id="%d" lat="%.7f" lon="%.7f"/>' % (i, lat, lng)
        for i, (lat, lng) in enumerate(coords, 1))
    refs = "".join('<nd ref="%d"/>' % i for i in (1, 2, 3, 4, 1))
    tags = "".join('<tag k="%s" v="%s"/>' % pair
                   for pair in TOTEMS["osm"]["tags"].items())
    return '<osm version="0.6">' + nodes + '<way id="67402599">' + refs + tags + '</way></osm>'


def read(url, host, limit):
    if url == BELLEVUE["facts"]["official_url"]:
        return page(BELLEVUE)
    if url == TOTEMS["facts"]["official_url"]:
        return page(TOTEMS)
    if "node/2810810943" in url:
        return node()
    if "way/67402599/full" in url:
        return way()
    raise AssertionError("unexpected request")


class IndependentPlacesGateTests(unittest.TestCase):
    def test_registry_and_current_six_places_are_valid(self):
        self.assertEqual(len(CURRENT["places"]), 6)
        self.assertEqual(len(source_index(REGISTRY, TODAY)), 2)
        self.assertEqual(validate(CURRENT), 6)

    def test_no_proposal_never_rewrites_catalogue(self):
        fresh, statuses = evaluate(private(), CURRENT, REGISTRY, TODAY, read=read)
        self.assertEqual(statuses, [])
        self.assertEqual(fresh, CURRENT)

    def test_historical_bellevue_publication_still_passes(self):
        old = historical("nantes-ludotheque-bellevue")
        after, report = evaluate(private(BELLEVUE), old, REGISTRY, TODAY, read=read)
        self.assertEqual(report, [{"id": BELLEVUE["id"], "status": "independently_verified"}])
        self.assertEqual(after["places"][:-1], old["places"])
        self.assertEqual(after["places"][-1]["id"], BELLEVUE["id"])
        self.assertIsNone(after["places"][-1]["age_min"])
        self.assertIsNone(after["places"][-1]["age_max"])
        assert_append_only(old, after)
        unchanged, report = evaluate(private(BELLEVUE), after, REGISTRY, TODAY, read=read)
        self.assertEqual(unchanged, after)
        self.assertEqual(report[0]["status"], "already_public")

    def test_two_distinct_verified_places_in_one_batch(self):
        old = historical("nantes-ludotheque-bellevue", "pace-totems")
        after, report = evaluate(private(BELLEVUE, TOTEMS), old,
                                 REGISTRY, TODAY, read=read)
        self.assertEqual(len(after["places"]), len(old["places"]) + 2)
        self.assertEqual({r["status"] for r in report}, {"independently_verified"})
        assert_append_only(old, after)
        self.assertEqual({x["id"] for x in after["places"][-2:]},
                         {BELLEVUE["id"], TOTEMS["id"]})

    def test_forged_private_data_is_never_authority(self):
        for field, bad in (
            ("age_min", 0), ("age_max", 18), ("admission", "gratuit"),
            ("address", "25 rue du Jamet, 44100 Nantes"),
            ("postal_code", "44000"), ("category", "musee-enfants"),
            ("is_publicly_accessible", False),
            ("activities", ["activité imaginaire"]),
        ):
            document = private(BELLEVUE)
            document["proposals"][0][field] = bad
            after, report = evaluate(document, historical(BELLEVUE["id"]),
                                     REGISTRY, TODAY, read=read)
            with self.subTest(field=field):
                self.assertEqual(after, historical(BELLEVUE["id"]))
                self.assertEqual(report[0]["status"], "deferred")
        for key, value in (("safe_to_publish", True), ("mode", "auto")):
            doc = private(BELLEVUE)
            doc[key] = value
            with self.assertRaises(ValueError):
                verify_envelope(doc)

    def test_unknown_source_cannot_be_self_authorized(self):
        doc = private(BELLEVUE)
        doc["proposals"][0]["id"] = "unknown-private-venue"
        after, report = evaluate(doc, CURRENT, REGISTRY, TODAY, read=read)
        self.assertEqual(after, CURRENT)
        self.assertEqual(report[0]["status"], "not_publicly_configured")

    def test_independent_proof_missing_does_not_block_other_place(self):
        old = historical(BELLEVUE["id"], TOTEMS["id"])
        def unavailable_one(url, host, limit):
            if "node/2810810943" in url:
                raise OSError("OSM unavailable")
            return read(url, host, limit)
        after, report = evaluate(private(BELLEVUE, TOTEMS), old, REGISTRY,
                                 TODAY, read=unavailable_one)
        self.assertEqual(len(after["places"]), len(old["places"]) + 1)
        self.assertEqual(after["places"][-1]["id"], TOTEMS["id"])
        self.assertEqual([x["status"] for x in report],
                         ["deferred", "independently_verified"])

    def test_forged_official_or_osm_content_is_blocked(self):
        with self.assertRaises(ValueError):
            official_proof(page(BELLEVUE).replace("8,80", "0,00"),
                           BELLEVUE["official_anchors"])
        with self.assertRaises(ValueError):
            official_proof("<script>" + " ".join(BELLEVUE["official_anchors"]) +
                           "</script>", BELLEVUE["official_anchors"])
        for xml in (
            node().replace('v="20"', 'v="25"'),
            node().replace('v="toy_library"', 'v="library"'),
            node().replace('v="Nantes"', 'v="Paris"'),
            node().replace('lat="47.2035757"', 'lat="48.2035757"'),
            node().replace('id="2810810943"', 'id="000"'),
        ):
            with self.subTest(xml=xml[:65]), self.assertRaises(ValueError):
                mapped_proof(xml, BELLEVUE["osm"], proposal(BELLEVUE))
        with self.assertRaises(ValueError):
            mapped_proof(way().replace('v="Totems"', 'v="Autre lieu"'),
                         TOTEMS["osm"], proposal(TOTEMS))

    def test_duplicate_alias_address_geolocation_and_source(self):
        old = historical(BELLEVUE["id"])
        alias = dict(proposal(BELLEVUE), id="nantes-ludotheque-meta-double",
                     name="La ludothèque de la Meta")
        old["places"].append(alias)
        validate(old)
        result, states = evaluate(private(BELLEVUE), old, REGISTRY, TODAY, read=read)
        self.assertEqual(states[0]["status"], "deferred")
        self.assertEqual(result, old)

    def test_stale_pinned_report_and_unsafe_registry_urls_fail_closed(self):
        for stamp in ("2026-10-01", "2026-11-07", "bad"):
            p = proposal(BELLEVUE)
            p["reviewed_at"] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                pinned_proposal(p, private(BELLEVUE), BELLEVUE, TODAY)
        for url in ("https://127.0.0.1/p", "https://localhost/p",
                    "http://ville.fr/p", "https://ville.fr:1234/p",
                    "https://ville.fr/p#fragment"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                safe_host(url)
        bad = deepcopy(REGISTRY)
        bad["sources"][0]["facts"]["age_min"] = 0
        with self.assertRaises(ValueError):
            source_index(bad, TODAY)

    def test_nonexistent_ages_and_any_date_fields_are_not_invented(self):
        old = historical(BELLEVUE["id"])
        after, _ = evaluate(private(BELLEVUE), old, REGISTRY, TODAY, read=read)
        new = after["places"][-1]
        self.assertEqual((new["age_min"], new["age_max"]), (None, None))
        self.assertFalse({"date_start", "date_end", "sessions", "timings"} & set(new))


if __name__ == "__main__":
    unittest.main()
