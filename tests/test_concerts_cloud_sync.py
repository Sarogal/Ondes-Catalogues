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
    def pilot_queue(self, with_events=True):
        from concerts_cloud_sync import PILOT_VENUES
        records=[]
        # Legacy fixture intentionally covers only its original two pilot venues.
        for pilot in (PILOT_VENUES["jokers-pub-angers"],
                      PILOT_VENUES["le-brin-de-zinc-barberaz"]):
            records.append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[
                    {"url":pilot["officialUrl"],
                     "proofType":"official-venue-address",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["name","address","postalCode","city"]},
                    {"url":pilot["locationUrl"],
                     "proofType":"openstreetmap-venue-node",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["venueName","coordinates"]}
                ],
                "venue":copy.deepcopy(pilot["venue"])
            })
        events=[]
        if with_events:
            for date,idpart,title,names,time in (
                ("2026-11-27","charles-de-goal","Charles de Goal",
                 ["Charles de Goal"],"21:00"),
                ("2026-12-11","aurore-brutaliste","Aurore + Brutaliste",
                 ["Aurore","Brutaliste"],"20:30")
            ):
                url=("https://www.jokerspubangers.com/"
                     "jokers-concert-programmation-"+idpart+".html")
                events.append({
                    "reviewDecision":"approved",
                    "reviewedBy":"independent-official-verifier",
                    "reviewedAt":"2026-11-02",
                    "officialEvidence":[{
                        "url":url,
                        "proofType":"official-organizer-or-venue",
                        "checkedAt":"2026-11-02",
                        "checkedFields":["artists","date","venue","genre","startTime"]
                    }],
                    "event":{
                        "id":"go-c-"+date.replace("-","")+"-angers-"+idpart,
                        "title":title,"date":date,"time":time,
                        "artistIds":[n.lower().replace(" ","-") for n in names],
                        "venueId":"jokers-pub-angers","genres":["Hardcore","Punk"],
                        "status":"confirmed","officialUrl":url,"sourceType":"salle"
                    },
                    "newArtists":[{"id":n.lower().replace(" ","-"),"name":n}
                                  for n in names]
                })
        return {"schema":"grossesondes.concert.approvals.v1",
                "venueApprovals":records,"approvals":events}

    def backstage_queue(self):
        from concerts_cloud_sync import PILOT_VENUES, BACKSTAGE_VERIFIED
        pilot=PILOT_VENUES["backstage-by-the-mill-paris"]
        venue_approval={
            "reviewDecision":"approved",
            "reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-02",
            "venue":copy.deepcopy(pilot["venue"]),
            "officialEvidence":[
                {"url":pilot["officialUrl"],"proofType":"official-venue-address",
                 "checkedAt":"2026-11-02",
                 "checkedFields":["name","address","postalCode","city"]},
                {"url":pilot["locationUrl"],"proofType":"openstreetmap-venue-node",
                 "checkedAt":"2026-11-02",
                 "checkedFields":["venueName","coordinates"]},
            ]
        }
        names={"turmion-katilot":"Turmion Kätilöt","despairsray":"D’espairsRay",
               "thulcandra":"Thulcandra","yoth-iria":"Yoth Iria","vorga":"Vorga"}
        approvals=[]
        for event_id, spec in BACKSTAGE_VERIFIED.items():
            approvals.append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":spec["url"],"proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]}],
                "event":{
                    "id":event_id,"title":spec["title"],"date":spec["date"],
                    "time":None,"artistIds":copy.deepcopy(spec["artistIds"]),
                    "venueId":"backstage-by-the-mill-paris",
                    "genres":copy.deepcopy(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["url"],"sourceType":"salle"
                },
                "newArtists":[{"id":i,"name":names[i]} for i in spec["artistIds"]]
            })
        return {"schema":"grossesondes.concert.approvals.v1",
                "venueApprovals":[venue_approval],"approvals":approvals}

    def test_backstage_three_events_and_true_theatre_pin(self):
        day=__import__("datetime").date(2026,11,2)
        queue=self.backstage_queue()
        out,stats=merge(BASE,BASE,queue,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newVenues"],1)
        self.assertEqual(stats["newEvents"],3)
        self.assertEqual(stats["newArtists"],5)
        self.assertEqual(len(out["events"]),130)
        self.assertEqual(len(out["venues"]),54)
        self.assertEqual(len(out["artists"]),198)
        self.assertEqual(out["events"][:127],BASE["events"])
        self.assertEqual(out["venues"][:53],BASE["venues"])
        venue=out["venues"][-1]
        self.assertEqual((venue["latitude"],venue["longitude"]),(48.8842402,2.3321006))
        self.assertEqual(venue["geoSource"],
                         "https://www.openstreetmap.org/api/0.6/node/4428897899")
        self.assertTrue(all(e["time"] is None for e in out["events"][-3:]))
        protect_reference(BASE,out)
        validate_catalogue(out)
        repeat,again=merge(BASE,out,queue,day)
        self.assertEqual(again["newEvents"],0)
        self.assertEqual(again["alreadyPublished"],3)
        self.assertEqual(again["alreadyRegisteredVenues"],1)
        self.assertEqual(repeat,out)

    def test_backstage_requires_independent_specific_approval_every_time(self):
        day=__import__("datetime").date(2026,11,2)
        source=self.backstage_queue()
        baseline,stats=merge(BASE,BASE,source,day)
        self.assertEqual(stats["held"],[])
        cases=("wrong-domain","wrong-lineup","unlisted-event","fake-time",
               "wrong-genre","wrong-reviewer","missing-official-proof",
               "stale-check","wrong-pin")
        for case in cases:
            with self.subTest(case=case):
                q=copy.deepcopy(source)
                a=q["approvals"][0]
                if case=="wrong-domain":
                    a["event"]["officialUrl"]="https://example.com/agenda/fake/"
                elif case=="wrong-lineup":
                    a["event"]["artistIds"]=["nonexisting"]
                elif case=="unlisted-event":
                    a["event"]["id"]="go-c-20270227-paris-guess"
                elif case=="fake-time":
                    a["event"]["time"]="19:00"
                elif case=="wrong-genre":
                    a["event"]["genres"]=["Electro"]
                elif case=="wrong-reviewer":
                    a["reviewedBy"]="automated-official-recheck"
                elif case=="missing-official-proof":
                    a["officialEvidence"]=[]
                elif case=="stale-check":
                    a["reviewedAt"]="2026-10-01"
                elif case=="wrong-pin":
                    q["venueApprovals"][0]["venue"]["latitude"]+=0.01
                result,reports=merge(BASE,BASE,q,day)
                self.assertTrue(reports["held"])
                if case=="wrong-pin":
                    self.assertEqual(reports["newEvents"],0)
                    self.assertEqual(reports["newVenues"],0)
                else:
                    self.assertEqual(reports["newEvents"],2)
        with self.assertRaises(ValueError):
            merge(BASE,baseline,{"schema":source["schema"],"approvals":[],
                                 "venueApprovals":source["venueApprovals"]},day)

    def glazart_queue(self):
        from concerts_cloud_sync import PILOT_VENUES, GLAZART_VERIFIED
        v=PILOT_VENUES["glazart-paris"]
        venue={
            "reviewDecision":"approved",
            "reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-02",
            "venue":copy.deepcopy(v["venue"]),
            "officialEvidence":[{
                "url":v["officialUrl"],
                "proofType":"official-venue-address",
                "checkedAt":"2026-11-02",
                "checkedFields":["name","address","postalCode","city"]
            },{
                "url":v["locationUrl"],
                "proofType":"openstreetmap-venue-way",
                "checkedAt":"2026-11-02",
                "checkedFields":["venueName","coordinates"]
            }]
        }
        names={"party-cannon":"Party Cannon",
               "internal-bleeding":"Internal Bleeding",
               "guttural-slug":"Guttural Slug"}
        approvals=[]
        for event_id, spec in GLAZART_VERIFIED.items():
            if event_id in ("go-c-20261106-paris-lagrimas",
                            "go-c-20261130-paris-black-sabbitch",
                            "go-c-20261104-paris-eyehategod",
                            "go-c-20261114-paris-the-vintage-caravan"):
                continue  # Earlier two-bill fixture remains stable.
            approvals.append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":spec["officialUrl"],
                    "proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]
                }],
                "event":{
                    "id":event_id,
                    "title":spec["title"],
                    "date":spec["date"],
                    "time":None,
                    "artistIds":list(spec["artistIds"]),
                    "venueId":"glazart-paris",
                    "genres":list(spec["genres"]),
                    "status":"confirmed",
                    "officialUrl":spec["officialUrl"],
                    "sourceType":"salle",
                    "organizer":"Glazart"
                },
                "newArtists":[{"id":k,"name":names[k]} for k in spec["newArtistIds"]]
            })
        return {"schema":"grossesondes.concert.approvals.v1",
                "venueApprovals":[venue], "approvals":approvals}

    def test_glazart_named_osm_way_and_two_correct_lineups_publish_once(self):
        day=__import__("datetime").date(2026,11,2)
        queue=self.glazart_queue()
        new,stats=merge(BASE,BASE,queue,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newEvents"],2)
        self.assertEqual(stats["newVenues"],1)
        self.assertEqual(stats["newArtists"],3)
        self.assertEqual(len(new["events"]),129)
        self.assertEqual(len(new["venues"]),54)
        self.assertEqual(len(new["artists"]),196)
        self.assertEqual(new["venues"][-1]["geoSource"],
                         "https://www.openstreetmap.org/api/0.6/way/64038567")
        self.assertIn("centre du bâtiment",new["venues"][-1]["geoPrecision"])
        self.assertEqual(new["events"][-2]["artistIds"],
                         ["sunami","desolated","missing-link","extinguish"])
        self.assertEqual(new["events"][-1]["artistIds"],
                         ["party-cannon","internal-bleeding","guttural-slug"])
        self.assertTrue(all(e["time"] is None for e in new["events"][-2:]))
        protect_reference(BASE,new)
        validate_catalogue(new)
        repeat,again=merge(BASE,new,queue,day)
        self.assertEqual(repeat,new)
        self.assertEqual(again["alreadyPublished"],2)
        self.assertEqual(again["newEvents"],0)
        self.assertEqual(again["newVenues"],0)

    def test_glazart_blocks_wrong_venue_point_lineup_time_or_official_domain(self):
        day=__import__("datetime").date(2026,11,2)
        for variant in ("invalid-way","fake-node-type","unlisted-show",
                        "missing-desolated","missing-guttural-slug",
                        "wrong-domain","fake-time","wrong-genre",
                        "untrusted-reviewer","missing-proof"):
            with self.subTest(variant=variant):
                queue=self.glazart_queue()
                a=queue["approvals"][0]
                b=queue["approvals"][1]
                if variant=="invalid-way":
                    queue["venueApprovals"][0]["venue"]["latitude"]+=.01
                elif variant=="fake-node-type":
                    queue["venueApprovals"][0]["officialEvidence"][1]["proofType"]="openstreetmap-venue-node"
                elif variant=="unlisted-show":
                    a["event"]["id"]="go-c-20261128-paris-unknown"
                elif variant=="missing-desolated":
                    a["event"]["artistIds"].remove("desolated")
                elif variant=="missing-guttural-slug":
                    b["event"]["artistIds"].remove("guttural-slug")
                elif variant=="wrong-domain":
                    a["event"]["officialUrl"]="https://evil.example/concert"
                elif variant=="fake-time":
                    a["event"]["time"]="19:00"
                elif variant=="wrong-genre":
                    a["event"]["genres"]=["Pop"]
                elif variant=="untrusted-reviewer":
                    a["reviewedBy"]="automated-official-recheck"
                elif variant=="missing-proof":
                    a["officialEvidence"].clear()
                out,stats=merge(BASE,BASE,queue,day)
                self.assertTrue(stats["held"])
                self.assertEqual(stats["newVenues"],0 if variant in
                                 ("invalid-way","fake-node-type") else 1)
                self.assertEqual(stats["newEvents"],0 if variant in
                                 ("invalid-way","fake-node-type") else 1)

    def glazart_november_queue(self):
        from concerts_cloud_sync import GLAZART_VERIFIED
        queue=self.glazart_queue()
        queue["approvals"]=[]
        for ident in ("go-c-20261106-paris-lagrimas",
                      "go-c-20261130-paris-black-sabbitch"):
            spec=GLAZART_VERIFIED[ident]
            queue["approvals"].append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":spec["officialUrl"],
                    "proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]
                }],
                "event":{
                    "id":ident,"title":spec["title"],"date":spec["date"],
                    "time":None,"artistIds":list(spec["artistIds"]),
                    "venueId":"glazart-paris","genres":list(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["officialUrl"],
                    "sourceType":"salle"
                },
                "newArtists":([{"id":"black-sabbitch","name":"Black Sabbitch"}]
                    if ident.endswith("black-sabbitch") else [])
            })
        return queue

    def test_glazart_lagrimas_known_and_black_sabbitch_added_no_duplicate(self):
        today=__import__("datetime").date(2026,11,2)
        # In the live catalogue, Lagrimas already exists due to Rock n' Eat.
        # Simulate only that known artist without relaxing the immutable 127.
        seeded=copy.deepcopy(BASE)
        seeded["artists"].append({"id":"lagrimas","name":"Lagrimas","aliases":[]})
        protect_reference(BASE,seeded)
        queue=self.glazart_november_queue()
        result,stats=merge(BASE,seeded,queue,today)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newVenues"],1)
        self.assertEqual(stats["newEvents"],2)
        self.assertEqual(stats["newArtists"],1)
        self.assertEqual(result["events"][-2]["title"],"Lagrimas")
        self.assertEqual(result["events"][-1]["title"],"Black Sabbitch")
        self.assertEqual(result["events"][-2]["genres"],["Hardcore","Screamo"])
        self.assertEqual(result["events"][-1]["genres"],["Doom"])
        self.assertTrue(all(e["time"] is None for e in result["events"][-2:]))
        self.assertEqual(len(result["artists"]),195)
        self.assertEqual(len([a for a in result["artists"] if a["id"]=="lagrimas"]),1)
        repeat,second=merge(BASE,result,queue,today)
        self.assertEqual(repeat,result)
        self.assertEqual(second["alreadyPublished"],2)
        self.assertEqual(second["newEvents"],0)

    def test_glazart_november_rejects_unverified_time_genre_and_identity(self):
        day=__import__("datetime").date(2026,11,2)
        seed=copy.deepcopy(BASE)
        seed["artists"].append({"id":"lagrimas","name":"Lagrimas","aliases":[]})
        for variant in ("unapproved-date","invented-start","wrong-artist",
                        "wrong-genre","missing-proof","new-show",
                        "wrong-source","missing-black-sabbitch",
                        "other-reviewer"):
            with self.subTest(variant=variant):
                q=self.glazart_november_queue()
                item=q["approvals"][1]
                event=item["event"]
                if variant=="unapproved-date":
                    event["date"]="2026-12-01"
                elif variant=="invented-start":
                    event["time"]="19:00"
                elif variant=="wrong-artist":
                    event["artistIds"]=["invented-artist"]
                elif variant=="wrong-genre":
                    event["genres"]=["Pop"]
                elif variant=="missing-proof":
                    item["officialEvidence"]=[]
                elif variant=="new-show":
                    event["id"]="go-c-20261130-paris-fake"
                elif variant=="wrong-source":
                    event["officialUrl"]="https://example.net/not-official"
                elif variant=="missing-black-sabbitch":
                    item["newArtists"]=[]
                elif variant=="other-reviewer":
                    item["reviewedBy"]="automated-official-recheck"
                result,stats=merge(BASE,seed,q,day)
                self.assertEqual(stats["newEvents"],1)
                self.assertEqual(len(stats["held"]),1)
                self.assertEqual(result["events"][-1]["title"],"Lagrimas")


    def glazart_new_lineups_queue(self):
        from concerts_cloud_sync import GLAZART_VERIFIED
        queue=self.glazart_queue()
        queue["approvals"]=[]
        extra_names={"eyehategod":"Eyehategod","deafkids":"Deafkids"}
        for ident in ("go-c-20261104-paris-eyehategod",
                      "go-c-20261114-paris-the-vintage-caravan"):
            spec=GLAZART_VERIFIED[ident]
            primary_fields=spec.get("primaryCheckedFields",
                                     ["artists","date","venue","genre"])
            queue["approvals"].append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":spec["officialUrl"],
                    "proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":list(primary_fields)
                },{
                    "url":spec["secondaryUrl"],
                    "proofType":spec["secondaryProofType"],
                    "checkedAt":"2026-11-02",
                    "checkedFields":list(spec["secondaryCheckedFields"])
                }],
                "event":{
                    "id":ident,"title":spec["title"],"date":spec["date"],
                    "time":None,"artistIds":list(spec["artistIds"]),
                    "venueId":"glazart-paris","genres":list(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["officialUrl"],
                    "sourceType":"salle","organizer":"Glazart"
                },
                "newArtists":[{"id":key,"name":extra_names[key]}
                    for key in spec["newArtistIds"]]
            })
        return queue

    def test_glazart_two_documented_lineups_publish_without_guest_artists(self):
        day=__import__("datetime").date(2026,11,2)
        queue=self.glazart_new_lineups_queue()
        result,stats=merge(BASE,BASE,queue,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newEvents"],2)
        self.assertEqual(stats["newArtists"],2)
        self.assertEqual(stats["newVenues"],1)
        self.assertEqual([e["title"] for e in result["events"][-2:]],
                         ["Eyehategod + Deafkids","The Vintage Caravan + Damantra"])
        self.assertEqual(result["events"][-2]["artistIds"],
                         ["eyehategod","deafkids"])
        self.assertTrue(all("guest" not in str(e["artistIds"])
                            for e in result["events"][-2:]))
        self.assertTrue(all(e["time"] is None for e in result["events"][-2:]))
        validate_catalogue(result)
        self.assertEqual(result["events"][:127],BASE["events"])
        repeated,second=merge(BASE,result,queue,day)
        self.assertEqual(repeated,result)
        self.assertEqual(second["newEvents"],0)
        self.assertEqual(second["alreadyPublished"],2)

    def test_glazart_vintage_ticket_and_eyehategod_guest_proofs_are_exact(self):
        day=__import__("datetime").date(2026,11,2)
        for variant in ("invented-guest","missing-promo","wrong-promo",
                        "fake-all-artists-on-venue","missing-promo-artists",
                        "wrong-primary-url","extra-unknown-date",
                        "fake-start","wrong-second-kind","unknown-event"):
            with self.subTest(variant=variant):
                queue=self.glazart_new_lineups_queue()
                vintage=queue["approvals"][1]
                e=vintage["event"]
                if variant=="invented-guest":
                    e["artistIds"][1]="guest"
                elif variant=="missing-promo":
                    vintage["officialEvidence"].pop()
                elif variant=="wrong-promo":
                    vintage["officialEvidence"][1]["url"]="https://example.org/fake"
                elif variant=="fake-all-artists-on-venue":
                    vintage["officialEvidence"][0]["checkedFields"]=[
                        "artists","date","venue","genre"]
                    # Missing the explicit "leadArtist" field is a failure.
                elif variant=="missing-promo-artists":
                    vintage["officialEvidence"][1]["checkedFields"]=[
                        "date","venue","genre"]
                elif variant=="wrong-primary-url":
                    e["officialUrl"]="https://evil.test/14-11-26-concert-the-vintage-caravan/"
                    vintage["officialEvidence"][0]["url"]=e["officialUrl"]
                elif variant=="extra-unknown-date":
                    e["date"]="2026-12-14"
                elif variant=="fake-start":
                    e["time"]="20:00"
                elif variant=="wrong-second-kind":
                    vintage["officialEvidence"][1]["proofType"]="organizer-submitted-partner"
                elif variant=="unknown-event":
                    e["id"]="go-c-20261114-paris-fake"
                result,stats=merge(BASE,BASE,queue,day)
                self.assertEqual(stats["newEvents"],1)
                self.assertEqual(len(stats["held"]),1)
                self.assertFalse(any(e["id"]=="go-c-20261114-paris-the-vintage-caravan"
                                  for e in result["events"]))

    def regional_reviewed_queue(self):
        from concerts_cloud_sync import PILOT_VENUES, REGIONAL_APPROVED
        named={
            "lagrimas":"Lagrimas","the-prestige":"The Prestige",
            "toxic-shock":"Toxic Shock","sick-lame-lazy":"Sick Lame & Lazy"}
        venues=[]
        for venue_id in ("rock-n-eat-lyon","la-maison-bleue-strasbourg"):
            p=PILOT_VENUES[venue_id]
            venues.append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "venue":copy.deepcopy(p["venue"]),
                "officialEvidence":[{
                    "url":p["officialUrl"],"proofType":"official-venue-address",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["name","address","postalCode","city"]
                },{
                    "url":p["locationUrl"],"proofType":"openstreetmap-venue-node",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["venueName","coordinates"]
                }]
            })
        rows=[]
        for ident, spec in REGIONAL_APPROVED.items():
            if ident=="go-c-20261113-strasbourg-local-heroes":
                continue  # This two-event fixture retains its original scope.
            rows.append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":spec["officialUrl"],
                    "proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]
                },{
                    "url":spec["venueCalendar"],
                    "proofType":"first-party-venue-calendar",
                    "checkedAt":"2026-11-02",
                    "checkedFields":(["artists","date","venue"] if
                                     spec["venueId"]=="rock-n-eat-lyon"
                                     else ["artists","date","venue","genre"])
                }],
                "event":{
                    "id":ident,"title":spec["title"],"date":spec["date"],
                    "time":None,"artistIds":list(spec["artistIds"]),
                    "venueId":spec["venueId"],"genres":list(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["officialUrl"],
                    "ticketUrl":spec["officialUrl"],"sourceType":"organisateur",
                    "organizer":"Independent reviewed venue"
                },
                "newArtists":[{"id":x,"name":named[x]}
                              for x in spec["newArtistIds"]]
            })
        return {"schema":"grossesondes.concert.approvals.v1",
                "approvals":rows,"venueApprovals":venues}

    def local_heroes_approval(self):
        from concerts_cloud_sync import REGIONAL_APPROVED
        ident="go-c-20261113-strasbourg-local-heroes"
        spec=REGIONAL_APPROVED[ident]
        return {
            "reviewDecision":"approved",
            "reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-02",
            "officialEvidence":[{
                "url":spec["officialUrl"],
                "proofType":"official-organizer-or-venue",
                "checkedAt":"2026-11-02",
                "checkedFields":["artists","date","venue"]
            },{
                "url":spec["venueCalendar"],
                "proofType":"first-party-venue-calendar",
                "checkedAt":"2026-11-02",
                "checkedFields":["date","venue","genre"]
            }],
            "event":{
                "id":ident,"title":spec["title"],"date":spec["date"],
                "time":None,"artistIds":list(spec["artistIds"]),
                "venueId":spec["venueId"],"genres":list(spec["genres"]),
                "status":"confirmed","officialUrl":spec["officialUrl"],
                "ticketUrl":spec["officialUrl"],"sourceType":"organisateur",
                "organizer":"La Maison Bleue / Dirty8"
            },
            "newArtists":[{"id":"dazzling-bravery","name":"Dazzling Bravery"},
                          {"id":"brdn","name":"BRDN"},
                          {"id":"curtains","name":"Curtains"},
                          {"id":"foggy-froggies","name":"Foggy Froggies"}]
        }

    def test_local_heroes_first_party_split_provenance_and_idempotence(self):
        day=__import__("datetime").date(2026,11,2)
        queue=self.regional_reviewed_queue()
        queue["approvals"].append(self.local_heroes_approval())
        out,stats=merge(BASE,BASE,queue,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newEvents"],3)
        self.assertEqual(stats["newArtists"],8)
        self.assertEqual(stats["newVenues"],2)
        self.assertEqual(len(out["events"]),130)
        self.assertEqual(len(out["artists"]),201)
        event=out["events"][-1]
        self.assertEqual(event["date"],"2026-11-13")
        self.assertEqual(event["artistIds"],
                         ["dazzling-bravery","brdn","curtains","foggy-froggies"])
        self.assertEqual(event["genres"],["Metal"])
        self.assertIsNone(event["time"])
        repeated,stats2=merge(BASE,out,queue,day)
        self.assertEqual(stats2["newEvents"],0)
        self.assertEqual(stats2["alreadyPublished"],3)
        self.assertEqual(repeated,out)

    def test_local_heroes_requires_four_named_acts_from_ticket_and_genre_from_venue(self):
        day=__import__("datetime").date(2026,11,2)
        cases=("unexpected-artist","invented-showtime","fake-ticket","bad-genre",
               "genre-without-calendar","names-without-ticket",
               "unapproved-new-artist","unlisted-event","missing-partner-proof")
        for case in cases:
            with self.subTest(case=case):
                queue=self.regional_reviewed_queue()
                row=self.local_heroes_approval()
                queue["approvals"].append(row)
                if case=="unexpected-artist":
                    row["event"]["artistIds"][0]="new-unsupported-act"
                elif case=="invented-showtime":
                    row["event"]["time"]="19:30"
                elif case=="fake-ticket":
                    row["event"]["officialUrl"]="https://example.com/not-official"
                elif case=="bad-genre":
                    row["event"]["genres"]=["Pop"]
                elif case=="genre-without-calendar":
                    row["officialEvidence"][1]["checkedFields"].remove("genre")
                elif case=="names-without-ticket":
                    row["officialEvidence"][0]["checkedFields"].remove("artists")
                elif case=="unapproved-new-artist":
                    row["newArtists"][0]["name"]="Different Band"
                elif case=="unlisted-event":
                    row["event"]["id"]="go-c-20261113-strasbourg-invented"
                elif case=="missing-partner-proof":
                    row["officialEvidence"].pop()
                out,stats=merge(BASE,BASE,queue,day)
                self.assertTrue(stats["held"])
                self.assertEqual(stats["newEvents"],2)
                self.assertEqual(len(out["events"]),129)

    def test_rock_and_maison_precise_venues_and_events_append_only_once(self):
        day=__import__("datetime").date(2026,11,2)
        queue=self.regional_reviewed_queue()
        new,stats=merge(BASE,BASE,queue,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newVenues"],2)
        self.assertEqual(stats["newEvents"],2)
        self.assertEqual(stats["newArtists"],4)
        self.assertEqual(len(new["events"]),129)
        self.assertEqual(len(new["venues"]),55)
        self.assertEqual(len(new["artists"]),197)
        self.assertEqual(new["events"][:127],BASE["events"])
        self.assertEqual(new["venues"][:53],BASE["venues"])
        self.assertTrue(all(x["time"] is None for x in new["events"][-2:]))
        self.assertEqual([x["date"] for x in new["events"][-2:]],
                         ["2026-11-04","2026-11-11"])
        pins={v["id"]:v for v in new["venues"][-2:]}
        self.assertEqual(pins["rock-n-eat-lyon"]["geoSource"],
                         "https://www.openstreetmap.org/api/0.6/node/5973017988")
        self.assertEqual(pins["la-maison-bleue-strasbourg"]["geoSource"],
                         "https://www.openstreetmap.org/api/0.6/node/7812445394")
        protect_reference(BASE,new)
        validate_catalogue(new)
        repeated,next_stats=merge(BASE,new,queue,day)
        self.assertEqual(next_stats["newVenues"],0)
        self.assertEqual(next_stats["newEvents"],0)
        self.assertEqual(next_stats["alreadyPublished"],2)
        self.assertEqual(repeated,new)

    def test_regional_venues_never_accept_unreviewed_event_or_changed_source(self):
        day=__import__("datetime").date(2026,11,2)
        base=self.regional_reviewed_queue()
        for variant in ("wrong-date","wrong-artist","wrong-ticket",
                        "fake-time","different-genre","other-reviewer",
                        "wrong-calendar","old-proof","wrong-pin",
                        "not-named-event","missing-proof",
                        "ticket-genre-unverified"):
            with self.subTest(variant=variant):
                queue=copy.deepcopy(base)
                row=queue["approvals"][0]
                e=row["event"]
                if variant=="wrong-date":
                    e["date"]="2026-11-05"
                elif variant=="wrong-artist":
                    e["artistIds"][0]="invented-artist"
                elif variant=="wrong-ticket":
                    e["officialUrl"]="https://shotgun.live/events/other-bill"
                    e["ticketUrl"]=e["officialUrl"]
                    row["officialEvidence"][0]["url"]=e["officialUrl"]
                elif variant=="fake-time":
                    e["time"]="19:00"
                elif variant=="different-genre":
                    e["genres"]=["Pop"]
                elif variant=="other-reviewer":
                    row["reviewedBy"]="automated-official-recheck"
                elif variant=="wrong-calendar":
                    row["officialEvidence"][1]["url"]="https://example.com/fake"
                elif variant=="old-proof":
                    row["reviewedAt"]="2026-10-01"
                elif variant=="wrong-pin":
                    queue["venueApprovals"][0]["venue"]["longitude"]+=.01
                elif variant=="not-named-event":
                    e["id"]="go-c-20261107-lyon-guessed"
                elif variant=="missing-proof":
                    row["officialEvidence"].pop()
                elif variant=="ticket-genre-unverified":
                    row["officialEvidence"][0]["checkedFields"].remove("genre")
                output,stats=merge(BASE,BASE,queue,day)
                self.assertTrue(stats["held"])
                self.assertEqual(stats["newEvents"],1)
                self.assertEqual(output["events"][:127],BASE["events"])
                if variant=="wrong-pin":
                    self.assertEqual(stats["newVenues"],1)
                else:
                    self.assertEqual(stats["newVenues"],2)

    def test_regional_existing_published_events_need_same_private_approvals(self):
        day=__import__("datetime").date(2026,11,2)
        queue=self.regional_reviewed_queue()
        published,_=merge(BASE,BASE,queue,day)
        no_longer_allowed=copy.deepcopy(queue)
        no_longer_allowed["approvals"]=no_longer_allowed["approvals"][1:]
        with self.assertRaises(ValueError):
            merge(BASE,published,no_longer_allowed,day)

    def test_two_vetted_venues_and_two_joker_events_append_without_damage(self):
        checked=__import__("datetime").date(2026,11,2)
        queue=self.pilot_queue()
        out,stats=merge(BASE,BASE,queue,checked)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newVenues"],2)
        self.assertEqual(stats["newEvents"],2)
        self.assertEqual(stats["newArtists"],3)
        self.assertEqual(len(out["venues"]),55)
        self.assertEqual(len(out["events"]),129)
        self.assertEqual(out["events"][:127],BASE["events"])
        self.assertEqual(out["venues"][:53],BASE["venues"])
        self.assertEqual(out["mode"],"preview-public-unlisted")
        self.assertEqual([e["time"] for e in out["events"][-2:]],["21:00","20:30"])
        protect_reference(BASE,out)
        validate_catalogue(out)
        again,next_stats=merge(BASE,out,queue,checked)
        self.assertEqual(next_stats["newEvents"],0)
        self.assertEqual(next_stats["newVenues"],0)
        self.assertEqual(next_stats["alreadyPublished"],2)
        self.assertEqual(next_stats["alreadyRegisteredVenues"],2)
        self.assertEqual(out,again)

    def test_unapproved_or_wrong_geocoded_venue_not_added(self):
        checked=__import__("datetime").date(2026,11,2)
        queue=self.pilot_queue(with_events=False)
        for mutation in ("wrong-lat","wrong-address","wrong-source",
                         "wrong-reviewer","unknown-id","missing-geo-proof"):
            with self.subTest(mutation=mutation):
                altered=copy.deepcopy(queue)
                entry=altered["venueApprovals"][0]
                if mutation=="wrong-lat":
                    entry["venue"]["latitude"]+=.01
                elif mutation=="wrong-address":
                    entry["venue"]["address"]="Adresse non vérifiée"
                elif mutation=="wrong-source":
                    entry["officialEvidence"][0]["url"]="https://other.example/lieu"
                elif mutation=="wrong-reviewer":
                    entry["reviewedBy"]="automated-official-recheck"
                elif mutation=="unknown-id":
                    entry["venue"]["id"]="unknown-hall"
                elif mutation=="missing-geo-proof":
                    entry["officialEvidence"].pop()
                out,stats=merge(BASE,BASE,altered,checked)
                self.assertEqual(stats["newVenues"],1)
                self.assertTrue(stats["held"])
                self.assertEqual(out["venues"][0:53],BASE["venues"])
                self.assertEqual(len(out["venues"]),54)
        # Without any verified venues a concert in a new location is held.
        bad=self.pilot_queue()
        bad["venueApprovals"]=[]
        out,stats=merge(BASE,BASE,bad,checked)
        self.assertEqual(stats["newVenues"],0)
        self.assertEqual(stats["newEvents"],0)
        self.assertTrue(stats["held"])

    def test_new_venue_event_cannot_use_aggregator_or_brin_ticketing(self):
        checked=__import__("datetime").date(2026,11,2)
        base=self.pilot_queue()
        for variant in ("other-domain","generic-agenda","wrong-reviewer",
                        "no-start-proof","unapproved-brin"):
            with self.subTest(variant=variant):
                q=copy.deepcopy(base)
                a=q["approvals"][0]
                if variant=="other-domain":
                    a["event"]["officialUrl"]="https://evil.example/jokers-concert-programmation-bad.html"
                    a["officialEvidence"][0]["url"]=a["event"]["officialUrl"]
                elif variant=="generic-agenda":
                    a["event"]["officialUrl"]="https://www.jokerspubangers.com/"
                    a["officialEvidence"][0]["url"]=a["event"]["officialUrl"]
                elif variant=="wrong-reviewer":
                    a["reviewedBy"]="automated-official-recheck"
                elif variant=="no-start-proof":
                    a["officialEvidence"][0]["checkedFields"]=["date","artists","venue","genre"]
                elif variant=="unapproved-brin":
                    a["event"]["venueId"]="le-brin-de-zinc-barberaz"
                    a["event"]["officialUrl"]="https://www.billetweb.fr/multi_event.php?multi=11236"
                    a["officialEvidence"][0]["url"]=a["event"]["officialUrl"]
                out,stats=merge(BASE,BASE,q,checked)
                self.assertEqual(stats["newEvents"],1)
                self.assertGreaterEqual(len(stats["held"]),1)

    def test_no_direct_edit_to_post_baseline_venue(self):
        checked=__import__("datetime").date(2026,11,2)
        queue=self.pilot_queue(with_events=False)
        with_venues,_=merge(BASE,BASE,queue,checked)
        forged=copy.deepcopy(with_venues)
        forged["venues"][-1]["longitude"]+=.001
        with self.assertRaisesRegex(ValueError,"Salle cloud"):
            merge(BASE,forged,queue,checked)
        # Removing the private approvals cannot silently grandfather a venue.
        with self.assertRaisesRegex(ValueError,"Salle cloud"):
            merge(BASE,with_venues,{"schema":queue["schema"],"approvals":[]},checked)

    def brin_queue(self):
        from concerts_cloud_sync import BRIN_ORGANIZER_VERIFIED
        queue=self.pilot_queue(with_events=False)
        for event_id,expected in BRIN_ORGANIZER_VERIFIED.items():
            if expected.get("partnerProofType"):
                continue  # Existing four organizer-submitted partner fixture.
            newcomers=[
                {"id":aid,"name":({
                    "noveria":"Noveria","tarchon-fist":"Tarchon Fist",
                    "wedingoth":"Wedingoth","fvzz-popvli":"Fvzz Popvli",
                    "ancient-settlers":"Ancient Settlers",
                })[aid]} for aid in expected["artistIds"]
                if aid!="moscow-death-brigade"
            ]
            queue["approvals"].append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":expected["ticketUrl"],"proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]
                },{
                    "url":expected["partnerUrl"],"proofType":"organizer-submitted-partner",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]
                }],
                "event":{
                    "id":event_id,"title":expected["title"],"date":expected["date"],
                    "time":None,"artistIds":list(expected["artistIds"]),
                    "venueId":"le-brin-de-zinc-barberaz",
                    "genres":list(expected["genres"]),"status":"confirmed",
                    "officialUrl":expected["ticketUrl"],"sourceType":"organisateur",
                    "organizer":"Le Brin de Zinc","ticketUrl":expected["ticketUrl"]
                },
                "newArtists":newcomers
            })
        return queue

    def test_brin_four_organizer_crosschecked_concerts_integrate_once(self):
        checked=__import__("datetime").date(2026,11,2)
        q=self.brin_queue()
        out,stats=merge(BASE,BASE,q,checked)
        self.assertEqual(stats["newVenues"],2)
        self.assertEqual(stats["newEvents"],4)
        self.assertEqual(stats["newArtists"],5)
        self.assertEqual(stats["held"],[])
        self.assertEqual(len(out["events"]),131)
        self.assertEqual(out["events"][:127],BASE["events"])
        self.assertEqual(out["venues"][:53],BASE["venues"])
        self.assertTrue(all(e["time"] is None for e in out["events"][-4:]))
        self.assertEqual({e["date"] for e in out["events"][-4:]},
            {"2026-11-05","2026-11-09","2026-11-12","2026-11-15"})
        validate_catalogue(out)
        repeated,repeat_stats=merge(BASE,out,q,checked)
        self.assertEqual(repeat_stats["newEvents"],0)
        self.assertEqual(repeat_stats["newVenues"],0)
        self.assertEqual(repeat_stats["alreadyPublished"],4)
        self.assertEqual(repeated,out)

    def test_brin_unapproved_or_modified_partner_ticket_cannot_publish(self):
        checked=__import__("datetime").date(2026,11,2)
        for variant in ("wrong-date","wrong-artist","extra-artist",
                        "different-ticket","generic-calendar","wrong-partner",
                        "no-partner","bogus-start-time","other-reviewer",
                        "aggregator-source","missing-genre","unregistered-event"):
            with self.subTest(variant=variant):
                q=self.brin_queue()
                a=q["approvals"][0]
                e=a["event"]
                if variant=="wrong-date":
                    e["date"]="2026-11-06"
                elif variant=="wrong-artist":
                    e["artistIds"][0]="made-up-act"
                    a["newArtists"][0]["id"]="made-up-act"
                    a["newArtists"][0]["name"]="Made Up Act"
                elif variant=="extra-artist":
                    e["artistIds"].append("moscow-death-brigade")
                elif variant=="different-ticket":
                    e["officialUrl"]="https://www.billetweb.fr/some-other-concert"
                    e["ticketUrl"]=e["officialUrl"]
                    a["officialEvidence"][0]["url"]=e["officialUrl"]
                elif variant=="generic-calendar":
                    e["officialUrl"]="https://www.billetweb.fr/multi_event.php?multi=11236"
                    e["ticketUrl"]=e["officialUrl"]
                    a["officialEvidence"][0]["url"]=e["officialUrl"]
                elif variant=="wrong-partner":
                    a["officialEvidence"][1]["url"]="https://www.culturesducoeur.org/Home/evenement_look?id_evenement=999"
                elif variant=="no-partner":
                    a["officialEvidence"].pop()
                elif variant=="bogus-start-time":
                    e["time"]="20:30"
                elif variant=="other-reviewer":
                    a["reviewedBy"]="automated-official-recheck"
                elif variant=="aggregator-source":
                    e["sourceType"]="aggregator"
                elif variant=="missing-genre":
                    e["genres"]=["Pop"]
                elif variant=="unregistered-event":
                    e["id"]="go-c-20261105-barberaz-invented"
                out,stats=merge(BASE,BASE,q,checked)
                self.assertEqual(stats["newEvents"],3)
                self.assertTrue(stats["held"])


    def crosschecked_brin_queue(self):
        from concerts_cloud_sync import BRIN_ORGANIZER_VERIFIED
        queue=self.pilot_queue(with_events=False)
        names={"ghouldozer":"Ghouldozer","xaon":"Xaon","vortex":"Vortex"}
        for event_id,expected in BRIN_ORGANIZER_VERIFIED.items():
            if not expected.get("partnerProofType"):
                continue
            added=[{"id":key,"name":names[key]}
                   for key in expected["artistIds"] if key in names]
            queue["approvals"].append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":expected["ticketUrl"],
                    "proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]
                },{
                    "url":expected["partnerUrl"],
                    "proofType":expected["partnerProofType"],
                    "checkedAt":"2026-11-02",
                    "checkedFields":list(expected["partnerCheckedFields"])
                }],
                "event":{
                    "id":event_id,"title":expected["title"],"date":expected["date"],
                    "time":None,"artistIds":list(expected["artistIds"]),
                    "venueId":"le-brin-de-zinc-barberaz",
                    "genres":list(expected["genres"]),"status":"confirmed",
                    "officialUrl":expected["ticketUrl"],"sourceType":"organisateur",
                    "organizer":"Le Brin de Zinc","ticketUrl":expected["ticketUrl"]
                },
                "newArtists":added
            })
        return queue

    def test_brin_two_additional_source_specific_approvals_publish_only_once(self):
        checked=__import__("datetime").date(2026,11,2)
        queue=self.crosschecked_brin_queue()
        out,stats=merge(BASE,BASE,queue,checked)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newEvents"],2)
        self.assertEqual(stats["newArtists"],3)
        self.assertEqual(stats["newVenues"],2)
        self.assertEqual(
            {e["id"] for e in out["events"][-2:]},
            {"go-c-20261110-barberaz-wake-the-dead",
             "go-c-20261206-barberaz-xaon"})
        self.assertTrue(all(e["time"] is None for e in out["events"][-2:]))
        self.assertEqual(out["events"][:127],BASE["events"])
        validate_catalogue(out)
        again,repeated=merge(BASE,out,queue,checked)
        self.assertEqual(repeated["newEvents"],0)
        self.assertEqual(repeated["alreadyPublished"],2)
        self.assertEqual(again,out)

    def test_brin_new_secondary_evidence_and_ticket_remain_exactly_scoped(self):
        checked=__import__("datetime").date(2026,11,2)
        for variant in ("missing-partner","wrong-kind","wrong-partner-url",
                        "wrong-ticket","wrong-date","unknown-show",
                        "invented-start","wrong-new-artist","missing-secondary-date"):
            with self.subTest(variant=variant):
                q=self.crosschecked_brin_queue()
                row=q["approvals"][0]
                e=row["event"]
                if variant=="missing-partner":
                    row["officialEvidence"].pop()
                elif variant=="wrong-kind":
                    row["officialEvidence"][1]["proofType"]="organizer-submitted-partner"
                elif variant=="wrong-partner-url":
                    row["officialEvidence"][1]["url"]="https://example.org/fake"
                elif variant=="wrong-ticket":
                    e["officialUrl"]="https://www.billetweb.fr/fake"
                    e["ticketUrl"]=e["officialUrl"]
                    row["officialEvidence"][0]["url"]=e["officialUrl"]
                elif variant=="wrong-date":
                    e["date"]="2027-12-10"
                elif variant=="unknown-show":
                    e["id"]="go-c-20261110-barberaz-unknown"
                elif variant=="invented-start":
                    e["time"]="20:30"
                elif variant=="wrong-new-artist":
                    row["newArtists"][0]["id"]="other-singer"
                    e["artistIds"][1]="other-singer"
                elif variant=="missing-secondary-date":
                    row["officialEvidence"][1]["checkedFields"]=["artists","venue"]
                out,stats=merge(BASE,BASE,q,checked)
                self.assertEqual(stats["newEvents"],1)
                self.assertEqual(len(stats["held"]),1)
                self.assertTrue(all(x["id"] != "go-c-20261110-barberaz-wake-the-dead"
                                    for x in out["events"]))

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
        from concerts_cloud_sync import legacy_corrected_events
        self.assertIn(live["events"][:127],
                      (BASE["events"],legacy_corrected_events(BASE)))

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

    def test_ferrailleur_auto_can_add_exact_officially_named_artists(self):
        from concerts_cloud_sync import FERRAILLEUR_LOCATION_FIX
        fixed=copy.deepcopy(BASE)
        next(x for x in fixed["venues"] if x["id"]=="le-ferrailleur-nantes").update(
            FERRAILLEUR_LOCATION_FIX)
        artist=BASE["artists"][0]  # Kamelot already identified
        event=approval("go-c-20270201-nantes-kamelot")
        event["reviewedBy"]="automated-official-recheck"
        url="https://www.leferrailleur.fr/evenement/kamelot-and-friends/8753"
        event["event"].update({
            "title":artist["name"]+" + Poison Ruïn + Precipice",
            "venueId":"le-ferrailleur-nantes",
            "sourceType":"salle",
            "officialUrl":url,
            "artistIds":[artist["id"],"poison-ruin","precipice"],
            "genres":["Punk","Metal"],
            "time":"20:30"
        })
        event["newArtists"]=[
            {"id":"poison-ruin","name":"Poison Ruïn"},
            {"id":"precipice","name":"Precipice"}
        ]
        event["officialEvidence"][0].update({
            "url":url,
            "checkedFields":["artists","date","venue","genre"],
            "officialArtistNames":[artist["name"],"Poison Ruïn","Precipice"],
            "verifiedNewArtists":["Poison Ruïn","Precipice"]
        })
        result,stats=merge(BASE,fixed,{"schema":"grossesondes.concert.approvals.v1",
                                       "approvals":[event]},NOW)
        self.assertEqual(stats["newEvents"],1)
        self.assertEqual(stats["newArtists"],2)
        self.assertEqual(result["events"][-1]["venueId"],"le-ferrailleur-nantes")
        self.assertEqual(len(result["artists"]),195)
        bad_items=[
            ("third-new",lambda a:a["newArtists"].append(
                {"id":"third-group","name":"Third Group"})),
            ("wrong-lineup",lambda a:a["officialEvidence"][0].update(
                {"officialArtistNames":["Kamelot","Unknown","Precipice"]})),
            ("missing-list",lambda a:a["officialEvidence"][0].pop(
                "officialArtistNames")),
            ("fake-identity",lambda a:a["event"].update(
                {"artistIds":["exit-eden","poison-ruin","precipice"]})),
            ("bad-id",lambda a:a["newArtists"][0].update({"id":"not-poison"})),
            ("alias-clash",lambda a:a["newArtists"][0].update(
                {"name":"No Place for soûl","id":"no-place-for-soul"})),
            ("changed-date",lambda a:a["event"].update({"date":"2026-10-01"})),
            ("wrong-domain",lambda a:a["event"].update(
                {"officialUrl":"https://www.example.org/evenement/kamelot/8753"})),
            ("generic-agenda",lambda a:a["event"].update(
                {"officialUrl":"https://www.leferrailleur.fr/agenda"}))
        ]
        for name,change in bad_items:
            with self.subTest(name=name):
                altered=copy.deepcopy(event)
                change(altered)
                if name in ("wrong-domain","generic-agenda"):
                    altered["officialEvidence"][0]["url"]=altered["event"]["officialUrl"]
                _,denied=merge(BASE,fixed,{
                    "schema":"grossesondes.concert.approvals.v1","approvals":[altered]
                },NOW)
                self.assertEqual(denied["newEvents"],0)
                self.assertTrue(denied["held"])
        # Old city-centre position is never acceptable for this new autonomy.
        _,denied=merge(BASE,BASE,{
            "schema":"grossesondes.concert.approvals.v1","approvals":[event]
        },NOW)
        self.assertEqual(denied["newEvents"],0)
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

    def test_three_independently_rechecked_rex_shows_preserve_references(self):
        # Multi-event acceptance: new artists only, separate dates, existing
        # venue, full official first-party URL, and no inferred start time.
        batch=[]
        for date, key, artist_names in (
                ("2026-11-22","punk-night",["Punk Band"]),
                ("2027-02-15","guitar-night",["Guitar Band"]),
                ("2027-04-09","doom-night",["Doom Band","Stoner Band"])):
            a=approval("go-c-"+date.replace("-","")+"-toulouse-"+key)
            official="https://www.lerextoulouse.com/fr/programmation/"+key+"/"
            a["reviewedBy"]="independent-official-verifier"
            a["event"].update({
                "title":" + ".join(artist_names),"date":date,
                "time":None,"venueId":"le-rex-toulouse",
                "genres":["Hard Rock"],"sourceType":"salle",
                "officialUrl":official,
                "artistIds":[s.lower().replace(" ","-") for s in artist_names]
            })
            a["newArtists"]=[
                {"id":s.lower().replace(" ","-"),"name":s}
                for s in artist_names
            ]
            a["officialEvidence"][0].update({
                "url":official,
                "checkedFields":["artists","date","venue","genre"]
            })
            batch.append(a)
        queue={"schema":"grossesondes.concert.approvals.v1",
               "approvals":batch}
        new,stats=merge(BASE,BASE,queue,NOW)
        self.assertEqual(stats["newEvents"],3)
        self.assertEqual(stats["newArtists"],4)
        self.assertEqual(stats["held"],[])
        self.assertEqual(len(new["venues"]),53)
        self.assertEqual(len(new["events"]),130)
        self.assertEqual(new["events"][:127],BASE["events"])
        self.assertEqual(new["mode"],"preview-public-unlisted")
        self.assertTrue(all(x["time"] is None for x in new["events"][-3:]))
        validate_catalogue(new)
        again,second=merge(BASE,new,queue,NOW)
        self.assertEqual(second["newEvents"],0)
        self.assertEqual(second["alreadyPublished"],3)
        self.assertEqual(again["events"],new["events"])

    def historic_lost_kyiv_approval(self):
        return {
            "schema":"grossesondes.concert.approvals.v1",
            "approvals":[],
            "referenceCorrections":[{
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "eventId":"go-c-20261212-nantes-lost-in-kyiv",
                "eventPatch":{
                    "title":"Lost in Kyiv + Årabrot",
                    "artistIds":["lost-in-kyiv","arabrot"],
                    "lastVerified":"2026-11-02"
                },
                "officialEvidence":[{
                    "url":"https://www.leferrailleur.fr/evenement/lost-in-kyiv/5307",
                    "proofType":"official-venue-detail",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","startTime"]
                }]
            }]
        }

    def test_historic_lost_kyiv_support_act_correction_is_approved_and_idempotent(self):
        day=__import__("datetime").date(2026,11,2)
        q=self.historic_lost_kyiv_approval()
        corrected,stats=merge(BASE,BASE,q,day)
        self.assertEqual(stats["correctedEvents"],1)
        self.assertEqual(stats["newEvents"],0)
        self.assertEqual(len(corrected["events"]),127)
        self.assertEqual(len(corrected["artists"]),193)
        original={x["id"]:x for x in BASE["events"]}
        event=next(e for e in corrected["events"] if e["id"]=="go-c-20261212-nantes-lost-in-kyiv")
        self.assertEqual(event["artistIds"],["lost-in-kyiv","arabrot"])
        self.assertEqual(event["title"],"Lost in Kyiv + Årabrot")
        self.assertEqual(event["time"],"20:30")
        self.assertEqual(event["date"],"2026-12-12")
        self.assertEqual(event["venueId"],"le-ferrailleur-nantes")
        self.assertEqual(event["officialUrl"],original[event["id"]]["officialUrl"])
        self.assertEqual(len(event["history"]),len(original[event["id"]]["history"])+1)
        self.assertEqual(
            [e for e in corrected["events"] if e["id"]!=event["id"]],
            [e for e in BASE["events"] if e["id"]!=event["id"]])
        protect_reference(BASE,corrected)
        validate_catalogue(corrected)
        repeated,counts=merge(BASE,corrected,q,day)
        self.assertEqual(counts["correctedEvents"],0)
        self.assertEqual(repeated,corrected)

    def test_historic_correction_cannot_bypass_private_approval_or_edit_date(self):
        day=__import__("datetime").date(2026,11,2)
        valid=self.historic_lost_kyiv_approval()
        corrected,_=merge(BASE,BASE,valid,day)
        for variant in ("approval-missing","fake-source","fake-artist",
                        "wrong-reviewer","modified-date","extra-venue-edit"):
            with self.subTest(variant=variant):
                q=copy.deepcopy(valid)
                current=copy.deepcopy(corrected)
                if variant=="approval-missing":
                    q.pop("referenceCorrections")
                elif variant=="fake-source":
                    q["referenceCorrections"][0]["officialEvidence"][0]["url"]="https://www.example.org/unverified"
                elif variant=="fake-artist":
                    q["referenceCorrections"][0]["eventPatch"]["artistIds"]=["lost-in-kyiv"]
                elif variant=="wrong-reviewer":
                    q["referenceCorrections"][0]["reviewedBy"]="automatic-guess"
                elif variant=="modified-date":
                    target=next(e for e in current["events"] if e["id"]=="go-c-20261212-nantes-lost-in-kyiv")
                    target["date"]="2026-12-13"
                elif variant=="extra-venue-edit":
                    current["venues"][0]["latitude"]+=1
                with self.assertRaises(ValueError):
                    merge(BASE,current,q,day)
        with self.assertRaises(ValueError):
            merge(BASE,BASE,{"schema":valid["schema"],
                             "approvals":[],"referenceCorrections":[{
                                "reviewDecision":"approved",
                                "eventId":"invented-event"}]},day)

    def trabendo_queue(self):
        from concerts_cloud_sync import PILOT_VENUES,TRABENDO_VERIFIED
        v=PILOT_VENUES["le-trabendo-paris"]
        venue={
            "reviewDecision":"approved",
            "reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-02",
            "venue":copy.deepcopy(v["venue"]),
            "officialEvidence":[
                {"url":v["officialUrl"],"proofType":"official-venue-address",
                 "checkedAt":"2026-11-02",
                 "checkedFields":["name","address","postalCode","city"]},
                {"url":v["locationUrl"],"proofType":"openstreetmap-venue-way",
                 "checkedAt":"2026-11-02",
                 "checkedFields":["venueName","coordinates"]}
            ]
        }
        approvals=[]
        for ident,entry in TRABENDO_VERIFIED.items():
            approvals.append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":entry["officialUrl"],
                    "proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]}],
                "event":{
                    "id":ident,"title":entry["title"],"date":entry["date"],
                    "time":None,"artistIds":entry["artistIds"],
                    "venueId":"le-trabendo-paris",
                    "genres":entry["genres"],"status":"confirmed",
                    "officialUrl":entry["officialUrl"],"sourceType":"salle",
                    "organizer":"Le Trabendo"},
                "newArtists":[{"id":key,"name":entry["title"]}
                    for key in entry["newArtistIds"]]
            })
        return {"schema":"grossesondes.concert.approvals.v1",
                "venueApprovals":[venue],"approvals":approvals}

    def test_trabendo_geo_way_and_two_explicit_bills_publish_once(self):
        day=__import__("datetime").date(2026,11,2)
        q=self.trabendo_queue()
        j,report=merge(BASE,BASE,q,day)
        self.assertEqual(report["held"],[])
        self.assertEqual(report["newVenues"],1)
        self.assertEqual(report["newEvents"],2)
        self.assertEqual(report["newArtists"],2)
        names=[e["title"] for e in j["events"][-2:]]
        self.assertEqual(set(names),{"Wage War","Whitechapel"})
        v=next(v for v in j["venues"] if v["id"]=="le-trabendo-paris")
        self.assertEqual((v["latitude"],v["longitude"]),(48.89265,2.39396))
        self.assertIn("indicatif",v["geoPrecision"])
        again,report=merge(BASE,j,q,day)
        self.assertEqual(report["newEvents"],0)
        self.assertEqual(report["newVenues"],0)
        self.assertEqual(again,j)

    def test_trabendo_refuses_unlisted_event_bad_pin_or_fake_start(self):
        day=__import__("datetime").date(2026,11,2)
        for variant in ("new-event","wrong-year","wrong-genre","added-time",
                        "fake-url","fake-lineup","wrong-reviewer","missing-proof",
                        "wrong-pin","fake-node"):
            with self.subTest(variant=variant):
                q=self.trabendo_queue()
                q["approvals"]=q["approvals"][:1]
                a=q["approvals"][0]
                event=a["event"]
                if variant=="new-event":event["id"]="go-c-20270206-paris-fake"
                elif variant=="wrong-year":event["date"]="2026-01-22"
                elif variant=="wrong-genre":event["genres"]=["Electro"]
                elif variant=="added-time":event["time"]="19:00"
                elif variant=="fake-url":event["officialUrl"]="https://evil.test/programmation/wage-war/"
                elif variant=="fake-lineup":event["artistIds"]=["whitechapel"]
                elif variant=="wrong-reviewer":a["reviewedBy"]="automatic-guess"
                elif variant=="missing-proof":a["officialEvidence"]=[]
                elif variant=="wrong-pin":q["venueApprovals"][0]["venue"]["latitude"]+=.003
                elif variant=="fake-node":q["venueApprovals"][0]["officialEvidence"][1]["proofType"]="openstreetmap-venue-node"
                resulting,report=merge(BASE,BASE,q,day)
                self.assertTrue(report["held"])
                self.assertEqual(report["newEvents"],0)
                self.assertEqual(report["newVenues"],0)
                self.assertEqual(resulting,BASE)

    def test_no_approval_means_exactly_127(self):
        current,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                       "approvals":[]},NOW)
        self.assertEqual(current,BASE)
        self.assertEqual(stats["newEvents"],0)


if __name__=="__main__":
    unittest.main()
