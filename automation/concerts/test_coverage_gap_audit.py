"""Offline, no-publication tests for nationwide concert coverage ranking."""
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from coverage_gap_audit import evaluate,public_url,report_md

TODAY=dt.date(2026,11,2)
CAT={"venues":[{"id":"v","name":"Salle","city":"Nantes","region":"Pays de la Loire"}],
     "artists":[{"id":"x","name":"Already"}],
     "events":[{"id":"e","title":"Already","date":"2026-11-20",
                "venueId":"v","artistIds":["x"]}]}
SRC={"schema":"grossesondes.concert.sourcelist.v1","venues":[{"name":"Salle","city":"Nantes"}]}
NAT={"schema":"grossesondes.concert.venues.v1","venues":[
    {"name":"Salle","city":"Nantes","sourceType":"existing"},
    {"name":"Nouveau Club","city":"Lille","sourceType":"official"}]}

def item(name,date="2026-12-05",genre=None,**extra):
    return {"status":"pending_review","candidate":{
        "name":name,"leadArtist":name,"date":date,"venue":"Nouveau Club",
        "city":"Lille","department":"59","classification":genre or [],
        "source":"agenda_officiel_structuré",
        "sourceUrl":"https://club.example/evenement/"+name.lower().replace(" ","-"),
        **extra}}

def audit(items):
    return evaluate(CAT,{"schema":"grossesondes.concert.intake.v1",
                         "items":{str(i):r for i,r in enumerate(items)}},
                    SRC,NAT,TODAY)

class TestCoverageGapAudit(unittest.TestCase):
    def test_new_genre_lead_is_prioritized_but_never_approved(self):
        r=audit([item("Loud Act",genre=["Thrash Metal"]),item("Mystery")])
        self.assertEqual(r["catalogue"]["upcoming"],1)
        self.assertEqual(r["discovery"]["potentialMissing"],2)
        self.assertEqual(r["discovery"]["genreDocumented"],1)
        self.assertEqual(r["priorityLeads"][0]["name"],"Loud Act")
        self.assertTrue(all(x["reviewRequired"] and not x["publicationAllowed"]
                            for x in r["priorityLeads"]))
        self.assertEqual(r["venuesOutsideSourceRotation"][0]["name"],"Nouveau Club")
        self.assertIn("aucune publication",report_md(r).lower())

    def test_least_covered_region_precedes_well_populated_city(self):
        paris = {"id":"paris","name":"Paris club","city":"Paris",
                 "region":"Île-de-France"}
        catalogue = {"venues":[CAT["venues"][0],paris],
                     "artists":CAT["artists"],"events":CAT["events"] + [
                         {"id":"paris-"+str(i),"date":"2026-11-26",
                          "venueId":"paris","artistIds":["x"]}
                         for i in range(20)]}
        items = [item("Tours Act",genre=["Punk"],city="Tours",
                      venue="Le Bateau Ivre",department="37"),
                 item("Paris Act",genre=["Punk"],city="Paris",
                      venue="Paris Club",department="75")]
        result = evaluate(catalogue,{"schema":"grossesondes.concert.intake.v1",
                                  "items":{str(i):r for i,r in enumerate(items)}},
                          SRC,NAT,TODAY)
        self.assertEqual(result["priorityLeads"][0]["region"],"Centre-Val de Loire")
        self.assertEqual(result["priorityLeads"][0]["name"],"Tours Act")
        self.assertTrue(all(not x["publicationAllowed"]
                            for x in result["priorityLeads"]))

    def test_existing_and_uncertain_not_counted_as_new(self):
        existing=item("Already",date="2026-11-20",venue="Salle",city="Nantes")
        rows=[existing,item("Old",date="2026-11-01",genre=["Metal"]),
              item("Cancelled",genre=["Metal"],cancellationNotice=True),
              item("Death Festival",genre=["Metal"]),
              item("New",genre=["Punk"]),item("New",genre=["Punk"]),
              item("Rejected",genre=["Metal"])]
        rows[-1]["status"]="rejected"
        result=audit(rows)
        self.assertEqual([x["name"] for x in result["priorityLeads"]],["New"])
        self.assertEqual(result["discovery"]["excluded"]["duplicate_lead"],1)
        self.assertGreater(result["discovery"]["excluded"]["possible_duplicate"],0)

    def test_security_requires_known_schema_and_hides_credentials(self):
        self.assertIsNone(public_url("https://user:secret@ticket.com/event?apikey=secret"))
        self.assertEqual(public_url("https://ticket.com/event?apikey=secret"),"https://ticket.com/event")
        with self.assertRaises(ValueError):
            evaluate(CAT,{"items":{}},SRC,NAT,TODAY)
        result=audit([item("Lead",source="ticketmaster_discovery",
                           sourceUrl="https://user:secret@ticket.com/evt?apikey=secret")])
        self.assertNotIn("secret",report_md(result))
        self.assertFalse(result["priorityLeads"][0]["individualOfficialLead"])

if __name__=="__main__":
    unittest.main()
