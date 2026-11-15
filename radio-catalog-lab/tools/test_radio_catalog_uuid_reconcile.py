"""Réconciliation des UUID : aucun identifiant ni flux n'est modifié."""
import copy
import unittest

from radio_catalog_uuid_reconcile import evaluate, canonical_url


def source(uid, name, stream, homepage):
    return {"id": uid, "name": name, "streamUrl": stream,
            "homepage": homepage, "streamVariants": []}


def indexed(*stations):
    return {"aliases": [{"legacy_id": station["id"],
                         "go_station_id": f"go-station-{i:06d}"}
                        for i, station in enumerate(stations, start=1)]}


def row(uuid, name=None, url=None, homepage=None):
    return {"uuid": uuid, "directory_found": bool(name),
            "directory_name": name, "directory_stream_url": url,
            "directory_homepage": homepage}


class UuidReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.catalog = {"stations": [
            source("old-001", "Radio One", "https://radio.example/ONE", "https://network.example/"),
            source("old-002", "Radio Two", "https://radio.example/two", "https://network.example/"),
            source("old-003", "Radio Three", "https://radio.example/shared", "https://three.example"),
            source("old-004", "Radio Four", "https://radio.example/shared", "https://four.example"),
        ]}
        self.aliases = indexed(*self.catalog["stations"])

    def report(self, *rows):
        return evaluate({"rows": list(rows)}, self.catalog, self.aliases)

    def test_matching_name_and_stream_is_review_only(self):
        old = copy.deepcopy(self.catalog)
        evidence = {"rows": [row("fresh-uuid", "Radio One", "https://radio.example/ONE",
                                 "https://network.example")]}
        evold = copy.deepcopy(evidence)
        res = evaluate(evidence, self.catalog, self.aliases)
        self.assertEqual(res["rows"][0]["classification"], "same_stream_and_name_review")
        self.assertFalse(res["rows"][0]["auto_merge"])
        self.assertFalse(res["rows"][0]["auto_admit"])
        self.assertEqual(res["rows"][0]["exact_stream_matches"][0]["go_station_id"],
                         "go-station-000001")
        self.assertEqual(self.catalog, old)
        self.assertEqual(evidence, evold)

    def test_shared_website_cannot_merge_different_programmes(self):
        res = self.report(row("punk", "Radio Punk", "https://other.example/punk",
                              "https://network.example"))
        self.assertEqual(res["rows"][0]["classification"], "shared_homepage_only_no_merge")
        self.assertEqual(len(res["rows"][0]["shared_homepage_matches"]), 2)
        self.assertEqual(res["rows"][0]["exact_stream_matches"], [])

    def test_same_stream_different_name_is_ambiguous(self):
        res = self.report(row("alias", "Metalcore renamed?", "https://radio.example/two",
                              "https://elsewhere.example"))
        self.assertEqual(res["rows"][0]["classification"], "same_stream_different_name_review")
        self.assertFalse(res["rows"][0]["auto_merge"])

    def test_multiple_stations_share_same_stream(self):
        res = self.report(row("alias", "Radio Three", "https://radio.example/shared",
                              "https://three.example"))
        self.assertEqual(res["rows"][0]["classification"], "ambiguous_shared_stream")
        self.assertEqual(len(res["rows"][0]["exact_stream_matches"]), 2)

    def test_unknown_id_remains_unresolved(self):
        res = self.report({"uuid": "gone-uuid", "directory_found": False})
        self.assertEqual(res["rows"][0]["classification"], "not_found_directory_recheck")
        self.assertFalse(res["rows"][0]["delete_previous_alias"])
        self.assertEqual(res["rows"][0]["exact_stream_matches"], [])

    def test_unmatched_candidate_remains_unapproved(self):
        res = self.report(row("punk", "New Punk Station", "https://punk.example/mp3",
                              "https://punk.example"))
        self.assertEqual(res["rows"][0]["classification"], "new_or_unlinked_candidate_review")
        self.assertFalse(res["rows"][0]["auto_admit"])

    def test_stream_comparison_preserves_path_case_and_query(self):
        self.assertNotEqual(canonical_url("https://radio.example/ONE"),
                            canonical_url("https://radio.example/one"))
        self.assertNotEqual(canonical_url("https://radio.example/a?x=1"),
                            canonical_url("https://radio.example/a?x=2"))
        self.assertEqual(canonical_url("HTTPS://RADIO.EXAMPLE/ONE"),
                         canonical_url("https://radio.example/ONE"))

    def test_alias_index_missing_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "absent"):
            evaluate({"rows": [row("u", "Radio One", "https://radio.example/ONE")]},
                     self.catalog, {"aliases": []})

    def test_duplicate_input_uuid_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.report({"uuid": "x", "directory_found": False},
                        {"uuid": "x", "directory_found": False})


if __name__ == "__main__":
    unittest.main()
