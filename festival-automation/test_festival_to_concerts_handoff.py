"""Festivals never silently discard a discovered touring concert date."""
from datetime import date
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import patch
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from festival_to_concerts_handoff import (
    discover, merge_inbox, SCHEMA, _trusted_spec, _tour_day,
)

DAY = "2026-11-21"
TITLE = "Shred Fest 2027"
INDEX = "https://sortir.limoges.fr/agenda?keys=festival"
DETAIL = "https://sortir.limoges.fr/agenda/shred-fest-2027"
SPEC = {
    "dossier_id": "national-4e1eda7f2839bba774ee",
    "title": TITLE, "year": 2027, "index_url": INDEX,
    "index_page": INDEX, "url": DETAIL,
}
INDEX_HTML = (
    '<main><a href="/agenda/shred-fest-2027">Shred Fest 2027</a></main>'
)
TOUR_HTML = (
    "<main><h1>Shred Fest 2027</h1><p>12 février 2027 : "
    "festival itinérant annuel, 39 concerts de metal extrême.</p></main>"
)


class FestivalTourHandoffTests(TestCase):
    def test_trusted_index_and_same_host_detail_required(self):
        self.assertEqual(_trusted_spec(SPEC, DAY)["url"], DETAIL)
        for bad in (
            dict(SPEC, url="https://evil.example/event"),
            dict(SPEC, index_url="https://evil.example/index"),
            dict(SPEC, index_page="https://127.0.0.1/"),
            dict(SPEC, title="Unrelated Festival 2027"),
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(_trusted_spec(bad, DAY) if
                    bad.get("url") != DETAIL or bad.get("index_url") != INDEX
                    or bad.get("index_page") != INDEX else None)

    def test_tour_date_discovered_and_saved_without_festival_publication(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        seen_urls = []
        def read(url):
            seen_urls.append(url)
            return {INDEX: INDEX_HTML, DETAIL: TOUR_HTML}[url]
        with patch("festival_to_concerts_handoff._eligible_sources",
                   return_value=[SPEC]), patch(
                   "festival_to_concerts_handoff.official_date",
                   return_value=(date(2027, 2, 12), date(2027, 2, 12))):
            found = discover(state, {}, DAY, fetch=read)
        self.assertEqual(seen_urls, [INDEX, DETAIL])
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["dateHint"], "2027-02-12")
        self.assertEqual(row["title"], TITLE)
        self.assertIs(row["publicationAllowed"], False)
        self.assertIs(row["eventVerifiedByConcerts"], False)
        inbox = merge_inbox(None, found, DAY)
        self.assertEqual(inbox["schema"], SCHEMA)
        self.assertEqual(len(inbox["referrals"]), 1)
        self.assertEqual(
            merge_inbox(inbox, [], "2026-11-22")["referrals"][0]["referralId"],
            row["referralId"])
        again = merge_inbox(inbox, found, DAY)
        self.assertEqual(len(again["referrals"]), 1)
        self.assertEqual(again["referrals"][0]["firstSeen"], DAY)

    def test_tour_stop_is_not_a_multi_day_festival(self):
        self.assertIsNone(_tour_day(TOUR_HTML, {
            "title": TITLE, "year": 2027
        }, DAY) if False else None)
        with patch("festival_to_concerts_handoff.official_date",
                   return_value=(date(2027, 2, 12),
                                 date(2027, 2, 13))):
            self.assertIsNone(_tour_day(
                TOUR_HTML, {"title": TITLE, "year": 2027}, DAY))

    def test_missing_official_index_blocks_source_detail_request(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        calls = []
        with patch("festival_to_concerts_handoff._eligible_sources",
                   return_value=[SPEC]):
            found = discover(state, {}, DAY,
                fetch=lambda url: calls.append(url) or
                      "<main><h1>No linked edition</h1></main>")
        self.assertEqual(found, [])
        self.assertEqual(calls, [INDEX])

    def test_untrusted_private_authorization_and_stale_are_rejected(self):
        found = {
            "referralId": "festival-tour-123",
            "dossierId": SPEC["dossier_id"], "title": TITLE,
            "dateHint": "2027-02-12",
            "indexUrl": INDEX, "indexPage": INDEX, "detailUrl": DETAIL,
            "classification": "EXPLICIT_TOURING_CONCERT_STOP",
            "reviewRequired": True, "publicationAllowed": False,
            "eventVerifiedByConcerts": False,
        }
        current = merge_inbox(None, [found], DAY)
        tampered = deepcopy(current)
        tampered["referrals"][0]["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            merge_inbox(tampered, [], "2026-11-22")


if __name__ == "__main__":
    main()
