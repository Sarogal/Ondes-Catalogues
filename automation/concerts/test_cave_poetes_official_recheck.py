"""Cave aux Poètes recheck: independent source, large bills and publisher safety."""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cave_poetes_adapter as source
import cave_poetes_official_recheck as check
import official_recheck as orchestrator
from concerts_cloud_sync import validate_approval
from test_cave_poetes_adapter import card, detail, SOURCE

TODAY = dt.date(2026, 11, 17)
URL = "https://caveauxpoetes.com/evenement/dalaidrama-dewaere/"
VENUE = {"id": "la-cave-aux-poetes-roubaix",
         "name": "La Cave aux Poètes", "city": "Roubaix",
         "latitude": 50.6921711, "longitude": 3.1692704}
DATE = "ven. 12 février 2027"
CLOCK = "OUVERTURE DES PORTES : 19H30 / CONCERTS : 20h"


def html(names=("Dewaere", "DALAÏDRAMA"), clock=CLOCK):
    return detail(date=DATE, artists=names, bio=(
        "Dewaere est un projet de noise punk et noise rock."
    ), clock=clock)


def candidate(page=None, names=("Dewaere", "DALAÏDRAMA")):
    page = page if page is not None else html(names)
    row = source.candidate(
        page, URL,
        source.cards(card(URL, date=DATE, artists=names))[0],
        SOURCE, TODAY.isoformat())
    return {**row, "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False}


def catalog(known=()):
    return {"schemaVersion": 1, "mode": "preview-public-unlisted",
            "venues": [copy.deepcopy(VENUE)],
            "artists": [{"id":source.norm(x).replace(" ","-"),
                         "name": x, "aliases": []} for x in known],
            "events": []}


def publish(record, c):
    return validate_approval(
        record,
        {x["id"]:x for x in c["venues"]},
        {x["id"]:x for x in c["artists"]},
        TODAY)


class CaveOfficialRecheckTests(unittest.TestCase):
    def test_real_pair_stable_future_and_start_time(self):
        page = html()
        c = catalog()
        approval = orchestrator.verify(candidate(page), page, c, TODAY)
        self.assertEqual(approval["event"]["date"], "2027-02-12")
        self.assertEqual(approval["event"]["time"], "20:00")
        self.assertEqual(approval["event"]["artistIds"],
                         ["dewaere", "dalaidrama"])
        self.assertEqual(approval["event"]["genres"], ["Punk"])
        self.assertEqual(len(approval["newArtists"]), 2)
        p = approval["officialEvidence"][0]
        self.assertEqual(p["officialArtistNames"], ["Dewaere", "DALAÏDRAMA"])
        self.assertEqual(p["concertStartTimeConfirmed"], "20:00")
        evt, new = publish(approval, c)
        self.assertEqual(evt["artistIds"], ["dewaere", "dalaidrama"])
        self.assertEqual(len(new), 2)

    def test_one_two_eight_twenty_new_groups_publisher(self):
        for count in (1, 2, 8, 20, 24):
            with self.subTest(count=count):
                names = tuple("ACT %02d" % i for i in range(count))
                page = html(names)
                row = candidate(page, names)
                approval = check.verify(row, page, catalog(), TODAY)
                self.assertEqual(len(approval["event"]["artistIds"]), count)
                self.assertEqual(len(approval["newArtists"]), count)
                evt, new = publish(approval, catalog())
                self.assertEqual(len(evt["artistIds"]), count)
                self.assertEqual(len(new), count)

    def test_unannounced_final_support_is_not_invented(self):
        acts = ("Dewaere", "Première partie")
        page = html(acts)
        c = catalog()
        approval = check.verify(candidate(page, acts), page, c, TODAY)
        self.assertEqual(approval["event"]["title"], "Dewaere")
        self.assertEqual(approval["event"]["artistIds"], ["dewaere"])
        self.assertEqual(approval["newArtists"], [{"id":"dewaere","name":"Dewaere"}])
        self.assertEqual(approval["officialEvidence"][0]["unannouncedSupportLabel"],
                         "premiere partie")
        publish(approval,c)
        # Placeholder in leading position is not a certified headliner.
        wrong = ("Première partie", "Dewaere")
        with self.assertRaises(ValueError):
            check.verify(candidate(html(wrong), wrong), html(wrong), c, TODAY)

    def test_existing_group_with_new_support(self):
        page = html()
        c = catalog(["Dewaere"])
        event = check.verify(candidate(page), page, c, TODAY)
        self.assertEqual(len(event["newArtists"]), 1)
        self.assertEqual(event["newArtists"][0]["id"], "dalaidrama")
        publish(event, c)

    def test_explicit_concert_start_vs_opening_doors(self):
        p = html(clock="OUVERTURE DES PORTES : 19H30")
        row = candidate(p)
        c = catalog()
        approval = check.verify(row, p, c, TODAY)
        self.assertIsNone(approval["event"]["time"])
        self.assertNotIn("concertStartTime", approval["officialEvidence"][0]["checkedFields"])
        publish(approval, c)
        forged = copy.deepcopy(approval)
        forged["event"]["time"] = "19:30"
        with self.assertRaises(ValueError):
            publish(forged, c)

    def test_two_day_stability_rotation_and_no_write(self):
        row = {"candidate": candidate(), "status": "pending_review",
               "stableObservations": 1}
        registry = {"schema":"grossesondes.concert.intake.v1",
                    "items":{"roubaix":row}}
        before = {"schema":"grossesondes.concert.approvals.v1", "approvals":[]}
        _o, r = orchestrator.process(
            registry, catalog(), before, TODAY,
            fetch=lambda *_: self.fail("No fetch on single day"))
        self.assertEqual(r["evaluated"],0)
        row["stableObservations"]=2
        result, r = orchestrator.process(
            registry, catalog(), before, TODAY, fetch=lambda *_: html())
        self.assertEqual(r["evaluated"],1)
        self.assertEqual(len(result["approvals"]),1)
        self.assertEqual(before["approvals"],[])

    def test_named_artist_missing_from_first_party_detail_is_held(self):
        page = html()
        lead = candidate(page)
        modified = page.replace(
            '<span class="artistehome">DALAÏDRAMA</span>', "")
        with self.assertRaises(ValueError):
            check.verify(lead, modified, catalog(), TODAY)

    def test_mismatched_date_venue_genre_and_status_fail_closed(self):
        original = html()
        lead = candidate(original)
        wrong = (
            original.replace("12 février 2027", "13 février 2027"),
            original.replace("La Cave aux Poètes</a>", "Autre Salle</a>"),
            original.replace("noise punk", "electro pop"),
            original.replace("Concert couche-tôt", "Festival"),
            original.replace("CONCERTS : 20h", "CONCERTS : 21h"),
        )
        for page in wrong:
            with self.subTest(page=page[-150:]),self.assertRaises(ValueError):
                check.verify(lead, page, catalog(), TODAY)
        for k,v in (
            ("sourceUrl","https://evil.example/evenement/fake/"),
            ("reviewBucket","genre_unknown"),
            ("possibleExistingConcert",True),
            ("officialDetailFound",False),
            ("publicationAllowed",True),
            ("reviewRequired",False),
            ("venue","Autre Salle"),
        ):
            with self.subTest(k=k),self.assertRaises(ValueError):
                check.verify({**lead,k:v}, original, catalog(), TODAY)

    def test_collisions_and_manipulated_publisher_proofs_fail_closed(self):
        page = html()
        c = catalog()
        lead = candidate(page)
        c["events"].append({"id":"already", "officialUrl":URL,
                            "date":"2027-02-12", "venueId":VENUE["id"],
                            "artistIds":[]})
        with self.assertRaises(ValueError):
            check.verify(lead, page, c, TODAY)
        c = catalog()
        c["artists"]=[{"id":"old", "name":"Other", "aliases":["Dewaere"]}]
        with self.assertRaises(ValueError):
            check.verify(lead, page, c, TODAY)
        c = catalog()
        original = check.verify(lead, page, c, TODAY)
        for mutate in (
            lambda a:a["event"].update({"time":"19:30"}),
            lambda a:a["event"].update({"date":"2027-02-13"}),
            lambda a:a["event"].update({"artistIds":["fake","dalaidrama"]}),
            lambda a:a["event"].update({"title":"Dewaere"}),
            lambda a:a["officialEvidence"][0].update(
                {"officialArtistNames":["Fake","DALAÏDRAMA"]}),
            lambda a:a["officialEvidence"][0].update(
                {"verifiedNewArtists":[]}),
            lambda a:a["officialEvidence"][0].update(
                {"concertStartTimeConfirmed":"19:30"}),
            lambda a:a["officialEvidence"][0].update(
                {"sourceStructure":"untrusted"}),
        ):
            forged = copy.deepcopy(original)
            mutate(forged)
            with self.subTest(forged=forged["event"]),self.assertRaises(
                    (ValueError, TypeError, KeyError)):
                publish(forged, c)


if __name__ == "__main__":
    unittest.main()
