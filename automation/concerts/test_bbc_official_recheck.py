"""BBC independent official verifier: positive yield and adversarial publisher tests."""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import bbc_adapter as adapter
import bbc_official_recheck as check
import official_recheck as orchestrator
from concerts_cloud_sync import validate_approval
from test_bbc_adapter import SOURCE

DAY = dt.date(2026, 11, 17)
URL = "https://bigbandcafe.com/ensemble-metal-experimental/"
VENUE = {
    "id": "big-band-cafe-herouville", "name": "Big Band Café",
    "city": "Hérouville-Saint-Clair", "department": "14",
    "latitude": 49.211031, "longitude": -0.334039,
}


def html_bill(names):
    return ("<html><body><nav><p>Unrelated Band</p></nav><section>"
            "<h1>" + " + ".join(names) + "</h1>"
            "<h2>ven. 12 mars 2027 - 20:00</h2>"
            "<p>Programmation metal confirmée au Big Band Café.</p>" +
            "".join("<p>" + n + " est un groupe de metal sur cette affiche.</p>"
                    for n in names) +
            "</section><section><p>OTHER ARTIST</p></section></body></html>")


def discovery(page):
    c = adapter.candidate(page, URL, SOURCE, DAY.isoformat())
    return {**c, "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False}


def catalog(known=()):
    return {"schemaVersion": 1, "mode": "preview-public-unlisted",
            "venues": [copy.deepcopy(VENUE)],
            "artists": [{"id": x.lower().replace(" ", "-"), "name": x,
                         "aliases": []} for x in known],
            "events": []}


def publishing(approval, catalogue):
    return validate_approval(
        approval, {v["id"]: v for v in catalogue["venues"]},
        {a["id"]: a for a in catalogue["artists"]}, DAY
    )


class BBCOfficialRecheckTests(unittest.TestCase):
    def test_one_two_eight_twenty_first_party_bands_admitted_by_real_publisher(self):
        for count in (1, 2, 8, 20):
            with self.subTest(count=count):
                names = ["ACT %02d" % i for i in range(count)]
                page = html_bill(names)
                c = catalog()
                app = orchestrator.verify(discovery(page), page, c, DAY)
                self.assertEqual(len(app["event"]["artistIds"]), count)
                self.assertEqual(len(app["newArtists"]), count)
                self.assertEqual(app["officialEvidence"][0]["officialArtistNames"], names)
                self.assertIsNone(app["event"]["time"])
                result, added = publishing(app, c)
                self.assertEqual(len(result["artistIds"]), count)
                self.assertEqual(len(added), count)
                self.assertEqual(result["date"], "2027-03-12")

    def test_existing_headliner_and_new_support_are_both_checked(self):
        names = ["ACT ONE", "ACT TWO"]
        page = html_bill(names)
        c = catalog(["ACT ONE"])
        app = check.verify(discovery(page), page, c, DAY)
        self.assertEqual(app["event"]["artistIds"], ["act-one", "act-two"])
        self.assertEqual(app["newArtists"], [{"id":"act-two", "name":"ACT TWO"}])
        publishing(app, c)

    def test_stability_second_day_and_exact_publisher_queue(self):
        page = html_bill(["ACT ONE", "ACT TWO"])
        row = {"status": "pending_review",
               "candidate": discovery(page), "stableObservations": 1}
        registry = {"schema": "grossesondes.concert.intake.v1",
                    "items": {"bbc": row}}
        approvals = {"schema": "grossesondes.concert.approvals.v1",
                     "approvals": []}
        c = catalog()
        _, status = orchestrator.process(
            registry, c, approvals, DAY,
            fetch=lambda *_: self.fail("No fetch until two distinct days"))
        self.assertEqual(status["evaluated"], 0)
        row["stableObservations"] = 2
        out, result = orchestrator.process(
            registry, c, approvals, DAY, fetch=lambda *_: page)
        self.assertEqual(result["evaluated"], 1)
        self.assertEqual(len(result["newApprovals"]), 1)
        publishing(out["approvals"][0], c)
        self.assertEqual(approvals["approvals"], [])

    def test_missing_artist_paragraph_cannot_be_accepted_from_title(self):
        page = html_bill(["ACT ONE", "ACT TWO"])
        c = discovery(page)
        without = page.replace(
            "<p>ACT TWO est un groupe de metal sur cette affiche.</p>", "")
        # The current event has the same headline but no second artist proof.
        with self.assertRaises((ValueError, TypeError)):
            check.verify(c, without, catalog(), DAY)
        # A fake paragraph in the menu or recommendation cannot replace it.
        rogue = without.replace("<nav>", "<nav><p>ACT TWO est un groupe.</p>")
        rogue = rogue.replace("</section></body>",
                              "<section><p>ACT TWO est un groupe.</p></section></body>")
        with self.assertRaises(ValueError):
            check.verify(c, rogue, catalog(), DAY)

    def test_invalid_date_genre_status_site_and_quarantine_are_held(self):
        page = html_bill(["ACT ONE", "ACT TWO"])
        valid = discovery(page)
        for changed in (
            page.replace("12 mars 2027", "13 mars 2027"),
            page.replace("Programmation metal", "Programmation pop").replace(
                "groupe de metal", "groupe de pop"),
            page.replace("est un groupe de metal", "est un concert annulé de metal"),
            page.replace("ACT TWO est un groupe", "ACT TWO est un hommage"),
            page.replace("ACT TWO</h1>", "OTHER</h1>"),
        ):
            with self.subTest(changed=changed[:140]), self.assertRaises(ValueError):
                check.verify(valid, changed, catalog(), DAY)
        for mutate in (
            {"sourceUrl": "https://evil.example/group/"},
            {"publicationAllowed": True},
            {"reviewRequired": False},
            {"possibleExistingConcert": True},
            {"officialDetailFound": False},
            {"reviewBucket": "genre_unknown"},
            {"sourcePage": "https://bigbandcafe.com/"},
        ):
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                check.verify({**valid, **mutate}, page, catalog(), DAY)

    def test_duplicate_and_alias_protection(self):
        page = html_bill(["ACT ONE", "ACT TWO"])
        lead = discovery(page)
        c = catalog()
        c["events"].append({"id": "old", "officialUrl": URL, "date": "2027-03-12",
                            "venueId": VENUE["id"], "artistIds": []})
        with self.assertRaisesRegex(ValueError, "déjà publié"):
            check.verify(lead, page, c, DAY)
        c = catalog()
        c["artists"].append({"id": "old-identity", "name": "Other",
                             "aliases": ["ACT TWO"]})
        with self.assertRaisesRegex(ValueError, "alias"):
            check.verify(lead, page, c, DAY)

    def test_publisher_rejects_forged_proofs_artists_and_times(self):
        names = ["ACT ONE", "ACT TWO"]
        page = html_bill(names)
        c = catalog()
        original = check.verify(discovery(page), page, c, DAY)
        for change in (
            lambda a: a["event"].update({"time": "20:00"}),
            lambda a: a["event"].update({"date": "2027-03-13"}),
            lambda a: a["event"].update({"artistIds": ["act-one", "faker"]}),
            lambda a: a["event"].update({"title": "ACT ONE"}),
            lambda a: a["officialEvidence"][0].update(
                {"officialArtistNames": ["ACT ONE", "FAKER"]}),
            lambda a: a["officialEvidence"][0].update(
                {"verifiedNewArtists": []}),
            lambda a: a["officialEvidence"][0].update(
                {"sourceStructure": "untrusted"}),
        ):
            forged = copy.deepcopy(original)
            change(forged)
            with self.subTest(change=forged["event"]), self.assertRaises(
                    (ValueError, TypeError, KeyError)):
                publishing(forged, c)

    def test_reserved_historical_bbc_manual_urls_cannot_be_resigned(self):
        # Both historical BBC signatures were already independently reviewed.
        page = html_bill(["ACT ONE"])
        c = catalog()
        row = check.verify(discovery(page), page, c, DAY)
        row["event"]["officialUrl"] = "https://bigbandcafe.com/ugly-kid-joe/"
        row["officialEvidence"][0]["url"] = row["event"]["officialUrl"]
        with self.assertRaises(ValueError):
            publishing(row, c)


if __name__ == "__main__":
    unittest.main()
