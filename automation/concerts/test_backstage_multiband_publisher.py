"""No-network publisher regression: first-party multi-band Backstage announcements.

Public, synthetic fixtures only. The named real bill is independently displayed
on the venue's public page, but these tests are NOT approvals or publication
authorization. All real approvals must still come from the private recheck.
"""
from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "concerts"))
sys.path.insert(0, str(ROOT / "scripts"))

import backstage_recheck as verifier
import concerts_cloud_sync as publisher

TODAY = dt.date(2026, 11, 15)
VENUE = {
    "id": "backstage-by-the-mill-paris",
    "name": "Backstage By The Mill",
    "city": "Paris",
}


def catalogue():
    return {
        "venues": [copy.deepcopy(VENUE)],
        "artists": [],
        "events": [],
    }


def checked_bill(names, date="2026-12-03", slug="blackgold"):
    """A synthetic, offline HTML detail with explicit venue, date and genre."""
    label = " + ".join(names)
    day, month, year = date[8:10], date[5:7], date[:4]
    url = "https://www.backstage-btm.com/agenda/" + slug + "/"
    lead = {
        "candidateId": "backstage:" + date + ":" + slug,
        "source": "agenda_officiel_backstage_detail",
        "sourceUrl": url,
        "name": label,
        "date": date,
        "venue": "Backstage By The Mill",
        "city": "Paris",
        "classification": ["metal"],
        "reviewBucket": "genre_tag_review",
        "possibleExistingConcert": False,
        "reviewRequired": True,
        "publicationAllowed": False,
    }
    html = (
        "<html><body><h1>" + label + "</h1>"
        "<div>metal</div><div>" + day + "/" + month + "/" + year + "</div>"
        "<div>O’Sullivans By The Mill, 92 bis bd de Clichy - Paris</div>"
        "</body></html>"
    )
    return lead, html


def signed_bill(names, date="2026-12-03", slug="blackgold", cat=None):
    cat = catalogue() if cat is None else cat
    lead, html = checked_bill(names, date, slug)
    return verifier.verify(lead, html, cat, TODAY)


def publisher_check(approval, cat=None):
    cat = catalogue() if cat is None else cat
    return publisher.validate_approval(
        approval,
        {v["id"]: v for v in cat["venues"]},
        {a["id"]: a for a in cat["artists"]},
        TODAY,
    )


class BackstageMultiBandPublisherTests(unittest.TestCase):
    def test_three_new_groups_from_officially_named_bill_are_accepted(self):
        names = ["BLACKGOLD", "SUMO CYCO", "HYRO THE HERO"]
        proposal = signed_bill(names)
        self.assertEqual(proposal["event"]["artistIds"],
                         ["blackgold", "sumo-cyco", "hyro-the-hero"])
        self.assertEqual(len(proposal["newArtists"]), 3)
        original = copy.deepcopy(proposal)
        emitted, new = publisher_check(proposal)
        self.assertEqual(emitted, proposal["event"])
        self.assertEqual(list(new), ["blackgold", "sumo-cyco", "hyro-the-hero"])
        self.assertEqual(proposal, original)

    def test_twenty_officially_named_new_groups_have_no_arbitrary_cap(self):
        # A real label must be validated act by act, even if all 20 acts
        # are absent from a still-incomplete national catalogue.
        names = [f"ACT{i:02d}" for i in range(1, 21)]
        proposal = signed_bill(names, date="2027-01-20",
                               slug="twenty-verified-acts")
        self.assertEqual(len(proposal["newArtists"]), 20)
        emitted, new = publisher_check(proposal)
        self.assertEqual(len(emitted["artistIds"]), 20)
        self.assertEqual(len(new), 20)
        self.assertEqual([new[aid]["name"] for aid in emitted["artistIds"]],
                         names)

    def test_six_named_groups_pass_verifier_and_publisher(self):
        names = ["ACT ONE", "ACT TWO", "ACT THREE",
                 "ACT FOUR", "ACT FIVE", "ACT SIX"]
        proposal = signed_bill(names, date="2027-01-20",
                               slug="six-verified-acts")
        emitted, new = publisher_check(proposal)
        self.assertEqual(len(emitted["artistIds"]), 6)
        self.assertEqual(len(new), 6)

    def test_extra_artist_outside_official_lineup_is_rejected(self):
        proposal = signed_bill(["BLACKGOLD", "SUMO CYCO", "HYRO THE HERO"])
        proposal["newArtists"].append({
            "id": "imaginary-fourth", "name": "Imaginary Fourth"
        })
        with self.assertRaisesRegex(ValueError, "nouveau nom en collision"):
            publisher_check(proposal)

    def test_mismatched_proof_does_not_pass_publisher(self):
        proposal = signed_bill(["BLACKGOLD", "SUMO CYCO", "HYRO THE HERO"])
        proposal["officialEvidence"][0]["officialArtistNames"][1] = "Unverified Act"
        with self.assertRaises(ValueError):
            publisher_check(proposal)

    def test_alias_collision_is_not_accepted_as_new_band(self):
        proposal = signed_bill(["BLACKGOLD", "SUMO CYCO", "HYRO THE HERO"])
        cat = catalogue()
        cat["artists"].append({
            "id": "other-group",
            "name": "Other Group",
            "aliases": ["SUMO CYCO"],
        })
        with self.assertRaisesRegex(ValueError, "collision"):
            publisher_check(proposal, cat)

    def test_unannounced_guest_keeps_headliner_without_fabricated_artist(self):
        lead, html = checked_bill(["BLACKGOLD", "Guest"])
        proposal = verifier.verify(lead, html, catalogue(), TODAY)
        self.assertEqual(proposal["event"]["title"], "BLACKGOLD")
        self.assertEqual(proposal["event"]["artistIds"], ["blackgold"])
        self.assertEqual(proposal["newArtists"],
                         [{"id": "blackgold", "name": "BLACKGOLD"}])
        emitted, new = publisher_check(proposal)
        self.assertEqual(emitted["artistIds"], ["blackgold"])
        self.assertEqual(list(new), ["blackgold"])
        self.assertNotIn("guest", new)


if __name__ == "__main__":
    unittest.main()
