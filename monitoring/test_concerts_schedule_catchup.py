import datetime as dt
import unittest
from concerts_schedule_catchup import trusted, trusted_scheduled_cron, should_wake, REPO, SOURCE

NOW=dt.datetime(2026,11,18,12,tzinfo=dt.timezone.utc)

def upstream(**kw):
    item={"repository":{"full_name":REPO},"workflow_run":{
        "name":SOURCE,"event":"schedule","status":"completed",
        "conclusion":"success","head_branch":"main",
        "head_repository":{"full_name":REPO}}}
    item["workflow_run"].update(kw)
    return item

def intake(hours, status="completed", conclusion="success", **kw):
    item={"head_branch":"main","event":"schedule","status":status,
          "conclusion":conclusion,
          "created_at":(NOW-dt.timedelta(hours=hours)).isoformat()}
    item.update(kw)
    return item

class ScheduleCatchupTests(unittest.TestCase):
    def test_publisher_must_be_trusted_main_schedule(self):
        self.assertTrue(trusted(upstream()))
        for override in ({"event":"workflow_run"},{"event":"pull_request"},
                         {"conclusion":"failure"},{"head_branch":"feature"},
                         {"head_repository":{"full_name":"attacker/repo"}},
                         {"name":"unrelated"}):
            with self.subTest(override=override):
                self.assertFalse(trusted(upstream(**override)))
        self.assertFalse(trusted({"repository":{"full_name":REPO}}))
        altered=upstream()
        altered["repository"]["full_name"]="attacker/repo"
        self.assertFalse(trusted(altered))

    def test_only_main_schedule_can_trigger_second_wakeup(self):
        self.assertTrue(trusted_scheduled_cron(REPO, "refs/heads/main"))
        self.assertFalse(trusted_scheduled_cron(REPO, "refs/heads/feature"))
        self.assertFalse(trusted_scheduled_cron("attacker/repo", "refs/heads/main"))
        self.assertFalse(trusted_scheduled_cron(REPO, "refs/pull/373/merge"))

    def test_no_duplicate_and_missed_schedule(self):
        self.assertEqual(should_wake([intake(4)],NOW)[0],False)
        self.assertEqual(should_wake([intake(6.9)],NOW)[0],False)
        self.assertEqual(should_wake([intake(7)],NOW)[0],True)
        self.assertEqual(should_wake([],NOW)[0],True)

    def test_rate_limit_after_failure_or_pending(self):
        self.assertFalse(should_wake([intake(1,conclusion="failure")],NOW)[0])
        self.assertTrue(should_wake([intake(1.5,conclusion="failure")],NOW)[0])
        self.assertFalse(should_wake([intake(2,status="in_progress")],NOW)[0])
        self.assertTrue(should_wake([intake(7,status="in_progress")],NOW)[0])

    def test_recent_latest_and_untrusted_runs(self):
        a=intake(10)
        b=intake(1,status="queued")
        self.assertFalse(should_wake([a,b],NOW)[0])
        self.assertFalse(should_wake([b,a],NOW)[0])
        self.assertTrue(should_wake([intake(1,event="pull_request")],NOW)[0])
        self.assertFalse(should_wake([intake(-1)],NOW)[0])
        with self.assertRaises(ValueError):
            should_wake(["bad"],NOW)

if __name__=="__main__":
    unittest.main()
