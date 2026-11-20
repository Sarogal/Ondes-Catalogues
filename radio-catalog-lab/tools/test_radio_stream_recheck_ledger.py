"""No-network multi-day technical evidence tests."""
import copy
import unittest
from radio_stream_recheck_ledger import next_evidence_report

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SHA1 = "a" * 64
SHA2 = "b" * 64


def probe(day="2026-11-20", checks=None):
    return {"schemaVersion": 1, "observationDate": day,
            "publicationAllowed": False, "checks": checks if checks is not None else []}


def row(uid=A, verdict="audio_sample_ok", sha=SHA1):
    return {"stationuuid": uid, "streamSha256": sha,
            "publicationAllowed": False, "verdict": verdict}



def sustained_row(uid=A, sha=SHA1, verdict="audio_sample_ok"):
    value = row(uid, verdict, sha)
    value["continuityEvidence"] = {
        "state": "transport_sustained",
        "elapsedMs": 6400,
        "observedBytes": 65536,
        "readChunks": 12,
        "publicationAllowed": False,
    }
    return value


class StreamRecheckTests(unittest.TestCase):
    def test_first_positive_sample_is_not_qualified(self):
        report = next_evidence_report(probe(checks=[row()]))
        self.assertEqual(report["technicallyQualifiedCount"], 0)
        self.assertFalse(report["records"][0]["repeatAudioSample"])
        self.assertEqual(report["records"][0]["audioEvidenceDates"], ["2026-11-20"])
        self.assertFalse(report["publicationAllowed"])

    def test_second_day_same_stream_only_signals_recheck_candidate(self):
        previous = next_evidence_report(probe(checks=[row()]))
        now = next_evidence_report(probe("2026-11-21", [row()]), previous)
        self.assertTrue(now["records"][0]["repeatAudioSample"])
        self.assertFalse(now["records"][0]["technicalQualified"])
        self.assertFalse(now["publicationAllowed"])
        self.assertEqual(now["repeatAudioCandidateCount"], 1)

    def test_repeat_same_day_is_not_two_days(self):
        first = next_evidence_report(probe(checks=[row()]))
        now = next_evidence_report(probe(checks=[row()]), first)
        self.assertEqual(now["records"][0]["audioEvidenceDates"], ["2026-11-20"])

    def test_stream_change_resets_sample_evidence(self):
        first = next_evidence_report(probe(checks=[row()]))
        now = next_evidence_report(probe("2026-11-21", [row(sha=SHA2)]), first)
        self.assertEqual(now["records"][0]["streamSha256"], SHA2)
        self.assertEqual(now["records"][0]["audioEvidenceDates"], ["2026-11-21"])
        self.assertFalse(now["records"][0]["repeatAudioSample"])

    def test_failed_recheck_never_removes_station(self):
        first = next_evidence_report(probe(checks=[row()]))
        now = next_evidence_report(probe("2026-11-21",
                                         [row(verdict="needs_review")]), first)
        self.assertEqual(len(now["records"]), 1)
        self.assertEqual(now["records"][0]["audioEvidenceDates"], ["2026-11-20"])
        self.assertFalse(now["records"][0]["repeatAudioSample"])

    def test_missing_today_keeps_old_evidence_without_claiming_current(self):
        first = next_evidence_report(probe(checks=[row()]))
        now = next_evidence_report(probe("2026-11-21"), first)
        self.assertEqual(now["notObservedTodayCount"], 1)
        self.assertEqual(now["records"][0]["lastObservedDate"], "2026-11-20")
        self.assertFalse(now["records"][0]["repeatAudioSample"])

    def test_untrusted_probe_with_publication_flag_rejected(self):
        bad = probe(checks=[row()])
        bad["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            next_evidence_report(bad)

    def test_embedded_approval_in_check_rejected(self):
        bad = row()
        bad["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            next_evidence_report(probe(checks=[bad]))

    def test_duplicate_uuid_and_over_budget_rejected(self):
        with self.assertRaises(ValueError):
            next_evidence_report(probe(checks=[row(), row()]))
        with self.assertRaises(ValueError):
            next_evidence_report(probe(checks=[row(uid=str(i).zfill(8) + "-0000-4000-8000-000000000000")
                                                  for i in range(6)]))

    def test_malformed_hash_refused(self):
        with self.assertRaises(ValueError):
            next_evidence_report(probe(checks=[row(sha="not-sha256")]))

    def test_out_of_order_old_dates_fail(self):
        first = next_evidence_report(probe(checks=[row()]))
        bad = copy.deepcopy(first)
        bad["records"][0]["audioEvidenceDates"] = ["2026-11-22"]
        with self.assertRaises(ValueError):
            next_evidence_report(probe("2026-11-21"), bad)

    def test_webm_mp4_or_ogg_container_without_codec_never_counts(self):
        first = next_evidence_report(probe(checks=[row()]))
        later = next_evidence_report(
            probe("2026-11-21", [row(verdict="container_pending")]), first)
        self.assertFalse(later["records"][0]["repeatAudioSample"])
        self.assertEqual(later["records"][0]["audioEvidenceDates"], ["2026-11-20"])
        self.assertEqual(later["technicallyQualifiedCount"], 0)

    def test_multi_radio_evidence_independent(self):
        first = next_evidence_report(probe(checks=[row(A), row(B)]))
        now = next_evidence_report(probe("2026-11-21",
                                         [row(A), row(B, verdict="playlist_pending")]),
                                   first)
        self.assertEqual(now["repeatAudioCandidateCount"], 1)
        self.assertTrue(next(x for x in now["records"]
                             if x["stationuuid"] == A)["repeatAudioSample"])
        self.assertFalse(next(x for x in now["records"]
                              if x["stationuuid"] == B)["repeatAudioSample"])


if __name__ == "__main__":
    unittest.main()
