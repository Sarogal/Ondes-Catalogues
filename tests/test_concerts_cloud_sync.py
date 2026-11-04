"""Contrôles de conservation et de fusion du catalogue Concerts (aucun réseau)."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import merge, protect_reference, validate_catalogue, validate_approval

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
    def test_regional_orleans_rouen_six_official_approvals_only(self):
        """Six precise bills, no invented start, secondary proof by its real origin."""
        import datetime as dt
        published=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        venues={v["id"]:v for v in published["venues"]}
        artists={a["id"]:a for a in published["artists"]}
        secondary={
            "astro-calendar":("first-party-venue-calendar",
                              "https://www.lastrolabe.org/agenda/"),
            "radio":("independent-local-radio-announcement",
                     "https://www.intensite.net/orleans-45-concert-la-jungle-sodom-sagesse"),
            "slaptrack":("independent-organizer-confirmation",
                         "https://www.helloasso.com/associations/slaptrack/evenements/final-show-orpheum-black"),
            "rouen-calendar":("first-party-venue-calendar","https://le106.com/agenda"),
            "eventim":("authorized-ticket-distributor",
                       "https://www.eventim.fr/eventseries/cosmic-trip-tour-4197731/"),
            "aeg":("independent-organizer-tour",
                   "https://www.aegpresents.fr/event/dynamite-shakers/"),
        }
        # id, venue, date, headline, artistIds, newArtists, official detail, genre,
        # proof 2, detail-only headliner?
        cases=[
            ("go-c-20261119-orleans-razorlight","l-astrolabe-orleans",
             "2026-11-19","Razorlight + Rubber Legs",
             ["razorlight","rubber-legs"],["Razorlight","Rubber Legs"],
             "https://www.lastrolabe.org/agenda/razorlight/","Indie Rock","astro-calendar",True),
            ("go-c-20270121-orleans-la-jungle","l-astrolabe-orleans",
             "2027-01-21","La Jungle + Sodom & Sagesse",
             ["la-jungle","sodom-sagesse"],["Sodom & Sagesse"],
             "https://www.lastrolabe.org/agenda/la-jungle-sodom-sagesse/","Noise Rock","radio",False),
            ("go-c-20270129-orleans-orpheum-black","l-astrolabe-orleans",
             "2027-01-29","Orpheum Black + Pledge of Healing — Le dernier acte",
             ["orpheum-black","pledge-of-healing"],["Orpheum Black","Pledge of Healing"],
             "https://www.lastrolabe.org/agenda/orpheum-black-le-dernier-acte/","Rock","slaptrack",True),
            ("go-c-20261117-rouen-elktrk-skin","le-106-rouen",
             "2026-11-17","ELKTRK SKIN + YÜ + KAASK",
             ["elktrk-skin","yu-band","kaask"],["ELKTRK SKIN","YÜ","KAASK"],
             "https://le106.com/agenda/elktrk-skin-yu-kaask","Punk Rock","rouen-calendar",False),
            ("go-c-20270128-rouen-powersolo","le-106-rouen",
             "2027-01-28","Powersolo + Weird Omen + DJ Tony Garagist",
             ["powersolo","weird-omen","dj-tony-garagist"],
             ["Powersolo","Weird Omen","DJ Tony Garagist"],
             "https://le106.com/agenda/power-solo-weird-omen-dj-tony-garagist",
             "Garage Punk","eventim",False),
            ("go-c-20270313-rouen-dynamite-shakers","le-106-rouen",
             "2027-03-13","Dynamite Shakers",
             ["dynamite-shakers"],[],
             "https://le106.com/agenda/dynamite-shakers","Punk Rock","aeg",False),
        ]
        day=dt.date(2026,11,3)
        reviewed="2026-11-03"
        valid=[]
        for eid,venue,date,title,ids,names,source,genre,key,head_only in cases:
            typ,url=secondary[key]
            row={
                "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
                "reviewedAt":reviewed,
                "officialEvidence":[
                    {"url":source,"proofType":"official-organizer-or-venue",
                     "checkedAt":reviewed,
                     "checkedFields":(["leadArtist","date","venue","genre"] if head_only
                                      else ["artists","date","venue","genre"])},
                    {"url":url,"proofType":typ,"checkedAt":reviewed,
                     "checkedFields":["artists","date","venue"]},
                ],
                "event":{
                    "id":eid,"title":title,"date":date,"time":None,
                    "artistIds":ids,"venueId":venue,"genres":[genre],
                    "status":"confirmed","officialUrl":source,
                    "sourceType":"salle",
                },
                "newArtists":[
                    {"id":name_id,"name":name}
                    for name_id,name in zip(
                        [i for i in ids if i not in artists], names)
                ],
            }
            with self.subTest(event=eid):
                parsed,added=validate_approval(row,venues,artists,day)
                self.assertEqual(parsed["artistIds"],ids)
                self.assertIsNone(parsed["time"])
                self.assertTrue(all(x in ids for x in added))
                valid.append(row)
        for label in ("wrong-host","invented-start","missing-support-proof",
                      "wrong-firstparty-fields","unsigned","future-check"):
            for baseline in (valid[0],valid[3]):
                row=copy.deepcopy(baseline)
                if label=="wrong-host":
                    row["event"]["officialUrl"]="https://wrong.example/agenda/faux"
                elif label=="invented-start":
                    row["event"]["time"]="20:00"
                elif label=="missing-support-proof":
                    row["officialEvidence"][1]["checkedFields"]=["date","venue"]
                elif label=="wrong-firstparty-fields":
                    row["officialEvidence"][0]["checkedFields"]=["date","venue","genre"]
                elif label=="unsigned":
                    row["reviewedBy"]="automated-official-recheck"
                else:
                    row["reviewedAt"]="2026-11-04"
                with self.subTest(case=label,venue=baseline["event"]["venueId"]):
                    with self.assertRaises((ValueError,KeyError)):
                        validate_approval(row,venues,artists,day)

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
        from concerts_cloud_sync import corrected_reference_event_state, CARGO_REFERENCE_TIME_FIXES
        ids=tuple(sorted(CARGO_REFERENCE_TIME_FIXES))
        self.assertIn(live["events"][:127], tuple(
            corrected_reference_event_state(
                BASE, legacy=legacy,
                cargo_ids=tuple(key for i,key in enumerate(ids) if mask & (1 << i)))
            for legacy in (False,True) for mask in range(1 << len(ids))))

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
            if ident not in ("go-c-20270122-paris-wage-war",
                             "go-c-20270203-paris-whitechapel"):
                continue
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
                # Venue approval is independent of the rejected concert.
                self.assertEqual(report["newVenues"],0 if variant in
                                 ("wrong-pin","fake-node") else 1)
                self.assertEqual(resulting["events"],BASE["events"])
                self.assertEqual(resulting["artists"],BASE["artists"])

    def trabendo_four_more_queue(self):
        from concerts_cloud_sync import TRABENDO_VERIFIED
        queue=self.trabendo_queue()
        queue["approvals"]=[]
        names={
            "frankie-and-the-witch-fingers":"Frankie and the Witch Fingers",
            "iguana-death-cult":"Iguana Death Cult",
            "comeback-kid":"Comeback Kid",
            "black-flag":"Black Flag",
        }
        keys=(
            "go-c-20261112-paris-frankie-witch-fingers",
            "go-c-20261128-paris-kid-kapichi",
            "go-c-20270119-paris-comeback-kid",
            "go-c-20270606-paris-black-flag",
        )
        for ident in keys:
            spec=TRABENDO_VERIFIED[ident]
            queue["approvals"].append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":spec["officialUrl"],
                    "proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02",
                    "checkedFields":["artists","date","venue","genre"]}],
                "event":{
                    "id":ident,"title":spec["title"],"date":spec["date"],
                    "time":None,"artistIds":list(spec["artistIds"]),
                    "venueId":"le-trabendo-paris","genres":list(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["officialUrl"],
                    "sourceType":"salle","organizer":"Le Trabendo"},
                "newArtists":[{"id":x,"name":names[x]}
                              for x in spec["newArtistIds"]],
            })
        return queue

    def test_trabendo_four_more_full_official_bills_and_known_artists(self):
        day=__import__("datetime").date(2026,11,2)
        # Kid Kapichi and Demob Happy already exist in current catalogue
        # from another December show, though not in the immutable baseline.
        seeded=copy.deepcopy(BASE)
        seeded["artists"].extend([
            {"id":"kid-kapichi","name":"Kid Kapichi","aliases":[]},
            {"id":"demob-happy","name":"Demob Happy","aliases":[]},
        ])
        protect_reference(BASE,seeded)
        queue=self.trabendo_four_more_queue()
        updated,report=merge(BASE,seeded,queue,day)
        self.assertEqual(report["held"],[])
        self.assertEqual(report["newEvents"],4)
        self.assertEqual(report["newArtists"],4)
        self.assertEqual(report["newVenues"],1)
        rows=updated["events"][-4:]
        self.assertEqual({x["date"] for x in rows},
                         {"2026-11-12","2026-11-28","2027-01-19","2027-06-06"})
        self.assertEqual(rows[0]["artistIds"],
                         ["frankie-and-the-witch-fingers","iguana-death-cult"])
        self.assertEqual(rows[1]["artistIds"],["kid-kapichi","demob-happy"])
        self.assertTrue(all(x["time"] is None for x in rows))
        self.assertTrue(all(x["venueId"]=="le-trabendo-paris" for x in rows))
        again,second=merge(BASE,updated,queue,day)
        self.assertEqual(second["newEvents"],0)
        self.assertEqual(second["newArtists"],0)
        self.assertEqual(again,updated)

    def test_trabendo_four_more_refuses_dropped_support_or_fake_time(self):
        day=__import__("datetime").date(2026,11,2)
        seeded=copy.deepcopy(BASE)
        seeded["artists"].extend([
            {"id":"kid-kapichi","name":"Kid Kapichi","aliases":[]},
            {"id":"demob-happy","name":"Demob Happy","aliases":[]},
        ])
        for variant in ("missing-iguana","missing-demob","wrong-genre",
                        "fake-start","wrong-source","wrong-date"):
            with self.subTest(variant=variant):
                queue=self.trabendo_four_more_queue()
                item=(queue["approvals"][1] if variant=="missing-demob"
                      else queue["approvals"][0])
                queue["approvals"]=[item]
                event=item["event"]
                if variant=="missing-iguana":
                    event["artistIds"]=["frankie-and-the-witch-fingers"]
                elif variant=="missing-demob":
                    event["artistIds"]=["kid-kapichi"]
                elif variant=="wrong-genre":
                    event["genres"]=["Disco"]
                elif variant=="fake-start":
                    event["time"]="19:00"
                elif variant=="wrong-source":
                    event["officialUrl"]="https://fake.test/programmation/"
                elif variant=="wrong-date":
                    event["date"]="2026-11-13"
                updated,report=merge(BASE,seeded,queue,day)
                self.assertTrue(report["held"])
                self.assertEqual(report["newEvents"],0)
                self.assertEqual(updated["events"],seeded["events"])
                self.assertEqual(updated["artists"],seeded["artists"])

    def secret_place_december_queue(self):
        from concerts_cloud_sync import SECRET_PLACE_DECEMBER_VERIFIED
        names={
            "the-cracked-heads":"The Cracked Heads",
            "the-psychotic-unicorns":"The Psychotic Unicorns",
            "noble-rot":"Noble Rot",
            "the-spitters":"The Spitters",
            "panic-lights":"Panic Lights",
        }
        rows=[]
        for ident,spec in SECRET_PLACE_DECEMBER_VERIFIED.items():
            rows.append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[
                    {"url":spec["officialUrl"],
                     "proofType":"official-organizer-or-venue",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["artists","date","venue"]},
                    {"url":spec["genreUrl"],
                     "proofType":"editorial-genre-context",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["artists","date","venue","genre"]}
                ],
                "event":{
                    "id":ident,"title":spec["title"],"date":spec["date"],
                    "time":spec["time"],"artistIds":list(spec["artistIds"]),
                    "venueId":"secret-place-saint-jean-de-vedas",
                    "genres":list(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["officialUrl"],
                    "sourceType":"salle","organizer":"TAF / Secret Place",
                },
                "newArtists":[{"id":aid,"name":names[aid]}
                               for aid in spec["newArtistIds"]]
            })
        return {"schema":"grossesondes.concert.approvals.v1",
                "venueApprovals":[],"approvals":rows}

    def test_secret_place_two_punk_bills_verified_without_fake_concert_start(self):
        day=__import__("datetime").date(2026,11,2)
        queue=self.secret_place_december_queue()
        out,stats=merge(BASE,BASE,queue,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual((stats["newEvents"],stats["newArtists"],
                          stats["newVenues"]),(2,5,0))
        self.assertEqual(len(out["events"]),len(BASE["events"])+2)
        self.assertEqual(out["events"][:len(BASE["events"])],BASE["events"])
        self.assertEqual(out["venues"],BASE["venues"])
        new=out["events"][-2:]
        self.assertEqual([(e["date"],e["title"],e["time"]) for e in new],
            [("2026-12-05","The Cracked Heads + The Psychotic Unicorns + Noble Rot",None),
             ("2026-12-06","The Spitters + Panic Lights",None)])
        self.assertEqual([a["name"] for a in out["artists"][-5:]],
                         ["The Cracked Heads","The Psychotic Unicorns","Noble Rot",
                          "The Spitters","Panic Lights"])
        repeated,again=merge(BASE,out,queue,day)
        self.assertEqual(again["newEvents"],0)
        self.assertEqual(again["newArtists"],0)
        self.assertEqual(repeated,out)

    def test_secret_place_only_exact_punk_events_sources_and_identity_pass(self):
        day=__import__("datetime").date(2026,11,2)
        for variant in ("invented-calendar-clock","fake-punk-genre","missing-panic",
                        "wrong-date","wrong-domain","missing-genre-proof",
                        "fake-genre-proof-url","wrong-proof-type","primary-pretends-genre",
                        "primary-pretends-clock","missing-source-date","wrong-reviewer",
                        "wrong-artist-name","unlisted-event","calendar-only"):
            for idx in (0,1):
                with self.subTest(variant=variant,event=idx):
                    q=self.secret_place_december_queue()
                    row=q["approvals"][idx]
                    q["approvals"]=[row]
                    e=row["event"]
                    primary,editorial=row["officialEvidence"]
                    if variant=="invented-calendar-clock":
                        e["time"]="19:00"
                    elif variant=="fake-punk-genre":
                        e["genres"]=["Electro"]
                    elif variant=="missing-panic":
                        e["artistIds"].pop()
                    elif variant=="wrong-date":
                        e["date"]="2026-12-08"
                    elif variant=="wrong-domain":
                        e["officialUrl"]="https://evil.example/event-details/fake"
                    elif variant=="missing-genre-proof":
                        row["officialEvidence"]=[primary]
                    elif variant=="fake-genre-proof-url":
                        editorial["url"]="https://example.org/artist"
                    elif variant=="wrong-proof-type":
                        editorial["proofType"]="official-organizer-or-venue"
                    elif variant=="primary-pretends-genre":
                        primary["checkedFields"].append("genre")
                    elif variant=="primary-pretends-clock":
                        primary["checkedFields"].append("startTime")
                    elif variant=="missing-source-date":
                        primary["checkedFields"].remove("date")
                    elif variant=="wrong-reviewer":
                        row["reviewedBy"]="automated-official-recheck"
                    elif variant=="wrong-artist-name":
                        row["newArtists"][0]["name"]="Invented Band"
                    elif variant=="unlisted-event":
                        e["id"]="go-c-20261224-secret-place-unlisted"
                    elif variant=="calendar-only":
                        e["officialUrl"]="https://www.toutafond.com/nos-evenements"
                    candidate,stats=merge(BASE,BASE,q,day)
                    self.assertEqual(stats["newEvents"],0)
                    self.assertEqual(candidate["events"],BASE["events"])
                    self.assertTrue(stats["held"])

    def cave_poetes_queue(self):
        from concerts_cloud_sync import PILOT_VENUES, CAVE_POETES_VERIFIED
        pilot=PILOT_VENUES["la-cave-aux-poetes-roubaix"]
        spec=CAVE_POETES_VERIFIED["go-c-20261108-roubaix-babe-haven-latter-muddle"]
        return {
            "schema":"grossesondes.concert.approvals.v1",
            "venueApprovals":[{
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "venue":copy.deepcopy(pilot["venue"]),
                "officialEvidence":[
                    {"url":pilot["officialUrl"],
                     "proofType":"official-venue-address",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["name","address","postalCode","city"]},
                    {"url":pilot["locationUrl"],
                     "proofType":"openstreetmap-venue-node",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["venueName","coordinates"]}
                ]
            }],
            "approvals":[{
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[
                    {"url":spec["officialUrl"],
                     "proofType":"official-organizer-or-venue",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["artists","date","venue","genre","startTime"]},
                    {"url":spec["organizerCalendar"],
                     "proofType":"organizer-submitted-calendar",
                     "checkedAt":"2026-11-02",
                     "checkedFields":["artists","date","venue","startTime"]}
                ],
                "event":{
                    "id":"go-c-20261108-roubaix-babe-haven-latter-muddle",
                    "title":spec["title"],"date":spec["date"],"time":spec["time"],
                    "artistIds":spec["artistIds"],
                    "venueId":"la-cave-aux-poetes-roubaix",
                    "genres":spec["genres"],"status":"confirmed",
                    "officialUrl":spec["officialUrl"],
                    "sourceType":"salle","organizer":"La Cave aux Poètes"},
                "newArtists":[{"id":"babe-haven","name":"Babe Haven"},
                              {"id":"latter","name":"Latter"},
                              {"id":"muddle","name":"Muddle"}]
            }]
        }

    def test_cave_poetes_punk_exact_venue_three_artists_and_explicit_start(self):
        day=__import__("datetime").date(2026,11,2)
        q=self.cave_poetes_queue()
        result,stats=merge(BASE,BASE,q,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newVenues"],1)
        self.assertEqual(stats["newEvents"],1)
        self.assertEqual(stats["newArtists"],3)
        v=result["venues"][-1]
        self.assertEqual((v["id"],v["address"]),
                         ("la-cave-aux-poetes-roubaix","16 rue du Grand Chemin"))
        self.assertEqual((v["latitude"],v["longitude"]),(50.6921711,3.1692704))
        self.assertEqual(v["geoSource"],
             "https://www.openstreetmap.org/api/0.6/node/5902484873")
        event=result["events"][-1]
        self.assertEqual(event["title"],"Babe Haven + Latter + Muddle")
        self.assertEqual(event["date"],"2026-11-08")
        self.assertEqual(event["time"],"18:30")
        self.assertEqual(event["artistIds"],["babe-haven","latter","muddle"])
        self.assertEqual([a["name"] for a in result["artists"][-3:]],
                         ["Babe Haven","Latter","Muddle"])
        same,again=merge(BASE,result,q,day)
        self.assertEqual((again["newEvents"],again["newArtists"],
                          again["newVenues"]),(0,0,0))
        self.assertEqual(same,result)

    def test_cave_poetes_rejects_non_punk_and_forged_evidence(self):
        day=__import__("datetime").date(2026,11,2)
        defects=("wrong-osm","false-osm-way","wrong-band","wrong-start",
                 "wrong-date","wrong-genre","wrong-domain",
                 "missing-calendar","wrong-calendar","no-start-proof",
                 "false-artist","unapproved-event")
        for bad in defects:
            with self.subTest(defect=bad):
                q=self.cave_poetes_queue()
                a=q["approvals"][0]
                if bad=="wrong-osm":
                    q["venueApprovals"][0]["venue"]["latitude"]+=.001
                elif bad=="false-osm-way":
                    q["venueApprovals"][0]["officialEvidence"][1]["proofType"]="openstreetmap-venue-way"
                elif bad=="wrong-band":
                    a["event"]["artistIds"][0]="other-band"
                elif bad=="wrong-start":
                    a["event"]["time"]="18:00"
                elif bad=="wrong-date":
                    a["event"]["date"]="2026-11-09"
                elif bad=="wrong-genre":
                    a["event"]["genres"]=["Electro"]
                elif bad=="wrong-domain":
                    a["event"]["officialUrl"]="https://fake.example/concert"
                elif bad=="missing-calendar":
                    a["officialEvidence"].pop()
                elif bad=="wrong-calendar":
                    a["officialEvidence"][1]["url"]="https://openagenda.com/fr/other"
                elif bad=="no-start-proof":
                    a["officialEvidence"][0]["checkedFields"].remove("startTime")
                elif bad=="false-artist":
                    a["newArtists"][2]["name"]="Another Group"
                elif bad=="unapproved-event":
                    a["event"]["id"]="go-c-20261108-roubaix-unreviewed"
                result,stats=merge(BASE,BASE,q,day)
                self.assertEqual(stats["newEvents"],0)
                self.assertTrue(stats["held"])
                self.assertEqual(result["events"],BASE["events"])

    def test_cave_poetes_secondary_calendar_cannot_impersonate_venue(self):
        today=__import__("datetime").date(2026,11,2)
        variants=("wrong-proof-type","wrong-calendar-date","missing-calendar-artist",
                  "swapped-proof","third-proof","untrusted-reviewer",
                  "non-first-party-event")
        for variant in variants:
            with self.subTest(variant=variant):
                q=self.cave_poetes_queue()
                a=q["approvals"][0]
                proofs=a["officialEvidence"]
                if variant=="wrong-proof-type":
                    proofs[1]["proofType"]="independent-official-verifier"
                elif variant=="wrong-calendar-date":
                    proofs[1]["checkedAt"]="2026-10-02"
                elif variant=="missing-calendar-artist":
                    proofs[1]["checkedFields"].remove("artists")
                elif variant=="swapped-proof":
                    proofs[0]["url"]=proofs[1]["url"]
                    proofs[1]["url"]="https://caveauxpoetes.com/evenement/babe-haven-latter-muddle/"
                elif variant=="third-proof":
                    proofs.append(dict(proofs[1]))
                elif variant=="untrusted-reviewer":
                    a["reviewedBy"]="automated-official-recheck"
                elif variant=="non-first-party-event":
                    a["event"]["officialUrl"]="https://shotgun.live/events/babe-haven"
                out,stats=merge(BASE,BASE,q,today)
                self.assertEqual(stats["newEvents"],0)
                self.assertEqual(out["events"],BASE["events"])
                self.assertTrue(stats["held"])
        # A change to the organizer's calendar is a manual alert; it cannot
        # authorize anything else in the venue without its own exact allowlist.
        q=self.cave_poetes_queue()
        a=q["approvals"][0]
        a["event"]["id"]="go-c-20261109-roubaix-unlisted-even-with-proof"
        a["event"]["date"]="2026-11-09"
        out,stats=merge(BASE,BASE,q,today)
        self.assertEqual(stats["newEvents"],0)
        self.assertTrue(stats["held"])

    def forum_queue(self):
        from concerts_cloud_sync import PILOT_VENUES, FORUM_VERIFIED
        pilot=PILOT_VENUES["le-forum-vaureal"]
        venue={
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
                 "checkedFields":["venueName","coordinates"]}
            ]
        }
        names={"senser":"Senser","wolves-in-the-throne-room":"Wolves in the Throne Room",
               "worm":"Worm","final-dose":"Final Dose",
               "harsh":"Harsh","furies":"Furies","charcoal":"Charcoal"}
        approval=[]
        for ident,spec in FORUM_VERIFIED.items():
            if ident in ("go-c-20270115-vaureal-motocultor-tour",
                         "go-c-20270423-vaureal-sortilege"):
                continue
            check=["artists","date","venue","genre"]
            if spec["time"] is not None:check.append("startTime")
            approval.append({
                "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":[{
                    "url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
                    "checkedAt":"2026-11-02","checkedFields":check}],
                "event":{
                    "id":ident,"title":spec["title"],"date":spec["date"],
                    "time":spec["time"],"artistIds":list(spec["artistIds"]),
                    "venueId":"le-forum-vaureal","genres":list(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["officialUrl"],
                    "sourceType":"salle","organizer":"Le Forum"},
                "newArtists":[{"id":aid,"name":names[aid]}
                              for aid in spec["newArtistIds"]]
            })
        return {"schema":"grossesondes.concert.approvals.v1",
                "venueApprovals":[venue],"approvals":approval}

    def forum_two_new_queue(self):
        from concerts_cloud_sync import FORUM_VERIFIED
        q=self.forum_queue()
        q["approvals"]=[]
        for ident in ("go-c-20270115-vaureal-motocultor-tour",
                      "go-c-20270423-vaureal-sortilege"):
            spec=FORUM_VERIFIED[ident]
            proofs=[
                {"url":spec["officialUrl"],
                 "proofType":"official-organizer-or-venue",
                 "checkedAt":"2026-11-02",
                 "checkedFields":["artists","date","venue","genre","startTime"]},
                {"url":spec["secondaryUrl"],
                 "proofType":spec["secondaryProofType"],
                 "checkedAt":"2026-11-02",
                 "checkedFields":["artists","date","venue"]},
            ]
            new=([{"id":"sortilege","name":"Sortilège"}] if
                 ident.endswith("sortilege") else [])
            q["approvals"].append({
                "reviewDecision":"approved",
                "reviewedBy":"independent-official-verifier",
                "reviewedAt":"2026-11-02",
                "officialEvidence":proofs,
                "event":{
                    "id":ident,"title":spec["title"],"date":spec["date"],
                    "time":spec["time"],"artistIds":list(spec["artistIds"]),
                    "venueId":"le-forum-vaureal","genres":list(spec["genres"]),
                    "status":"confirmed","officialUrl":spec["officialUrl"],
                    "sourceType":"salle","organizer":"Le Forum"},
                "newArtists":new
            })
        return q

    def test_forum_two_2027_acts_published_with_correct_full_artist_names(self):
        day=__import__("datetime").date(2026,11,2)
        q=self.forum_two_new_queue()
        out,stats=merge(BASE,BASE,q,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newVenues"],1)
        self.assertEqual(stats["newEvents"],2)
        self.assertEqual(stats["newArtists"],1)
        e={x["id"]:x for x in out["events"]}
        mot=e["go-c-20270115-vaureal-motocultor-tour"]
        self.assertEqual(mot["title"],
            "Rhapsody of Fire + Serious Black + Submasq + Aeon Gods + Rock Out")
        self.assertEqual(mot["artistIds"],
            ["rhapsody-of-fire","serious-black","submasq","aeon-gods","rock-out"])
        self.assertEqual((mot["date"],mot["time"],mot["genres"]),
                         ("2027-01-15","19:00",["Metal"]))
        sor=e["go-c-20270423-vaureal-sortilege"]
        self.assertEqual((sor["title"],sor["artistIds"],sor["date"],sor["time"],
                          sor["genres"]),("Sortilège",["sortilege"],"2027-04-23",
                                          "20:30",["Heavy Metal"]))
        self.assertEqual([x["name"] for x in out["artists"][-1:]],["Sortilège"])
        same,stats=merge(BASE,out,q,day)
        self.assertEqual((stats["newEvents"],stats["newArtists"],
                          stats["newVenues"]),(0,0,0))
        self.assertEqual(same,out)

    def test_forum_2027_forged_lineups_secondary_evidence_and_clocks_are_held(self):
        day=__import__("datetime").date(2026,11,2)
        for variant in ("submask-typo","missed-rock-out","incorrect-date",
                        "wrong-clock","no-organizer-proof","fake-promoter-proof",
                        "missing-artist","wrong-heavy-genre","artist-not-verified",
                        "false-url","untrusted-reviewer"):
            with self.subTest(variant=variant):
                q=self.forum_two_new_queue()
                a=q["approvals"][0]
                b=q["approvals"][1]
                q["approvals"]=[b] if variant in ("wrong-heavy-genre",
                    "artist-not-verified") else [a]
                if variant=="submask-typo":
                    a["event"]["title"]=a["event"]["title"].replace("Submasq","Submask")
                elif variant=="missed-rock-out":
                    a["event"]["artistIds"].remove("rock-out")
                elif variant=="incorrect-date":
                    a["event"]["date"]="2027-01-16"
                elif variant=="wrong-clock":
                    a["event"]["time"]="18:30"
                elif variant=="no-organizer-proof":
                    a["officialEvidence"].pop()
                elif variant=="fake-promoter-proof":
                    a["officialEvidence"][1]["url"]="https://unknown.example/tour"
                elif variant=="missing-artist":
                    a["event"]["artistIds"][2]="submask"
                elif variant=="wrong-heavy-genre":
                    b["event"]["genres"]=["Electro"]
                elif variant=="artist-not-verified":
                    b["newArtists"]=[{"id":"sortilege","name":"Other Band"}]
                elif variant=="false-url":
                    a["event"]["officialUrl"]="https://evil.example/agenda/tour"
                elif variant=="untrusted-reviewer":
                    a["reviewedBy"]="automated-official-recheck"
                out,stats=merge(BASE,BASE,q,day)
                self.assertEqual(stats["newEvents"],0)
                self.assertTrue(stats["held"])
                self.assertEqual(out["events"],BASE["events"])

    def test_forum_2027_secondary_proof_must_be_distinct_current_exact_and_scoped(self):
        day=__import__("datetime").date(2026,11,2)
        for which in ("go-c-20270115-vaureal-motocultor-tour",
                      "go-c-20270423-vaureal-sortilege"):
            for defect in ("same-as-venue","wrong-kind","missing-venue-field",
                           "old-review","extra-proof","wrong-artist-field",
                           "switch-sources"):
                with self.subTest(which=which,defect=defect):
                    queue=self.forum_two_new_queue()
                    row=next(a for a in queue["approvals"]
                             if a["event"]["id"]==which)
                    queue["approvals"]=[row]
                    secondary=row["officialEvidence"][1]
                    if defect=="same-as-venue":
                        secondary["url"]=row["officialEvidence"][0]["url"]
                    elif defect=="wrong-kind":
                        secondary["proofType"]="official-organizer-or-venue"
                    elif defect=="missing-venue-field":
                        secondary["checkedFields"].remove("venue")
                    elif defect=="old-review":
                        secondary["checkedAt"]="2025-11-02"
                    elif defect=="extra-proof":
                        row["officialEvidence"].append(dict(secondary))
                    elif defect=="wrong-artist-field":
                        secondary["checkedFields"].remove("artists")
                    elif defect=="switch-sources":
                        row["officialEvidence"][0],row["officialEvidence"][1]=(
                            row["officialEvidence"][1],row["officialEvidence"][0])
                        row["officialEvidence"][0]["proofType"]="official-organizer-or-venue"
                    merged,stats=merge(BASE,BASE,queue,day)
                    self.assertEqual(stats["newEvents"],0)
                    self.assertTrue(stats["held"])
                    self.assertEqual(merged["events"],BASE["events"])

    def test_forum_real_named_osm_node_and_five_concerts_append_without_collisions(self):
        day=__import__("datetime").date(2026,11,2)
        q=self.forum_queue()
        out,stats=merge(BASE,BASE,q,day)
        self.assertEqual(stats["held"],[])
        self.assertEqual(stats["newVenues"],1)
        self.assertEqual(stats["newEvents"],5)
        self.assertEqual(stats["newArtists"],7)
        self.assertEqual(len(out["events"]),len(BASE["events"])+5)
        names={x["title"] for x in out["events"][-5:]}
        self.assertIn("Senser + Psykup",names)
        self.assertIn("Wolves in the Throne Room + Worm + Final Dose",names)
        self.assertIn("Harsh + Furies + Charcoal",names)
        point=out["venues"][-1]
        self.assertEqual(point["name"],"Le Forum")
        self.assertEqual((point["latitude"],point["longitude"]),(49.0313663,2.0218937))
        self.assertEqual(point["geoSource"],
             "https://www.openstreetmap.org/api/0.6/node/4742610793")
        wolves=next(x for x in out["events"]
                    if x["id"]=="go-c-20261107-vaureal-wolves-throne-room")
        self.assertIsNone(wolves["time"])
        self.assertEqual(next(x for x in out["events"]
                       if x["id"]=="go-c-20261106-vaureal-senser-psykup")["time"],
                         "20:00")
        second,again=merge(BASE,out,q,day)
        self.assertEqual(again["newEvents"],0)
        self.assertEqual(again["newVenues"],0)
        self.assertEqual(second,out)

    def test_forum_blocks_unlisted_bad_lineup_or_wrong_official_clock(self):
        day=__import__("datetime").date(2026,11,2)
        variants=("wrong-point","fake-way","unknown-event","missing-psykup",
                  "missing-worm","fake-wolves-time","wrong-date","fake-genre",
                  "wrong-official-domain","missing-clock-proof",
                  "wrong-reviewer")
        for variant in variants:
            with self.subTest(case=variant):
                q=self.forum_queue()
                q["approvals"]=q["approvals"][:2]
                a=q["approvals"][0]
                wolf=q["approvals"][1]
                if variant=="wrong-point":
                    q["venueApprovals"][0]["venue"]["longitude"]+=.01
                elif variant=="fake-way":
                    q["venueApprovals"][0]["officialEvidence"][1]["proofType"]="openstreetmap-venue-way"
                elif variant=="unknown-event":a["event"]["id"]="go-c-20261212-vaureal-unknown"
                elif variant=="missing-psykup":a["event"]["artistIds"].remove("psykup")
                elif variant=="missing-worm":wolf["event"]["artistIds"].remove("worm")
                elif variant=="fake-wolves-time":wolf["event"]["time"]="18:30"
                elif variant=="wrong-date":a["event"]["date"]="2026-11-08"
                elif variant=="fake-genre":a["event"]["genres"]=["Electro"]
                elif variant=="wrong-official-domain":a["event"]["officialUrl"]="https://example.org/agenda/senser"
                elif variant=="missing-clock-proof":a["officialEvidence"][0]["checkedFields"].remove("startTime")
                elif variant=="wrong-reviewer":a["reviewedBy"]="automated-official-recheck"
                after,stats=merge(BASE,BASE,q,day)
                self.assertTrue(stats["held"])
                if variant in ("wrong-point","fake-way"):
                    self.assertEqual(stats["newVenues"],0)
                    self.assertEqual(stats["newEvents"],0)
                else:
                    self.assertEqual(stats["newVenues"],1)
                    self.assertEqual(stats["newEvents"],1)
                self.assertEqual(after["events"][:len(BASE["events"])],
                                 BASE["events"])

    def test_cumulative_approval_limit_rejects_instead_of_silent_truncation(self):
        day=__import__("datetime").date(2026,11,2)
        q={"schema":"grossesondes.concert.approvals.v1",
           "approvals":[{} for _ in range(401)]}
        with self.assertRaisesRegex(ValueError,"Trop d.approbations"):
            merge(BASE,BASE,q,day)

    def test_fifty_two_approvals_are_processed_without_silent_limit(self):
        today=__import__("datetime").date(2026,11,2)
        # Old sync failed with ValueError at the hidden second 50-item cap.
        # 52 rejected mock records must be explicitly accounted for,
        # not silently ignored or cause an all-or-nothing crash.
        q={"schema":"grossesondes.concert.approvals.v1",
           "approvals":[{"reviewDecision":"rejected",
                         "event":{"id":f"go-c-20270101-mock-{i:03d}"}}
                        for i in range(52)]}
        result,report=merge(BASE,BASE,q,today)
        self.assertEqual(result,BASE)
        self.assertEqual(report["newEvents"],0)
        self.assertEqual(len(report["held"]),52)


    def secret_place_location_approval(self):
        from concerts_cloud_sync import SECRET_PLACE_LOCATION_FIX
        return {
            "schema": "grossesondes.concert.approvals.v1",
            "approvals": [],
            "referenceVenueCorrections": [{
                "reviewDecision": "approved",
                "reviewedBy": "independent-official-verifier",
                "reviewedAt": "2026-11-02",
                "venueId": "secret-place-saint-jean-de-vedas",
                "venuePatch": copy.deepcopy(SECRET_PLACE_LOCATION_FIX),
                "officialEvidence": [
                    {
                        "url": "https://www.toutafond.com/acces",
                        "proofType": "official-venue-address",
                        "checkedAt": "2026-11-02",
                        "checkedFields": ["name", "address", "postalCode", "city"],
                    },
                    {
                        "url": "https://www.openstreetmap.org/api/0.6/way/382485149",
                        "proofType": "openstreetmap-venue-way",
                        "checkedAt": "2026-11-02",
                        "checkedFields": ["venueName", "coordinates"],
                    },
                ],
            }],
        }

    def test_secret_place_map_fix_is_signed_precise_idempotent_and_preserves_events(self):
        from concerts_cloud_sync import (
            corrected_reference_venues, SECRET_PLACE_LOCATION_FIX
        )
        day = __import__("datetime").date(2026, 11, 2)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(BASE)
        approval = self.secret_place_location_approval()
        result, counts = merge(BASE, current, approval, day)
        self.assertEqual(counts["correctedVenues"], 1)
        self.assertEqual(counts["newEvents"], 0)
        self.assertEqual(len(result["events"]), 127)
        self.assertEqual(result["events"], current["events"])
        self.assertEqual(result["artists"], current["artists"])
        self.assertEqual(result["venues"][:53], corrected_reference_venues(BASE, secret_place=True))
        old = next(v for v in BASE["venues"] if v["id"] == "secret-place-saint-jean-de-vedas")
        fresh = next(v for v in result["venues"] if v["id"] == old["id"])
        for field in ("id", "name", "address", "city", "postalCode"):
            self.assertEqual(fresh[field], old[field])
        for field, value in SECRET_PLACE_LOCATION_FIX.items():
            self.assertEqual(fresh[field], value)
        again, stats = merge(BASE, result, approval, day)
        self.assertEqual(stats["correctedVenues"], 0)
        self.assertEqual(again, result)
        protect_reference(BASE, result)

    def test_secret_place_map_fix_rejects_missing_or_forged_evidence(self):
        from concerts_cloud_sync import corrected_reference_venues
        day = __import__("datetime").date(2026, 11, 2)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(BASE)
        approval = self.secret_place_location_approval()
        changed, _ = merge(BASE, current, approval, day)
        for variant in (
            "missing-signature", "wrong-osm-url", "missing-address-proof",
            "fictional-venue", "wrong-coordinates", "wrong-reviewer",
            "future-reviewed", "altered-address", "modified-other-venue"
        ):
            with self.subTest(variant=variant):
                candidate = copy.deepcopy(approval)
                published = copy.deepcopy(changed)
                row = candidate["referenceVenueCorrections"][0]
                if variant == "missing-signature":
                    candidate.pop("referenceVenueCorrections")
                elif variant == "wrong-osm-url":
                    row["officialEvidence"][1]["url"] = "https://example.org/way"
                elif variant == "missing-address-proof":
                    row["officialEvidence"] = row["officialEvidence"][1:]
                elif variant == "fictional-venue":
                    row["venueId"] = "other-venue"
                elif variant == "wrong-coordinates":
                    row["venuePatch"]["latitude"] += 0.1
                elif variant == "wrong-reviewer":
                    row["reviewedBy"] = "automatic-guess"
                elif variant == "future-reviewed":
                    row["reviewedAt"] = "2026-11-03"
                elif variant == "altered-address":
                    next(v for v in published["venues"] if v["id"] == row["venueId"])["address"] = "adresse falsifiée"
                elif variant == "modified-other-venue":
                    published["venues"][0]["latitude"] += 0.1
                with self.assertRaises((ValueError, KeyError)):
                    merge(BASE, published, candidate, day)

    def rex_location_approval(self):
        from concerts_cloud_sync import REX_LOCATION_FIX
        return {
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-03",
            "venueId": "le-rex-toulouse",
            "venuePatch": copy.deepcopy(REX_LOCATION_FIX),
            "officialEvidence": [
                {
                    "url": "https://www.lerextoulouse.com/fr/contact/acces/",
                    "proofType": "official-venue-gps",
                    "checkedAt": "2026-11-03",
                    "checkedFields": [
                        "name", "address", "postalCode", "city", "latitude", "longitude"
                    ],
                },
                {
                    "url": "https://www.toulouse-tourisme.com/activite/le-rex-de-toulouse/",
                    "proofType": "tourism-office-address",
                    "checkedAt": "2026-11-03",
                    "checkedFields": ["name", "address", "postalCode", "city"],
                },
            ],
        }

    def test_rex_location_correction_preserves_127_events_and_is_idempotent(self):
        from concerts_cloud_sync import corrected_reference_venues, REX_LOCATION_FIX
        day = __import__("datetime").date(2026, 11, 3)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(BASE, secret_place=True)
        approvals = self.secret_place_location_approval()
        approvals["referenceVenueCorrections"].append(self.rex_location_approval())
        changed, stats = merge(BASE, current, approvals, day)
        self.assertEqual(stats["newEvents"], 0)
        self.assertEqual(stats["correctedVenues"], 1)
        self.assertEqual(changed["events"], current["events"])
        self.assertEqual(changed["artists"], current["artists"])
        self.assertEqual(
            changed["venues"][:53],
            corrected_reference_venues(BASE, secret_place=True, le_rex=True)
        )
        old = next(v for v in current["venues"] if v["id"] == "le-rex-toulouse")
        new = next(v for v in changed["venues"] if v["id"] == "le-rex-toulouse")
        for key in ("id", "name", "city", "department", "region"):
            self.assertEqual(new[key], old[key])
        for key, value in REX_LOCATION_FIX.items():
            self.assertEqual(new[key], value)
        again, second = merge(BASE, changed, approvals, day)
        self.assertEqual(again, changed)
        self.assertEqual(second["correctedVenues"], 0)
        protect_reference(BASE, changed)

    def test_rex_and_secret_place_can_be_reviewed_together_without_baseline_rewrite(self):
        from concerts_cloud_sync import corrected_reference_venues
        day = __import__("datetime").date(2026, 11, 3)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(BASE)
        approvals = self.secret_place_location_approval()
        approvals["referenceVenueCorrections"].append(self.rex_location_approval())
        result, stats = merge(BASE, current, approvals, day)
        self.assertEqual(stats["correctedVenues"], 2)
        self.assertEqual(result["events"], current["events"])
        self.assertEqual(result["venues"][:53],
                         corrected_reference_venues(BASE, secret_place=True, le_rex=True))
        protect_reference(BASE, result)

    def test_rex_rejects_fake_gps_signature_or_missing_independent_proof(self):
        from concerts_cloud_sync import corrected_reference_venues
        day = __import__("datetime").date(2026, 11, 3)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(BASE, secret_place=True)
        approvals = self.secret_place_location_approval()
        approvals["referenceVenueCorrections"].append(self.rex_location_approval())
        changed, _ = merge(BASE, current, approvals, day)
        for variant in (
            "missing-signed-review", "forged-gps", "forged-source",
            "missing-tourism", "unapproved-reviewer", "wrong-date",
            "duplicate-rex", "unrelated-venue-changed"
        ):
            with self.subTest(variant=variant):
                q = copy.deepcopy(approvals)
                published = copy.deepcopy(changed)
                rex = q["referenceVenueCorrections"][1]
                if variant == "missing-signed-review":
                    q["referenceVenueCorrections"] = q["referenceVenueCorrections"][:1]
                elif variant == "forged-gps":
                    rex["venuePatch"]["latitude"] += 0.01
                elif variant == "forged-source":
                    rex["officialEvidence"][0]["url"] = "https://example.com/rex"
                elif variant == "missing-tourism":
                    rex["officialEvidence"] = rex["officialEvidence"][:1]
                elif variant == "unapproved-reviewer":
                    rex["reviewedBy"] = "guess"
                elif variant == "wrong-date":
                    rex["reviewedAt"] = "2026-11-04"
                elif variant == "duplicate-rex":
                    q["referenceVenueCorrections"].append(copy.deepcopy(rex))
                elif variant == "unrelated-venue-changed":
                    published["venues"][0]["latitude"] += 0.01
                with self.assertRaises((ValueError, KeyError)):
                    merge(BASE, published, q, day)

    def test_no_approval_means_exactly_127(self):
        current,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                       "approvals":[]},NOW)
        self.assertEqual(current,BASE)
        self.assertEqual(stats["newEvents"],0)



class BikiniIndependentReviewTests(unittest.TestCase):
    """Freeze exact first-party bills; refuse an invented concert start time."""

    @staticmethod
    def approved_row(spec, event_id):
        return {
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-03",
            "officialEvidence": [
                {
                    "url": spec["officialUrl"],
                    "proofType": "official-organizer-or-venue",
                    "checkedAt": "2026-11-03",
                    "checkedFields": ["artists", "date", "venue", "genre"],
                },
                {
                    "url": "https://lebikini.com/programmation/-/concert",
                    "proofType": "first-party-venue-calendar",
                    "checkedAt": "2026-11-03",
                    "checkedFields": ["artists", "date", "venue", "genre"],
                },
            ],
            "event": {
                "id": event_id,
                "title": spec["title"],
                "date": spec["date"],
                "time": None,
                "venueId": "le-bikini-toulouse",
                "artistIds": copy.deepcopy(spec["artistIds"]),
                "genres": copy.deepcopy(spec["genres"]),
                "status": "confirmed",
                "officialUrl": spec["officialUrl"],
                "sourceType": "salle",
            },
            "newArtists": copy.deepcopy(spec["newArtists"]),
        }

    def test_four_approved_bikini_bills_and_safety_rejections(self):
        from concerts_cloud_sync import (
            BIKINI_OFFICIAL_VERIFIED, validate_approval
        )
        day = __import__("datetime").date(2026, 11, 3)
        venues = {
            "le-bikini-toulouse": next(
                v for v in BASE["venues"] if v["id"] == "le-bikini-toulouse")
        }
        self.assertEqual(len(BIKINI_OFFICIAL_VERIFIED), 7)
        for event_id, spec in BIKINI_OFFICIAL_VERIFIED.items():
            with self.subTest(event_id=event_id):
                new_ids = {a["id"] for a in spec["newArtists"]}
                known = {
                    aid: {"id": aid, "name": name, "aliases": []}
                    for aid, name in zip(spec["artistIds"], spec["artistNames"])
                    if aid not in new_ids
                }
                row = self.approved_row(spec, event_id)
                event, artists = validate_approval(row, venues, known, day)
                self.assertEqual(event["id"], event_id)
                self.assertIsNone(event["time"])
                self.assertEqual(set(artists), new_ids)
                for change in ("doors-as-start", "wrong-host", "other-lineup",
                               "missing-calendar", "wrong-venue", "fake-genre"):
                    invalid = copy.deepcopy(row)
                    if change == "doors-as-start":
                        invalid["event"]["time"] = "19:30"
                    elif change == "wrong-host":
                        invalid["event"]["officialUrl"] = "https://example.com/event"
                    elif change == "other-lineup":
                        invalid["event"]["artistIds"] = ["unverified-act"]
                    elif change == "missing-calendar":
                        invalid["officialEvidence"].pop()
                    elif change == "wrong-venue":
                        invalid["event"]["venueId"] = "le-rex-toulouse"
                    else:
                        invalid["event"]["genres"] = ["Unverified"]
                    with self.assertRaises((ValueError, KeyError)):
                        validate_approval(invalid, venues, known, day)


    def test_bikini_old_url_slug_does_not_allow_replaced_opening_act(self):
        """The historic URL says Tailgunner; the live official bill says Enforcer."""
        from concerts_cloud_sync import BIKINI_OFFICIAL_VERIFIED, validate_approval
        identifier = "go-c-20261129-toulouse-accept"
        spec = BIKINI_OFFICIAL_VERIFIED[identifier]
        self.assertIn("tailgunner", spec["officialUrl"])
        self.assertEqual(spec["artistNames"], ["Accept", "Dynazty", "Enforcer"])
        self.assertEqual(spec["genres"], ["Heavy Metal"])
        row = self.approved_row(spec, identifier)
        venues = {
            "le-bikini-toulouse": next(
                v for v in BASE["venues"] if v["id"] == "le-bikini-toulouse")
        }
        known = {
            aid: {"id": aid, "name": name, "aliases": []}
            for aid, name in zip(spec["artistIds"], spec["artistNames"])
        }
        # Even if the old support act were otherwise a known artist,
        # the published bill must not take its lineup from the URL slug.
        known["tailgunner"] = {
            "id": "tailgunner", "name": "Tailgunner", "aliases": []
        }
        valid, _ = validate_approval(row, venues, known, __import__("datetime").date(2026,11,3))
        self.assertEqual(valid["artistIds"], ["accept","dynazty","enforcer"])
        forged = copy.deepcopy(row)
        forged["event"]["artistIds"] = ["accept","dynazty","tailgunner"]
        forged["event"]["title"] = (
            'Accept "50th Anniversary Tour" + Dynazty + Tailgunner')
        with self.assertRaises((ValueError,KeyError)):
            validate_approval(
                forged, venues, known, __import__("datetime").date(2026,11,3))



class RockstoreBlackLabOfficialSafetyTests(unittest.TestCase):
    """Frozen first-party approvals; never infer show start or artist identity."""

    @staticmethod
    def row(spec, event_id):
        return {
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-03",
            "officialEvidence": [
                {"url": spec["officialUrl"],
                 "proofType": "official-organizer-or-venue",
                 "checkedAt": "2026-11-03",
                 "checkedFields": ["artists", "date", "venue", "genre"]},
                {"url": spec["calendarUrl"],
                 "proofType": "first-party-venue-calendar",
                 "checkedAt": "2026-11-03",
                 "checkedFields": ["artists", "date", "venue"]},
            ],
            "event": {
                "id": event_id,
                "title": spec["title"],
                "date": spec["date"],
                "time": None,
                "venueId": spec["venueId"],
                "artistIds": copy.deepcopy(spec["artistIds"]),
                "genres": copy.deepcopy(spec["genres"]),
                "status": "confirmed",
                "officialUrl": spec["officialUrl"],
                "sourceType": "salle",
            },
            "newArtists": copy.deepcopy(spec["newArtists"]),
        }

    @staticmethod
    def known(spec):
        fresh_ids = {a["id"] for a in spec["newArtists"]}
        return {
            aid: {"id": aid, "name": name, "aliases": []}
            for aid, name in zip(spec["artistIds"], spec["artistNames"])
            if aid not in fresh_ids
        }

    def test_four_bills_validate_and_reject_six_forms_of_tampering(self):
        from concerts_cloud_sync import (
            ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED, validate_approval
        )
        day = __import__("datetime").date(2026, 11, 3)
        venue_ids = ("rockstore-montpellier", "the-black-lab-wasquehal")
        venues = {v["id"]: v for v in BASE["venues"]
                  if v["id"] in venue_ids}
        self.assertEqual(len(ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED), 4)
        for event_id, spec in ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED.items():
            with self.subTest(event_id=event_id):
                row = self.row(spec, event_id)
                evt, artists = validate_approval(
                    row, venues, self.known(spec), day)
                self.assertEqual(evt["id"], event_id)
                self.assertIsNone(evt["time"])
                self.assertEqual(set(artists),
                                 {x["id"] for x in spec["newArtists"]})
                for variant in ("inferred-time", "changed-date",
                                "changed-genre", "wrong-host",
                                "missing-calendar", "changed-artist",
                                "wrong-venue", "forged-review"):
                    candidate = copy.deepcopy(row)
                    if variant == "inferred-time":
                        candidate["event"]["time"] = "19:00"
                    elif variant == "changed-date":
                        candidate["event"]["date"] = "2026-12-31"
                    elif variant == "changed-genre":
                        candidate["event"]["genres"] = ["Rap"]
                    elif variant == "wrong-host":
                        candidate["event"]["officialUrl"] = "https://evil.example/gig"
                    elif variant == "missing-calendar":
                        candidate["officialEvidence"].pop()
                    elif variant == "changed-artist":
                        candidate["event"]["artistIds"] = ["fake-act"]
                    elif variant == "wrong-venue":
                        candidate["event"]["venueId"] = (
                            "the-black-lab-wasquehal"
                            if spec["venueId"] == "rockstore-montpellier"
                            else "rockstore-montpellier"
                        )
                    elif variant == "forged-review":
                        candidate["reviewedBy"] = "automated-official-recheck"
                    with self.subTest(variant=variant), self.assertRaises(
                            (ValueError, KeyError)):
                        validate_approval(
                            candidate, venues, self.known(spec), day)

    def test_four_first_party_bills_merge_without_touching_reference(self):
        from concerts_cloud_sync import (
            ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED,
        )
        day = __import__("datetime").date(2026, 11, 3)
        specs = ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED
        approvals = [self.row(spec, event_id)
                     for event_id, spec in specs.items()]
        # Three artists are already in the live cloud catalogue, but not
        # in the immutable 193-artist reference. Seed a current-state fixture
        # with exactly these known identities without rewriting the baseline.
        current = copy.deepcopy(BASE)
        catalogue = json.loads((ROOT / "docs/grossesondes/concerts.json")
                               .read_text(encoding="utf-8"))
        known = {x["id"] for x in current["artists"]}
        current["artists"].extend(copy.deepcopy(x)
                                  for x in catalogue["artists"]
                                  if x["id"] in {"houle", "can-bardd", "galibot"}
                                  and x["id"] not in known)
        out, stats = merge(
            BASE, current,
            {"schema": "grossesondes.concert.approvals.v1",
             "approvals": approvals, "venueApprovals": []},
            day,
        )
        self.assertEqual(stats["held"], [])
        self.assertEqual(stats["newEvents"], 4)
        self.assertEqual(stats["newArtists"], 2)
        self.assertEqual(out["events"][:127], BASE["events"])
        self.assertEqual(out["venues"][:53], BASE["venues"])
        protect_reference(BASE, out)
        validate_catalogue(out)

    def test_queue_ceiling_is_still_enforced_at_400(self):
        from concerts_cloud_sync import ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED
        event_id, spec = next(iter(
            ROCKSTORE_BLACKLAB_OFFICIAL_VERIFIED.items()))
        row = self.row(spec, event_id)
        with self.assertRaisesRegex(ValueError, "Trop d.approbations"):
            merge(
                BASE, BASE,
                {"schema": "grossesondes.concert.approvals.v1",
                 "approvals": [row] * 401, "venueApprovals": []},
                __import__("datetime").date(2026, 11, 3),
            )


class ThreeHistoricVenueGeoCorrectionTests(unittest.TestCase):
    """Exact source-bound patches, idempotent and historic snapshot protected."""

    @staticmethod
    def private_review_fixture():
        from concerts_cloud_sync import NEW_REFERENCE_GEO_SOURCES
        legacy = ConcertsCloudSyncTests()
        approvals = legacy.secret_place_location_approval()
        approvals["referenceVenueCorrections"].append(
            legacy.rex_location_approval())
        for venue_id, spec in NEW_REFERENCE_GEO_SOURCES.items():
            approvals["referenceVenueCorrections"].append({
                "venueId": venue_id,
                "reviewDecision": "approved",
                "reviewedBy": "independent-official-verifier",
                "reviewedAt": "2026-11-03",
                "venuePatch": copy.deepcopy(spec["patch"]),
                "officialEvidence": [
                    {"url": spec["officialUrl"],
                     "proofType": spec["officialProof"],
                     "checkedAt": "2026-11-03",
                     "checkedFields": sorted(spec["officialFields"])},
                    {"url": spec["geoUrl"],
                     "proofType": spec["geoProof"],
                     "checkedAt": "2026-11-03",
                     "checkedFields": sorted(spec["geoFields"])},
                ],
            })
        return approvals

    def test_all_four_exact_fixes_preserve_reference_and_are_idempotent(self):
        from concerts_cloud_sync import (
            NEW_REFERENCE_GEO_SOURCES, corrected_reference_venues
        )
        day = __import__("datetime").date(2026, 11, 3)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(
            BASE, secret_place=True, le_rex=True)
        signed = self.private_review_fixture()
        corrected, stats = merge(BASE, current, signed, day)
        self.assertEqual(stats["correctedVenues"], 4)
        self.assertEqual(stats["newEvents"], 0)
        self.assertEqual(corrected["events"], current["events"])
        self.assertEqual(corrected["artists"], current["artists"])
        self.assertEqual(
            corrected["venues"][:53],
            corrected_reference_venues(
                BASE, secret_place=True, le_rex=True,
                extra_venues=tuple(NEW_REFERENCE_GEO_SOURCES)))
        for venue_id, spec in NEW_REFERENCE_GEO_SOURCES.items():
            old = next(v for v in current["venues"] if v["id"] == venue_id)
            fixed = next(v for v in corrected["venues"] if v["id"] == venue_id)
            self.assertEqual(fixed["name"], old["name"])
            for key, val in spec["patch"].items():
                self.assertEqual(fixed[key], val)
        self.assertEqual(next(v for v in corrected["venues"]
                              if v["id"] == "le-bikini-toulouse")["city"],
                         "Ramonville-Saint-Agne")
        again, counts = merge(BASE, corrected, signed, day)
        self.assertEqual(counts["correctedVenues"], 0)
        self.assertEqual(again, corrected)
        protect_reference(BASE, corrected)
        validate_catalogue(corrected)

    def test_four_fixes_can_be_approved_one_by_one_without_reversions(self):
        from concerts_cloud_sync import (
            NEW_REFERENCE_GEO_SOURCES, corrected_reference_venues
        )
        day = __import__("datetime").date(2026, 11, 3)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(
            BASE, secret_place=True, le_rex=True)
        signatures = self.private_review_fixture()
        for n, venue_id in enumerate(NEW_REFERENCE_GEO_SOURCES, start=1):
            subset = copy.deepcopy(signatures)
            subset["referenceVenueCorrections"] = [
                x for x in signatures["referenceVenueCorrections"]
                if x["venueId"] in
                {"secret-place-saint-jean-de-vedas", "le-rex-toulouse",
                 *list(NEW_REFERENCE_GEO_SOURCES)[:n]}
            ]
            current, result = merge(BASE, current, subset, day)
            self.assertEqual(result["correctedVenues"], 1)
            self.assertEqual(len(current["events"]), 127)
            protect_reference(BASE, current)

    def test_any_missing_or_forged_geo_evidence_is_rejected(self):
        from concerts_cloud_sync import corrected_reference_venues
        day = __import__("datetime").date(2026, 11, 3)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(
            BASE, secret_place=True, le_rex=True)
        signed = self.private_review_fixture()
        corrected, _ = merge(BASE, current, signed, day)
        for venue_id in ("le-bikini-toulouse", "rockstore-montpellier",
                         "the-black-lab-wasquehal"):
            for variant in (
                "missing-persistent-signature", "wrong-osm-node",
                "wrong-official-address", "altered-coordinates",
                "altered-city", "wrong-reviewer", "future-date",
                "missing-official-proof", "changed-other-venue"):
                with self.subTest(venue_id=venue_id, variant=variant):
                    q = copy.deepcopy(signed)
                    published = copy.deepcopy(corrected)
                    row = next(x for x in q["referenceVenueCorrections"]
                               if x["venueId"] == venue_id)
                    if variant == "missing-persistent-signature":
                        q["referenceVenueCorrections"].remove(row)
                    elif variant == "wrong-osm-node":
                        row["officialEvidence"][1]["url"] = "https://example.org/node"
                    elif variant == "wrong-official-address":
                        row["officialEvidence"][0]["url"] = "https://example.org/venue"
                    elif variant == "altered-coordinates":
                        row["venuePatch"]["latitude"] += 0.025
                    elif variant == "altered-city":
                        row["venuePatch"]["city"] = "Paris"
                    elif variant == "wrong-reviewer":
                        row["reviewedBy"] = "automatic-guess"
                    elif variant == "future-date":
                        row["reviewedAt"] = "2026-11-04"
                    elif variant == "missing-official-proof":
                        row["officialEvidence"].pop(0)
                    elif variant == "changed-other-venue":
                        published["venues"][0]["longitude"] += 0.1
                    with self.assertRaises((ValueError, KeyError)):
                        merge(BASE, published, q, day)

    def test_extra_venue_ids_and_duplicate_signed_rows_refused(self):
        from concerts_cloud_sync import (
            NEW_REFERENCE_GEO_SOURCES, corrected_reference_venues)
        day = __import__("datetime").date(2026, 11, 3)
        current = copy.deepcopy(BASE)
        current["venues"] = corrected_reference_venues(BASE)
        signed = self.private_review_fixture()
        fake = copy.deepcopy(signed)
        fake["referenceVenueCorrections"][2]["venueId"] = "unknown-fake-venue"
        with self.assertRaises((ValueError, KeyError)):
            merge(BASE, current, fake, day)
        duplicate = copy.deepcopy(signed)
        duplicate["referenceVenueCorrections"][3]["venueId"] = (
            duplicate["referenceVenueCorrections"][2]["venueId"])
        with self.assertRaises((ValueError, KeyError)):
            merge(BASE, current, duplicate, day)
        self.assertEqual(len(NEW_REFERENCE_GEO_SOURCES), 4)



class BretagneStrictAllowlist20261103Tests(unittest.TestCase):
    """Deux dates brestoises admises nominativement, jamais les pistes brutes."""

    @staticmethod
    def row(event_id):
        from concerts_cloud_sync import CARENE_VERIFIED
        spec = CARENE_VERIFIED[event_id]
        new = {
            "fff": "FFF",
            "les-fatals-picards": "Les Fatals Picards",
        }
        return {
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-03",
            "officialEvidence": [
                {
                    "url": spec["officialUrl"],
                    "proofType": "official-organizer-or-venue",
                    "checkedAt": "2026-11-03",
                    "checkedFields": ["artists", "date", "venue", "genre", "startTime"],
                },
                {
                    "url": "https://www.lacarene.fr/-agenda-.html",
                    "proofType": "first-party-venue-calendar",
                    "checkedAt": "2026-11-03",
                    "checkedFields": ["artists", "date", "venue"],
                },
            ],
            "event": {
                "id": event_id,
                "title": spec["title"],
                "date": spec["date"],
                "time": spec["time"],
                "artistIds": list(spec["artistIds"]),
                "venueId": "la-carene-brest",
                "genres": list(spec["genres"]),
                "status": "confirmed",
                "officialUrl": spec["officialUrl"],
                "sourceType": "salle",
            },
            "newArtists": [{"id": aid, "name": new[aid]} for aid in spec["newArtistIds"]],
        }

    @staticmethod
    def source_data():
        cat = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        venue = next(v for v in cat["venues"] if v["id"] == "la-carene-brest")
        # La lecture du catalogue ne réhabilite pas les artistes déjà nouveaux
        # si une exécution de synchronisation a entre-temps publié les dates.
        excluded = {"fff", "les-fatals-picards"}
        artists = {x["id"]: x for x in cat["artists"] if x["id"] not in excluded}
        return {"la-carene-brest": venue}, artists

    def test_two_named_brest_approvals_pass_with_both_first_party_proofs(self):
        venues, artists = self.source_data()
        for event_id in (
            "go-c-20261209-brest-fff-howlin-jaws",
            "go-c-20270402-brest-les-fatals-picards",
        ):
            with self.subTest(event_id=event_id):
                row = self.row(event_id)
                event, added = validate_approval(
                    row, venues, artists, __import__("datetime").date(2026, 11, 3))
                self.assertEqual(event["id"], event_id)
                self.assertIsNone(event["time"])
                self.assertEqual(list(added), [a["id"] for a in row["newArtists"]])

    def test_no_approval_without_original_official_calendar_or_without_exact_bill(self):
        venues, artists = self.source_data()
        for event_id in (
            "go-c-20261209-brest-fff-howlin-jaws",
            "go-c-20270402-brest-les-fatals-picards",
        ):
            row = self.row(event_id)
            invalid = []
            a = copy.deepcopy(row)
            a["officialEvidence"][1]["url"] = "https://billetterie.example.org/agenda"
            invalid.append(a)
            a = copy.deepcopy(row)
            a["event"]["time"] = "20:00"  # portes ou heure non approuvée
            invalid.append(a)
            a = copy.deepcopy(row)
            a["event"]["date"] = "2027-02-25"
            invalid.append(a)
            a = copy.deepcopy(row)
            a["event"]["id"] += "-autre"
            invalid.append(a)
            for payload in invalid:
                with self.subTest(event_id=event_id, changed=payload["event"]):
                    with self.assertRaises((ValueError, KeyError)):
                        validate_approval(
                            payload, venues, artists,
                            __import__("datetime").date(2026, 11, 3))


class NationalGapLot20261104Tests(unittest.TestCase):
    """Quinze fiches autorisées individuellement, sans admission par domaine entier."""

    IDS = (
        "go-c-20261113-nancy-michel-cloup-trio",
        "go-c-20261121-nancy-les-fatals-picards",
        "go-c-20261212-nancy-benighted",
        "go-c-20270205-nancy-skip-the-use",
        "go-c-20270216-nancy-laibach",
        "go-c-20270224-nancy-maquina",
        "go-c-20270206-reims-skip-the-use",
        "go-c-20270211-reims-pamela",
        "go-c-20270218-reims-revnoir",
        "go-c-20270219-reims-la-jungle",
        "go-c-20270319-reims-ayron-jones",
        "go-c-20270403-reims-igorrr",
        "go-c-20270409-reims-rodrigo-y-gabriela",
        "go-c-20270312-poitiers-tramhaus",
        "go-c-20261115-wasquehal-cage-fight",
    )

    @classmethod
    def setUpClass(cls):
        from concerts_cloud_sync import UNDERCOVERED_REGIONS_NOV2026_VERIFIED
        cls.specs = UNDERCOVERED_REGIONS_NOV2026_VERIFIED
        cls.catalogue = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues = {v["id"]: v for v in cls.catalogue["venues"]}
        cls.artists = {a["id"]: a for a in cls.catalogue["artists"]}
        cls.today = __import__("datetime").date(2026, 11, 4)

    def row(self, event_id):
        spec = self.specs[event_id]
        return {
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-04",
            "officialEvidence": [
                {"url": spec["officialUrl"], "proofType": "official-organizer-or-venue",
                 "checkedAt": "2026-11-04", "checkedFields": ["artists", "date", "venue", "genre"]},
                {"url": spec["calendarUrl"], "proofType": "first-party-venue-calendar",
                 "checkedAt": "2026-11-04", "checkedFields": ["artists", "date", "venue"]},
            ],
            "event": {
                "id": event_id, "title": spec["title"], "date": spec["date"],
                "time": None, "artistIds": list(spec["artistIds"]),
                "venueId": spec["venueId"], "genres": list(spec["genres"]),
                "status": "confirmed", "officialUrl": spec["officialUrl"],
                "sourceType": "salle",
            },
            "newArtists": copy.deepcopy(spec["newArtists"]),
        }

    def test_fifteen_named_events_have_unique_ids_no_prior_collision_and_valid_signatures(self):
        from concerts_cloud_sync import validate_approval
        self.assertEqual(len(self.IDS), 15)
        self.assertEqual(len(set(self.IDS)), len(self.IDS))
        existing = {e["id"] for e in self.catalogue["events"]}
        for event_id in self.IDS:
            with self.subTest(event_id=event_id):
                self.assertNotIn(event_id, existing)
                row = self.row(event_id)
                event, added = validate_approval(row, self.venues, self.artists, self.today)
                self.assertEqual(event["id"], event_id)
                self.assertIsNone(event["time"])
                self.assertEqual(sorted(added), sorted(a["id"] for a in row["newArtists"]))
                self.assertEqual(len(row["officialEvidence"]), 2)

    def test_forged_details_or_missing_official_calendar_are_rejected(self):
        from concerts_cloud_sync import validate_approval
        for event_id in self.IDS:
            approved = self.row(event_id)
            variants = []
            variant = copy.deepcopy(approved)
            variant["event"]["title"] += " + Groupe imaginaire"
            variants.append(variant)
            variant = copy.deepcopy(approved)
            variant["event"]["date"] = "2027-10-01"
            variants.append(variant)
            variant = copy.deepcopy(approved)
            variant["event"]["time"] = "20:00"  # portes / créneau, pas début musical
            variants.append(variant)
            variant = copy.deepcopy(approved)
            variant["officialEvidence"] = variant["officialEvidence"][:1]
            variants.append(variant)
            variant = copy.deepcopy(approved)
            variant["event"]["officialUrl"] = "https://invalid.example.org/affiche"
            variants.append(variant)
            variant = copy.deepcopy(approved)
            variant["event"]["venueId"] = "le-molotov-marseille"
            variants.append(variant)
            for i, bad in enumerate(variants):
                with self.subTest(event_id=event_id, mutation=i):
                    with self.assertRaises((ValueError, KeyError)):
                        validate_approval(bad, self.venues, self.artists, self.today)


if __name__=="__main__":
    unittest.main()
