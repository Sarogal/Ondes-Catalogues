"""Offline batch caching and privacy checks: synthetic sources only."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_geo_batch import diagnose_batch, MAX_BATCH
from test_ptitesondes_openagenda_v2_geo_fetch import (
    SOURCE, LEAD, EVENT, AGENDA, HTML, GEO,
)


def case(**patch):
    row = {
        "lead": deepcopy(LEAD), "api_event": deepcopy(EVENT),
        "reviewed_agenda": deepcopy(AGENDA),
        "reviewed_source": deepcopy(SOURCE),
    }
    for name, value in patch.items():
        row[name] = value
    return row


class IndependentGeoBatchTests(unittest.TestCase):
    def test_fifty_records_at_one_reviewed_venue_use_one_page_and_one_ign_read(self):
        pages, geocodes = [], []
        def page_reader(source):
            pages.append(source["exact_url"])
            return {"url": source["exact_url"], "html": HTML}
        def geo_reader(url):
            geocodes.append(url)
            return deepcopy(GEO)
        result = diagnose_batch(
            [case() for _ in range(50)], date(2026, 11, 18),
            official_reader=page_reader, geo_reader=geo_reader)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(geocodes), 1)
        self.assertEqual(result["checked_leads"], 50)
        self.assertEqual(result["pinned_pages_attempted"], 1)
        self.assertEqual(result["ign_ban_queries_attempted"], 1)
        self.assertEqual(result["reason_counts"], {
            "geo_and_direct_structurally_verified": 50,
        })
        self.assertEqual(result["public_writes"], 0)
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["organizer_independently_attested"])

    def test_cached_geo_never_overrides_candidate_venue_coordinates(self):
        altered = case()
        altered["api_event"]["location"]["latitude"] += 0.05
        result = diagnose_batch(
            [case(), altered], date(2026, 11, 18),
            official_reader=lambda src: {"url": src["exact_url"], "html": HTML},
            geo_reader=lambda url: deepcopy(GEO))
        self.assertEqual(result["pinned_pages_attempted"], 1)
        self.assertEqual(result["ign_ban_queries_attempted"], 1)
        self.assertEqual(result["reason_counts"], {
            "geo_and_direct_structurally_verified": 1,
            "independent_geo_not_concordant": 1,
        })

    def test_explicit_adult_only_is_held_after_shared_venue_geocoding(self):
        adult = case()
        adult["api_event"]["description"]["fr"] = "Réservé aux adultes uniquement"
        result = diagnose_batch(
            [case(), adult], date(2026, 11, 18),
            official_reader=lambda src: {"url": src["exact_url"], "html": HTML},
            geo_reader=lambda url: deepcopy(GEO))
        self.assertEqual(result["reason_counts"], {
            "direct_api_structure_or_audience_hold": 1,
            "geo_and_direct_structurally_verified": 1,
        })
        self.assertFalse(result["category_and_access_fully_verified"])

    def test_unknown_pin_does_not_trigger_any_network(self):
        invalid = case(reviewed_source={
            "approved_host": "rouen.fr.evil.test",
            "exact_url": SOURCE["exact_url"],
        })
        counts = diagnose_batch(
            [invalid], date(2026, 11, 18),
            official_reader=lambda src: self.fail("Network attempted"),
            geo_reader=lambda url: self.fail("BAN attempted"))
        self.assertEqual(counts["reason_counts"], {"pin_unreviewed": 1})
        self.assertEqual(counts["pinned_pages_attempted"], 0)

    def test_bad_first_party_response_is_cached_but_not_used(self):
        calls = []
        def bad_reader(src):
            calls.append(1)
            raise RuntimeError("PRIVATE_URL/oa_pk_SUPERSECRET")
        result = diagnose_batch(
            [case() for _ in range(4)], date(2026, 11, 18),
            official_reader=bad_reader,
            geo_reader=lambda url: self.fail("BAN attempted"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["reason_counts"], {
            "institutional_page_unavailable_or_mismatch": 4,
        })
        self.assertNotIn("PRIVATE_URL", json.dumps(result))
        self.assertNotIn("oa_pk_", json.dumps(result))

    def test_distinct_pinned_sites_can_share_ban_query_without_cross_site_approval(self):
        alt = case()
        alt["reviewed_source"] = {
            "approved_host": "mairie-rouen.fr",
            "exact_url": "https://mairie-rouen.fr/mediatheque",
        }
        pages, geo = [], []
        def official_reader(source):
            pages.append(source["exact_url"])
            return {"url": source["exact_url"], "html": HTML}
        def geo_reader(url):
            geo.append(url)
            return deepcopy(GEO)
        result = diagnose_batch(
            [case(), alt], date(2026, 11, 18),
            official_reader=official_reader, geo_reader=geo_reader)
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(geo), 1)
        self.assertEqual(result["reason_counts"]["geo_and_direct_structurally_verified"], 2)
        self.assertFalse(result["approval_granted"])

    def test_untrusted_input_shape_and_batch_limits_are_bounded(self):
        for bad in ([], [case()] * (MAX_BATCH + 1), "bad", None):
            with self.subTest(case=type(bad).__name__):
                with self.assertRaises(ValueError):
                    diagnose_batch(bad, date(2026, 11, 18))
        result = diagnose_batch([{"lead": {}}], date(2026, 11, 18))
        self.assertEqual(result["reason_counts"], {"case_shape_invalid": 1})

    def test_no_private_metadata_ever_leaves_aggregated_result(self):
        out = diagnose_batch(
            [case()], date(2026, 11, 18),
            official_reader=lambda src: {"url": src["exact_url"], "html": HTML},
            geo_reader=lambda url: deepcopy(GEO))
        output = json.dumps(out)
        for private in ("Rouen", "12345678", "Bibliothèque", "rouen.fr",
                        "42 rue", "oa_pk_"):
            self.assertNotIn(private, output)
        self.assertEqual(sum(out["reason_counts"].values()), out["checked_leads"])


if __name__ == "__main__":
    unittest.main()
