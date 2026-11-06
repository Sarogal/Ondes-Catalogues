"""No-network tests: a discovery lead never becomes a trusted concert on its own."""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backstage_recheck as b
import official_recheck as official

DAY = dt.date(2026, 11, 5)
URL = "https://www.backstage-btm.com/agenda/lost-society-hokka/"
PAGE = """<html><head><script type="application/ld+json">
{"startDate":"2024-10-01","name":"Fake festival"}</script></head>
<body><h1>LOST SOCIETY + HOKKA</h1>
<div>Groove metal</div><div>19/02/2027</div>
<div>O’Sullivans By The Mill, 92 bis bd de Clichy - Paris</div>
<p>LOST SOCIETY et HOKKA préparent une tournée européenne.</p>
</body></html>"""


def candidate():
    return {
        "candidateId": "backstage:2027-02-19:lost-society-hokka",
        "source": "agenda_officiel_backstage_detail",
        "sourceUrl": URL,
        "name": "LOST SOCIETY + HOKKA",
        "date": "2027-02-19",
        "venue": "Backstage By The Mill",
        "city": "Paris",
        "classification": ["groove metal"],
        "reviewBucket": "genre_tag_review",
        "possibleExistingConcert": False,
        "reviewRequired": True,
        "publicationAllowed": False
    }


def catalogue():
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "venues": [{"id": "backstage-by-the-mill-paris",
                    "name": "Backstage By The Mill", "city": "Paris"}],
        "artists": [], "events": []
    }


class BackstageRecheckTests(unittest.TestCase):
    def test_positive_first_party_details_only_and_unknown_artists_explicit(self):
        a = official.verify(candidate(), PAGE, catalogue(), DAY)
        self.assertEqual(a["reviewedBy"], "automated-official-recheck")
        self.assertEqual(a["event"]["id"], "go-c-20270219-paris-lost-society")
        self.assertEqual(a["event"]["artistIds"], ["lost-society", "hokka"])
        self.assertEqual(a["newArtists"],
                         [{"id": "lost-society", "name": "LOST SOCIETY"},
                          {"id": "hokka", "name": "HOKKA"}])
        self.assertEqual(a["officialEvidence"][0]["officialArtistNames"],
                         ["LOST SOCIETY", "HOKKA"])
        self.assertEqual(a["event"]["genres"], ["Groove Metal"])
        self.assertIsNone(a["event"]["time"])

    def test_two_observations_are_required_and_second_run_is_idempotent(self):
        reg = {"items": {"only": {"candidate": candidate(), "observations": 2}}}
        queue = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        cat = catalogue()
        original = copy.deepcopy(cat)
        out, report = official.process(reg, cat, queue, DAY,
                                       fetch=lambda url, cache: PAGE)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(cat, original)
        self.assertEqual(queue["approvals"], [])
        out2, report2 = official.process(reg, cat, out, DAY,
                                         fetch=lambda url, cache: PAGE)
        self.assertEqual(len(out2["approvals"]), 1)
        self.assertEqual(report2["newApprovals"], [])
        reg["items"]["only"]["observations"] = 1
        _, held = official.process(reg, cat, queue, DAY,
                                   fetch=lambda url, cache: PAGE)
        self.assertEqual(held["evaluated"], 0)

    def test_fail_closed_on_incomplete_or_misleading_page(self):
        variants = [
            (PAGE.replace("19/02/2027", ""), "Date"),
            (PAGE.replace("19/02/2027", "20/02/2027"), "Date"),
            (PAGE.replace("LOST SOCIETY + HOKKA</h1>",
                          "LOST SOCIETY</h1>"), "Titre"),
            (PAGE.replace("Groove metal</div>", "Dance</div>"), "Genre"),
            (PAGE.replace("92 bis bd de Clichy", "ailleurs"), "Lieu"),
            (PAGE.replace("Paris</div>", "Lyon</div>"), "Lieu"),
            (PAGE.replace("</body>", "<h1>Fake</h1></body>"), "H1"),
            (PAGE.replace("LOST SOCIETY + HOKKA</h1>",
                          "LOST SOCIETY + Guest</h1>"), "Titre"),
        ]
        for html, reason in variants:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                official.verify(candidate(), html, catalogue(), DAY)

    def test_no_approval_for_other_hosts_or_venues_or_unknown_genre(self):
        variants = []
        x = candidate()
        x["sourceUrl"] = "https://not-backstage.example/agenda/lost-society-hokka/"
        variants.append(x)
        x = candidate()
        x["sourceUrl"] = "https://www.backstage-btm.com/agenda/"
        variants.append(x)
        x = candidate()
        x["sourceUrl"] = URL + "?id=42"
        variants.append(x)
        x = candidate()
        x["venue"] = "Fake Club"
        variants.append(x)
        x = candidate()
        x["classification"] = ["pop"]
        variants.append(x)
        x = candidate()
        x["reviewBucket"] = "possible_duplicate"
        variants.append(x)
        x = candidate()
        x["possibleExistingConcert"] = True
        variants.append(x)
        x = candidate()
        x["source"] = "third_party_calendar_lead"
        variants.append(x)
        for x in variants:
            with self.subTest(x=x), self.assertRaises(ValueError):
                official.verify(x, PAGE, catalogue(), DAY)

    def test_collision_with_published_date_or_alias_stays_pending(self):
        c = catalogue()
        c["events"] = [{"id": "existing", "date": "2027-02-19",
                        "venueId": "backstage-by-the-mill-paris",
                        "artistIds": ["hokka"]}]
        c["artists"] = [{"id": "hokka", "name": "HOKKA"}]
        with self.assertRaisesRegex(ValueError, "déjà publié"):
            official.verify(candidate(), PAGE, c, DAY)
        c = catalogue()
        c["artists"] = [{"id": "prior", "name": "Someone",
                         "aliases": ["HOKKA"]}]
        with self.assertRaisesRegex(ValueError, "alias"):
            official.verify(candidate(), PAGE, c, DAY)

    def test_missing_venue_and_unconfirmed_start_not_imputed(self):
        c = catalogue()
        c["venues"] = []
        with self.assertRaisesRegex(ValueError, "Salle"):
            official.verify(candidate(), PAGE, c, DAY)
        a = official.verify(candidate(), PAGE + "<p>Ouverture des portes : 19h</p>",
                            catalogue(), DAY)
        self.assertIsNone(a["event"]["time"])


if __name__ == "__main__":
    unittest.main()
