"""Verrou de couverture des UUID et des favoris historiques pour un catalogue GO."""
import copy
import unittest

from radio_catalog_coverage_gate import coverage_report, dart_uuid_set

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
C = "33333333-3333-4333-8333-333333333333"


def source(allowed=(A, B), rejected=(C,)):
    return (
        "class RadioBrowserAdmission {\n"
        " static const Set<String> allowedStationIds = <String>{\n"
        + "\n".join("  '" + x + "'," for x in allowed)
        + "\n };\n"
        " static const Set<String> editoriallyRejectedStationIds = <String>{\n"
        + "\n".join("  '" + x + "'," for x in rejected)
        + "\n };\n }\n"
    )


def station(goid, *uuids):
    return {"go_station_id": goid, "legacy_aliases": list(uuids)}


class CoverageGateTest(unittest.TestCase):
    def test_missing_allowed_uuid_blocks_publication(self):
        document = {"stations": [station("go-station-000001", A)], "tombstones": []}
        before = copy.deepcopy(document)
        result = coverage_report(source(), document)
        self.assertFalse(result["coverage_gate_passed"])
        self.assertEqual(result["missing_admissible_uuids"], [B])
        self.assertFalse(result["ready_to_publish"])
        self.assertEqual(document, before)

    def test_historical_alias_in_tombstone_meets_identity_coverage(self):
        document = {"stations": [station("go-station-000001", A)],
                    "tombstones": [station("go-station-000002", B, C)]}
        historical = {"aliases": [
            {"legacy_id": A, "go_station_id": "go-station-000001"},
            {"legacy_id": B, "go_station_id": "go-station-000002"},
            {"legacy_id": C, "go_station_id": "go-station-000002"}
        ]}
        result = coverage_report(source(), document, historical)
        self.assertTrue(result["coverage_gate_passed"])
        self.assertFalse(result["ready_to_publish"])

    def test_rejected_station_is_not_forced_active_but_historical_kept(self):
        raw = source(allowed=(A, C), rejected=(C,))
        document = {"stations": [station("go-station-000001", A)], "tombstones": []}
        result = coverage_report(raw, document)
        self.assertEqual(result["admission_admissible_count"], 1)
        self.assertTrue(result["coverage_gate_passed"])
        hist = {"aliases": [{"legacy_id": C, "go_station_id": "go-station-000002"}]}
        self.assertFalse(coverage_report(raw, document, hist)["coverage_gate_passed"])

    def test_lost_historical_favorite_id_blocks_even_if_not_allowed(self):
        doc = {"stations": [station("go-station-000001", A, B)], "tombstones": []}
        historical = {"aliases": [
            {"legacy_id": A, "go_station_id": "go-station-000001"},
            {"legacy_id": B, "go_station_id": "go-station-000001"},
            {"legacy_id": C, "go_station_id": "go-station-000001"}]}
        result = coverage_report(source(), doc, historical)
        self.assertEqual(result["missing_historical_aliases"], [C])
        self.assertFalse(result["coverage_gate_passed"])

    def test_collision_detected_across_tombstones(self):
        doc = {"stations": [station("go-station-000001", A, B)],
               "tombstones": [station("go-station-000002", B)]}
        result = coverage_report(source(), doc)
        self.assertFalse(result["coverage_gate_passed"])
        self.assertEqual(result["alias_collisions"], [B])

    def test_missing_dart_declarations_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "missing Dart UUID set"):
            dart_uuid_set("class RadioBrowserAdmission {}", "allowedStationIds")

    def test_comments_are_not_parsed_as_ids(self):
        text = source(allowed=(A,), rejected=())
        text = text.replace("'" + A + "',", "'" + A + "',\n // '" + B + "'\n")
        self.assertEqual(dart_uuid_set(text, "allowedStationIds"), {A})


if __name__ == "__main__":
    unittest.main()
