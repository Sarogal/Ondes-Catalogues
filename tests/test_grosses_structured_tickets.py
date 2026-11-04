import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_structured_tickets import (
    official_ticket_categories, validate_structured_tickets, PROOF_MODE
)
from grossesondes_stage import stage
from grossesondes_cloud_sync import collect_registered_update_sources
from grossesondes_calendar_approval import merge_staged_with_approved
from test_grosses_stage import fixtures

ROW = {"slug":"metal-fest-2027", "name":"Metal Fest 2027",
       "startDate":"2027-08-12", "endDate":"2027-08-13",
       "officialSite":"https://metal-fest.example.org/",
       "status":"Confirmé", "lastVerified":"2026-10-01"}
DAY = "2026-11-05"


def event(**kw):
    v={"@type":"MusicFestival", "name":ROW["name"],
       "startDate":ROW["startDate"], "endDate":ROW["endDate"],
       "offers":[{"name":"Pass samedi","availability":"SoldOut"},
                 {"name":"Pass dimanche","availability":"InStock"}]}
    v.update(kw)
    return v


def page(*events):
    return '<script type="application/ld+json">'+json.dumps({"@graph":list(events)})+'</script>'


def proposed():
    return {"slug":ROW["slug"],"proofMode":PROOF_MODE,
            "evidence":[ROW["officialSite"]],"verified_at":DAY,
            "changes":[{"field":"ticketAvailability","before":None,
                        "after":{"source":ROW["officialSite"],"verifiedAt":DAY,
                                 "scope":"per_category_only",
                                 "categories":[
                                     {"name":"Pass dimanche","status":"in_stock"},
                                     {"name":"Pass samedi","status":"sold_out"}]}}]}


class TicketTests(unittest.TestCase):
    def test_exact_categories_not_global_sold_out(self):
        result=validate_structured_tickets(ROW,proposed(),page(event()),DAY)
        self.assertIsNotNone(result)
        self.assertEqual(result[1],["ticketAvailability"])
        self.assertEqual(result[0]["status"],"Confirmé")
        self.assertIsNone(validate_structured_tickets(
            ROW,proposed(),"<p>Sold out</p>",DAY))

    def test_generic_schema_event_requires_exact_official_edition(self):
        # Generic Event is accepted only for a unique name, year and date match.
        generic = event(**{"@type": "Event"})
        self.assertEqual(official_ticket_categories(page(generic), ROW), [
            {"name": "Pass dimanche", "status": "in_stock"},
            {"name": "Pass samedi", "status": "sold_out"},
        ])
        self.assertIsNone(official_ticket_categories(
            page(event(**{"@type": "Event", "name": "Metal Fest"})), ROW))
        self.assertIsNone(official_ticket_categories(
            page(event(**{"@type": "Event", "startDate": "2027-08-14"})), ROW))
        self.assertIsNone(official_ticket_categories(
            page(event(**{"@type": "OtherEvent"})), ROW))

    def test_dates_year_status_or_conflicting_events_rejected(self):
        for altered in (
            event(name="Metal Fest"),
            event(name="Different Metal Fest 2027"),
            event(startDate="2027-08-14"),
            event(eventStatus="EventCancelled"),
            event(eventStatus="EventPostponed"),
            event(offers=[{"name":"Pass samedi","availability":"InStock"},
                          {"name":"Pass samedi","availability":"SoldOut"}]),
            event(offers=[{"name":"Pass samedi","availability":"https://evil.org/SoldOut"}])
        ):
            self.assertIsNone(official_ticket_categories(page(altered),ROW))
        self.assertIsNone(official_ticket_categories(
            page(event(), event(offers=[{"name":"Pass samedi","availability":"SoldOut"}])),ROW))

    def test_forged_patch_and_stale_data_rejected(self):
        cases=[
            ("evidence",["https://unregistered.example.org"]),
            ("verified_at","2026-11-07"),
        ]
        for field, val in cases:
            p=proposed()
            p[field]=val
            self.assertIsNone(validate_structured_tickets(ROW,p,page(event()),DAY))
        for field, val in (("scope","whole_festival_sold_out"),
                           ("verifiedAt","2026-10-01")):
            p=proposed()
            p["changes"][0]["after"][field]=val
            self.assertIsNone(validate_structured_tickets(ROW,p,page(event()),DAY))
        p=proposed()
        p["changes"][0]["after"]["categories"][0]["status"]="sold_out"
        self.assertIsNone(validate_structured_tickets(ROW,p,page(event()),DAY))
        p=proposed()
        p["changes"].append({"field":"status","before":"Confirmé","after":"Annulé"})
        self.assertIsNone(validate_structured_tickets(ROW,p,page(event()),DAY))

    def test_independent_fetch_uses_registered_url_not_private_evidence(self):
        seen=[]
        def fetcher(url,registered=False,raw=False):
            seen.append((url,registered,raw))
            return page(event())
        sources=collect_registered_update_sources(
            {"updates":[proposed()]},{ROW["slug"]:ROW},fetcher)
        self.assertEqual(seen,[(ROW["officialSite"],True,True)])
        self.assertEqual(sources["registered-ticket:"+ROW["slug"]],page(event()))

    def test_stage_requires_fresh_evidence(self):
        c,h,p=fixtures()
        c["festivals"][3]=dict(ROW)
        p["updates"]=[proposed()]
        p["additions"]=[]
        out,r=stage(c,h,p,{},DAY)
        self.assertEqual(r["accepted_updates"],[])
        out,r=stage(c,h,p,{"registered-ticket:"+ROW["slug"]:page(event())},DAY)
        self.assertEqual(r["accepted_updates"][0]["fields"],["ticketAvailability"])
        self.assertEqual(out["festivals"][3]["ticketAvailability"]["scope"],
                         "per_category_only")

    def test_stale_cumulative_replay_cannot_downgrade_newer(self):
        from copy import deepcopy
        base={"schema":1,"festivals":[dict(ROW)]}
        staged=deepcopy(base)
        staged["festivals"][0]["ticketAvailability"]=proposed()["changes"][0]["after"]
        trusted=deepcopy(staged)
        trusted["festivals"][0]["ticketAvailability"]["verifiedAt"]="2026-11-06"
        merged=merge_staged_with_approved(base,staged,trusted)
        self.assertEqual(merged["festivals"][0]["ticketAvailability"]["verifiedAt"],"2026-11-06")
        trusted["festivals"][0]["ticketAvailability"]["verifiedAt"]=DAY
        trusted["festivals"][0]["ticketAvailability"]["categories"][0]["status"]="sold_out"
        with self.assertRaises(ValueError):
            merge_staged_with_approved(base,staged,trusted)


if __name__=="__main__":
    unittest.main()
