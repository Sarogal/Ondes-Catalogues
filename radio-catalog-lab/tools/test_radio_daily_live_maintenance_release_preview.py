import unittest
from unittest.mock import patch
from types import SimpleNamespace

from radio_daily_live_maintenance_release_preview import preview_status, preview_merge, positive
from radio_daily_live_evidence import LiveEvidence
from radio_daily_v9_generator import digest
import test_radio_daily_status_release_validation as status_fixture
import test_radio_daily_merge_release_validation as merge_fixture
from test_radio_daily_repair_plan import DAY


class LiveMaintenanceReleaseTests(unittest.TestCase):
    def status(self, quarantined=False):
        f = status_fixture.IndependentStatusGateTests()
        f.fixture(quarantined=quarantined, approved=False)
        return f

    def status_preview(self, f):
        return preview_status(f.pointer, f.raw, anchor=f.anchor, day=DAY, **f.evidence)

    @patch("radio_daily_live_evidence.PinnedHttpTransport.request", return_value=SimpleNamespace(status=410))
    def test_explicit_gone_reaches_quarantine_gate(self, request):
        f = self.status()
        r = self.status_preview(f)
        self.assertEqual(r["candidateSha256"], digest(f.candidate))
        self.assertEqual(r["outcome"], "strict_gate_validated")
        self.assertGreater(r["networkCalls"], 0)

    @patch("radio_daily_live_evidence.PinnedHttpTransport.request", return_value=SimpleNamespace(status=503))
    def test_temporary_server_failure_does_not_quarantine(self, request):
        r = self.status_preview(self.status())
        self.assertEqual(r["outcome"], "live_evidence_deferred")
        self.assertIsNone(r["candidateSha256"])

    @patch("radio_daily_live_evidence.PinnedHttpTransport.request", side_effect=OSError("network down"))
    def test_network_failure_does_not_quarantine(self, request):
        r = self.status_preview(self.status())
        self.assertEqual(r["outcome"], "live_evidence_deferred")
        self.assertIsNone(r["candidateSha256"])

    @patch("radio_daily_live_maintenance_release_preview.positive", return_value=True)
    def test_recovery_revalidated(self, probe):
        f = self.status(quarantined=True)
        self.assertEqual(self.status_preview(f)["candidateSha256"], digest(f.candidate))
        probe.assert_called()

    @patch("radio_daily_live_maintenance_release_preview.positive", return_value=False)
    def test_stale_recovery_is_held(self, probe):
        self.assertEqual(self.status_preview(self.status(True))["outcome"], "live_evidence_deferred")

    @patch("radio_daily_live_maintenance_release_preview.positive", return_value=True)
    @patch("radio_daily_live_maintenance_release_preview.confirm_page", return_value=("confirmed", None, None))
    def test_merge_requires_official_binding_and_live_shared_stream(self, page, probe):
        f = merge_fixture.IndependentMergeGateTests()
        f.fixture(approved=False)
        r = preview_merge(f.pointer, f.raw, anchor=f.anchor, day=DAY, **f.evidence)
        self.assertEqual(r["candidateSha256"], digest(f.candidate))
        page.assert_called()
        probe.assert_called()

    @patch("radio_daily_live_maintenance_release_preview.positive")
    @patch("radio_daily_live_maintenance_release_preview.confirm_page", return_value=(None, None, None))
    def test_unlinked_merge_held_before_audio(self, page, probe):
        f = merge_fixture.IndependentMergeGateTests()
        f.fixture(approved=False)
        r = preview_merge(f.pointer, f.raw, anchor=f.anchor, day=DAY, **f.evidence)
        self.assertEqual(r["outcome"], "live_evidence_deferred")
        probe.assert_not_called()

    @patch("radio_daily_live_evidence.probe_url", return_value={"streamSha256": "wrong"})
    def test_positive_refuses_wrong_endpoint(self, probe):
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            positive(LiveEvidence(), "https://radio.example.org/live", "expected")

    @patch("radio_daily_live_evidence.observe_hls", return_value={"verdict": "advancing_hls_manifest_only"})
    @patch("radio_daily_live_evidence.probe_url", return_value={"streamSha256": "expected", "verdict": "playlist_pending"})
    def test_manifest_without_audio_is_not_positive(self, probe, hls):
        self.assertFalse(positive(LiveEvidence(), "https://radio.example.org/live", "expected"))

    @patch("radio_daily_live_evidence.PinnedHttpTransport.request")
    def test_one_unavailable_station_does_not_block_other(self, request):
        import json
        f = status_fixture.IndependentStatusGateTests()
        f.fixture(count=2, approved=False)
        request.side_effect = [SimpleNamespace(status=503), SimpleNamespace(status=410)]
        operations = {}
        result = preview_status(f.pointer, f.raw, anchor=f.anchor, day=DAY,
            operations=operations, **f.evidence)
        self.assertEqual(result["selectedCount"], 1)
        self.assertEqual(len(result["deferred"]), 1)
        new = json.loads(operations["status"]["candidate"])
        self.assertEqual(sum(s["status"]["state"]=="quarantined" for s in new["stations"]), 1)
        self.assertEqual(request.call_count, 2)

    def test_status_fresh_check_repeated_at_signer(self):
        from radio_daily_status_release_validation import validate_status_release
        f = self.status()
        selected = [f.evidence["status"]["proposals"][0]["goStationId"]]
        with self.assertRaisesRegex(ValueError, "fresh denied"):
            validate_status_release(f.pointer, f.raw, f.candidate, anchor=f.anchor, day=DAY,
                selected=selected, fresh_check=lambda p: self.fail_fresh(), **f.evidence)

    def fail_fresh(self):
        raise ValueError("fresh denied")

    def test_merge_fresh_check_repeated_at_signer(self):
        from radio_daily_merge_release_validation import validate_merge_release
        from radio_daily_baseline_verify import strict_json
        f = merge_fixture.IndependentMergeGateTests()
        f.fixture(approved=False)
        old = strict_json(f.raw)
        new = strict_json(f.candidate)
        selected = [s["go_station_id"] for s in old["stations"] if s not in new["stations"]]
        with self.assertRaisesRegex(ValueError, "fresh denied"):
            validate_merge_release(f.pointer, f.raw, f.candidate, anchor=f.anchor, day=DAY,
                selected=selected, fresh_check=lambda p:self.fail_fresh(), **f.evidence)

    def test_merge_subset_unknown_refused(self):
        from radio_daily_merge_release_validation import validate_merge_release
        f = merge_fixture.IndependentMergeGateTests()
        f.fixture(approved=False)
        with self.assertRaisesRegex(ValueError,"invalid selected"):
            validate_merge_release(f.pointer, f.raw, f.candidate, anchor=f.anchor, day=DAY,
                selected=["unknown"], **f.evidence)
