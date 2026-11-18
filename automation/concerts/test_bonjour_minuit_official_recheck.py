"""Bonjour Minuit: event-agnostic verification & exact publisher contract.

Every fixture constructs a NEW official article. No show name/URL exception
is used to qualify the events; historical already-signed URLs stay reserved.
"""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import bonjour_minuit_adapter as bm
import bonjour_minuit_official_recheck as verify
import official_recheck
from concerts_cloud_sync import validate_approval

TODAY = dt.date(2026, 11, 18)
SOURCE = {"name": "Bonjour Minuit", "city": "Saint-Brieuc",
          "department": "22", "url": bm.AGENDA}
VENUE = {"id": "bonjour-minuit-saint-brieuc", "name": "Bonjour Minuit",
         "city": "Saint-Brieuc", "latitude": 48.5196, "longitude": -2.7852}
URL = "https://bonjour-minuit.fr/evenement/novodata-12fev27/"
DAY = "vendredi 12 février 2027"


def show(names=("Novö Data", "Barre à Mine"), day=DAY, room="Club • 20h30",
         status="", first_style="rock post-punk Bretagne", extra="",
         short_p=False, notes="", release_party=False):
    leading = names[0] + (" release party" if release_party else "")
    lineup = [leading] + list(names[1:])
    styles = [first_style] + ["electro post-indus Bretagne"] * (len(names) - 1)
    sections = "".join(
        "<h2>" + n + "</h2>" +
        (("<p>" + style + "</p>") if short_p else
         ("<div class='genre'><span>" + style + "</span></div>")) +
        "<p>" + n + " présente un nouveau concert sur scène.</p>"
        for n,style in zip(lineup, styles))
    return (
        "<html><nav><h2>Unrelated Band</h2><span>metal</span></nav><main>"
        "<article><h1>" + " ".join(lineup) + "</h1>"
        "<div>" + day + "</div>"
        "<div>" + room + "</div>"
        "<div>Début : 30 minutes après l'ouverture</div>"
        "<div>Ces horaires sont indicatifs.</div>"
        "<div>" + status + "</div>"
        "<div>Si vous aimez : Nine Inch Nails, The Clash.</div>"
        "<p>Deux groupes à découvrir. " + notes + "</p>"
        + extra + sections + "</article></main>"
        "<footer><h2>Fake Band</h2><span>rock metal</span></footer></html>"
    )


def discovery(page, url=URL):
    c = bm.candidate(page, url, SOURCE, TODAY.isoformat())
    return {**c, "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False}


def catalogue(known=()):
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "venues": [copy.deepcopy(VENUE)],
        "artists": [{"id":bm.plain(x).replace(" ", "-"), "name":x,
                     "aliases": []} for x in known],
        "events": [],
    }


def publish(record, cat):
    return validate_approval(
        record, {v["id"]:v for v in cat["venues"]},
        {a["id"]:a for a in cat["artists"]}, TODAY)


class BonjourMinuitIndependentTests(unittest.TestCase):
    def test_novodata_barre_a_mine_multi_artist_and_door_time(self):
        page = show()
        cat = catalogue()
        approval = official_recheck.verify(discovery(page), page, cat, TODAY)
        self.assertEqual(approval["event"]["title"], "Novö Data + Barre à Mine")
        self.assertEqual(approval["event"]["date"], "2027-02-12")
        self.assertIsNone(approval["event"]["time"])
        self.assertEqual(approval["event"]["genres"], ["Rock"])
        self.assertEqual(approval["event"]["artistIds"], ["novo-data", "barre-a-mine"])
        self.assertEqual(len(approval["newArtists"]), 2)
        self.assertEqual(approval["officialEvidence"][0]["officialRoom"], "Le Club")
        event, artists = publish(approval, cat)
        self.assertEqual(event["artistIds"], approval["event"]["artistIds"])
        self.assertEqual(len(artists), 2)

    def test_not_a_concert_allowlist_one_two_eight_twenty_named_artists(self):
        for total in (1, 2, 8, 20):
            names = tuple("ACT %02d" % index for index in range(total))
            page = show(names)
            with self.subTest(billed=total):
                cat = catalogue(names[:1] if total > 1 else ())
                approval = verify.verify(discovery(page), page, cat, TODAY)
                self.assertEqual(len(approval["event"]["artistIds"]), total)
                self.assertEqual(len(approval["newArtists"]),
                                 total - (1 if total > 1 else 0))
                event, artists = publish(approval, cat)
                self.assertEqual(len(event["artistIds"]), total)
                self.assertEqual(len(artists),
                                 total - (1 if total > 1 else 0))

    def test_release_party_and_short_genre_p_alternative_html(self):
        page = show(("SBRBS", "Atoem", "Sarakiniko", "DJ Cup of Tea"),
                    short_p=True, release_party=True, first_style="rock indéSaint-Brieuc")
        cat = catalogue()
        record = verify.verify(discovery(page), page, cat, TODAY)
        self.assertEqual(record["event"]["title"],
                         "SBRBS + Atoem + Sarakiniko + DJ Cup of Tea")
        self.assertEqual(record["event"]["artistIds"], [
            "sbrbs", "atoem", "sarakiniko", "dj-cup-of-tea"])
        publish(record, cat)

    def test_unnamed_guest_does_not_create_artist_from_biography(self):
        page = show(notes="La première partie sera surprise.")
        record = verify.verify(discovery(page), page, catalogue(), TODAY)
        self.assertEqual(len(record["event"]["artistIds"]), 2)
        self.assertNotIn("surprise", record["event"]["artistIds"])
        with self.assertRaises(ValueError):
            altered = page.replace(
                "<h2>Barre à Mine</h2>", "<h2>Unannounced Support</h2>")
            verify.verify(discovery(page), altered, catalogue(), TODAY)

    def test_wordpress_markup_spans_sup_tags_resale_h2_and_style_divs(self):
        # Same DOM structure as two live articles: several titarthome SPANs,
        # the first musician is marked by nomartiste and styleart, and an
        # unrelated ticket-resale H2 appears before the named acts.
        page = show()
        page = page.replace(
            "<h1>Novö Data Barre à Mine</h1>",
            '<h1 class="titevt"><span class="titarthome">Novö Data </span>'
            '<span class="titarthome">Barre à Mine</span></h1>')
        page = page.replace(
            "<h2>Novö Data</h2>",
            '<h2 class="nomartiste">Novö Data<sup>Artiste accompagné·e</sup></h2>')
        page = page.replace(
            '<div class=\'genre\'><span>rock post-punk Bretagne</span></div>',
            '<div id="styleart"><span>rock post-punk</span>'
            '<span>Bretagne</span></div>')
        page = page.replace(
            "<h2>Barre à Mine</h2>",
            '<h2 class="nomartiste">Barre à Mine</h2>')
        page = page.replace(
            '<div class=\'genre\'><span>electro post-indus Bretagne</span></div>',
            '<div id="styleart"><span>electro post-indus</span>'
            '<span>Douarnenez</span></div>')
        page = page.replace(
            '<h2 class="nomartiste">Novö Data',
            '<h2>Vous cherchez des billets ou vous avez un empêchement ?</h2>'
            '<p>Consultez notre bourse aux billets officielle pour échanger.</p>'
            '<h2 class="nomartiste">Novö Data')
        cat = catalogue()
        approved = verify.verify(discovery(page),page,cat,TODAY)
        self.assertEqual(approved["event"]["artistIds"],
                         ["novo-data", "barre-a-mine"])
        publish(approved,cat)

    def test_unnamed_support_as_explicit_headline_suffix(self):
        page=show().replace(
            "<h1>Novö Data Barre à Mine</h1>",
            "<h1>Novö Data Barre à Mine + première partie surprise</h1>")
        cat=catalogue()
        approved=verify.verify(discovery(page),page,cat,TODAY)
        self.assertEqual(approved["event"]["artistIds"],
                         ["novo-data","barre-a-mine"])
        self.assertEqual(approved["officialEvidence"][0]["unannouncedSupportLabel"],
                         "premiere partie surprise")
        publish(approved,cat)
        tampered=copy.deepcopy(approved)
        tampered["officialEvidence"][0]["unannouncedSupportLabel"]="guest"
        with self.assertRaises(ValueError):
            publish(tampered,cat)

    def test_missing_named_support_and_recommendations_are_not_evidence(self):
        page = show()
        row = discovery(page)
        for changed in (
            page.replace("<h2>Barre à Mine</h2>", "<h3>Barre à Mine</h3>"),
            page.replace("electro post-indus Bretagne", "inconnue"),
            page.replace("<h2>Barre à Mine</h2>", "<h2>Fake Band</h2>"),
            page.replace("<h1>Novö Data Barre à Mine</h1>",
                         "<h1>Novö Data Barre à Mine + Fake</h1>"),
        ):
            with self.subTest(changed=changed[-100:]), self.assertRaises(ValueError):
                verify.verify(row, changed, catalogue(), TODAY)

    def test_changes_cancellation_soldout_and_genre_review(self):
        page=show()
        row=discovery(page)
        bad = [
            page.replace("12 février 2027","13 février 2027"),
            page.replace("Club • 20h30","Grande Salle • 20h30"),
            page.replace("rock post-punk Bretagne","chanson FRA"),
            page.replace("Barre à Mine","Barre à Un Autre Groupe"),
            show(status="Concert annulé"),
            show(status="Concert reporté"),
        ]
        for altered in bad:
            with self.subTest(v=altered[-100:]), self.assertRaises(ValueError):
                verify.verify(row, altered, catalogue(), TODAY)
        sold_out = show(status="Concert complet")
        rec = verify.verify(discovery(sold_out), sold_out, catalogue(), TODAY)
        self.assertEqual(rec["event"]["status"], "confirmed")
        self.assertIsNone(rec["event"]["time"])
        publish(rec, catalogue())

    def test_quarantine_untrusted_source_alias_and_duplicate_fail_closed(self):
        page = show()
        lead = discovery(page)
        for k,val in (
            ("source", "another_provider"),
            ("sourceUrl", "https://evil.example/evenement/novodata-12fev27/"),
            ("reviewBucket", "possible_duplicate"),
            ("possibleExistingConcert", True),
            ("officialDetailFound", False),
            ("publicationAllowed", True),
            ("venue", "Un Autre Lieu"),
            ("classification", ["Metal"]),
        ):
            with self.subTest(k=k), self.assertRaises(ValueError):
                verify.verify({**lead,k:val},page,catalogue(),TODAY)
        cat=catalogue()
        cat["artists"]=[{"id":"old","name":"Other","aliases":["Novö Data"]}]
        with self.assertRaises(ValueError):
            verify.verify(lead,page,cat,TODAY)
        cat=catalogue()
        cat["events"].append({"id":"published", "officialUrl":URL,
                              "date":"2027-02-12","venueId":VENUE["id"],
                              "artistIds":[]})
        with self.assertRaises(ValueError):
            verify.verify(lead,page,cat,TODAY)

    def test_publisher_tamper_rejection_and_legacy_url_reserved(self):
        page=show()
        cat=catalogue()
        record=verify.verify(discovery(page),page,cat,TODAY)
        def edit_event(**changes):
            rec=copy.deepcopy(record);rec["event"].update(changes);return rec
        forged=[
            edit_event(date="2027-02-13"),
            edit_event(time="21:00"),
            edit_event(artistIds=["faux","barre-a-mine"]),
            edit_event(title="Novö Data"),
            edit_event(officialUrl="https://bonjour-minuit.fr/evenement/magma-02dec26/"),
        ]
        for rec in forged:
            with self.subTest(rec=rec["event"]),self.assertRaises(ValueError):
                publish(rec,cat)
        for k,val in (
            ("officialArtistNames",["Magma","Barre à Mine"]),
            ("sourceStructure","untrusted"),
            ("officialArtistBadges",["chanson","electro"]),
            ("verifiedNewArtists",[]),
            ("officialRoom","Une autre salle"),
            ("concertStartTimeConfirmed","21:00"),
        ):
            rec=copy.deepcopy(record)
            rec["officialEvidence"][0][k]=val
            with self.subTest(proof=k),self.assertRaises(ValueError):
                publish(rec,cat)

    def test_twice_observed_distinct_days_required_and_read_only(self):
        page=show()
        lead=discovery(page)
        record={"candidate":lead, "status":"pending_review",
                "stableObservations":1}
        registry={"items":{"test":record}}
        before={"schema":"grossesondes.concert.approvals.v1",
                "approvals":[]}
        untouched=copy.deepcopy(before)
        _out,r=official_recheck.process(
            registry,catalogue(),before,TODAY,
            fetch=lambda *_:self.fail("No fetch before 2 distinct days"))
        self.assertEqual(r["evaluated"],0)
        record["stableObservations"]=2
        out,r=official_recheck.process(
            registry,catalogue(),before,TODAY,fetch=lambda *_:page)
        self.assertEqual(r["evaluated"],1)
        self.assertEqual(len(r["newApprovals"]),1)
        self.assertEqual(len(out["approvals"]),1)
        self.assertEqual(before,untouched)


if __name__=="__main__":
    unittest.main()
