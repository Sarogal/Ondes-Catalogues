import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from grossesondes_future_city_publisher import (
    PROOF_MODE, apply_independently_verified_city, private_city_report,
    ready_city_reviews,
)
from grossesondes_stage import published_patch_duplicate
from grossesondes_cloud_sync import build_candidate
from test_grosses_stage import fixtures
from future_city_preflight import SCHEMA
from test_future_city_preflight import MESSAGE

SITE = "https://festival-exemple.fr/"
ROW = {
    "slug": "festival-exemple-2027", "name": "Festival Exemple 2027",
    "startDate": "2027-07-02", "endDate": "2027-07-03",
    "source": SITE, "officialSite": SITE,
    "city": None, "venue": None, "lat": None, "lon": None,
    "showOnMap": False, "futureVenueConfirmed": False,
    "status": "Annoncé", "department": "39", "region": "Bourgogne-Franche-Comté",
}


def catalog(row=ROW):
    return {"schema": 1, "generatedAt": "2026-11-20",
            "festivals": [deepcopy(row)]}


def review(**update):
    report = {
        "schema": SCHEMA, "as_of": "2026-11-21",
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publisher_city_sync_connected": False,
        "eligible": 1, "checked": 1, "two_day_stable": 1, "first_day": 0,
        "findings": [{
            "slug": ROW["slug"], "status": "TWO_DAY_STABLE_REVIEW_ONLY",
            "candidate_city": {"slug": ROW["slug"], "city": "Colonne",
                               "source": SITE},
            "first_seen": "2026-11-20", "publication_authorized": False,
        }],
    }
    report.update(update)
    return report


def api(name="Colonne", code="39161", department="39"):
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"nom": name, "code": code,
                       "codeDepartement": department},
        "geometry": {"type": "Point", "coordinates": [5.5577, 46.8832]},
    }]}


class CityPublisherTests(unittest.TestCase):
    def test_report_is_fetched_from_fixed_private_branch_only(self):
        urls = []
        raw = json.dumps(review()).encode()
        def load(url, token):
            urls.append((url, token))
            return {"encoding": "base64",
                    "content": base64.b64encode(raw).decode()}
        self.assertEqual(private_city_report("TOKEN", load), review())
        self.assertEqual(len(urls), 1)
        self.assertIn("future-festival-city-review.json?ref=automation%2Fgrossesondes-intake",
                      urls[0][0])
        self.assertIsNone(private_city_report("TOKEN",
                          lambda *_: {"encoding": "base64", "content": "badbase64"}))

    def test_real_city_marker_is_not_precise_festival_venue(self):
        first_party = []
        national = []
        def fetch(url):
            first_party.append(url)
            return MESSAGE
        def government(url):
            national.append(url)
            return api()
        updated, report = apply_independently_verified_city(
            catalog(), catalog(), review(), "2026-11-21",
            fetcher=fetch, admin_reader=government)
        self.assertEqual(first_party, [SITE])
        self.assertEqual(len(national), 1)
        self.assertTrue(national[0].startswith("https://geo.api.gouv.fr/communes?"))
        row = updated["festivals"][0]
        self.assertEqual((row["lat"], row["lon"]), (46.8832, 5.5577))
        self.assertEqual(row["city"], "Colonne")
        self.assertEqual(row["geoCity"], "Colonne")
        self.assertEqual(row["geoInsee"], "39161")
        self.assertEqual(row["geoPrecision"], "commune")
        self.assertTrue(row["showOnMap"])
        self.assertFalse(row["futureVenueConfirmed"])
        self.assertIsNone(row["venue"])
        self.assertEqual(row["geoVerification"]["proofMode"], PROOF_MODE)
        self.assertEqual(row["geoVerification"]["markerMeaning"],
                         "centre_indicatif_de_commune")
        self.assertEqual(updated["generatedAt"], "2026-11-21")
        self.assertEqual(report["accepted_city_updates"], [ROW["slug"]])
        self.assertEqual(published_patch_duplicate(ROW, updated), "ALREADY_PUBLISHED")
        self.assertEqual(catalog()["festivals"][0]["lat"], None)

    def test_old_unverified_venue_text_is_not_silently_replaced(self):
        old = {**ROW, "city": "Colonne", "venue": "Lieu 2026 à confirmer",
               "showOnMap": None}
        updated, report = apply_independently_verified_city(
            catalog(old), catalog(old), review(), "2026-11-21",
            lambda _: MESSAGE, lambda _: api())
        self.assertEqual(report["accepted_city_updates"], [ROW["slug"]])
        self.assertEqual(updated["festivals"][0]["venue"], old["venue"])
        self.assertIsNot(updated["festivals"][0]["futureVenueConfirmed"], True)

    def test_forged_private_hint_is_never_network_authority(self):
        payload = review()
        payload["findings"][0]["candidate_city"]["source"] = "http://127.0.0.1/internal"
        calls = []
        result, info = apply_independently_verified_city(
            catalog(), catalog(), payload, "2026-11-21",
            lambda url: calls.append(url), lambda url: calls.append(url))
        self.assertEqual(calls, [])
        self.assertEqual(result, catalog())
        self.assertEqual(info["held_city"], 1)

    def test_admin_homonym_or_official_contradiction_blocks_public_marker(self):
        variants = [
            (MESSAGE.replace("Colonne", "Bordeaux"), api()),
            (MESSAGE, api(name="Bordeaux")),
            (MESSAGE, {"type": "FeatureCollection",
                       "features": api()["features"] * 2}),
            (MESSAGE, {"type": "FeatureCollection", "features": []}),
        ]
        for html, response in variants:
            with self.subTest(html=html, response=str(response)[:50]):
                updated, report = apply_independently_verified_city(
                    catalog(), catalog(), review(), "2026-11-21",
                    lambda _: html, lambda _: response)
                self.assertEqual(updated, catalog())
                self.assertEqual(report["accepted_city_updates"], [])
                self.assertEqual(report["held_city"], 1)

    def test_no_second_publication_of_already_pinned_commune(self):
        done, _ = apply_independently_verified_city(
            catalog(), catalog(), review(), "2026-11-21",
            lambda _: MESSAGE, lambda _: api())
        later, report = apply_independently_verified_city(
            done, done, review(as_of="2026-11-22"), "2026-11-22",
            lambda _: self.fail("Should not revisit signed pinned row"),
            lambda _: self.fail("Should not query geocoder"))
        self.assertEqual(later, done)
        self.assertEqual(report["accepted_city_updates"], [])
        corrupted = deepcopy(done)
        corrupted["festivals"][0]["status"] = "Faux statut"
        self.assertEqual(published_patch_duplicate(ROW, corrupted),
                         "PUBLISHED_COLLISION")
        corrupted = deepcopy(done)
        corrupted["festivals"][0]["geoVerification"]["markerMeaning"] = "exact venue"
        self.assertEqual(published_patch_duplicate(ROW, corrupted),
                         "PUBLISHED_COLLISION")

    def test_stale_or_malformed_private_report_vetoes_fetch(self):
        values = [review(as_of="2026-11-20"),
                  review(publication_authorized=True),
                  review(review_only=False), review(two_day_stable=0),
                  review(findings=review()["findings"] * 2)]
        bogus = review()
        bogus["findings"][0]["first_seen"] = "2026-11-21"
        values.append(bogus)
        for report in values:
            with self.subTest(report=str(report)[:100]):
                self.assertEqual(ready_city_reviews(report, "2026-11-21"),
                                 ([], "invalid_or_stale"))
                output, state = apply_independently_verified_city(
                    catalog(), catalog(), report, "2026-11-21",
                    lambda _: self.fail("Forbidden official fetch"))
                self.assertEqual(output, catalog())
                self.assertEqual(state["accepted_city_updates"], [])

    def test_signed_existing_geo_or_modified_edition_never_overwritten(self):
        changes = [
            {**ROW, "lat": 46.8, "lon": 5.5},
            {**ROW, "showOnMap": True},
            {**ROW, "futureVenueConfirmed": True},
            {**ROW, "startDate": "2026-07-02"},
            {**ROW, "officialSite": "http://127.0.0.1/private"},
        ]
        for old in changes:
            with self.subTest(old=str(old)[:100]):
                signed = catalog(old)
                result, state = apply_independently_verified_city(
                    signed, signed, review(), "2026-11-21",
                    lambda _: self.fail("Signed row unsuitable"))
                self.assertEqual(result, signed)
                self.assertEqual(state["accepted_city_updates"], [])

    def test_integrated_cloud_candidate_is_idempotent(self):
        c, h, patch = fixtures()
        c["festivals"][0] = deepcopy(ROW)
        snapshot = {"festivals.json": c, "festival-history.json": h}
        out, report = build_candidate(
            snapshot, snapshot, patch, {}, "2026-11-21",
            trusted_published=True, city_review=review(),
            city_fetcher=lambda _: MESSAGE, city_admin_reader=lambda _: api())
        self.assertTrue(report["changed"])
        self.assertEqual(report["future_city_publisher"]["accepted_city_updates"],
                         [ROW["slug"]])
        self.assertEqual(out["festivals"][0]["geoPrecision"], "commune")
        again, last = build_candidate(
            snapshot, {"festivals.json": out, "festival-history.json": h},
            patch, {}, "2026-11-22", trusted_published=True,
            city_review=review(as_of="2026-11-22"),
            city_fetcher=lambda _: self.fail("Cannot replay pinned edition"))
        self.assertFalse(last["changed"])
        self.assertEqual(again, out)


if __name__ == "__main__":
    unittest.main()
