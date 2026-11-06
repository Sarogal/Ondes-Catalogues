"""Tests stricts des calendriers tiers sans connexion Internet."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import partner_calendars as p

SOURCE = {
    "id": "secret-place-agendatickets-ics",
    "url": "https://www.agendatickets.com/lieu/secret-place-2/?ical=1",
    "sourceLabel": "Agenda Tickets",
    "venueName": "Secret Place",
    "city": "Saint-Jean-de-Védas",
    "department": "34",
    "officialVenuePage": "https://www.toutafond.com/nos-evenements",
    "maxEntriesPerRun": 60,
}

FIXTURE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=Europe/Paris:20261114T190000
UID:ta-1
SUMMARY:MOSCOW DEATH BRIGADE - SAINT JEAN DE VEDAS
URL:https://www.agendatickets.com/evenement/moscow-death-brigade-saint-jean-de-vedas/
CATEGORIES:Concerts,Punk
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20270403
UID:ta-2
SUMMARY:UUHAI – HUMAN HERDS EUROPEAN TOUR
URL:https://www.agendatickets.com/evenement/uuhai/
CATEGORIES:Metal
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Paris:20270403T190000
UID:ta-3
SUMMARY:LA TAF & BOOMERANG présentent UUHAI
URL:https://www.agendatickets.com/evenement/la-taf-uuhai/
CATEGORIES:Metal
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Paris:20261201T200000
UID:bad-1
SUMMARY:ANNULÉ - Concert Metal
STATUS:CANCELLED
CATEGORIES:Metal
END:VEVENT
END:VCALENDAR
"""

class PartnerTests(unittest.TestCase):
    def test_dates_year_and_no_publication(self):
        rows=p.partner_ics_candidates(FIXTURE,SOURCE,"2026-11-01")
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]["date"],"2026-11-14")
        self.assertEqual(rows[1]["date"],"2027-04-03")
        self.assertTrue(all(x["publicationAllowed"] is False for x in rows))
        self.assertTrue(all(x["thirdPartyOnly"] for x in rows))
        self.assertEqual(rows[0]["sourceUrl"],
                         "https://www.agendatickets.com/evenement/moscow-death-brigade-saint-jean-de-vedas/")

    def test_same_day_not_silently_fused(self):
        rows=p.partner_ics_candidates(FIXTURE,SOURCE,"2026-11-01")
        self.assertTrue(rows[1]["otherListingsSameDay"])
        self.assertTrue(rows[2]["otherListingsSameDay"])
        self.assertFalse(rows[0]["otherListingsSameDay"])

    def test_cancelled_is_alert(self):
        rows=p.partner_ics_candidates(FIXTURE,SOURCE,"2026-11-01")
        self.assertTrue(rows[-1]["cancellationNotice"])

    def test_bad_or_incomplete_date_is_rejected(self):
        base=("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Concert\n"
              "DTSTART:2026\nEND:VEVENT\nBEGIN:VEVENT\nSUMMARY:Concert 2\n"
              "DTSTART:20261340T190000\nEND:VEVENT\nEND:VCALENDAR")
        self.assertEqual(p.partner_ics_candidates(base,SOURCE,"2026-11-01"),[])

    def test_external_url_not_used_as_official(self):
        base=FIXTURE.replace("https://www.agendatickets.com/evenement/uuhai/",
                             "https://evil.example/event/abc")
        rows=p.partner_ics_candidates(base,SOURCE,"2026-11-01")
        self.assertEqual(rows[1]["sourceUrl"],SOURCE["url"])

    def test_past_event_rejected_and_bad_feed_fails(self):
        self.assertEqual(p.partner_ics_candidates(FIXTURE,SOURCE,"2028-01-01"),[])
        with self.assertRaises(ValueError):
            p.partner_ics_candidates("invalid",SOURCE,"2026-11-01")

if __name__=="__main__":
    unittest.main()
