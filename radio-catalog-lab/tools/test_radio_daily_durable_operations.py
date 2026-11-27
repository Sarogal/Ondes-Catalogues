"""End-to-end strict admission and repair, with entirely synthetic evidence."""
import json
import secrets
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_radio_daily_admission_release_validation as admission
import test_radio_daily_repair_release_validation as repair
from test_radio_daily_baseline_selection import signed
from radio_daily_admission_release_validation import qualify_admission
from radio_daily_repair_release_validation import qualify_repair
from radio_daily_combined_release_validation import compose, publish_combined
from radio_daily_durable_lab_signer import DurableLabSigner
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_git_lab_transport import LocalGitLabTransport, REF, ZERO
from radio_daily_git_lab_transfer import transmit
from radio_daily_git_lab_reader import prepare_from_git
from radio_daily_deployment_verify import verify_deployment, PublicResponse, ROOT, POINTER_URL
from radio_daily_maintenance_preview import build as maintenance_build
from radio_daily_repair_preview import build as repair_build
from radio_daily_repair_confirmation import build as confirm_build
from radio_daily_repair_plan import plan
from radio_daily_status_preview import build as status_build
from radio_daily_logo_maintenance import build as logo_build
from radio_daily_missing_logo import build as missing_build
from radio_daily_v9_generator import digest, encode


class DurableOperationChainTests(unittest.TestCase):
    def exercise(self, doc, evidence, kind, *, day):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            password = secrets.token_bytes(32)
            key_file = root/"key.pem"
            signer = DurableLabSigner.create(key_file, password)
            key = dict(public_key=signer.public_key, key_id=signer.key_id)
            pin = dict(expected_public_key=signer.public_key, expected_key_id=signer.key_id)
            prior, raw = signed(doc, signer._key, signer.key_id)
            sha = digest(raw)
            anchor = dict(expected_sha=sha, expected_sequence=8, **key)
            if kind == "admission":
                evidence["dossiers"]["catalogBaselineSha256"] = sha
                candidate = qualify_admission(prior, raw, anchor=anchor, day=day, **evidence)
                m = maintenance_build(raw, day, expected=sha)
                d = evidence["discovery"]
                r = repair_build(raw, m, d, expected=sha)
                c = confirm_build(raw, r, expected=sha)
            else:
                candidate = qualify_repair(prior, raw, anchor=anchor, day=day, **evidence)
                m, r, c = (evidence[k] for k in ("maintenance", "repair", "confirmation"))
            rp = plan(raw, m, r, c, expected=sha)
            state = dict(maintenance=m, repair=r, confirmation=c,
                status=status_build(raw, m, rp, expected=sha),
                logo=logo_build(raw, day, expected=sha),
                missing=missing_build(raw, day, expected=sha))
            operations = {kind: dict(candidate=candidate, evidence=evidence)}
            combined = compose(prior, raw, anchor=anchor, day=day,
                               operations=operations, objects={})
            self.assertEqual(combined, candidate)
            db = root/"lab.sqlite"
            store = DurableLabStore.initialize(db, prior, raw, **key)
            def repo(name):
                path = root/name
                subprocess.run(["git", "init", "--bare", "--object-format=sha1", str(path)],
                               check=True, capture_output=True)
                return LocalGitLabTransport(path)
            source, receiver = repo("source.git"), repo("receiver.git")
            def transfer(seq, content_sha, lease):
                head = source.publish(store, expected_head=lease,
                    expected_sequence=seq, expected_sha=content_sha)["commit"]
                return transmit(source, receiver, store, expected_commit=head,
                    expected_remote_head=lease, expected_sequence=seq,
                    expected_sha=content_sha)["commit"]
            base = transfer(8, sha, ZERO)
            pub = dict(expected_sha=sha, expected_sequence=8,
                expected_candidate_sha=digest(combined), day=day,
                operations=operations, objects={})
            def interrupt(phase):
                if phase == "after_pointer_swap":
                    raise RuntimeError("synthetic interruption")
            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                publish_combined(store, signer, prior, raw, combined, checkpoint=interrupt, **pub)
            store = DurableLabStore(db, **key)
            signer = DurableLabSigner.reopen(key_file, password, **pin)
            result = publish_combined(store, signer, prior, raw, combined, **pub)
            self.assertTrue(result["resumed"])
            self.assertFalse(result["publicationAllowed"])
            new_sha = digest(combined)
            head = transfer(9, new_sha, base)
            def fetch(url, limit):
                path = "pointer.json" if url == POINTER_URL else "releases/"+new_sha+".json"
                self.assertIn(url, (POINTER_URL, ROOT+path))
                data = receiver._git("show", head+":"+path)
                self.assertLessEqual(len(data), limit)
                return PublicResponse(200, url, "application/json", data)
            read_args = dict(expected_commit=head, bootstrap_sha=sha, **anchor)
            report = verify_deployment(receiver, deployment_commit=head,
                deployment_status="success", fetch=fetch, **read_args)
            self.assertEqual(report["selectedSha256"], new_sha)
            self.assertTrue(report["deploymentVerified"])
            selected, _, migrated, context = prepare_from_git(receiver, day=day,
                                                               state=state, **read_args)
            self.assertEqual(selected, combined)
            self.assertEqual(context["selectedSequence"], 9)
            self.assertEqual(context["stateMode"], "migrated")
            self.assertTrue(migrated)
            for report in migrated.values():
                self.assertEqual(report["catalogBaselineSha256"], new_sha)
            self.assertEqual(receiver._git("rev-list", "--count", REF), b"2\n")
            return json.loads(selected), context

    def test_admission_without_logo_survives_full_chain(self):
        f = admission.StrictAdmissionTests()
        f.setUp()
        doc = json.loads(f.raw)
        # The generator's synthetic quarantine has no playable variant.
        # Use the existing one-station maintenance fixture and retain its redirect.
        doc["stations"] = doc["stations"][:1]
        evidence = {k:v for k,v in f.args.items() if k not in ("anchor","day")}
        result, context = self.exercise(doc, evidence, "admission", day=admission.DAY)
        self.assertEqual(result["stations"][:-1], doc["stations"])
        self.assertEqual(result["tombstones"], doc["tombstones"])
        new = result["stations"][-1]
        self.assertEqual(new["legacy_aliases"], [admission.A])
        self.assertEqual(new["streams"][0]["state"], "verified")
        self.assertIsNone(new["logo"])
        self.assertIn("qualification-dossiers.json", context["qualificationReportsToRebuild"])

    def test_legacy_repair_preserves_original_stream_and_identity(self):
        f = repair.StrictRepairGateTests()
        f.prepare(approved=False)
        doc = json.loads(f.raw)
        evidence = {k:v for k,v in f.args.items() if k not in ("anchor","day")}
        result, context = self.exercise(doc, evidence, "repair", day=repair.DAY)
        row = result["stations"][0]
        self.assertEqual(row["streams"][-1]["url"], repair.NEW)
        self.assertEqual(row["streams"][-1]["state"], "verified")
        row["streams"].pop()
        self.assertEqual(row, doc["stations"][0])
        self.assertEqual(context["migration"]["repairHistoriesRetained"], 0)
