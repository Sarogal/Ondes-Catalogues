import unittest
from unittest.mock import Mock
from radio_daily_proposal_subset import isolate, select_proposals, AdmissionGateHeld
from radio_daily_live_evidence import LiveEvidence, EvidenceDeferred
from radio_daily_v9_generator import digest
from test_radio_daily_decision_preview import A, DAY
from test_radio_daily_repair_plan import SID
import test_radio_daily_admission_release_validation as admission
import test_radio_daily_repair_release_validation as repair


class SubsetTests(unittest.TestCase):
    def test_full_input_conflict_is_not_removed(self):
        f=admission.StrictAdmissionTests()
        f.setUp()
        self.assertEqual(f.qualify(selected=[A]), f.qualify())
        with self.assertRaisesRegex(ValueError,"invalid selected"):
            f.qualify(selected=["unknown"])

    def test_repair_subset_is_revalidated_at_signing(self):
        f=repair.StrictRepairGateTests()
        f.prepare(approved=False)
        body=f.qualify(selected=[SID])
        self.assertEqual(body,f.qualify())
        f.args["selected"]=[SID]
        self.assertEqual(f.publish_current(body)["release_sequence"],9)
        with self.assertRaisesRegex(ValueError,"invalid selected"):
            f.qualify(selected=["unknown"])

    def test_duplicate_selection_refused(self):
        with self.assertRaisesRegex(ValueError,"invalid selected"):
            select_proposals([{"id":"a"}],"id",["a","a"],4)

    def run_isolate(self, bad, exception=ValueError, maximum=4):
        proposed=[{"id":"a"},{"id":"b"},{"id":"c"}]
        def qualify(p,r,**kw):
            if bad in kw["selected"]:
                raise exception("held")
            return ",".join(kw["selected"]).encode()
        def validate(p,r,body,**kw):
            return digest(qualify(p,r,**kw))
        return isolate(b"p",b"r",anchor={},day=DAY,proposed=proposed,key="id",
            qualify=qualify,validate=validate,evidence={"complete":"report"},
            live=LiveEvidence(),maximum=maximum)

    def test_bad_candidate_does_not_block_others(self):
        report,material=self.run_isolate("b")
        self.assertEqual(report["selectedCount"],2)
        self.assertEqual(material["candidate"],b"a,c")
        self.assertEqual(material["evidence"]["selected"],["a","c"])
        self.assertEqual(material["evidence"]["complete"],"report")
        self.assertEqual(report["deferred"],[dict(id="b",reason="strict_gate_held")])

    def test_transient_failure_does_not_block_others(self):
        report,material=self.run_isolate("b",EvidenceDeferred)
        self.assertEqual(material["candidate"],b"a,c")
        self.assertEqual(report["deferred"],[dict(id="b",reason="live_evidence_deferred")])

    def test_admission_gate_reports_fixed_code_without_exception_text(self):
        report,material=self.run_isolate("b",lambda message: AdmissionGateHeld(
            "directory_identity","private https://example.org/source"))
        self.assertEqual(material["candidate"],b"a,c")
        self.assertEqual(report["deferred"],[dict(id="b",reason="strict_gate_held",
                                                  detail="directory_identity")])
        self.assertNotIn("https://",str(report))

    def test_actual_admission_refusal_has_stable_code(self):
        f=admission.StrictAdmissionTests()
        f.setUp()
        with self.assertRaises(AdmissionGateHeld) as exc:
            f.qualify(continuity=lambda u:dict(verdict="finite_response_review"))
        self.assertEqual(exc.exception.code,"direct_continuity")

    def test_unknown_gate_code_refused(self):
        with self.assertRaisesRegex(ValueError,"unknown admission gate code"):
            AdmissionGateHeld("https://example.org/private","message")

    def test_budget_is_bounded(self):
        report,material=self.run_isolate(None,maximum=1)
        self.assertEqual(report["selectedCount"],1)
        self.assertEqual(len(report["deferred"]),2)
        self.assertTrue(all(r["reason"]=="family_attempt_budget" for r in report["deferred"]))
