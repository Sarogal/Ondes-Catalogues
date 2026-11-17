"""Adversarial offline tests for national family independent-source preflight.

All organiser pages, venues, dates, coordinates and host trust lists below
are deliberately SYNTHETIC. No public/private approvals or publishing.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_family_national_source_preflight import (
    SCHEMA, official_host, inspect_family_national_preflight,
    canonical_sha256,
)
from ptitesondes_family_national_scope import FAMILY_TYPES

TODAY = date(2026, 11, 17)
HOST = "agenda.commune.test"
REGISTRY = [{
    "venue_key": "ajaccio-maison-des-enfants",
    "city": "Ajaccio",
    "venue": "Maison des enfants",
    "lat": 41.9191,
    "lng": 8.7385,
    "institutional_url": "https://culture.commune.test/maison-des-enfants",
    "geo_source_url": "https://www.openstreetmap.org/way/123456",
}]


def historical():
    return json.loads(
        (ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8")
    )


def fixture(code="atelier-creatif", index=1):
    title = "Atelier enfant fictif " + str(index)
    url = f"https://{HOST}/animations/session-{index}"
    scope = {
        "record_kind": "dated_event",
        "category": code, "category_label": FAMILY_TYPES[code][0],
        "title": title, "city": "Ajaccio", "venue": "Maison des enfants",
        "source_url": url, "date_start": "2026-11-18",
        "date_end": "2026-11-18", "audience_claim": "explicit_child",
        "age_min": 5, "age_max": 12,
        "price_evidence": "not_stated",
        "registration_evidence": "not_stated",
    }
    source = {
        "official_url": url, "start_local": "14:00",
        "venue_key": "ajaccio-maison-des-enfants",
        "region": "Corse", "department": "Corse-du-Sud (2A)",
        "lat": 41.9191, "lng": 8.7385,
    }
    page = (
        "<!doctype html><html><body><main><h1>"
        + title + "</h1><div>Ajaccio, Maison des enfants</div>"
        + "<time>18 novembre 2026 à 14h00</time>"
        + "<p>Pour les enfants de 5 ans à 12 ans. "
        + "Consulter les conditions de réservation.</p></main></body></html>"
    )
    return {"scope": scope, "source": source}, page


MISSING = object()


def run(*, docs=MISSING, catalog=None, hosts=None, reg=None, pages=None,
        reader=None, pin=None):
    if catalog is None:
        catalog = historical()
    if docs is MISSING:
        docs, text = fixture()
        docs, pages = [docs], {docs["source"]["official_url"]: text}
    if pages is None and isinstance(docs, list):
        pages = {
            item["source"]["official_url"]: fixture(
                item["scope"]["category"], i + 1
            )[1]
            for i, item in enumerate(docs)
        }
    if pages is None:
        pages = {}
    if reader is None:
        reader = lambda url: pages[url]
    return inspect_family_national_preflight(
        catalog, docs, TODAY,
        catalogue_sha256=pin or canonical_sha256(catalog),
        trusted_official_hosts=hosts if hosts is not None else [HOST],
        venue_registry=reg if reg is not None else deepcopy(REGISTRY),
        source_get=reader,
    )


class NationalFamilyIndependentPreflightTests(unittest.TestCase):
    def test_one_realistic_synthetic_organizer_page_passes_cues_never_release(self):
        before = historical()
        expected = deepcopy(before)
        with patch("merge_policy.merge", side_effect=AssertionError(
            "production publisher forbidden"
        )):
            out = run(catalog=before)
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["official_source_cues_passed"], 1)
        self.assertTrue(out["source_preflight_batch_passed"])
        self.assertEqual(out["blocked_occurrences"], 0)
        self.assertEqual(out["catalogue_events_preserved"], 548)
        self.assertTrue(out["human_approvals_not_checked"])
        self.assertTrue(out["geo_provider_not_refetched"])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted_to_publisher"])
        self.assertEqual(out["public_writes"], 0)
        self.assertEqual(before, expected)
        for forbidden in ("events", "additions", "patch", "candidate",
                          "source_url", "review_id", "catalogue"):
            self.assertNotIn(forbidden, out)

    def test_all_thirteen_categories_check_source_without_opening_publisher(self):
        docs, pages = [], {}
        for i, category in enumerate(FAMILY_TYPES, start=1):
            row, html = fixture(category, i)
            docs.append(row)
            pages[row["source"]["official_url"]] = html
        out = run(docs=docs, pages=pages)
        self.assertEqual(out["official_source_cues_passed"], 13)
        self.assertTrue(out["source_preflight_batch_passed"])
        self.assertEqual(out["public_writes"], 0)

    def test_no_wildcard_host_trust_or_aggregator(self):
        called = []
        def reader(url):
            called.append(url)
            raise AssertionError("Untrusted page must not be read")
        out = run(hosts=["other.commune.test"], reader=reader)
        self.assertEqual(called, [])
        self.assertEqual(out["official_source_cues_passed"], 0)
        self.assertIn("official_organizer_host_not_trusted_or_url_changed",
                      out["blocked_reason_counts"])
        self.assertEqual(run(hosts=["*.commune.test"])["official_source_cues_passed"], 0)

    def test_collector_cannot_substitute_different_organizer_url(self):
        item, page = fixture()
        item["source"]["official_url"] = "https://another.commune.test/activities/1"
        out = run(docs=[item], pages={item["source"]["official_url"]: page},
                  hosts=["another.commune.test"])
        self.assertIn("official_organizer_host_not_trusted_or_url_changed",
                      out["blocked_reason_counts"])

    def test_unsafe_source_urls_and_invalid_hosts_are_rejected(self):
        for url in ("http://agenda.commune.test/e", "https://user:pass@agenda.commune.test/e",
                    "https://agenda.commune.test/e#fake", "javascript:alert(1)"):
            with self.subTest(url=url):
                item, page = fixture()
                item["scope"]["source_url"] = url
                item["source"]["official_url"] = url
                out = run(docs=[item], pages={url: page})
                self.assertEqual(out["official_source_cues_passed"], 0)
        self.assertIsNone(official_host("https://malicious.example/x"))

    def test_page_missing_date_or_time_or_place_blocks(self):
        item, page = fixture()
        url = item["source"]["official_url"]
        for needle in ("18 novembre 2026", "14h00", "Ajaccio",
                       "Maison des enfants", item["scope"]["title"]):
            with self.subTest(needle=needle):
                out = run(docs=[item], pages={url: page.replace(needle, "inconnu")})
                self.assertEqual(out["official_source_cues_passed"], 0)

    def test_cancelled_postponed_full_session_is_refused(self):
        item, page = fixture()
        url = item["source"]["official_url"]
        for status in ("Événement annulé", "Événement complet", "Atelier reporté"):
            with self.subTest(status=status):
                out = run(docs=[item], pages={url: page.replace(
                    "</main>", f"<p>{status}</p></main>"
                )})
                self.assertIn("cancelled_full_or_postponed",
                              out["blocked_reason_counts"])

    def test_missing_or_changed_family_audience_and_age_proofs(self):
        item, page = fixture()
        url = item["source"]["official_url"]
        out = run(docs=[item], pages={url: page.replace("enfants", "public")})
        self.assertIn("official_family_audience_not_confirmed",
                      out["blocked_reason_counts"])
        out = run(docs=[item], pages={url: page.replace("12 ans", "15 ans")})
        self.assertIn("exact_age_bounds_not_confirmed",
                      out["blocked_reason_counts"])

    def test_misleading_pricing_cannot_be_marked_free(self):
        item, page = fixture()
        item["scope"]["price_evidence"] = "explicit_free"
        out = run(docs=[item], pages={item["source"]["official_url"]: page})
        self.assertIn("explicit_free_claim_not_on_official_page",
                      out["blocked_reason_counts"])
        out = run(docs=[item], pages={item["source"]["official_url"]:
                  page.replace("</main>", "<p>Gratuit.</p></main>")})
        self.assertEqual(out["official_source_cues_passed"], 1)
        self.assertFalse(out["publication_ready"])

    def test_registration_not_assumed_without_official_words(self):
        item, page = fixture()
        item["scope"]["registration_evidence"] = "explicit_not_required"
        out = run(docs=[item], pages={item["source"]["official_url"]: page})
        self.assertIn("no_registration_claim_not_on_official_page",
                      out["blocked_reason_counts"])
        out = run(docs=[item], pages={item["source"]["official_url"]:
                  page.replace("</main>", "<p>Sans inscription.</p></main>")})
        self.assertEqual(out["official_source_cues_passed"], 1)

    def test_contradictory_access_blocks_not_source_only_automatically(self):
        item, page = fixture()
        item["scope"]["price_evidence"] = "contradictory"
        out = run(docs=[item], pages={item["source"]["official_url"]: page})
        self.assertIn("unresolved_access_contradiction",
                      out["blocked_reason_counts"])

    def test_past_date_and_permanent_place_cannot_join_event_preflight(self):
        item, page = fixture()
        item["scope"]["date_start"] = "2026-11-01"
        item["scope"]["date_end"] = "2026-11-01"
        out = run(docs=[item], pages={item["source"]["official_url"]: page})
        self.assertIn("national_scope_not_plausible",
                      out["blocked_reason_counts"])
        item, page = fixture()
        item["scope"].update(record_kind="permanent_place",
                             date_start=None, date_end=None,
                             category=None, category_label=None)
        out = run(docs=[item], pages={item["source"]["official_url"]: page})
        self.assertIn("permanent_place_requires_independent_place_pipeline",
                      out["blocked_reason_counts"])

    def test_missing_geo_record_or_different_coordinates_refused(self):
        out = run(reg=[])
        self.assertIn("venue_point_or_independent_provenance_unverified",
                      out["blocked_reason_counts"])
        changed = deepcopy(REGISTRY)
        changed[0]["lat"] = 41.1234
        out = run(reg=changed)
        self.assertEqual(out["official_source_cues_passed"], 0)

    def test_geo_source_same_host_or_non_https_fails(self):
        for geo in ("https://culture.commune.test/geo",
                    "http://www.openstreetmap.org/way/1"):
            with self.subTest(geo=geo):
                changed = deepcopy(REGISTRY)
                changed[0]["geo_source_url"] = geo
                out = run(reg=changed)
                self.assertEqual(out["official_source_cues_passed"], 0)

    def test_source_unavailable_never_claims_preflight(self):
        def dead(url):
            raise OSError("offline")
        out = run(reader=dead)
        self.assertEqual(out["official_source_cues_passed"], 0)
        self.assertIn("official_source_unavailable_or_unverifiable",
                      out["blocked_reason_counts"])

    def test_duplicate_within_batch_blocks_second_occurrence(self):
        first, html = fixture()
        second = deepcopy(first)
        out = run(docs=[first, second],
                  pages={first["source"]["official_url"]: html})
        self.assertEqual(out["official_source_cues_passed"], 1)
        self.assertIn("duplicate_within_candidate_batch",
                      out["blocked_reason_counts"])
        self.assertFalse(out["source_preflight_batch_passed"])
        self.assertEqual(out["public_writes"], 0)

    def test_cross_source_catalogue_duplicate_always_blocked(self):
        item, html = fixture()
        current = historical()
        current["events"].append({
            "id": "different-feed-copy-for-test",
            "category": "concert",
            "title": item["scope"]["title"],
            "city": item["scope"]["city"],
            "venue": item["scope"]["venue"],
            "date_start": "2026-11-18", "date_end": "2026-11-18",
            "source_url": "https://other.example.org/unrelated",
        })
        out = run(catalog=current, docs=[item],
                  pages={item["source"]["official_url"]: html})
        self.assertIn("already_published_from_any_source",
                      out["blocked_reason_counts"])
        self.assertEqual(out["catalogue_events_preserved"], 549)

    def test_sha_change_invalidates_snapshot(self):
        with self.assertRaisesRegex(ValueError, "catalogue_sha_pin_mismatch"):
            run(pin="0" * 64)

    def test_callback_mutation_of_historical_catalogue_detected(self):
        current = historical()
        item, page = fixture()
        def malicious(url):
            current["events"][0]["title"] = "changed by third-party callback"
            return page
        with self.assertRaisesRegex(ValueError, "catalogue_mutated_during"):
            run(catalog=current, reader=malicious)

    def test_malformed_inputs_and_arbitrary_collector_privilege_refused(self):
        item, page = fixture()
        item["scope"]["approved"] = True
        out = run(docs=[item], pages={item["source"]["official_url"]: page})
        self.assertIn("national_scope_not_plausible",
                      out["blocked_reason_counts"])
        for bad in ([], None, {}):
            with self.assertRaisesRegex(ValueError, "invalid_preflight_batch"):
                run(docs=bad)
        with self.assertRaisesRegex(ValueError, "invalid_preflight_date"):
            inspect_family_national_preflight(
                historical(), [fixture()[0]], "2026-11-17",
                catalogue_sha256=canonical_sha256(historical()),
                trusted_official_hosts=[HOST], venue_registry=REGISTRY,
                source_get=lambda url: fixture()[1],
            )

    def test_reject_source_header_missing_and_identityless_venue(self):
        item, page = fixture()
        item["source"].pop("start_local")
        out = run(docs=[item], pages={item["source"]["official_url"]: page})
        self.assertIn("invalid_source_evidence_shape",
                      out["blocked_reason_counts"])

    def test_no_permanent_place_or_new_category_changes_to_historical_catalogue(self):
        current = historical()
        original = deepcopy(current)
        run(catalog=current)
        self.assertEqual(current, original)
        self.assertEqual(set(e["category"] for e in current["events"]), {
            "concert", "conte-musical", "spectacle-musical",
            "eveil-musical", "atelier-musical", "cine-concert", "festival",
        })


if __name__ == "__main__":
    unittest.main()
