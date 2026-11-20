"""Source-wide first-party paragraph concerts, no individual show whitelist."""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "concerts"))
sys.path.insert(0, str(ROOT / "scripts"))
import generic_music_event
import official_paragraph_bill as bill
import official_recheck
import approval_preflight
from concerts_cloud_sync import merge

DAY = dt.date(2026, 11, 21)
EVENT_DATE = "2027-04-02"
URL = "https://www.lastrolabe.org/agenda/knives/"
VENUE_ID = "l-astrolabe-orleans"
ARTISTS = ("KNIVES", "FRAGILE")


def source(names=ARTISTS, date="02.04.2027", genres=None, cancelled=False):
    genres = genres or ("Post-Punk – Hardcore Fusion", "Punk – Rock")
    artists = " + ".join(names)
    blocks = [
        "<p>Post-Punk - Punk - Punk Hardcore</p>",
        "<p>" + artists + "</p>",
        "<p>" + date + " - 20H30 - LE CLUB</p>",
        "<h2>Billetterie</h2>",
        "<p>Ouverture des portes à 20H30, début des concerts à 21H</p>",
    ]
    for n, style in zip(names, genres):
        blocks.append("<p>" + n + " (" + style + " / FRANCE)</p>")
        blocks.append("<hr/><p>Bio et tournée 2035 : n'est jamais une date.</p>")
    if cancelled:
        blocks[4] = "<p>CONCERT ANNULÉ</p>"
    return ("<html><head><script>window.unsafe='Fake Metal';</script></head>"
            "<body><nav><p>Metal festival hors programme</p></nav>"
            "<main>" + "".join(blocks) + "</main>"
            "<footer>Concerts 2029</footer></body></html>")


def lead(names=ARTISTS):
    return {
        "candidateId": "astrolabe:2027-04-02:knives",
        "name": " + ".join(names),
        "leadArtist": names[0],
        "source": "agenda_officiel_astrolabe_detail_review",
        "sourceUrl": URL, "sourcePage": "https://www.lastrolabe.org/",
        "venue": "L'Astrolabe", "city": "Orléans", "department": "45",
        "date": EVENT_DATE,
        "classification": ["Post-Punk - Punk - Punk Hardcore"],
        "officialDetailFound": True,
        "newVenueToReview": True,
        "possibleExistingConcert": False,
        "reviewBucket": "genre_tag_review",
        "publicationAllowed": False, "reviewRequired": True,
    }


def catalogue():
    return json.loads((ROOT / "docs/grossesondes/concerts-reference.json")
                      .read_text(encoding="utf-8"))


class ParagraphBillTests(unittest.TestCase):
    def test_first_party_mixed_genres_reach_real_publisher(self):
        actual = catalogue()
        candidate = lead()
        verified = official_recheck.verify(candidate, source(), actual, DAY)
        self.assertEqual(verified["event"]["venueId"], VENUE_ID)
        self.assertEqual(verified["event"]["title"], "KNIVES + FRAGILE")
        self.assertEqual(verified["event"]["genres"],
                         ["Post-Punk – Hardcore Fusion", "Punk – Rock"])
        self.assertEqual(verified["event"]["artistIds"], ["knives", "fragile"])
        self.assertIsNone(verified["event"]["time"])
        proof = verified["officialEvidence"][0]
        self.assertEqual(proof["officialArtistNames"], ["KNIVES", "FRAGILE"])
        self.assertEqual(proof["visibleBillProfile"],
                         "paragraph-artist-genre-v1")
        original = {"schema": "grossesondes.concert.approvals.v1",
                    "approvals": []}
        registry = {"items": {"lead": {
            "candidate": candidate, "status": "pending_review",
            "stableObservations": 2,
        }}}
        proposed, report = official_recheck.process(
            registry, actual, original, DAY,
            fetch=lambda u, cache: source())
        self.assertEqual(report["newApprovals"], [verified["event"]["id"]])
        self.assertEqual(report["newSiteApprovals"], [])
        checked = approval_preflight.validate_proposal(
            original, proposed, actual, copy.deepcopy(actual),
            DAY, merge)
        self.assertTrue(checked["validatedByPublisher"])
        published, stats = merge(actual, actual, proposed, DAY)
        self.assertEqual(stats["newEvents"], 1)
        self.assertEqual(stats["newVenues"], 0)
        self.assertEqual(published["events"][-1]["title"], "KNIVES + FRAGILE")

    def test_metal_opener_is_sufficient_even_when_headliner_is_jazz(self):
        p = source(names=("JAZZ BAND", "THRASH SUPPORT"),
                   genres=("Jazz", "Thrash Metal"))
        candidate = lead(("JAZZ BAND", "THRASH SUPPORT"))
        signed = official_recheck.verify(candidate, p, catalogue(), DAY)
        self.assertEqual(signed["event"]["genres"], ["Jazz", "Thrash Metal"])
        self.assertEqual(signed["event"]["artistIds"],
                         ["jazz-band", "thrash-support"])

    def test_no_band_count_cap(self):
        names = tuple("GROUPE %03d" % i for i in range(25))
        genres = ["Jazz"] * 24 + ["Death Metal"]
        candidate = lead(names)
        signed = official_recheck.verify(
            candidate, source(names, genres=genres), catalogue(), DAY)
        self.assertEqual(len(signed["event"]["artistIds"]), 25)
        self.assertEqual(signed["event"]["genres"], ["Jazz", "Death Metal"])

    def test_official_identity_and_genre_fail_closed(self):
        base = lead()
        doc = source()
        variants = [
            ({**base, "date": "2027-04-03"}, doc),
            ({**base, "sourceUrl": "https://evil.example/agenda/knives/"}, doc),
            ({**base, "venue": "Autre salle"}, doc),
            ({**base, "source": "agenda_ics"}, doc),
            ({**base, "publicationAllowed": True}, doc),
            ({**base, "possibleExistingConcert": True}, doc),
            (base, source(names=("KNIVES", "OTHER"))),
            (base, source(date="03.04.2027")),
            (base, source(genres=("Jazz", "Indie Pop"))),
            (base, source(cancelled=True)),
            (base, doc.replace("LE CLUB", "UNE SALLE INCONNUE")),
            (base, doc.replace("FRAGILE (Punk – Rock / FRANCE)", "")),
            (base, doc.replace("<main>", "<main><main>")),
        ]
        for bad_candidate, bad_html in variants:
            with self.subTest(cand=bad_candidate.get("sourceUrl"),
                              sample=bad_html[:70]), self.assertRaises(ValueError):
                official_recheck.verify(bad_candidate, bad_html,
                                        catalogue(), DAY)

    def test_publisher_rejects_spoofed_visible_profile_genres_or_url(self):
        actual = catalogue()
        good = official_recheck.verify(lead(), source(), actual, DAY)
        for field, value in (
            ("visibleBillProfile", "forged-profile"),
            ("officialGenreLabels", ["Jazz"]),
            ("verifiedVenueId", "le-metronum"),
        ):
            tampered = copy.deepcopy(good)
            tampered["officialEvidence"][0][field] = value
            queue = {"schema":"grossesondes.concert.approvals.v1",
                     "approvals":[tampered]}
            _, stats = merge(actual, actual, queue, DAY)
            self.assertEqual(stats["newEvents"], 0, field)
            self.assertTrue(stats["held"], field)


if __name__ == "__main__":
    unittest.main()
