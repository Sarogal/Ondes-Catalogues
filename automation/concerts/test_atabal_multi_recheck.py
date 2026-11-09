"""Offline Atabal multi-act safety tests against official-page-shaped fixtures."""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parents[1] / "scripts"))
import atabal_multi_recheck as multi
import official_recheck
from concerts_cloud_sync import validate_approval, PILOT_VENUES

NOW = dt.date(2026, 11, 9)
URL = ("https://www.atabal-biarritz.fr/agenda/concerts/"
       "coilguns-pussy-miel-killkilldiana-jeudi-11-mars-2027/")
PAGE = """<html><head><script>festival=1</script></head><body>
<article><section><p>11 mars 2027 19H30</p>
<h1>COILGUNS</h1><h2>Pussy Miel ~ Kill!Kill!Diana</h2></section>
<p>Tarifs 15 ~ 18 EUR</p>
<h2>COILGUNS</h2><p>Hardcore DYI, noise-rock</p><h5>POST H-CORE</h5>
<h2>PUSSY MIEL</h2><p>Rock garage, stoner</p><h5>PUNK ROCK</h5>
<h2>Kill!Kill!Diana</h2><p>Post hardcore</p><h5>POST H-CORE</h5>
<h4>Vous devriez aimer:</h4>
<h2>Unrelated recommended act</h2><h5>PUNK ROCK</h5>
</article></body></html>"""


def candidate():
    return {
        "candidateId":
            "atabal:2027-03-11:coilguns-pussy-miel-killkilldiana-jeudi-11-mars-2027",
        "source": "agenda_officiel_atabal_detail", "sourceUrl": URL,
        "sourcePage": multi.AGENDA, "name": "COILGUNS",
        "date": "2027-03-11", "venue": "Atabal", "city": "Biarritz",
        "venueCatalogueId": "atabal-biarritz", "classification": ["Hardcore"],
        "reviewBucket": "genre_tag_review", "possibleExistingConcert": False,
        "reviewRequired": True, "publicationAllowed": False,
        "officialDetailFound": True
    }


def catalogue():
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "venues": [copy.deepcopy(PILOT_VENUES["atabal-biarritz"]["venue"])],
        "artists": [], "events": []
    }


class StrictMultiBillTests(unittest.TestCase):
    def test_exact_first_party_bill_produces_three_named_artists(self):
        approval = official_recheck.verify(candidate(), PAGE, catalogue(), NOW)
        self.assertEqual(approval["event"]["date"], "2027-03-11")
        self.assertEqual(approval["event"]["genres"], ["Hardcore"])
        self.assertEqual(approval["event"]["artistIds"],
                         ["coilguns", "pussy-miel", "kill-kill-diana"])
        self.assertEqual(approval["event"]["title"],
                         "COILGUNS + Pussy Miel + Kill!Kill!Diana")
        self.assertIsNone(approval["event"]["time"])
        self.assertEqual(len(approval["newArtists"]), 3)
        self.assertEqual(approval["officialEvidence"][0]["sourceStructure"],
                         multi.STRUCTURE)

    def test_live_template_inline_heading_fragments_and_duplicate_sections(self):
        # The actual venue template breaks artist heading text into inline
        # chunks and repeats Pussy Miel's biography section. Ignore markup
        # boundaries, not unknown artist names or other heading elements.
        page = PAGE.replace(
            "<h2>Pussy Miel ~ Kill!Kill!Diana</h2>",
            "<h2>Pussy Miel <span>~</span> Kill!Kill!Diana</h2>")
        page = page.replace(
            "<h2>Kill!Kill!Diana</h2>",
            "<h2>Kill!<strong>Kill!</strong>Diana<br/></h2>")
        page = page.replace(
            "<h2>PUSSY MIEL</h2>",
            "<h2>PUSSY MIEL</h2><p>Biography</p><h2>PUSSY MIEL</h2>")
        self.assertEqual(
            multi.exact_names(page), ["COILGUNS", "Pussy Miel", "Kill!Kill!Diana"])
        approval = multi.verify(candidate(), page, catalogue(), NOW)
        event, added = validate_approval(
            approval, {v["id"]: v for v in catalogue()["venues"]}, {}, NOW)
        self.assertEqual(event["artistIds"],
                         ["coilguns", "pussy-miel", "kill-kill-diana"])
        self.assertEqual(len(added), 3)

    def test_unlisted_fourth_artist_section_is_not_silently_ignored(self):
        page = PAGE.replace(
            "<h4>Vous devriez aimer:</h4>",
            "<h2>UNANNOUNCED GUEST</h2><h4>Vous devriez aimer:</h4>")
        with self.assertRaisesRegex(ValueError, "étrangère"):
            multi.verify(candidate(), page, catalogue(), NOW)

    def test_unlisted_artist_inside_recommendations_is_ignored(self):
        page = PAGE.replace(
            "<h2>Unrelated recommended act</h2>",
            "<h2>OTHER POP STAR</h2>")
        self.assertEqual(
            multi.exact_names(page), ["COILGUNS", "Pussy Miel", "Kill!Kill!Diana"])

    def test_exact_approval_accepted_by_real_publisher(self):
        approval = multi.verify(candidate(), PAGE, catalogue(), NOW)
        evt, additions = validate_approval(
            approval, {v["id"]: v for v in catalogue()["venues"]}, {}, NOW)
        self.assertEqual(evt["artistIds"],
                         ["coilguns", "pussy-miel", "kill-kill-diana"])
        self.assertEqual(len(additions), 3)

    def test_malformed_date_and_changed_headliner_rejected(self):
        for body in (
                PAGE.replace("11 mars 2027", "12 mars 2027"),
                PAGE.replace("<h1>COILGUNS</h1>", "<h1>OTHER</h1>"),
                PAGE.replace("<h2>PUSSY MIEL</h2>", "<h2>OTHER</h2>"),
                PAGE.replace("<h2>Kill!Kill!Diana</h2>", ""),
                PAGE.replace("Pussy Miel ~ Kill!Kill!Diana", "Pussy Miel"),
                PAGE.replace("<h5>POST H-CORE</h5>", "<h5>REGGAE</h5>"),
                PAGE.replace("Tarifs 15 ~ 18 EUR", "Concert annulé"),
                PAGE.replace("Tarifs 15 ~ 18 EUR", "Gare du Midi"),
        ):
            with self.subTest(body=body[:130]):
                with self.assertRaises(ValueError):
                    multi.verify(candidate(), body, catalogue(), NOW)

    def test_no_implicit_artist_from_biography_or_recommendations(self):
        body = PAGE.replace("<h2>Kill!Kill!Diana</h2>", "")
        body = body.replace("<h4>Vous devriez aimer:", "<h4>Vous devriez aimer:")
        with self.assertRaises(ValueError):
            multi.verify(candidate(), body, catalogue(), NOW)

    def test_untrusted_metadata_and_incomplete_proofs_rejected(self):
        cases = [
            {"source": "ticketmaster"},
            {"sourceUrl": URL + "?fake=1"},
            {"date": "2027-03-12"},
            {"name": "Other"},
            {"city": "Pau"},
            {"venueCatalogueId": "other"},
            {"classification": ["Pop"]},
            {"possibleExistingConcert": True},
            {"reviewRequired": False},
            {"publicationAllowed": True},
            {"officialDetailFound": False},
        ]
        for change in cases:
            row = candidate()
            row.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                multi.verify(row, PAGE, catalogue(), NOW)

    def test_duplicate_venue_day_artist_and_alias_rejected(self):
        cat = catalogue()
        cat["events"].append({"id": "existing", "date": "2027-03-11",
                              "venueId": "atabal-biarritz",
                              "artistIds": ["coilguns"]})
        cat["artists"].append({"id": "coilguns", "name": "Coilguns"})
        with self.assertRaises(ValueError):
            multi.verify(candidate(), PAGE, cat, NOW)
        cat = catalogue()
        cat["artists"] = [{"id": "another", "name": "Another",
                           "aliases": ["Pussy Miel"]}]
        with self.assertRaises(ValueError):
            multi.verify(candidate(), PAGE, cat, NOW)

    def test_publisher_rejects_artists_or_proofs_manipulation(self):
        original = multi.verify(candidate(), PAGE, catalogue(), NOW)
        for operation in (
            lambda x: x["event"].update({"time": "19:30"}),
            lambda x: x["event"].update({"date": "2027-03-12"}),
            lambda x: x["event"].update({"artistIds": ["fake", "pussy-miel", "kill-kill-diana"]}),
            lambda x: x["event"].update({"genres": ["Reggae"]}),
            lambda x: x["event"].update({"title": "COILGUNS"}),
            lambda x: x["officialEvidence"][0].update({"officialArtistNames": ["FAKE", "Pussy Miel", "Kill!Kill!Diana"]}),
            lambda x: x["officialEvidence"][0].update({"sourceStructure": "untrusted"}),
            lambda x: x["officialEvidence"][0].update({"verifiedNewArtists": []}),
        ):
            approval = copy.deepcopy(original)
            operation(approval)
            with self.subTest(approval=approval["event"]), self.assertRaises((ValueError, KeyError, TypeError)):
                validate_approval(
                    approval, {v["id"]: v for v in catalogue()["venues"]}, {}, NOW)

    def test_unmodified_peter_hook_pilot_remains_separate(self):
        from test_atabal_recheck import candidate as hook, PAGE as hook_page, catalogue as hook_cat
        row = official_recheck.verify(hook(), hook_page, hook_cat(), NOW)
        self.assertEqual(row["event"]["id"],
                         "go-c-20270408-biarritz-peter-hook-and-the-light")


if __name__ == "__main__":
    unittest.main()
