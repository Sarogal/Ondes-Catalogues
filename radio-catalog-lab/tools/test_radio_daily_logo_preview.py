import unittest
from radio_daily_logo_preview import review, source_class, digest

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DAY = "2026-11-25"


def inputs():
    rows = [{"stationuuid": uid, "homepage": "https://radio.example.org",
             "favicon": "https://radio.example.org/logo.png",
             "streamUrl": "https://radio.example.org/live",
             "editorialSignal": "target_genre_indication"} for uid in (A, B)]
    return ({"schemaVersion": 1, "publicationAllowed": False, "scanDate": DAY,
             "candidates": rows},
            {"schemaVersion": 1, "automaticAdmissionAllowed": False,
             "catalogChanged": False, "scanDate": DAY,
             "candidates": [{"stationuuid": uid, "classification": "unmapped_candidate"} for uid in (A, B)]},
            {"schemaVersion": 1, "publicationAllowed": False,
             "technicallyQualifiedCount": 0, "observationDate": DAY,
             "records": [{"stationuuid": uid, "lastVerdict": "audio_sample_ok",
                          "streamSha256": digest(rows[0]["streamUrl"]),
                          "liveFrameEvidenceDates": [DAY]} for uid in (A, B)]})


class LogoPreviewTests(unittest.TestCase):
    def test_strict_source_selection(self):
        for image, expected in (
            ("https://radio.example.org/a.png", "same_reported_host"),
            ("https://www.radio.example.org/a.png", "same_reported_host"),
            ("https://other.example.org/a.png", "external_image_host_review"),
            ("https://radio.example.org/a.png?token=private", "query_source_review"),
            ("http://radio.example.org/a.png", "unsafe_or_unsupported_source"),
            ("https://127.0.0.1/a.png", "unsafe_or_unsupported_source"),
            ("https://radcap.ru/a.png", "unsafe_or_unsupported_source"),
            ("", "missing_source"),
        ):
            self.assertEqual(source_class("https://radio.example.org", image)[0], expected)

    def test_offline_default_no_fetch(self):
        result = review(*inputs(), fetch=lambda *a: self.fail("network"))
        self.assertEqual(result["candidateCount"], 2)
        self.assertEqual(result["attemptedSourceCount"], 0)

    def test_shared_image_one_fetch_never_approves_identity(self):
        calls = []
        def fetch(url, host):
            calls.append((url, host))
            return b"fake", "image/png"
        result = review(*inputs(), limit=1, fetch=fetch,
                        decode=lambda b: ("image/png", 128, 128))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["decodedCandidateCount"], 2)
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["approvedLogoCount"], 0)
        self.assertNotIn("radio.example.org", str(result))

    def test_mismatched_stream_and_existing_station_not_probed(self):
        d, r, s = inputs()
        r["candidates"][0]["classification"] = "already_mapped"
        d["candidates"][1]["streamUrl"] += "changed"
        result = review(d, r, s, limit=8, fetch=lambda *a: self.fail("network"))
        self.assertEqual(result["candidateCount"], 1)
        self.assertEqual(result["attemptedSourceCount"], 0)

    def test_mime_mismatch_never_decoded(self):
        result = review(*inputs(), limit=1, fetch=lambda *a: (b"fake", "image/png"),
                        decode=lambda b: ("image/jpeg", 128, 128))
        self.assertEqual(result["decodedCandidateCount"], 0)

    def test_invalid_inputs_fail_closed(self):
        d, r, s = inputs()
        r["automaticAdmissionAllowed"] = True
        with self.assertRaises(ValueError):
            review(d, r, s)
        with self.assertRaises(ValueError):
            review(*inputs(), limit=9)


if __name__ == "__main__":
    unittest.main()
