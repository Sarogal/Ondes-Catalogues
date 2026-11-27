import copy
import unittest
from radio_daily_release_context import prepare,STATE_FILES,MIGRATED_FILES
from radio_daily_v9_generator import digest
from test_radio_daily_baseline_selection import setup as selection_setup,signed
from test_radio_daily_state_migration import repair_setup
from test_radio_daily_repair_plan import DAY

def setup():
    _,_,key,_,_,_,_,anchor=selection_setup()
    old,new,state=repair_setup()
    p,a=signed(old,key)
    q,b=signed(new,key)
    anchor["expected_sha"]=digest(a)
    return p,a,q,b,state,anchor

class ReleaseContextTests(unittest.TestCase):
    def test_current_keeps_state_without_rewriting(self):
        p,a,q,b,state,anchor=setup()
        before=copy.deepcopy(state)
        raw,selected,migrated,ctx=prepare(p,lambda path,length:a,day=DAY,state=state,**anchor)
        self.assertEqual(raw,a)
        self.assertFalse(selected["advanced"])
        self.assertEqual(migrated,{})
        self.assertEqual(ctx["stateReportsChecked"],6)
        self.assertEqual(ctx["stateMode"],"unchanged")
        self.assertEqual(state,before)

    def test_successor_migrates_all_reports_and_requalifies(self):
        p,a,q,b,state,anchor=setup()
        before=copy.deepcopy(state)
        raw,selected,migrated,ctx=prepare(q,lambda path,length:b,day=DAY,state=state,
             prior_pointer=p,prior_body=a,**anchor)
        self.assertEqual(raw,b)
        self.assertTrue(selected["advanced"])
        self.assertEqual(set(migrated),set(MIGRATED_FILES.values()))
        self.assertTrue(all(r["catalogBaselineSha256"]==digest(b) for r in migrated.values()))
        self.assertEqual(migrated["repair-plan-preview.json"]["proposalCount"],1)
        self.assertEqual(ctx["stateMode"],"migrated")
        self.assertIn("qualification-dossiers.json",ctx["qualificationReportsToRebuild"])
        self.assertEqual(state,before)
        self.assertFalse(ctx["publicationAllowed"])

    def test_incomplete_state_blocks_advancement(self):
        p,a,q,b,state,anchor=setup()
        state.pop("repair")
        with self.assertRaisesRegex(ValueError,"complete predecessor evidence"):
            prepare(q,lambda path,length:b,day=DAY,state=state,prior_pointer=p,prior_body=a,**anchor)

    def test_mixed_baseline_rejected_even_without_advancement(self):
        p,a,q,b,state,anchor=setup()
        state["maintenance"]["catalogBaselineSha256"]="a"*64
        with self.assertRaisesRegex(ValueError,"incompatible release context"):
            prepare(p,lambda path,length:a,day=DAY,state=state,**anchor)

    def test_bootstrap_no_state(self):
        p,a,q,b,state,anchor=setup()
        _,_,migrated,ctx=prepare(p,lambda path,length:a,day=DAY,**anchor)
        self.assertEqual(migrated,{})
        self.assertEqual(ctx["stateReportsChecked"],0)

if __name__=="__main__":
    unittest.main()
