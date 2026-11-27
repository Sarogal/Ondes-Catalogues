"""Exercise exact production-shaped successor history helpers using synthetic evidence.

No network, real key, published station or production state is modified.
"""
import os
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from test_radio_daily_lab_multiversion import MultiversionCycleTests, DAY3
from test_radio_daily_logo_plan import DAY
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_git_lab_transport import LocalGitLabTransport, snapshot, ZERO, REF
from radio_daily_git_lab_reader import verify_snapshot_entries
from radio_daily_github_transfer_contract import prepare, DESTINATION
from radio_daily_combined_release_validation import publish_combined
from radio_daily_v9_generator import digest
from radio_lab_first_release import stage_deterministic, write_bundle, read_bundle
from radio_lab_successor_sign import restore_history


class SuccessorHistoryContract(unittest.TestCase):
    def test_restore_v9_sign_v10_and_stage_exact_parent(self):
        fixture=MultiversionCycleTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        p9,a9,state,v10,operations=fixture.second()
        f=fixture.f
        key=dict(public_key=f.signer.public_key,key_id=f.signer.key_id)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store=DurableLabStore.initialize(root/"first.sqlite",f.pointer,f.raw,**key)
            publish_combined(store,f.signer,f.pointer,f.raw,fixture.v9,
                expected_sha=digest(f.raw),expected_sequence=8,
                expected_candidate_sha=digest(fixture.v9),day=DAY,
                operations=f.operations,objects=f.objects)
            files9=snapshot(store,9)
            write_bundle(root/"bundle9",files9)
            with patch.dict(os.environ,{"RADIO_LAB_PUBLIC_KEY":key["public_key"],
                                      "RADIO_LAB_KEY_ID":key["key_id"]}):
                restored=restore_history(read_bundle(root/"bundle9"),root/"restored.sqlite",9)
                self.assertEqual(snapshot(restored,9),files9)
                self.assertEqual(restored.current(),p9)
                bare=root/"git"
                subprocess.run(["git","init","--bare","--object-format=sha1",str(bare)],
                    check=True,capture_output=True)
                transport=LocalGitLabTransport(bare)
                root8=stage_deterministic(transport,restored,8,ZERO)
                head9=stage_deterministic(transport,restored,9,root8)
                publish_combined(restored,f.signer,p9,fixture.v9,v10,
                    expected_sha=a9["expected_sha"],expected_sequence=9,
                    expected_candidate_sha=digest(v10),day=DAY3,
                    operations=operations,objects={})
                files10=snapshot(restored,10)
                write_bundle(root/"bundle10",files10)
                recovered=restore_history(read_bundle(root/"bundle10"),root/"successor.sqlite",10)
                self.assertEqual(snapshot(recovered,10),files10)
                self.assertEqual(snapshot(recovered,9),files9)
                head10=stage_deterministic(transport,recovered,10,head9)
                plan=prepare(transport,recovered,destination=DESTINATION,ref=REF,
                    expected_commit=head10,expected_remote_head=head9,
                    expected_sequence=10,expected_sha=digest(v10))
                self.assertEqual(plan.commit,head10)
                transport._verify_tree(head9,files9)
                accepted=verify_snapshot_entries({p:len(b) for p,b in files10.items()},
                    files10.__getitem__,transport.head,expected_commit=head10,
                    bootstrap_sha=digest(f.raw),**a9)
                self.assertEqual(accepted["sequence"],10)
                self.assertEqual(accepted["anchor_pointer"],p9)
                self.assertEqual(accepted["body"],v10)
                self.assertEqual(transport._git("rev-list","--count",REF),b"3\n")


if __name__=="__main__":
    unittest.main()
