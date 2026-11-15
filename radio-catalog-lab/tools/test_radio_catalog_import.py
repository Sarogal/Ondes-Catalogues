"""Import legacy vers GO v1 : aucun réseau, aucun changement des données d'origine."""
import copy
import unittest

from radio_catalog_bootstrap_import_v1 import import_legacy
from radio_catalog_guard import validate_catalog


def old_station(uid, name="Station test", variants=None):
    return {
        "id": uid, "name": name, "countryCode": "FR", "genre": "Heavy",
        "homepage": "https://radio.example.org",
        "streamUrl": "https://radio.example.org/live-" + uid + ".mp3",
        "codec": "MP3", "bitrate": 128,
        "logoUrl": "https://radio.example.org/logo.png",
        "streamVariants": variants or [],
    }


class SafeLegacyImportTest(unittest.TestCase):
    AS_OF = "2026-11-15T09:00:00Z"

    def test_assign_id_and_aliases_but_no_auto_approval(self):
        source = {"stations": [old_station("uuid-b", variants=[
            {"stationId": "uuid-b-variant", "streamUrl": "http://radio.example.org/alternative",
             "codec": "AAC", "bitrate": 64}
        ]), old_station("uuid-a")]}
        original = copy.deepcopy(source)
        result, report = import_legacy(source, as_of=self.AS_OF)
        self.assertEqual(source, original)
        self.assertEqual(report["catalog_total_stations"], 2)
        self.assertEqual(report["unique_historical_aliases"], 3)
        self.assertEqual([x["go_station_id"] for x in result["stations"]],
                         ["go-station-000001", "go-station-000002"])
        self.assertEqual(result["stations"][1]["legacy_aliases"], ["uuid-b", "uuid-b-variant"])
        self.assertIsNone(result["stations"][1]["logo"])
        self.assertIsNone(result["stations"][1]["editorial"]["reviewed_at"])
        self.assertEqual(result["stations"][1]["streams"][1]["protocol"], "http")
        self.assertEqual(result["stations"][1]["streams"][0]["state"], "candidate")
        self.assertEqual(validate_catalog(result, mode="staging"), [])
        self.assertFalse(report["publish_ready"])
        self.assertTrue(any("not approved" in e for e in
                            validate_catalog(result, mode="publish")))

    def test_existing_identity_and_editorial_data_immutable(self):
        source = {"stations": [old_station("uuid-b")]}
        old, _ = import_legacy(source, as_of=self.AS_OF)
        old["stations"][0]["editorial"]["admission_state"] = "approved"
        old["stations"][0]["editorial"]["reviewed_at"] = self.AS_OF
        old["stations"][0]["streams"][0]["state"] = "verified"
        future = copy.deepcopy(source)
        future["stations"][0]["streamUrl"] = "https://radio.example.org/new-b.mp3"
        future["stations"].append(old_station("uuid-c"))
        new, summary = import_legacy(future, as_of=self.AS_OF, previous=old)
        self.assertEqual(new["stations"][0], old["stations"][0])
        self.assertEqual(new["stations"][1]["go_station_id"], "go-station-000002")
        self.assertEqual(summary["unchanged_existing_stations"], 1)
        self.assertEqual(summary["new_unreviewed_stations"], 1)

    def test_alias_collisions_refused(self):
        source = {"stations": [old_station("uuid-a"), old_station("uuid-a")]}
        with self.assertRaisesRegex(ValueError, "duplicate alias"):
            import_legacy(source, as_of=self.AS_OF)

    def test_unsafe_stream_refused(self):
        bad = old_station("uuid-a")
        bad["streamUrl"] = "http://127.0.0.1/private"
        with self.assertRaisesRegex(ValueError, "unsafe stream"):
            import_legacy({"stations": [bad]}, as_of=self.AS_OF)


if __name__ == "__main__":
    unittest.main()
