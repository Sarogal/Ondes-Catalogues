"""Generic Black Lab source-wide published-watch regression tests."""
import datetime as dt
import unittest

import published_watch as watch
from test_blacklab_adapter import DETAIL

URL="https://theblacklab.fr/agenda/houle-can-bardd-galibot/"
EVENT={
    "id":"go-c-20270305-wasquehal-houle",
    "title":"Houle + Cân Bardd + Galibot",
    "date":"2027-03-05",
    "time":None,
    "artistIds":["houle","can-bardd","galibot"],
    "venueId":"the-black-lab-wasquehal",
    "officialUrl":URL,
}
ARTISTS={"houle":"Houle","can-bardd":"Cân Bardd","galibot":"Galibot"}


def page(title="HOULE + CÂN BARDD + GALIBOT",
         date="vendredi 5 mars 2027", status=""):
    return DETAIL.format(title=title,date=date,
        organizer="THE BLACK LAB",
        description=title+" - black metal. "+status)


class BlackLabGenericWatchTests(unittest.TestCase):
    def test_any_first_party_blacklab_url_but_never_aggregator_or_query(self):
        self.assertEqual(watch.source_kind(EVENT),"blacklab")
        self.assertIsNone(watch.source_kind({**EVENT,"officialUrl":URL+"?aff=spam"}))
        self.assertIsNone(watch.source_kind({**EVENT,"officialUrl":
            "https://example.org/agenda/houle-can-bardd-galibot/"}))
        self.assertIsNone(watch.source_kind({**EVENT,"officialUrl":
            "https://theblacklab.fr/agenda/"}))

    def test_official_date_and_all_named_artists_match_read_only(self):
        original=dict(EVENT)
        response=watch.inspect(EVENT,page(),ARTISTS)
        self.assertEqual(response["status"],"matched")
        self.assertEqual(response["observedDate"],"2027-03-05")
        self.assertEqual(EVENT,original)

    def test_first_party_changes_generate_anomalies_not_publication(self):
        self.assertEqual(watch.inspect(EVENT,page(date="samedi 6 mars 2027"),
                                       ARTISTS)["status"],"date_review")
        self.assertEqual(watch.inspect(
            EVENT,page(title="HOULE + GALIBOT"),ARTISTS)["status"],
                         "lineup_review")
        self.assertEqual(watch.inspect(
            EVENT,page(status="Ce concert est annulé."),ARTISTS)["status"],
                         "content_review")

    def test_unsupported_and_unverifiable_never_count_as_cancellation(self):
        self.assertEqual(watch.inspect(
            EVENT,"<html><body>site indisponible</body></html>",
            ARTISTS)["status"],"unverifiable")
        changed=page(title="HOULE + GALIBOT")
        response=watch.inspect(EVENT,changed,ARTISTS)
        self.assertNotIn("cancel",response["status"])


if __name__=="__main__":
    unittest.main()
