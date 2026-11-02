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
                    "checkedFields":["artists","date","venue","genre"]
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
                        "not-named-event","missing-proof"):
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

    def test_no_approval_means_exactly_127(self):
        current,stats=merge(BASE,BASE,{"schema":"grossesondes.concert.approvals.v1",
                                       "approvals":[]},NOW)
        self.assertEqual(current,BASE)
        self.assertEqual(stats["newEvents"],0)


if __name__=="__main__":
    unittest.main()
