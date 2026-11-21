"""Concerts intake must reprove festival tour links, never trust referrals."""
import json
import unittest
from datetime import date
from unittest.mock import patch

import festival_tour_handoff as bridge
import intake_archive
import triage

TODAY = "2026-11-21"
INDEX = "https://sortir.limoges.fr/agenda?keys=festival"
DETAIL = "https://sortir.limoges.fr/agenda/shred-fest-2027"
TITLE = "Shred Fest 2027"
HTML = (
    "<main><h1>Shred Fest 2027</h1><p>12 février 2027, "
    "festival itinérant annuel avec 39 concerts metal.</p></main>"
)
INDEX_HTML = '<a href="/agenda/shred-fest-2027">Shred Fest 2027</a>'


def envelope(row=None):
    return {
        "schema": "grossesondes.festival-to-concerts-private.v1",
        "review_only": True, "publication_authorized": False,
        "referrals": [row] if row is not None else [],
    }


def valid_row():
    source = {
        "index_url": INDEX, "index_page": INDEX,
        "url": DETAIL, "title": TITLE, "year": 2027,
    }
    day = "2027-02-12"
    import hashlib
    raw = json.dumps({
        "index": INDEX, "detail": DETAIL,
        "title": TITLE, "day": day,
    }, sort_keys=True).encode("utf-8")
    return {
        "referralId": "festival-tour-" + hashlib.sha256(raw).hexdigest()[:24],
        "dossierId": "national-4e1eda7f2839bba774ee",
        "title": TITLE, "dateHint": day,
        "indexUrl": INDEX, "indexPage": INDEX, "detailUrl": DETAIL,
        "classification": "EXPLICIT_TOURING_CONCERT_STOP",
        "reviewRequired": True, "publicationAllowed": False,
        "eventVerifiedByConcerts": False,
        "firstSeen": TODAY, "lastSeen": TODAY,
    }


class PrivateTourConcertsHandoffTests(unittest.TestCase):
    def test_valid_referral_never_grants_network_permission_by_itself(self):
        row = valid_row()
        self.assertEqual(bridge.trusted_referral(row, TODAY)["url"], DETAIL)
        for field, replacement in (
            ("indexUrl", "https://attacker.example/agenda"),
            ("detailUrl", "https://127.0.0.1/"),
            ("referralId", "fake"),
            ("publicationAllowed", True),
            ("dateHint", "2027-02-13"),
            ("firstSeen", "2026-11-22"),
        ):
            with self.subTest(field=field):
                bad = dict(row, **{field: replacement})
                self.assertIsNone(bridge.trusted_referral(bad, TODAY))

    def test_recheck_is_independent_and_archivable_as_research_only(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return {INDEX: INDEX_HTML, DETAIL: HTML}[url]
        with patch("festival_to_concerts_handoff.official_date",
                   return_value=(date(2027, 2, 12), date(2027, 2, 12))):
            report = bridge.reverify(envelope(valid_row()), TODAY, fetch)
        self.assertEqual(calls, [INDEX, DETAIL])
        self.assertEqual(report["triageCounts"], {"tour_source_research": 1})
        self.assertEqual(len(report["candidates"]), 1)
        c = report["candidates"][0]
        self.assertIs(c["publicationAllowed"], False)
        self.assertIs(c["reviewRequired"], True)
        self.assertIsNone(c["leadArtist"])
        self.assertIsNone(c["venue"])
        self.assertIsNone(c["city"])
        self.assertEqual(c["reviewBucket"], "tour_source_research")
        archive, stats = intake_archive.merge(
            None, report, "2026-11-21T03:00:00+00:00")
        self.assertEqual(stats["added"], 1)
        self.assertEqual(archive["total"], 1)
        self.assertEqual(list(archive["items"].values())[0]["status"],
                         "pending_review")

    def test_removed_live_link_never_fetches_suggested_detail(self):
        calls = []
        with patch("festival_to_concerts_handoff.official_date",
                   side_effect=AssertionError("source detail must not be read")):
            out = bridge.reverify(envelope(valid_row()), TODAY,
                fetch=lambda url: calls.append(url) or
                       "<main>Other unrelated event</main>")
        self.assertEqual(calls, [INDEX])
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["triageCounts"], {"tour_source_research": 0})

    def test_a_same_day_multipart_festival_is_not_a_tour_lead(self):
        def read(url):
            return INDEX_HTML if url == INDEX else HTML
        with patch("festival_to_concerts_handoff.official_date",
                   return_value=(date(2027, 2, 12), date(2027, 2, 13))):
            out = bridge.reverify(envelope(valid_row()), TODAY, fetch=read)
        self.assertEqual(out["candidates"], [])

    def test_untrusted_private_inbox_fails_closed(self):
        for doc in (
            dict(envelope(valid_row()), publication_authorized=True),
            dict(envelope(valid_row()), review_only=False),
            dict(envelope(valid_row()), schema="unknown"),
            dict(envelope(valid_row()), referrals=[valid_row(), valid_row()]),
        ):
            with self.subTest(doc=doc):
                with self.assertRaises(ValueError):
                    bridge.reverify(doc, TODAY, fetch=lambda _: self.fail(
                        "Invalid private inbox must never authorize fetching"))

    def test_festival_word_is_not_a_rejection_of_verified_touring_date(self):
        base = {
            "date": "2027-02-12", "name": TITLE,
            "source": "festival_to_concerts_handoff",
            "touringEventRechecked": True,
            "requiresArtistAndVenueReproof": True,
            "publicationAllowed": False,
            "reviewRequired": True,
        }
        row = triage.triage(base)
        self.assertEqual(row["reviewBucket"], "tour_source_research")
        self.assertFalse(row["publicationAllowed"])
        plain = dict(base, touringEventRechecked=False)
        self.assertEqual(
            triage.triage(plain)["reviewBucket"], "festival_overlap_review")


if __name__ == "__main__":
    unittest.main()
