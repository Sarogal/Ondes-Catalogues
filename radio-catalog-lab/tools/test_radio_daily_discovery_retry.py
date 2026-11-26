import datetime as dt
import unittest
from radio_daily_discovery import discover, DiscoveryQueryUnavailable
from radio_daily_discovery_retry import load, failed, due, report, MAX_RETRIES
from test_radio_daily_discovery import station, ID_A, ID_B

DAY=dt.date(2026,11,26)
NEXT=DAY+dt.timedelta(days=1)


class RetryTests(unittest.TestCase):
    def scan(self, fetch, day=DAY, prior=None, tags=("metal","punk"), size=2):
        return discover(fetch=fetch,tags=list(tags),names=[],day=day,page_size=size,
                        max_pages=1,known_ids=set(),retry_state=prior)

    def test_failed_page_retried_even_outside_daily_rotation(self):
        def first(field,term,offset,size):
            if term=="punk":
                raise DiscoveryQueryUnavailable("down")
            return [station(ID_A)]
        a=self.scan(first)
        self.assertEqual(a["pendingRetryCount"],1)
        calls=[]
        def next_fetch(*k):
            calls.append(k)
            return [station(ID_B,name="Punk Radio",tags="punk")] if k[1]=="punk" else [station(ID_A)]
        b=self.scan(next_fetch,day=NEXT,prior=a["retryState"],tags=("metal",),size=100)
        self.assertIn(("tag","punk",0,2),calls)
        self.assertEqual(b["pendingRetryCount"],0)
        self.assertEqual({r["stationuuid"] for r in b["candidates"]},{ID_A,ID_B})

    def test_same_page_not_requested_twice(self):
        def first(f,t,o,s):
            if t=="punk":
                raise DiscoveryQueryUnavailable("down")
            return []
        a=self.scan(first)
        calls=[]
        b=self.scan(lambda *k: calls.append(k) or [],day=NEXT,prior=a["retryState"])
        self.assertEqual(calls.count(("tag","punk",0,2)),1)
        self.assertEqual(b["pendingRetryCount"],0)

    def test_backoff_is_bounded_and_same_day_does_not_increment(self):
        p={}
        k=("tag","metal",0,100)
        failed(p,k,DAY)
        failed(p,k,DAY)
        self.assertEqual(p[k]["attemptCount"],1)
        failed(p,k,NEXT)
        self.assertEqual(p[k]["nextAttemptDate"],(NEXT+dt.timedelta(days=2)).isoformat())
        self.assertFalse(due(p,NEXT,set()))
        self.assertEqual(load(report(p,NEXT),NEXT),p)

    def test_retry_budget_independent_and_bounded(self):
        p={}
        for i in range(8):
            failed(p,("tag","metal "+str(i),0,100),DAY)
        self.assertEqual(len(due(p,NEXT,set())),MAX_RETRIES)

    def test_invalid_prior_is_refused(self):
        p={}
        failed(p,("tag","metal",0,100),DAY)
        state=report(p,DAY)
        state["pending"][0]["term"]="https://invalid.example"
        with self.assertRaises(ValueError):
            load(state,NEXT)

    def test_all_unavailable_still_fails_closed(self):
        def fail(*a):
            raise DiscoveryQueryUnavailable("down")
        with self.assertRaisesRegex(DiscoveryQueryUnavailable,"all discovery pages"):
            self.scan(fail)
