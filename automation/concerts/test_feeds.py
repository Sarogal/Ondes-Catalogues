import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import feeds

ROOM={"name":"La Salle","city":"Montpellier","department":"34"}
BASE="https://example.org/agenda/"

class FeedTests(unittest.TestCase):
    def test_ics_link_resolution_and_cross_domain(self):
        page='<link type="application/rss+xml" href="/rss.xml"><a href="/agenda.ics">cal</a><a href="https://evil.example/event.ics">ignore</a>'
        links=feeds.feed_links(page,BASE,lambda a,b: a.startswith("https://example.org/"))
        self.assertEqual(links["ics"],["https://example.org/agenda.ics"])
        self.assertEqual(links["rss"],["https://example.org/rss.xml"])

    def test_ics_dates_et_annulations(self):
        body=("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:test-1\r\nSUMMARY:Groupe Metal + Guest\r\n"
              "DTSTART;TZID=Europe/Paris:20270206T200000\r\nLOCATION:La Salle\r\nEND:VEVENT\r\n"
              "BEGIN:VEVENT\r\nUID:test-2\r\nSUMMARY:Annulé\r\nDTSTART;VALUE=DATE:20270207\r\n"
              "STATUS:CANCELLED\r\nEND:VEVENT\r\nEND:VCALENDAR")
        r=feeds.ics_candidates(body,ROOM,BASE,"2026-11-01")
        self.assertEqual(len(r),2)
        self.assertEqual(r[0]["date"],"2027-02-06")
        self.assertFalse(r[0]["publicationAllowed"])
        self.assertEqual(r[1]["source"],"ics_cancellation_notice")
        self.assertTrue(r[1]["leadOnly"])
        self.assertFalse(r[1]["publicationAllowed"])

    def test_ics_annulation_dans_titre_et_atelier(self):
        body=("BEGIN:VEVENT\nSUMMARY:HEAVY LUNGS - ANNULÉ\nDTSTART:20270206T200000\nEND:VEVENT\n"
              "BEGIN:VEVENT\nSUMMARY:Atelier photographie\nDTSTART:20270207T200000\nEND:VEVENT")
        candidates=feeds.ics_candidates(body,ROOM,BASE,"2026-11-01")
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]["source"],"ics_cancellation_notice")
        self.assertTrue(candidates[0]["cancellationNotice"])

    def test_ics_continuation(self):
        self.assertEqual(feeds.unfold_ics("SUMMARY:Groupe Me\r\n tal\n"),["SUMMARY:Groupe Metal",""])

    def test_recurring_event_waits(self):
        body="BEGIN:VEVENT\nSUMMARY:Repetition\nDTSTART:20270206T200000\nRRULE:FREQ=WEEKLY\nEND:VEVENT"
        self.assertEqual(feeds.ics_candidates(body,ROOM,BASE,"2026-11-01"),[])

    def test_rss_no_event_date(self):
        body='<rss><channel><item><title>Nouvelle tournée métal</title><link>https://example.org/news</link><pubDate>Sun, 1 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>'
        r=feeds.rss_candidates(body,ROOM,BASE)
        self.assertEqual(len(r),1)
        self.assertIsNone(r[0]["date"])
        self.assertTrue(r[0]["leadOnly"])
        self.assertTrue(r[0]["reviewRequired"])
        self.assertFalse(r[0]["publicationAllowed"])

    def test_ics_invalid_date(self):
        body="BEGIN:VEVENT\nSUMMARY:Concert\nDTSTART:20279999T200000\nEND:VEVENT"
        self.assertEqual(feeds.ics_candidates(body,ROOM,BASE,"2026-11-01"),[])


    def test_wordpress_comment_feed_is_not_a_concert_news_source(self):
        page = ('<link type="application/rss+xml" href="/feed/"/>'
                '<link type="application/rss+xml" href="/comments/feed/"/>')
        urls=feeds.feed_links(page,"https://lasourisverte-epinal.fr/",
                              lambda a,b:a.startswith("https://lasourisverte-epinal.fr/"))
        self.assertEqual(urls["rss"],["https://lasourisverte-epinal.fr/feed/"])
        comments = ("<rss><channel><item><title>Commentaires sur UNE TOURNÉE MÉTAL "
                    "par cheap pharmacy spam</title>"
                    "<link>https://lasourisverte-epinal.fr/news/#comment-52097</link>"
                    "</item></channel></rss>")
        self.assertEqual(feeds.rss_candidates(comments,ROOM,
                         "https://lasourisverte-epinal.fr/comments/feed/"),[])
        self.assertEqual(feeds.rss_candidates(comments,ROOM,
                         "https://lasourisverte-epinal.fr/feed/"),[])

    def test_rss_comment_spam_does_not_block_legitimate_news(self):
        body = ('<rss><channel>'
                '<item><title>Commentaires sur un concert par spambot</title>'
                '<link>https://example.org/actu/#comment-8</link></item>'
                '<item><title>Concert métal confirmé par la salle</title>'
                '<link>https://example.org/concert</link></item>'
                '</channel></rss>')
        c=feeds.rss_candidates(body,ROOM,BASE)
        self.assertEqual([x["name"] for x in c],["Concert métal confirmé par la salle"])
        self.assertIsNone(c[0]["date"])
        self.assertFalse(c[0]["publicationAllowed"])


if __name__=="__main__":unittest.main()
