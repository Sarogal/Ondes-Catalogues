import unittest
from radio_daily_qualification_dossiers import build_dossiers, safe_digest

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DAY = "2026-11-25"
BASELINE = "a" * 64
STREAM = "https://radio.example.org/live?token=secret"


def inputs():
    preview = {"schemaVersion": 1, "scanDate": DAY, "publicationAllowed": False}
    return (
        {**preview, "candidates": [{"stationuuid": A, "countrycode": "FR", "tags": "metal",
          "homepage": "https://radio.example.org/?secret=yes", "streamUrl": STREAM}]},
        {"schemaVersion": 1, "scanDate": DAY, "automaticAdmissionAllowed": False,
         "catalogChanged": False, "candidates": [{"stationuuid": A, "classification": "unmapped_candidate"}]},
        {**preview, "automaticallyApprovedCount": 0, "records": [{"stationuuid": A, "name": "Radio X",
          "firstSeen": DAY, "lastSeen": DAY, "seenDays": 1, "editorialSignal": "target_genre_indication"}]},
        {"schemaVersion": 1, "observationDate": DAY, "publicationAllowed": False, "technicallyQualifiedCount": 0,
         "records": [{"stationuuid": A, "streamSha256": safe_digest(STREAM), "lastVerdict": "audio_sample_ok",
                      "audioEvidenceDates": [DAY], "liveFrameEvidenceDates": [DAY], "lastObservedDate": DAY,
                      "technicalQualified": False, "publicationAllowed": False}]},
        {**preview, "approvedLogoCount": 0, "records": []},
    )


class DossierTests(unittest.TestCase):
    def test_join_no_approval_no_raw_urls(self):
        report = build_dossiers(*inputs(), BASELINE)
        row = report["records"][0]
        self.assertEqual(row["status"], "awaiting_evidence")
        self.assertTrue(row["streamEvidenceMatchesCurrentSource"])
        self.assertIn("independent_editorial_programme_evidence_required", row["reviewReasons"])
        self.assertIn("repeat_live_frame_evidence_on_distinct_days", row["reviewReasons"])
        self.assertEqual(row["nextReviewDate"], "2026-11-26")
        self.assertEqual(row["lastSourceObservation"]["reportedHomepageHost"], "radio.example.org")
        self.assertNotIn("secret", str(report))
        self.assertEqual(report["approvedCount"], 0)

    def test_absent_candidate_retains_source_observation(self):
        first = build_dossiers(*inputs(), BASELINE)
        d, r, h, s, l = inputs()
        d["candidates"] = []
        r["candidates"] = []
        for x in (d, r, h, l):
            x["scanDate"] = "2026-11-26"
        s["observationDate"] = "2026-11-26"
        row = build_dossiers(d, r, h, s, l, BASELINE, first)["records"][0]
        self.assertFalse(row["observedInScan"])
        self.assertEqual(row["lastSourceObservation"]["date"], DAY)
        self.assertTrue(row["streamEvidenceMatchesCurrentSource"])
        self.assertIn("source_not_in_current_scan", row["reviewReasons"])

    def test_changed_stream_needs_new_probe(self):
        d, r, h, s, l = inputs()
        d["candidates"][0]["streamUrl"] = "https://radio.example.org/new"
        row = build_dossiers(d, r, h, s, l, BASELINE)["records"][0]
        self.assertFalse(row["streamEvidenceMatchesCurrentSource"])
        self.assertIn("probe_current_stream_fingerprint", row["reviewReasons"])

    def test_known_and_duplicate_are_not_admitted(self):
        for cls, expected in (("already_mapped", "already_known"),
                              ("possible_variant_or_duplicate", "identity_review")):
            d, r, h, s, l = inputs()
            r["candidates"][0]["classification"] = cls
            row = build_dossiers(d, r, h, s, l, BASELINE)["records"][0]
            self.assertEqual(row["status"], expected)
            self.assertFalse(row["approved"])

    def test_invalid_approval_or_date_rejected(self):
        d, r, h, s, l = inputs()
        s["records"][0]["technicalQualified"] = True
        with self.assertRaises(ValueError):
            build_dossiers(d, r, h, s, l, BASELINE)
        d, r, h, s, l = inputs()
        l["scanDate"] = "2026-11-24"
        with self.assertRaises(ValueError):
            build_dossiers(d, r, h, s, l, BASELINE)


if __name__ == "__main__":
    unittest.main()
