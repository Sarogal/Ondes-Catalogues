"""Offline safety tests for official Secret Place Wix calendar crosscheck."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_place_official as s

PAGE = """
<div role="gridcell" aria-label="14 novembre, samedi. 1 événement, sélectionnez pour en voir plus">
  <div>14</div><div>19:00</div>
  <div><a href="/event-details/moscow-death-brigade-1">MOSCOW DEATH BRIGADE</a></div>
</div>
<div role="gridcell" aria-label="20 novembre, vendredi. 1 événement, sélectionnez pour en voir plus">
  <div>20</div><div>19:00</div>
  <div><a href="/event-details/blind-test">BLIND TEST SECRET PLACE</a></div>
</div>
<div role="gridcell" aria-label="11 novembre, mercredi. 2 événements, sélectionnez pour en voir plus">
 <div>11</div><div>19:00</div><a href="/event-details/ambiguous">Band + Guest</a>
</div>"""


def registry():
    return {"items":{
        "a":{"candidate":{"candidateId":"third:moscow","venue":"Secret Place",
                          "name":"Moscow Death Brigade - Saint Jean de Védas",
                          "date":"2026-11-14","source":"third_party_calendar_lead"}},
        "b":{"candidate":{"candidateId":"third:bad-date","venue":"Secret Place",
                          "name":"Moscow Death Brigade","date":"2026-11-15"}}
    }}


class SecretPlaceTests(unittest.TestCase):
    def test_read_only_calendar_matches_day_month_no_year(self):
        rows=s.parse_calendar(PAGE)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["day"],14)
        self.assertEqual(rows[0]["month"],11)
        self.assertFalse(rows[0]["yearConfirmed"])
        self.assertFalse(rows[0]["publicationAllowed"])
        self.assertEqual(rows[0]["sourceUrl"],
                         "https://www.toutafond.com/event-details/moscow-death-brigade-1")
        matches=s.crosscheck(rows,registry())
        self.assertEqual(matches[0]["corroboratingCandidateIds"],["third:moscow"])

    def test_no_third_party_is_never_an_approval(self):
        rows=s.parse_calendar(PAGE)
        out=s.crosscheck(rows,{"items":{}})
        self.assertEqual(out[0]["status"],"official_calendar_lead")
        self.assertFalse(out[0]["publicationAllowed"])
        self.assertFalse(out[0]["yearConfirmed"])

    def test_many_events_one_day_are_held(self):
        self.assertNotIn("Band + Guest",str(s.parse_calendar(PAGE)))

    def test_unknown_year_does_not_invent_date(self):
        row=s.parse_calendar(PAGE)[0]
        self.assertNotIn("date",row)

    def test_wrong_host_is_not_an_official_event_link(self):
        page=PAGE.replace("/event-details/moscow-death-brigade-1",
            "https://attacker.example/event-details/moscow-death-brigade-1")
        rows=s.parse_calendar(page)
        self.assertEqual(rows[0]["sourceUrl"],s.OFFICIAL)
        self.assertFalse(rows[0]["detailUrlConfirmed"])

    def test_unknown_date_and_location_do_not_match(self):
        data=registry()
        data["items"]["a"]["candidate"]["venue"]="Le Dodu"
        data["items"]["b"]["candidate"]["date"]="bad"
        result=s.crosscheck(s.parse_calendar(PAGE),data)
        self.assertEqual(result[0]["corroboratingCandidateIds"],[])


if __name__=="__main__":
    unittest.main()
