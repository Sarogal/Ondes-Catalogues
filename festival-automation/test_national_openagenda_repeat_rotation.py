"""Same-day OpenAgenda rotation is fair even after the first full pass."""
import unittest
from unittest.mock import patch
from national_openagenda_linked_primary_preflight import examine, STATE_KEY

DAY = "2026-11-26"
SOURCES = [{
    "url": "https://openagenda.com/test/events/festival-%s" % i,
    "dossier_id": "national-%08d" % i,
    "title": "Festival fictif %02d 2027" % i,
    "year": 2027, "municipality": None,
    "priority_date_hint": "2027-01-%02d" % (i+1),
} for i in range(13)]


class RotationTests(unittest.TestCase):
    def cycle(self, state):
        with patch("national_openagenda_linked_primary_preflight.eligible",
                   return_value=SOURCES), patch(
                    "national_openagenda_linked_primary_preflight.validated_openagenda_leads",
                    return_value=[]):
            report = examine(state, {}, {}, DAY,
                             event_fetch=lambda _: "<h1>Unrelated page</h1>")
        self.assertLessEqual(report["checked_count"], 4)
        self.assertEqual(report["publications"], 0)
        return [row["event_ref_review_only"] for row in report["rows"]]

    def test_fair_rotation_including_legacy_same_day_observations(self):
        state = {"schema": "grossesondes.source-watch.v1",
                 STATE_KEY: {s["url"]: {"lastChecked": DAY} for s in SOURCES}}
        checked = []
        for _ in range(7):
            checked.extend(self.cycle(state))
        for offset in (0, 13):
            self.assertEqual(len(set(checked[offset:offset+13])), 13)
        self.assertEqual(len(state[STATE_KEY]), 13)
        self.assertTrue(all("lastResultStatus" in row
                            for row in state[STATE_KEY].values()))

    def test_rate_limit_does_not_stop_rotation_or_repeat_network_requests(self):
        from dns_pinned_https import OfficialHTTPStatusError
        state = {"schema": "grossesondes.source-watch.v1"}
        leads = [{"source_url": source["url"], "professional_source_hints_review_only": {
            "location_name": None, "originagenda_title": None, "verified": False,
            "links": [{"field": "registration",
                       "url": "https://billetterie.fr/events/festival-%s" % i}]}}
                 for i, source in enumerate(SOURCES)]
        calls = []
        def limited(url):
            calls.append(url)
            raise OfficialHTTPStatusError(429)
        with patch("national_openagenda_linked_primary_preflight.eligible",
                   return_value=SOURCES), patch(
                    "national_openagenda_linked_primary_preflight.validated_openagenda_leads",
                    return_value=leads):
            report = examine(state, {}, {}, DAY,
                             event_fetch=lambda _: "<h1>Unrelated page</h1>",
                             organizer_fetch=limited)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["checked_count"], 4)
        self.assertEqual(report["publications"], 0)
        self.assertEqual([x["lastCheckedSequence"] for x in state[STATE_KEY].values()],
                         [1, 2, 3, 4])
        self.assertTrue(all(x["lastProfessionalStatus"] == "PROFESSIONAL_RATE_LIMITED"
                            for x in state[STATE_KEY].values()))

    def test_unchecked_first_and_sequence_does_not_grant_proof(self):
        state = {"schema": "grossesondes.source-watch.v1",
                 STATE_KEY: {s["url"]: {"lastChecked": DAY,
                                       "lastCheckedSequence": 100+i}
                             for i, s in enumerate(SOURCES[:10])}}
        checked = self.cycle(state)
        self.assertEqual(checked[:3], [s["url"] for s in SOURCES[10:]])
        self.assertEqual(checked[3], SOURCES[0]["url"])
        self.assertTrue(all("digest" not in row for row in state[STATE_KEY].values()))

if __name__ == "__main__":
    unittest.main()
