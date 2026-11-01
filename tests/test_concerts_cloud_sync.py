"""Contrôles de conservation et de fusion du catalogue Concerts (aucun réseau)."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import merge, protect_reference, validate_catalogue

BASE=json.loads((ROOT/"docs/grossesondes/concerts-reference.json").read_text(encoding="utf-8"))
NOW=__import__("datetime").date(2026,11,1)


def approval(event_id="go-c-20270201-nantes-groupe-essai"):
    return {
        "reviewDecision":"approved",
        "reviewedBy":"human",
        "reviewedAt":"2026-11-01",
        "officialEvidence":[{
            "url":"https://example.org/official/metal-event",
            "proofType":"official-organizer-or-venue",
            "checkedAt":"2026-11-01"
        }],
        "event":{
            "id":event_id,
            "title":"Groupe Essai",
            "date":"2027-02-01",
            "time":"20:30",
            "artistIds":["groupe-essai"],
            "venueId":"le-ferrailleur-nantes",
            "genres":["Metal"],
            "status":"confirmed",
            "officialUrl":"https://example.org/official/metal-event",
            "sourceType":"organisateur"
        },
        "newArtists":[{"id":"groupe-essai","name":"Groupe Essai"}]
    }


class ConcertsCloudSyncTests(unittest.TestCase):
    def test_reference_127_immutable(self):
        self.assertEqual(len(BASE["events"]),127)
        self.assertEqual(len(BASE["venues"]),53)
        self.assertEqual(len(BASE["artists"]),193)
        protect_reference(BASE,BASE)

    def test_only_precise_ferrailleur_geocorrection_is_allowed(self):
        from concerts_cloud_sync import FERRAILLEUR_LOCATION_FIX
        fixed=copy.deepcopy(BASE)
        venue=next(v for v in fixed["venues"] if v["id"]=="le-ferrailleur-nantes")
        venue.update(FERRAILLEUR_LOCATION_FIX)
        protect_reference(BASE,fixed)
        self.assertEqual(venue["address"],"Quai des Antilles")
        self.assertEqual(venue["postalCode"],"44200")
        self.assertEqual((venue["latitude"],venue["longitude"]),
                         (47.20058,-1.57365))
        for tampered in (
            ("latitude",47.217),("longitude",-1.554),
            ("postalCode","44000"),("city","Rennes"),
            ("geoSource","Sans preuve")
        ):
            with self.subTest(tampered=tampered):
                bad=copy.deepcopy(fixed)
                next(v for v in bad["venues"]
                     if v["id"]=="le-ferrailleur-nantes")[tampered[0]]=tampered[1]
                with self.assertRaises(ValueError):
                    protect_reference(BASE,bad)
        # A different venue must never piggyback on this exception.
        bad=copy.deepcopy(fixed)
        bad["venues"][0]["name"]="Nom de salle altéré"
        with self.assertRaises(ValueError):
            protect_reference(BASE,bad)

    def test_current_live_catalogue_retains_every_initial_event(self):
        live=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        protect_reference(BASE,live)
        validate_catalogue(live)
        self.assertGreaterEqual(len(live["events"]),127)
        self.assertEqual(live["events"][:127],BASE["events"])

    def test_approved_addition_only(self):
        new, stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                   "approvals":[approval()]},NOW)
        self.assertEqual(stats["newEvents"],1)
        self.assertEqual(stats["newArtists"],1)
        self.assertEqual(len(new["events"]),128)
        self.assertEqual(len(new["artists"]),194)
        self.assertEqual(new["events"][:127],BASE["events"])
        self.assertEqual(new["venues"],BASE["venues"])
        self.assertEqual(new["mode"],"preview-public-unlisted")
        validate_catalogue(new)

    def test_repeated_approval_does_not_duplicate(self):
        queue={"schema":"grossesondes.concert.approvals.v1",
               "approvals":[approval()]}
        first,_=merge(BASE,BASE,queue,NOW)
        again,stats=merge(BASE,first,queue,NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertEqual(stats["alreadyPublished"],1)
        self.assertEqual(len(again["events"]),128)

    def test_never_overwrite_existing_event(self):
        wrong=copy.deepcopy(BASE)
        wrong["events"][0]["title"]="Titre effacé"
        with self.assertRaises(ValueError):
            protect_reference(BASE,wrong)

    def test_no_deletion_of_original_events(self):
        wrong=copy.deepcopy(BASE)
        wrong["events"].pop()
        with self.assertRaises(ValueError):
            protect_reference(BASE,wrong)

    def test_missing_approval_is_held(self):
        bad=approval()
        bad["reviewDecision"]="pending"
        x,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                 "approvals":[bad]},NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertEqual(len(stats["held"]),1)
        self.assertEqual(x,BASE)

    def test_fresh_automated_official_recheck_is_accepted(self):
        a=approval("go-c-20270201-toulouse-groupe-essai")
        a["reviewedBy"]="automated-official-recheck"
        a["event"]["venueId"]="le-rex-toulouse"
        a["event"]["sourceType"]="salle"
        official="https://www.lerextoulouse.com/fr/programmation/groupe-essai/"
        a["event"]["officialUrl"]=official
        a["officialEvidence"][0]["url"]=official
        a["officialEvidence"][0]["checkedFields"]=["artists","date","venue","genre"]
        out,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                  "approvals":[a]},NOW)
        self.assertEqual(stats["newEvents"],1)
        self.assertEqual(stats["held"],[])
        self.assertEqual(out["events"][-1]["venueId"],"le-rex-toulouse")

    def test_automated_recheck_rejects_missing_fields(self):
        a=approval("go-c-20270201-toulouse-groupe-essai")
        a["reviewedBy"]="automated-official-recheck"
        a["event"]["venueId"]="le-rex-toulouse"
        a["event"]["sourceType"]="salle"
        official="https://www.lerextoulouse.com/fr/programmation/groupe-essai/"
        a["event"]["officialUrl"]=official
        a["officialEvidence"][0]["url"]=official
        a["officialEvidence"][0]["checkedFields"]=["date","venue"]
        _,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                 "approvals":[a]},NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertTrue(stats["held"])

    def test_automated_recheck_rejects_non_official_domain(self):
        a=approval("go-c-20270201-nantes-groupe-essai")
        a["reviewedBy"]="automated-official-recheck"
        a["officialEvidence"][0]["checkedFields"]=["artists","date","venue","genre"]
        _,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                 "approvals":[a]},NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertTrue(stats["held"])

    def test_molotov_auto_evidence_known_artists_only(self):
        artist = BASE["artists"][0]
        a = approval("go-c-20270201-marseille-" + artist["id"])
        official = "https://lemolotov.com/events/" + artist["id"] + "/"
        a["reviewedBy"] = "automated-official-recheck"
        a["event"]["venueId"] = "le-molotov-marseille"
        a["event"]["title"] = artist["name"]
        a["event"]["artistIds"] = [artist["id"]]
        a["event"]["officialUrl"] = official
        a["event"]["sourceType"] = "salle"
        a["newArtists"] = []
        a["officialEvidence"][0]["url"] = official
        a["officialEvidence"][0]["checkedFields"] = [
            "artists", "date", "venue", "genre"
        ]
        out, stats = merge(BASE, BASE, {"schema": "grossesondes.concert.approvals.v1",
                                        "approvals": [a]}, NOW)
        self.assertEqual(stats["newEvents"], 1)
        self.assertEqual(stats["held"], [])
        self.assertEqual(out["events"][-1]["venueId"], "le-molotov-marseille")

        from copy import deepcopy
        for mutant in ("wrong-venue", "wrong-host", "agenda-url", "new-artist",
                       "missing-proof"):
            with self.subTest(mutant=mutant):
                bad = deepcopy(a)
                if mutant == "wrong-venue":
                    bad["event"]["venueId"] = "le-ferrailleur-nantes"
                if mutant == "wrong-host":
                    bad["event"]["officialUrl"] = "https://example.org/events/malicious/"
                    bad["officialEvidence"][0]["url"] = bad["event"]["officialUrl"]
                if mutant == "agenda-url":
                    bad["event"]["officialUrl"] = "https://lemolotov.com/events/"
                    bad["officialEvidence"][0]["url"] = bad["event"]["officialUrl"]
                if mutant == "new-artist":
                    bad["newArtists"] = [{"id": "unverified-band", "name": "Unverified Band"}]
                    bad["event"]["artistIds"] = ["unverified-band"]
                if mutant == "missing-proof":
                    bad["officialEvidence"][0]["checkedFields"] = ["date", "venue"]
                _, denied = merge(BASE, BASE, {
                    "schema": "grossesondes.concert.approvals.v1", "approvals": [bad]
                }, NOW)
                self.assertEqual(denied["newEvents"], 0)
                self.assertTrue(denied["held"])

    def test_event_third_party_only_rejected(self):
        bad=approval()
        bad["event"]["sourceType"]="aggregator"
        _,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                  "approvals":[bad]},NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertEqual(len(stats["held"]),1)

    def test_approval_without_exact_official_proof_rejected(self):
        bad=approval()
        bad["officialEvidence"][0]["url"]="https://another.example/test"
        _,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                  "approvals":[bad]},NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertEqual(len(stats["held"]),1)

    def test_event_date_must_be_valid_future(self):
        bad=approval()
        bad["event"]["date"]="2025-03-02"
        _,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                  "approvals":[bad]},NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertTrue(stats["held"])

    def test_missing_artist_id_rejected(self):
        bad=approval()
        bad["newArtists"]=[]
        _,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                  "approvals":[bad]},NOW)
        self.assertEqual(stats["newEvents"],0)
        self.assertTrue(stats["held"])

    def test_no_approval_means_exactly_127(self):
        current,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                       "approvals":[]},NOW)
        self.assertEqual(current,BASE)
        self.assertEqual(stats["newEvents"],0)


if __name__=="__main__":
    unittest.main()
