"""Bateau Ivre 2027: no fictitious guests, verified identities and publisher gate."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
import bateau_ivre_adapter as discovery
import bateau_ivre_official_recheck as check
import official_recheck
from concerts_cloud_sync import PILOT_VENUES, validate_approval

TODAY = dt.date(2026, 11, 12)
URL = (discovery.BASE + "/%C3%A9v%C3%A8nements/"
       "orchestre-tout-puissant-marcel-duchamp/")
HEAD = "Orchestre tout puissant Marcel Duchamp"
SOURCE = {
    "name": "Le Bateau Ivre", "city": "Tours", "department": "37",
    "url": discovery.ARCHIVE,
}


def page(support="+ TACHYCARDIE", second_section="+ TACHYCARDIE",
         date="Jeudi 21 Jan 2027", genre="rock punk"):
    return ("""<html><main><article class="events type-events status-publish">
    <div class="singleEvententry-header"><h1 class="entry-title">""" + HEAD +
    "</h1><h2 class=\"subtitle-event\">" + support + "</h2>" +
    date + "<br>20h<p>Accueil / billetterie</p></div>"
    "<div class=\"mobileView\"><h1 class=\"entry-title\">" + HEAD +
    "</h1>" + date + "<br>20h</div>"
    "<div class=\"singleEvententry-content\">"
    "<h2 class=\"wp-block-post-title\">" + HEAD + "</h2>"
    "<p>Le groupe joue " + genre + " sur scène.</p>"
    "<h2 class=\"wp-block-heading\">" + second_section + "</h2>"
    "<p>Un artiste avec une vraie section nominative rock.</p>"
    "</div></article></main></html>")


def candidate(html=None):
    c = discovery.candidate(
        html if html is not None else page(),
        URL, SOURCE, TODAY.isoformat())
    return {**c, "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False}


def catalogue(artists=()):
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "artists": list(artists),
        "venues": [copy.deepcopy(PILOT_VENUES["le-bateau-ivre-tours"]["venue"])],
        "events": [],
    }


class BateauIndependentRecheck(unittest.TestCase):
    def test_named_new_support_and_headliner_get_distinct_sections(self):
        item = candidate()
        self.assertEqual(item["firstPartyNamedSupport"], ["TACHYCARDIE"])
        decision = check.verify(item, page(), catalogue(), TODAY)
        event = decision["event"]
        self.assertEqual(event["title"], HEAD + " + TACHYCARDIE")
        self.assertIsNone(event["time"])
        self.assertEqual(event["date"], "2027-01-21")
        self.assertEqual(event["artistIds"], [
            "orchestre-tout-puissant-marcel-duchamp", "tachycardie"])
        self.assertEqual([a["name"] for a in decision["newArtists"]],
                         [HEAD, "TACHYCARDIE"])
        self.assertEqual(decision["officialEvidence"][0]["sourceStructure"],
                         check.STRUCTURE)

    def test_plurally_named_artist_only_when_first_party_section_confirms(self):
        item = candidate()
        bad = page(second_section="+ ANOTHER GROUP")
        with self.assertRaisesRegex(ValueError, "changement officiel|corroborée"):
            check.verify(item, bad, catalogue(), TODAY)

    def test_unannounced_first_part_is_not_fictitious_artist(self):
        html = page(support="+ Première partie", second_section="+ Première partie")
        item = candidate(html)
        self.assertEqual(item["name"], HEAD)
        self.assertEqual(item["firstPartyNamedSupport"], [])
        decision = check.verify(item, html, catalogue(), TODAY)
        self.assertEqual(decision["event"]["title"], HEAD)
        self.assertEqual(decision["event"]["artistIds"],
                         ["orchestre-tout-puissant-marcel-duchamp"])
        self.assertNotIn("premiere-partie", [a["id"] for a in decision["newArtists"]])

    def test_new_headliner_needs_own_named_heading(self):
        html = page().replace('class="wp-block-post-title"', 'class="elsewhere"')
        item = candidate(html)
        with self.assertRaisesRegex(ValueError, "section nominative"):
            check.verify(item, html, catalogue(), TODAY)

    def test_same_run_process_and_real_publication_validation(self):
        item = candidate()
        reg = {"schema": "grossesondes.concert.intake.v1",
               "items": {"one": {"status": "pending_review",
                                 "candidate": item, "stableObservations": 2}}}
        approvals = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        new, report = official_recheck.process(
            reg, catalogue(), approvals, TODAY,
            fetch=lambda url, cache: page())
        self.assertEqual(report["evaluated"], 1)
        self.assertEqual(len(report["newApprovals"]), 1)
        decision = new["approvals"][0]
        event, added = validate_approval(
            decision,
            {v["id"]: v for v in catalogue()["venues"]},
            {}, TODAY)
        self.assertEqual(event["venueId"], "le-bateau-ivre-tours")
        self.assertEqual(len(added), 2)
        self.assertEqual(approvals["approvals"], [])

        reg["items"]["one"]["stableObservations"] = 1
        denied, skipped = official_recheck.process(
            reg, catalogue(), approvals, TODAY,
            fetch=lambda url, cache: self.fail("Cannot fetch unstable row"))
        self.assertEqual(skipped["evaluated"], 0)
        self.assertEqual(denied, approvals)

    def test_a_new_artist_must_not_shadow_an_existing_alias(self):
        item = candidate()
        artist = {"id": "different", "name": "Other",
                  "aliases": [HEAD]}
        with self.assertRaises(ValueError):
            check.verify(item, page(), catalogue([artist]), TODAY)

    def test_mismatched_date_and_masthead_never_publish(self):
        item = candidate()
        for content in (
            page(date="Jeudi 22 Jan 2027"),
            page().replace("rock punk", "chanson française"),
            page().replace('status-publish', "status-draft"),
            page().replace('id="main"', 'id="aside"').replace("<main>", "<div>"),
            page().replace("<h1 class=\"entry-title\">" + HEAD,
                           "<h1 class=\"entry-title\">OTHER", 1),
        ):
            with self.subTest(content=content[:80]), self.assertRaises(ValueError):
                check.verify(item, content, catalogue(), TODAY)

    def test_duplicate_reservation_and_tampered_publisher_proof_rejected(self):
        item = candidate()
        original = check.verify(item, page(), catalogue(), TODAY)
        cat = catalogue()
        cat["events"].append({"id": "published", "officialUrl": URL})
        with self.assertRaises(ValueError):
            check.verify(item, page(), cat, TODAY)
        for field, value in (
            ("sourceStructure", "generic-agenda"),
            ("verifiedNewArtists", []),
            ("officialArtistNames", ["Unlisted Artist", "TACHYCARDIE"]),
            ("sourcePage", "https://untrusted.example"),
        ):
            changed = copy.deepcopy(original)
            changed["officialEvidence"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_approval(changed, {
                    v["id"]: v for v in catalogue()["venues"]}, {}, TODAY)
        changed = copy.deepcopy(original)
        changed["event"]["time"] = "20:00"
        with self.assertRaises(ValueError):
            validate_approval(changed, {
                v["id"]: v for v in catalogue()["venues"]}, {}, TODAY)


if __name__ == "__main__":
    unittest.main()
