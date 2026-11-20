import base64
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from grossesondes_future_geo_publisher import (
    PROOF_MODE, apply_independently_verified_geo, private_geo_report,
    ready_reviews,
)
from grossesondes_stage import published_patch_duplicate
from future_geo_preflight import SCHEMA, exact_edition_geo


SITE = "https://exemple-festival.fr/"
ROW = {
    "slug": "festival-exemple-2027",
    "name": "Festival Exemple 2027",
    "startDate": "2027-07-02", "endDate": "2027-07-03",
    "officialSite": SITE, "source": SITE,
    "city": None, "venue": None, "department": None, "region": None,
    "lat": None, "lon": None, "showOnMap": False,
    "status": "Annoncé", "futureVenueConfirmed": False,
}


def page(**changes):
    ev = {
        "@context": "https://schema.org",
        "@type": "MusicFestival",
        "name": "Festival Exemple 2027",
        "startDate": "2027-07-02", "endDate": "2027-07-03",
        "location": {
            "@type": "Place", "name": "Le Champ des Guitares",
            "address": {"@type": "PostalAddress",
                        "addressLocality": "Colonne", "addressCountry": "FR"},
            "geo": {"@type": "GeoCoordinates",
                    "latitude": 46.8832, "longitude": 5.5577},
        },
    }
    ev.update(changes)
    return ("<html><script type='application/ld+json'>"
            + json.dumps(ev) + "</script></html>")


def review(**changes):
    claim = exact_edition_geo(page(), ROW)
    result = {
        "schema": SCHEMA, "as_of": "2026-11-21",
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publisher_geo_sync_connected": False,
        "checked": 1, "two_day_stable": 1,
        "findings": [{
            "slug": ROW["slug"], "status": "TWO_DAY_STABLE_REVIEW_ONLY",
            "first_seen": "2026-11-20", "candidate_geo": claim,
            "publication_authorized": False,
        }],
    }
    result.update(changes)
    return result


def calendar(rows=None):
    return {"schema": 1, "generatedAt": "2026-11-20",
            "festivals": [deepcopy(ROW) if rows is None else rows]}


class GeoPublisherTests(unittest.TestCase):
    def test_private_report_reads_only_fixed_path_with_token(self):
        calls = []
        payload = review()
        def fake(url, token):
            calls.append((url, token))
            return {"encoding": "base64",
                    "content": base64.b64encode(
                        json.dumps(payload).encode("utf-8")).decode("ascii")}
        self.assertEqual(private_geo_report("TOKEN", fake), payload)
        self.assertEqual(len(calls), 1)
        self.assertIn("future-festival-geo-review.json?ref=automation%2Fgrossesondes-intake",
                      calls[0][0])
        self.assertNotIn("exemple-festival", calls[0][0])
        self.assertIsNone(private_geo_report("TOKEN", lambda *_: {"encoding": "utf8"}))
        with self.assertRaises(ValueError):
            private_geo_report("", fake)

    def test_only_signed_current_edition_source_is_contacted(self):
        calls = []
        old = calendar()
        target = calendar()
        def fetch(url):
            calls.append(url)
            return page()
        out, summary = apply_independently_verified_geo(
            target, old, review(), "2026-11-21", fetch)
        self.assertEqual(calls, [SITE])
        self.assertEqual(summary["accepted_geo_updates"], [ROW["slug"]])
        row = out["festivals"][0]
        self.assertTrue(row["showOnMap"])
        self.assertTrue(row["futureVenueConfirmed"])
        self.assertEqual(row["geoPrecision"], "lieu")
        self.assertEqual(row["geoCity"], "Colonne")
        self.assertEqual(row["geoSource"], SITE)
        self.assertEqual(row["venue"], "Le Champ des Guitares")
        self.assertEqual((row["lat"], row["lon"]), (46.8832, 5.5577))
        self.assertEqual(row["geoVerification"]["proofMode"], PROOF_MODE)
        self.assertEqual(out["generatedAt"], "2026-11-21")
        self.assertEqual(old["festivals"][0], ROW)
        self.assertFalse(summary["publication_authorized_by_private_report"])

    def test_publisher_rederives_same_host_access_page_from_signed_home(self):
        access = SITE + "infos-pratiques/acces"
        home = (
            '<a href="infos-pratiques/acces">Accès - Parkings</a>'
            '<a href="https://external.example/faux-acces">Accès externe</a>'
        )
        calls = []
        def fetch(url):
            calls.append(url)
            return home if url == SITE else page()
        out, summary = apply_independently_verified_geo(
            calendar(), calendar(), review(), "2026-11-21", fetch)
        self.assertEqual(calls, [SITE, access])
        self.assertEqual(summary["accepted_geo_updates"], [ROW["slug"]])
        self.assertTrue(out["festivals"][0]["showOnMap"])
        self.assertEqual(out["festivals"][0]["geoSource"], SITE)
        self.assertNotIn("external.example", str(calls))

    def test_publisher_does_not_certify_old_access_page(self):
        home = '<a href="/acces">Accès au festival</a>'
        old_event = page(name="Festival Exemple 2026")
        out, summary = apply_independently_verified_geo(
            calendar(), calendar(), review(), "2026-11-21",
            lambda url: home if url == SITE else old_event)
        self.assertEqual(out, calendar())
        self.assertEqual(summary["accepted_geo_updates"], [])
        self.assertEqual(summary["held_geo"], 1)

    def test_replay_does_not_publish_again_and_legacy_patch_is_idempotent(self):
        updated, summary = apply_independently_verified_geo(
            calendar(), calendar(), review(), "2026-11-21", lambda _: page())
        next_day, report = apply_independently_verified_geo(
            updated, updated, review(as_of="2026-11-22"),
            "2026-11-22", lambda _: page())
        self.assertEqual(next_day, updated)
        self.assertEqual(report["accepted_geo_updates"], [])
        self.assertEqual(published_patch_duplicate(ROW, updated), "ALREADY_PUBLISHED")
        forged = deepcopy(updated)
        forged["festivals"][0]["name"] = "Autre Festival 2027"
        self.assertEqual(published_patch_duplicate(ROW, forged), "PUBLISHED_COLLISION")
        forged = deepcopy(updated)
        forged["festivals"][0]["geoVerification"]["proofMode"] = "private-forged"
        self.assertEqual(published_patch_duplicate(ROW, forged), "PUBLISHED_COLLISION")

    def test_private_report_is_never_network_authority(self):
        altered = review()
        altered["findings"][0]["candidate_geo"]["source"] = (
            "https://127.0.0.1/private")
        calls = []
        _, res = apply_independently_verified_geo(
            calendar(), calendar(), altered, "2026-11-21",
            lambda url: calls.append(url) or page())
        self.assertEqual(calls, [])
        self.assertEqual(res["accepted_geo_updates"], [])

    def test_tampered_candidate_geo_does_not_publish(self):
        variants = [
            {"city": "Other Town"},
            {"lat": 47.0}, {"venue": "Another Place"},
            {"country": None}, {"country": "US"},
        ]
        for change in variants:
            with self.subTest(change=change):
                evidence = review()
                evidence["findings"][0]["candidate_geo"].update(change)
                new, summary = apply_independently_verified_geo(
                    calendar(), calendar(), evidence, "2026-11-21",
                    lambda _: page())
                self.assertEqual(new, calendar())
                self.assertEqual(summary["accepted_geo_updates"], [])

    def test_missing_french_country_or_event_specific_venue_blocks_pin(self):
        no_country = page(location={
            **json.loads(page().split("application/ld+json'>", 1)[1].split("</script>", 1)[0])["location"],
            "address": {"addressLocality": "Colonne"}})
        for html in [no_country, page(location={
                    "@type": "Place", "name": None,
                    "address": {"addressLocality": "Colonne", "addressCountry": "FR"},
                    "geo": {"latitude": 46.8832, "longitude": 5.5577}})]:
            with self.subTest(html=html):
                new, report = apply_independently_verified_geo(
                    calendar(), calendar(), review(),
                    "2026-11-21", lambda _: html)
                self.assertEqual(new, calendar())
                self.assertEqual(report["held_geo"], 1)

    def test_stale_or_forged_review_does_not_authorize(self):
        cases = [
            review(as_of="2026-11-20"),
            review(review_only=False),
            review(publication_authorized=True),
            review(two_day_stable=2),
            review(findings=review()["findings"] * 2),
        ]
        invalid_first = review()
        invalid_first["findings"][0]["first_seen"] = "2026-11-21"
        cases.append(invalid_first)
        for stale in cases:
            with self.subTest(data=stale):
                ready, state = ready_reviews(stale, "2026-11-21")
                self.assertEqual(ready, [])
                self.assertEqual(state, "invalid_or_stale")
                out, summary = apply_independently_verified_geo(
                    calendar(), calendar(), stale, "2026-11-21",
                    lambda _: self.fail("Forbidden fetch"))
                self.assertEqual(out, calendar())
                self.assertEqual(summary["accepted_geo_updates"], [])

    def test_unsigned_or_manually_hidden_rows_cannot_publish(self):
        for variant in [
            {**ROW, "showOnMap": None},
            {**ROW, "lat": 46.88, "lon": 5.55},
            {**ROW, "futureVenueConfirmed": True},
            {**ROW, "startDate": None},
            {**ROW, "officialSite": "http://127.0.0.1/"}
        ]:
            with self.subTest(variant=variant):
                old = calendar(variant)
                out, report = apply_independently_verified_geo(
                    old, old, review(), "2026-11-21",
                    lambda _: self.fail("Forbidden fetch"))
                self.assertEqual(out, old)
                self.assertEqual(report["accepted_geo_updates"], [])

    def test_mutated_signed_row_stops_geo_without_undoing_other_edits(self):
        signed = calendar()
        changed = calendar()
        changed["festivals"][0]["name"] = "Forged"
        out, report = apply_independently_verified_geo(
            changed, signed, review(), "2026-11-21",
            lambda _: self.fail("Forbidden fetch"))
        self.assertEqual(out, changed)
        self.assertEqual(report["held_geo"], 1)


if __name__ == "__main__":
    unittest.main()
