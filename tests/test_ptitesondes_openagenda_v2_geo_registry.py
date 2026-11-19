"""Offline test of source independence for GPS proof: no external I/O."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_geo_registry import (
    diagnose_with_curated_registry, _validate_registry, MAX_REVIEWED_SOURCES,
)
from test_ptitesondes_openagenda_v2_geo_fetch import (
    SOURCE, LEAD, EVENT, AGENDA, HTML, GEO,
)

REVIEWED = {
    "city": "Rouen", "aliases": ["Bibliothèque fictive"],
    "approved_host": SOURCE["approved_host"],
    "exact_url": SOURCE["exact_url"],
}


def row(**kwargs):
    x = {
        "lead": deepcopy(LEAD), "api_event": deepcopy(EVENT),
        "reviewed_agenda": deepcopy(AGENDA),
    }
    x.update(kwargs)
    return x


class SeparateRegistryTests(unittest.TestCase):
    def test_curated_source_is_used_even_if_collector_claims_another_site(self):
        candidate = row()
        candidate["lead"].update({
            "official_url": "https://untrusted.example/official",
            "approved": True, "venue_gps_verified": True,
        })
        pages = []
        def official(source):
            pages.append(source["exact_url"])
            return {"url": source["exact_url"], "html": HTML}
        result = diagnose_with_curated_registry(
            [candidate], [REVIEWED], date(2026, 11, 18),
            official_reader=official, geo_reader=lambda _: deepcopy(GEO))
        self.assertEqual(pages, [SOURCE["exact_url"]])
        self.assertEqual(result["reason_counts"], {
            "geo_and_direct_structurally_verified": 1,
        })
        self.assertTrue(result["source_pins_selected_from_curated_registry_only"])
        self.assertFalse(result["registry_identity_attested"])
        self.assertFalse(result["approval_granted"])
        self.assertEqual(result["public_writes"], 0)

    def test_collector_supplied_reviewed_source_cannot_be_forced(self):
        extra = row(reviewed_source={
            "approved_host": "other.example.org",
            "exact_url": "https://other.example.org/fake",
        })
        result = diagnose_with_curated_registry(
            [extra], [REVIEWED], date(2026, 11, 18),
            official_reader=lambda _: self.fail("Untrusted source fetched"),
            geo_reader=lambda _: self.fail("BAN fetched"))
        self.assertEqual(result["reason_counts"], {"case_shape_invalid": 1})
        self.assertEqual(result["pinned_pages_attempted"], 0)

    def test_ambiguous_same_name_two_reviewed_sites_is_hold_not_autopick(self):
        other = dict(REVIEWED,
                     approved_host="autre-rouen.fr",
                     exact_url="https://autre-rouen.fr/lieu")
        result = diagnose_with_curated_registry(
            [row()], [REVIEWED, other], date(2026, 11, 18),
            official_reader=lambda _: self.fail("Ambiguous source fetched"),
            geo_reader=lambda _: self.fail("BAN fetched"))
        self.assertEqual(result["reason_counts"], {"pin_unreviewed": 1})
        self.assertEqual(result["pinned_pages_attempted"], 0)

    def test_unknown_venue_is_not_inferred_from_similar_institution_alias(self):
        cand = row()
        cand["lead"]["venue"] = "Bibliothèque fictive annexe"
        report = diagnose_with_curated_registry(
            [cand], [REVIEWED], date(2026, 11, 18),
            official_reader=lambda _: self.fail("Unknown venue fetched"),
            geo_reader=lambda _: self.fail("BAN fetched"))
        self.assertEqual(report["reason_counts"], {"pin_unreviewed": 1})

    def test_invalid_registry_domains_and_oversized_aliases_fail_before_http(self):
        for bad in (
            [dict(REVIEWED, exact_url="https://rouen.fr.evil.test/lieu")],
            [dict(REVIEWED, aliases=[])],
            [dict(REVIEWED, aliases=[42])],
            [dict(REVIEWED, city="")],
            [dict(REVIEWED, approved_host="127.0.0.1",
                  exact_url="https://127.0.0.1/page")],
            [dict(REVIEWED, aliases=["alias"] * 26)],
            [REVIEWED] * (MAX_REVIEWED_SOURCES + 1),
        ):
            with self.subTest(bad=str(type(bad))):
                with self.assertRaises(ValueError):
                    _validate_registry(bad)

    def test_batch_count_output_is_private_data_free_and_never_authorizes(self):
        out = diagnose_with_curated_registry(
            [row() for _ in range(10)], [REVIEWED], date(2026, 11, 18),
            official_reader=lambda source: {
                "url": source["exact_url"], "html": HTML},
            geo_reader=lambda _: deepcopy(GEO))
        self.assertEqual(out["pinned_pages_attempted"], 1)
        self.assertEqual(out["ign_ban_queries_attempted"], 1)
        self.assertEqual(sum(out["reason_counts"].values()), 10)
        self.assertFalse(out["publisher_connected"])
        raw = json.dumps(out)
        for private in ("Rouen", "Bibliothèque", "rouen.fr",
                        "12345678", "42 rue", "oa_pk_"):
            self.assertNotIn(private, raw)


if __name__ == "__main__":
    unittest.main()
