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


def framed_row(uid=A, sha=SHA1):
    value = sustained_row(uid, sha)
    value["continuityEvidence"]["frameEvidence"] = {
        "state": "frame_chain", "codec": "mpeg_audio", "frameCount": 3,
        "sampleBytes": 32768, "publicationAllowed": False,
    }
    return value


def decoded_row(uid=A, sha=SHA1):
    check = framed_row(uid, sha)
    check['continuityEvidence']['decodeEvidence'] = {
        'state': 'decoded_pcm', 'demuxer': 'mp3', 'pcmBytes': 4096,
        'inputBytes': 32768, 'publicationAllowed': False,
    }
    return check

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


    def test_sustained_transport_two_days_never_certifies(self):
        first = next_evidence_report(probe(checks=[sustained_row()]))
        second = next_evidence_report(probe("2026-11-21", [sustained_row()]), first)
        self.assertEqual(second["repeatSustainedTransportCount"], 1)
        self.assertTrue(second["records"][0]["repeatSustainedTransport"])
        self.assertFalse(second["records"][0]["technicalQualified"])
        self.assertFalse(second["publicationAllowed"])

    def test_header_only_yesterday_not_backfilled_as_sustained(self):
        first = next_evidence_report(probe(checks=[row()]))
        second = next_evidence_report(probe("2026-11-21", [sustained_row()]), first)
        self.assertEqual(second["repeatSustainedTransportCount"], 0)
        self.assertEqual(second["records"][0]["sustainedTransportDates"], ["2026-11-21"])

    def test_forged_extended_evidence_is_rejected(self):
        bad_mime = sustained_row(verdict="audio_mime_only")
        bad_duration = sustained_row()
        bad_duration["continuityEvidence"]["elapsedMs"] = 100
        bad_permission = sustained_row()
        bad_permission["continuityEvidence"]["publicationAllowed"] = True
        for check in (bad_mime, bad_duration, bad_permission):
            with self.subTest(check=check), self.assertRaises(ValueError):
                next_evidence_report(probe(checks=[check]))

    def test_changed_stream_resets_continuity_evidence(self):
        first = next_evidence_report(probe(checks=[sustained_row()]))
        second = next_evidence_report(probe("2026-11-21", [sustained_row(sha=SHA2)]), first)
        self.assertEqual(second["records"][0]["sustainedTransportDates"], ["2026-11-21"])
        self.assertFalse(second["records"][0]["repeatSustainedTransport"])

    def test_missing_continuity_today_does_not_falsely_repeat(self):
        first = next_evidence_report(probe(checks=[sustained_row()]))
        second = next_evidence_report(probe("2026-11-21", [sustained_row()]), first)
        third = next_evidence_report(probe("2026-11-22", [row()]), second)
        self.assertEqual(len(third["records"][0]["sustainedTransportDates"]), 2)
        self.assertFalse(third["records"][0]["repeatSustainedTransport"])

    def test_thirty_sample_window_retains_consistent_continuity_dates(self):
        import datetime as dt
        prior = None
        for i in range(35):
            day = (dt.date(2026, 10, 1) + dt.timedelta(days=i)).isoformat()
            check = sustained_row() if i < 3 else row()
            prior = next_evidence_report(probe(day, [check]), prior)
        evidence = prior["records"][0]
        self.assertEqual(len(evidence["audioEvidenceDates"]), 30)
        self.assertTrue(set(evidence["sustainedTransportDates"]).issubset(
            evidence["audioEvidenceDates"]))

    def test_frame_chain_recurs_on_distinct_dates_without_certification(self):
        first = next_evidence_report(probe(checks=[framed_row()]))
        second = next_evidence_report(probe('2026-11-21', [framed_row()]), first)
        self.assertEqual(second['repeatFrameChainCount'], 1)
        self.assertEqual(second['records'][0]['frameChainDates'], ['2026-11-20', '2026-11-21'])
        self.assertFalse(second['records'][0]['technicalQualified'])
        self.assertFalse(second['publicationAllowed'])

    def test_transport_only_history_cannot_become_frame_history(self):
        first = next_evidence_report(probe(checks=[sustained_row()]))
        second = next_evidence_report(probe('2026-11-21', [framed_row()]), first)
        self.assertEqual(second['repeatSustainedTransportCount'], 1)
        self.assertEqual(second['repeatFrameChainCount'], 0)

    def test_frame_evidence_rejects_invalid_or_claimed_publication(self):
        for key, value in (('codec', 'unknown'), ('frameCount', 2),
                           ('sampleBytes', 90000), ('publicationAllowed', True)):
            bad = framed_row()
            bad['continuityEvidence']['frameEvidence'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                next_evidence_report(probe(checks=[bad]))

    def test_frame_evidence_resets_on_stream_change(self):
        first = next_evidence_report(probe(checks=[framed_row()]))
        second = next_evidence_report(probe('2026-11-21', [framed_row(sha=SHA2)]), first)
        self.assertEqual(second['records'][0]['frameChainDates'], ['2026-11-21'])
        self.assertFalse(second['records'][0]['repeatFrameChain'])

    def test_no_retroactive_frame_approval_during_mime_only_recheck(self):
        first = next_evidence_report(probe(checks=[framed_row()]))
        second = next_evidence_report(probe('2026-11-21', [framed_row()]), first)
        third = next_evidence_report(probe('2026-11-22', [row(verdict='audio_mime_only')]), second)
        self.assertFalse(third['records'][0]['repeatFrameChain'])
        self.assertEqual(len(third['records'][0]['frameChainDates']), 2)
        self.assertEqual(third['technicallyQualifiedCount'], 0)

    def test_previous_report_cannot_forge_frame_dates_outside_transport(self):
        first = next_evidence_report(probe(checks=[framed_row()]))
        bad = copy.deepcopy(first)
        bad['records'][0]['frameChainDates'] = ['2026-11-19']
        with self.assertRaises(ValueError):
            next_evidence_report(probe('2026-11-21', []), bad)

    def test_real_pcm_success_two_dates_is_not_automatic_admission(self):
        first = next_evidence_report(probe(checks=[decoded_row()]))
        second = next_evidence_report(probe('2026-11-21', [decoded_row()]), first)
        self.assertEqual(second['repeatDecodedPcmCount'], 1)
        self.assertEqual(second['records'][0]['decodedPcmDates'], ['2026-11-20','2026-11-21'])
        self.assertFalse(second['records'][0]['technicalQualified'])
        self.assertFalse(second['publicationAllowed'])

    def test_legacy_frames_cannot_be_reinterpreted_as_pcm(self):
        first = next_evidence_report(probe(checks=[framed_row()]))
        second = next_evidence_report(probe('2026-11-21', [decoded_row()]), first)
        self.assertEqual(second['repeatFrameChainCount'], 1)
        self.assertEqual(second['repeatDecodedPcmCount'], 0)

    def test_pcm_proof_rejects_fake_bytes_and_publication(self):
        for key, value in (('pcmBytes', 10), ('inputBytes', 999999),
                           ('publicationAllowed', True), ('state','impossible')):
            bad = decoded_row()
            bad['continuityEvidence']['decodeEvidence'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                next_evidence_report(probe(checks=[bad]))

    def test_pcm_proof_requires_transport_and_audio_verdict(self):
        false_audio = decoded_row()
        false_audio['verdict'] = 'audio_mime_only'
        bad_continuity = decoded_row()
        bad_continuity['continuityEvidence']['state'] = 'not_confirmed'
        for item in (false_audio, bad_continuity):
            with self.assertRaises(ValueError):
                next_evidence_report(probe(checks=[item]))

    def test_changed_stream_resets_decoded_pcm_history(self):
        first = next_evidence_report(probe(checks=[decoded_row()]))
        second = next_evidence_report(probe('2026-11-21', [decoded_row(sha=SHA2)]), first)
        self.assertEqual(second['records'][0]['decodedPcmDates'], ['2026-11-21'])
        self.assertFalse(second['records'][0]['repeatDecodedPcm'])

    def test_missing_new_decode_preserves_old_history_without_current_claim(self):
        first = next_evidence_report(probe(checks=[decoded_row()]))
        second = next_evidence_report(probe('2026-11-21', [decoded_row()]), first)
        third = next_evidence_report(probe('2026-11-22', [framed_row()]), second)
        self.assertEqual(len(third['records'][0]['decodedPcmDates']), 2)
        self.assertFalse(third['records'][0]['repeatDecodedPcm'])

    def test_prior_pcm_days_cannot_precede_sustained_evidence(self):
        first = next_evidence_report(probe(checks=[decoded_row()]))
        bad = copy.deepcopy(first)
        bad['records'][0]['decodedPcmDates'] = ['2026-11-19']
        with self.assertRaises(ValueError):
            next_evidence_report(probe('2026-11-21', []), bad)

if __name__ == "__main__":
    unittest.main()
