"""Offline tests of bounded venue probes: never trust a ticket alone."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ticketmaster_venue_probes as p
import discover as d

TODAY=dt.date(2026,11,2)
CONFIG={"schema":p.SCHEMA,"maxVenuesPerRun":2,"venues":[
    {"id":"secret-place-saint-jean-de-vedas","name":"Secret Place",
     "aliases":["Secret Place","La Secret Place"],
     "city":"Saint-Jean-de-Védas","postalCode":"34430"},
    {"id":"le-ferrailleur-nantes","name":"Le Ferrailleur",
     "aliases":["Le Ferrailleur"],"city":"Nantes","postalCode":"44200"}]}
CAT={"venues":[{"id":x["id"],"name":x["name"],"city":x["city"]}
               for x in CONFIG["venues"]]}

def venue(id,name,city,postcode):
    return {"id":id,"name":name,"city":{"name":city},
            "country":{"countryCode":"FR"},"postalCode":postcode}

SECRET=venue("platform-secret-id","La Secret Place","Saint-Jean-de-Védas","34430")
FERR=venue("platform-ferrailleur-id","Le Ferrailleur","Nantes","44200")

def event(v=SECRET,*,name="Secret Metal Night",status="onsale"):
    return {"id":"evt-004","name":name,
            "url":"https://www.ticketmaster.fr/event/evt-004",
            "dates":{"start":{"localDate":"2027-02-04","localTime":"20:00"},
                     "status":{"code":status}},
            "_embedded":{"venues":[v],
                         "attractions":[{"name":"Secret Metal Night"}]},
            "classifications":[{"genre":{"name":"Metal"}}]}

def api(url):
    from urllib.parse import urlsplit,parse_qs
    parsed=urlsplit(url)
    args=parse_qs(parsed.query)
    assert args.get("apikey")==["NOT_A_REAL_SECRET"]
    if parsed.path.endswith("venues.json"):
        if args["keyword"][0]=="Secret Place":
            return {"_embedded":{"venues":[SECRET]}}
        return {"_embedded":{"venues":[FERR]}}
    if parsed.path.endswith("events.json"):
        chosen=args["venueId"][0]
        return {"_embedded":{"events":[event(SECRET if chosen==SECRET["id"] else FERR)]}}
    raise AssertionError("Unexpected request")

class ProbeTests(unittest.TestCase):
    def test_exact_venue_search_only_and_no_auto_publication(self):
        leads,diag=p.probe(CONFIG,CAT,"NOT_A_REAL_SECRET",TODAY,api,
                           d.ticketmaster_candidate,set())
        self.assertEqual(len(diag),2)
        self.assertEqual(len(leads),2)
        self.assertTrue(all(r["reviewRequired"] for r in leads))
        self.assertTrue(all(r["publicationAllowed"] is False for r in leads))
        self.assertEqual({r["venueCatalogueId"] for r in leads},
                         {x["id"] for x in CONFIG["venues"]})
        self.assertEqual(diag[0]["status"],"venue_indexed")
        self.assertNotIn("NOT_A_REAL_SECRET",json.dumps(diag))

    def test_wrong_city_wrong_postcode_foreign_and_ambiguous_names_refused(self):
        for bad in (
            venue("q","La Secret Place","Paris","75001"),
            venue("q","La Secret Place","Saint-Jean-de-Védas","44000"),
            venue("q","La Secret Place","Saint-Jean-de-Védas","34430"),
        ):
            if bad["id"]=="q" and bad["postalCode"]=="34430":
                bad["country"]["countryCode"]="BE"
            with self.subTest(bad=bad):
                self.assertFalse(p.venue_matches(bad,CONFIG["venues"][0]))
        self.assertFalse(p.venue_matches(venue("q","Secret Place 2","Saint-Jean-de-Védas","34430"),CONFIG["venues"][0]))

    def test_same_name_different_city_not_queried_for_events(self):
        calls=[]
        def request(url):
            calls.append(url.split("?")[0])
            return {"_embedded":{"venues":[venue("wrong","Secret Place","Paris","75001")]}}
        leads,report=p.probe(CONFIG,CAT,"NOT_A_REAL_SECRET",TODAY,request,
                             d.ticketmaster_candidate,set())
        self.assertEqual(leads,[])
        self.assertTrue(all(r["status"]=="not_indexed_or_ambiguous" for r in report))
        self.assertTrue(all(x.endswith("venues.json") for x in calls))

    def test_event_embedded_venue_must_match_platform_id_and_city(self):
        def request(url):
            if "venues.json" in url:
                return {"_embedded":{"venues":[SECRET]}}
            return {"_embedded":{"events":[event(venue("fake","Secret Place","Saint-Jean-de-Védas","34430"))]}}
        config=dict(CONFIG,venues=[CONFIG["venues"][0]])
        cat={"venues":[CAT["venues"][0]]}
        leads,diag=p.probe(config,cat,"NOT_A_REAL_SECRET",TODAY,request,d.ticketmaster_candidate,set())
        self.assertEqual(leads,[])
        self.assertEqual(diag[0]["eventsReturned"],1)

    def test_cancelled_and_non_french_event_held(self):
        def request(url):
            if "venues.json" in url:
                return {"_embedded":{"venues":[SECRET]}}
            from copy import deepcopy
            foreign=event(deepcopy(SECRET))
            foreign["_embedded"]["venues"][0]["country"]["countryCode"]="BE"
            return {"_embedded":{"events":[event(SECRET,status="cancelled"),foreign]}}
        config=dict(CONFIG,venues=[CONFIG["venues"][0]])
        cat={"venues":[CAT["venues"][0]]}
        leads,_=p.probe(config,cat,"NOT_A_REAL_SECRET",TODAY,request,
                         d.ticketmaster_candidate,set())
        self.assertEqual(leads,[])

    def test_api_errors_held_without_leaking_key(self):
        from urllib.error import HTTPError
        def fail(url):
            raise HTTPError(url,429,"rate limited",{},None)
        leads,report=p.probe(CONFIG,CAT,"NOT_A_REAL_SECRET",TODAY,fail,
                             d.ticketmaster_candidate,set())
        self.assertEqual(leads,[])
        self.assertEqual([r["httpStatus"] for r in report],[429,429])
        self.assertNotIn("NOT_A_REAL_SECRET",json.dumps(report))

    def test_only_named_existing_catalogue_venues(self):
        bad=dict(CONFIG,venues=[{**CONFIG["venues"][0],"city":"Paris"}])
        with self.assertRaises(ValueError):
            p.selected_venues(bad,CAT,TODAY)

    def test_unconfigured_api_keeps_existing_discovery_safe(self):
        leads,report=p.probe(CONFIG,CAT,"",TODAY,api,d.ticketmaster_candidate,set())
        self.assertEqual(leads,[])
        self.assertEqual(report[0]["status"],"not_configured")

    def test_bounded_two_venue_probes_even_with_twelve_configured(self):
        cfg=dict(CONFIG,venues=[
            {"id":f"v{i}","name":f"Concert Hall {i}",
             "aliases":[f"Concert Hall {i}"],"city":f"City {i}"}
            for i in range(12)])
        cat={"venues":[{"id":x["id"],"name":x["name"],"city":x["city"]}
                       for x in cfg["venues"]]}
        self.assertEqual(len(p.selected_venues(cfg,cat,TODAY)),2)


if __name__=="__main__":
    unittest.main()
