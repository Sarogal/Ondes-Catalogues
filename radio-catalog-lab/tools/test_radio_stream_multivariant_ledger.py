"""No-network opt-in tests: independent stream histories for one radio UUID."""
import copy
import unittest

from radio_stream_recheck_ledger import next_evidence_report

UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SHA_A = "a" * 64
SHA_B = "b" * 64


def report(day, *, sha=SHA_A, verdict="audio_sample_ok"):
    return {
        "schemaVersion": 1, "observationDate": day,
        "publicationAllowed": False,
        "checks": [{
            "stationuuid": UID, "streamSha256": sha,
            "verdict": verdict, "publicationAllowed": False,
        }],
    }


def each(report):
    return {x["streamSha256"]: x for x in report["records"]}


class MultiVariantEvidenceTests(unittest.TestCase):
    def test_first_stream_remains_after_other_variant_is_observed(self):
        first = next_evidence_report(
            report("2026-11-20"), retain_stream_variants=True)
        second = next_evidence_report(
            report("2026-11-21", sha=SHA_B), first,
            retain_stream_variants=True)
        self.assertEqual(len(second["records"]), 2)
        self.assertEqual(each(second)[SHA_A]["audioEvidenceDates"], ["2026-11-20"])
        self.assertEqual(each(second)[SHA_B]["audioEvidenceDates"], ["2026-11-21"])
        self.assertEqual(second["streamHistoryMode"], "per_stream")
        self.assertFalse(second["publicationAllowed"])

    def test_revisiting_first_variant_after_alternation_preserves_two_days(self):
        first = next_evidence_report(
            report("2026-11-20"), retain_stream_variants=True)
        second = next_evidence_report(
            report("2026-11-21", sha=SHA_B), first,
            retain_stream_variants=True)
        third = next_evidence_report(
            report("2026-11-22"), second, retain_stream_variants=True)
        self.assertEqual(each(third)[SHA_A]["audioEvidenceDates"],
                         ["2026-11-20", "2026-11-22"])
        self.assertTrue(each(third)[SHA_A]["repeatAudioSample"])
        self.assertFalse(each(third)[SHA_B]["repeatAudioSample"])
        self.assertEqual(third["technicallyQualifiedCount"], 0)

    def test_legacy_one_stream_report_migrates_without_losing_its_dates(self):
        first = next_evidence_report(report("2026-11-20"))
        self.assertEqual(first["streamHistoryMode"], "legacy_uuid")
        second = next_evidence_report(
            report("2026-11-21", sha=SHA_B), first,
            retain_stream_variants=True)
        self.assertEqual(len(second["records"]), 2)
        self.assertEqual(each(second)[SHA_A]["audioEvidenceDates"], ["2026-11-20"])

    def test_old_unmarked_ledger_migrates_too(self):
        first = next_evidence_report(report("2026-11-20"))
        first.pop("streamHistoryMode")
        second = next_evidence_report(
            report("2026-11-21", sha=SHA_B), first,
            retain_stream_variants=True)
        self.assertEqual(len(second["records"]), 2)

    def test_downgrade_to_legacy_mode_is_blocked(self):
        first = next_evidence_report(
            report("2026-11-20"), retain_stream_variants=True)
        with self.assertRaisesRegex(ValueError, "downgrade"):
            next_evidence_report(report("2026-11-21", sha=SHA_B), first)

    def test_duplicate_uuid_and_sha_history_is_invalid(self):
        first = next_evidence_report(
            report("2026-11-20"), retain_stream_variants=True)
        bad = copy.deepcopy(first)
        bad["records"].append(copy.deepcopy(bad["records"][0]))
        with self.assertRaisesRegex(ValueError, "repeated"):
            next_evidence_report(report("2026-11-21"), bad,
                                 retain_stream_variants=True)

    def test_disjoint_streams_never_inherit_other_audio_proof(self):
        first = next_evidence_report(
            report("2026-11-20"), retain_stream_variants=True)
        second = next_evidence_report(
            report("2026-11-21", sha=SHA_B, verdict="audio_mime_only"), first,
            retain_stream_variants=True)
        self.assertEqual(each(second)[SHA_B]["audioEvidenceDates"], [])
        self.assertEqual(each(second)[SHA_A]["audioEvidenceDates"], ["2026-11-20"])
        self.assertEqual(second["repeatAudioCandidateCount"], 0)

    def test_same_day_sequential_batches_can_update_distinct_uuids(self):
        other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        first = next_evidence_report(
            report("2026-11-20"), retain_stream_variants=True)
        subsequent = report("2026-11-20", sha=SHA_B)
        subsequent["checks"][0]["stationuuid"] = other
        second = next_evidence_report(
            subsequent, first, retain_stream_variants=True)
        self.assertEqual(len(second["records"]), 2)
        self.assertTrue(all(not r["technicalQualified"] for r in second["records"]))

    def test_cannot_supply_two_variants_same_uuid_in_one_five_probe_batch(self):
        invalid = report("2026-11-20")
        invalid["checks"].append(dict(invalid["checks"][0], streamSha256=SHA_B))
        with self.assertRaisesRegex(ValueError, "Duplicate probe UUID"):
            next_evidence_report(invalid, retain_stream_variants=True)


if __name__ == "__main__":
    unittest.main()
