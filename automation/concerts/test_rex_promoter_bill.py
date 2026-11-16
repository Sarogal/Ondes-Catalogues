"""Rex: an explicitly promoted named support is not an unknown guest.

Offline example follows the official 22 January 2027 Rex page wording. No
live publication, invented artist, fabricated time or private approvals.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "automation" / "concerts"))

import concerts_cloud_sync as publisher
import official_recheck as rex

TODAY = dt.date(2026, 11, 16)
URL = "https://www.lerextoulouse.com/fr/programmation/spicy-box-mooan-exis-/"
HTML = """<html><body>
<p>ven 22 janvier 2027 - 19H30</p>
<h2>Spicy Box (+ Mooan Exis) !</h2>
<p>Punk, Techno</p>
<p>Les Productions du Possible et Le bruit du papier invitent SPICY BOX + MOOAN EXIS !</p>
<p>SPICY BOX se reforme pour une série de concerts exceptionnels.</p>
<p>Première partie par les excellents MOOANS EXIS. Moaan Exis est un duo toulousain.</p>
<p>15 avenue Honoré Serres 31000 Toulouse</p>
</body></html>"""


def candidate():
    return {"candidateId": "rex:2027-01-22:spicy-box-mooan-exis",
            "source": "agenda_officiel_rex_genre", "sourceUrl": URL,
            "name": "Spicy Box (+ Mooan Exis) !", "date": "2027-01-22",
            "venue": "Le Rex", "city": "Toulouse",
            "classification": ["punk", "techno"], "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False, "publicationAllowed": False,
            "reviewRequired": True}


def catalogue():
    return {"schemaVersion": 1, "mode": "preview-public-unlisted",
            "artists": [{"id": "known-act", "name": "Known Act", "aliases": []}],
            "venues": [{"id": "le-rex-toulouse", "name": "Le Rex",
                        "city": "Toulouse"}], "events": []}


class RexPromoterBillTests(unittest.TestCase):
    def verified(self, html=HTML, cand=None, catalog=None):
        return rex.verify(cand or candidate(), html, catalog or catalogue(), TODAY)

    def test_official_exact_promoter_bill_creates_only_two_named_artists(self):
        row = self.verified()
        self.assertEqual(row["event"]["artistIds"], ["spicy-box", "mooan-exis"])
        self.assertEqual(row["event"]["id"], "go-c-20270122-toulouse-spicy-box")
        self.assertEqual(row["event"]["title"], "Spicy Box (+ Mooan Exis) !")
        self.assertIsNone(row["event"]["time"])
        self.assertEqual(row["newArtists"], [
            {"id": "spicy-box", "name": "Spicy Box"},
            {"id": "mooan-exis", "name": "Mooan Exis"}])
        proof = row["officialEvidence"][0]
        self.assertEqual(proof["sourceStructure"], "rex-promoter-exact-bill")
        self.assertEqual(proof["officialArtistNames"], ["Spicy Box", "Mooan Exis"])
        venues = {v["id"]: v for v in catalogue()["venues"]}
        artists = {a["id"]: a for a in catalogue()["artists"]}
        event, added = publisher.validate_approval(row, venues, artists, TODAY)
        self.assertEqual(event, row["event"])
        self.assertEqual(set(added), {"spicy-box", "mooan-exis"})

    def test_current_published_catalogue_remains_unchanged(self):
        """Exercise the real public catalogue after #329 without writing to it.

        Once the Rex date is eventually published, the same proof must be
        rejected as a duplicate rather than creating a second event.
        """
        current = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(
            encoding="utf-8"))
        original = copy.deepcopy(current)
        target = "go-c-20270122-toulouse-spicy-box"
        if any(e["id"] == target for e in current["events"]):
            with self.assertRaisesRegex(ValueError, "déjà référencé"):
                self.verified(catalog=current)
        else:
            row = self.verified(catalog=current)
            self.assertEqual(row["event"]["id"], target)
            self.assertEqual(row["event"]["artistIds"], ["spicy-box", "mooan-exis"])
            self.assertIsNone(row["event"]["time"])
            venues = {v["id"]: v for v in current["venues"]}
            artists = {a["id"]: a for a in current["artists"]}
            event, _ = publisher.validate_approval(row, venues, artists, TODAY)
            self.assertEqual(event, row["event"])
        self.assertEqual(current, original)

    def test_biographies_without_exact_promoter_bill_are_not_approvals(self):
        variants = [
            HTML.replace("invitent SPICY BOX + MOOAN EXIS !",
                         "invitent SPICY BOX !"),
            HTML.replace("invitent SPICY BOX + MOOAN EXIS !",
                         "invitent SPICY BOX + UNNAMED SUPPORT !"),
            HTML.replace("invitent SPICY BOX + MOOAN EXIS !",
                         "SPICY BOX + MOOAN EXIS ont joue jadis ensemble."),
            HTML.replace("invitent SPICY BOX + MOOAN EXIS !",
                         "SPICY BOX et MOOAN EXIS sont des groupes connus."),
            HTML.replace("invitent SPICY BOX + MOOAN EXIS !",
                         "invitent SPICY BOX. MOOAN EXIS !"),
        ]
        for html in variants:
            with self.subTest(html=html[80:160]), self.assertRaisesRegex(
                    ValueError, "Affiche sans détail"):
                self.verified(html)

    def test_alias_duplicate_and_date_mutations_are_rejected(self):
        cat = catalogue()
        cat["artists"][0]["aliases"] = ["Mooan Exis"]
        with self.assertRaisesRegex(ValueError, "Alias"):
            self.verified(catalog=cat)
        cat = catalogue()
        cat["events"] = [{"id": "older-show", "date": "2027-01-22",
                          "venueId": "le-rex-toulouse", "artistIds": ["spicy-box"]}]
        with self.assertRaisesRegex(ValueError, "déjà référencé"):
            self.verified(catalog=cat)
        wrong = candidate()
        wrong["date"] = "2027-01-23"
        with self.assertRaisesRegex(ValueError, "Date"):
            self.verified(cand=wrong)

    def test_unapproved_third_group_and_placeholder_stay_held(self):
        changed_title = "Spicy Box + Mooan Exis + New Band"
        changed_candidate = candidate()
        changed_candidate["name"] = changed_title
        with self.assertRaisesRegex(ValueError, "Affiche sans détail"):
            self.verified(HTML.replace("Spicy Box (+ Mooan Exis) !",
                                       changed_title), cand=changed_candidate)
        with self.assertRaises(ValueError):
            self.verified(HTML.replace("Spicy Box (+ Mooan Exis) !",
                                       "Spicy Box (+ Guest) !"))
        with self.assertRaisesRegex(ValueError, "Genre incompatible"):
            bad = candidate()
            bad["classification"] = ["trance"]
            self.verified(cand=bad)

    def test_real_publisher_rejects_forged_lineup_and_time(self):
        row = self.verified()
        venues = {v["id"]: v for v in catalogue()["venues"]}
        artists = {a["id"]: a for a in catalogue()["artists"]}
        mutations = []
        forged = copy.deepcopy(row)
        forged["event"]["artistIds"].append("third-band")
        mutations.append(forged)
        forged = copy.deepcopy(row)
        forged["event"]["time"] = "19:30"
        mutations.append(forged)
        forged = copy.deepcopy(row)
        forged["newArtists"][0]["name"] = "Different Artist"
        mutations.append(forged)
        for bad in mutations:
            with self.subTest(bad=bad["event"]["id"]), self.assertRaises(ValueError):
                publisher.validate_approval(bad, venues, artists, TODAY)


if __name__ == "__main__":
    unittest.main()
