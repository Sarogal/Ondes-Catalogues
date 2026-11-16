"""Live, opt-in and read-only checks of 9 publicly announced Gosier sessions.

No private reports, tokens, write APIs, patch or publication.
Runs only when PTITESONDES_MUNICIPAL_LIVE_CHECK=1, and does not run
automatically in the main synchronizer test suite.
"""
from datetime import date
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_municipal_preflight import (
    CalendarCards, OfficialPage, access_is_honest, calendar_card_date_matches,
    municipal_calendar_url,
    official_calendar_verified, official_event_verified, read_official,
)
from ptitesondes_nonmusic_release_contract import safe_event_url
from proof import norm

VENUE = "Médiathèque Raoul Georges Nicolo"
# The expectations below come from publicly dated municipal agendas and
# official event pages checked 2026-11-16. These are NOT approved events.
CASES = (
    ("2026-11-18", "mon doudou raconte", "09:00", "09:30", "jusqua_3_ans"),
    ("2026-11-18", "les rendez vous du numerique", "09:30", "11:30", "des_8_ans"),
    ("2026-11-18", "la magie des histoires", "10:00", "11:00", "des_4_ans"),
    ("2026-11-21", "les jeux du samedi", "09:00", "16:30", "tous_ages_familles"),
    ("2026-11-25", "mon doudou raconte", "09:00", "09:30", "jusqua_3_ans"),
    ("2026-11-25", "les rendez vous du numerique", "09:30", "11:30", "des_8_ans"),
    ("2026-11-25", "la magie des histoires", "10:00", "11:00", "des_4_ans"),
    ("2026-11-25", "le rendez vous des p tits racoons", "15:00", "17:00", "des_5_ans"),
    ("2026-11-28", "les jeux du samedi", "09:00", "16:30", "tous_ages_familles"),
)


@unittest.skipUnless(os.environ.get("PTITESONDES_MUNICIPAL_LIVE_CHECK") == "1",
                     "opt-in only: public municipality read-only probing")
class LiveGosierPublicSessionTests(unittest.TestCase):
    def test_nine_official_calendar_occurrences(self):
        day_cache = {}
        page_cache = {}
        checked = 0
        for day_text, title_prefix, start, end, audience in CASES:
            with self.subTest(day=day_text, series=title_prefix):
                if day_text not in day_cache:
                    url = municipal_calendar_url(date.fromisoformat(day_text))
                    html = read_official(url)
                    parser = CalendarCards()
                    parser.feed(html)
                    day_cache[day_text] = (html, parser.cards)
                calendar_html, cards = day_cache[day_text]
                matching = [
                    card for card in cards
                    if len(card["title_ids"]) == 1
                    and card["title_ids"] == card["venue_ids"]
                    and calendar_card_date_matches(card, date.fromisoformat(day_text))
                    and norm(VENUE) in norm(" ".join(card["words"]))
                    and title_prefix in norm(" ".join(card["words"]))
                ]
                if len(matching) != 1:
                    def fingerprint(card):
                        return (
                            tuple(card["title_ids"]), tuple(card["venue_ids"]),
                            tuple(sorted(set(card["links"]))),
                            *(norm(" ".join(card[key]))
                              for key in ("day", "month", "year", "hours", "words")),
                        )
                    print("PUBLIC_GOSIER_CARD_DIAGNOSTIC",
                          "matches=", len(matching),
                          "byte_equivalent=", len({fingerprint(c) for c in matching}) == 1)
                self.assertEqual(len(matching), 1, "ambiguous or absent municipal card")
                card = matching[0]
                links = {url for url in card["links"] if safe_event_url(url)}
                self.assertEqual(len(links), 1, "ambiguous or absent official link")
                event_url = next(iter(links))
                if event_url not in page_cache:
                    page_cache[event_url] = read_official(event_url)
                event_html = page_cache[event_url]
                page = OfficialPage()
                page.feed(event_html)
                self.assertEqual(len(page.titles), 1, "event heading ambiguous")
                self.assertTrue(page.finished, "event page boundary absent")
                candidate = {
                    "title": " ".join(page.titles[0]),
                    "date_start": day_text, "date_end": day_text,
                    "start_local": start, "end_local": end,
                    "venue": VENUE,
                    "source_event_id": card["title_ids"][0],
                    "official_event_url": event_url,
                    "audience_evidence": audience,
                }
                self.assertTrue(
                    official_calendar_verified(candidate, calendar_html),
                    "independent calendar occurrence proof failed",
                )
                self.assertTrue(
                    official_event_verified(candidate, event_html),
                    "independent official event proof failed",
                )
                okay, reason = access_is_honest(
                    candidate,
                    {"price_evidence": "not_stated",
                     "registration_evidence": "not_stated"},
                    event_html,
                )
                self.assertTrue(okay, "access conditions have changed or conflict")
                self.assertEqual(reason, "editorial_conditions_required")
                checked += 1
        self.assertEqual(checked, 9)


if __name__ == "__main__":
    unittest.main()
