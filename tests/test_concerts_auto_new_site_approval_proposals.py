"""No-publication-by-discovery tests for independently verified new-site pairs."""
import copy
import datetime as dt
import json
import unittest

from automation.concerts import dynamic_new_site_approval_proposals as producer
import test_concerts_dynamic_new_site_source as fixture

TODAY = dt.date(2026,11,21)

def evidence(bad_witness=False):
    review, site, origin_venue, raw, witness, geo, osm = fixture.fixture()
    if bad_witness:
        witness["startDate"] = "2030-02-02T20:00:00+02:00"
    pages = {
        fixture.ORIGIN_API: osm,
        fixture.EVENT_URL: '<html><script type="application/ld+json">' +
                           json.dumps(raw) + '</script></html>',
        fixture.SITE_API: json.dumps(geo),
        fixture.WITNESS_URL: '<html><script type="application/ld+json">' +
                             json.dumps(witness) + '</script></html>',
    }
    calls = []
    def fetch(url, cache):
        calls.append(url)
        return pages[url]
    row = {
        "date": fixture.DAY, "leadArtist": fixture.BANDS[0],
        "venue": site["venue"]["name"], "city":site["venue"]["city"],
        "crossDomainEventVerified":True,
        "publishedAlreadyKnown":False,"markedPossibleDuplicate":False,
        "sourceOwnershipVerified":False,
        "publisherAuthorityGranted":False,
        "publicationAllowed":False,
        "verifiedWitnesses":[
            {"url":fixture.EVENT_URL,
             "host":"scene-officielle-inconnue.fr"},
            {"url":fixture.WITNESS_URL,
             "host":"agenda-independant.fr"},
        ],
    }
    catalogue = {"schemaVersion":1,
                 "mode":"preview-public-unlisted",
                 "venues":[origin_venue],"artists":[],"events":[]}
    before = {"schema":"grossesondes.concert.approvals.v1",
              "approvals":[],"venueApprovals":[]}
    report = {"schema":producer.witnesses.SCHEMA,
              "sourceOwnershipVerified":False,
              "publicationAllowed":False,"checks":[row]}
    return report,catalogue,before,fetch,calls

class PairedProposalTests(unittest.TestCase):
    def test_eight_entirely_new_bands_and_new_physical_site_are_jointly_proposed(self):
        report,catalogue,before,fetch,calls=evidence()
        original=copy.deepcopy(before)
        output,metrics=producer.build(report,catalogue,before,TODAY,fetch=fetch)
        self.assertEqual(len(output["approvals"]),1)
        self.assertEqual(len(output["venueApprovals"]),1)
        event,site=output["approvals"][0],output["venueApprovals"][0]
        self.assertEqual(len(event["newArtists"]),8)
        self.assertEqual(event["event"]["venueId"],site["venue"]["id"])
        self.assertEqual(site["eventBinding"]["eventId"],event["event"]["id"])
        self.assertEqual(event["officialEvidence"][1]["corroboratingEventUrl"],
                         fixture.WITNESS_URL)
        self.assertEqual(metrics["stateCounts"]["publisher_bound_pairs_proposed"],1)
        self.assertFalse(metrics["privateApprovalApplied"])
        self.assertFalse(metrics["publicationAllowed"])
        self.assertEqual(before,original)
        self.assertIn(fixture.ORIGIN_API,calls)
        self.assertIn(fixture.EVENT_URL,calls)
        self.assertIn(fixture.SITE_API,calls)
        self.assertIn(fixture.WITNESS_URL,calls)

    def test_rejected_second_source_never_creates_orphan_site(self):
        report,catalogue,before,fetch,calls=evidence(bad_witness=True)
        output,metrics=producer.build(report,catalogue,before,TODAY,fetch=fetch)
        self.assertEqual(output,before)
        self.assertEqual(metrics["stateCounts"]["held_missing_independent_evidence"],1)

    def test_discovery_or_single_source_is_not_an_approval(self):
        report,catalogue,before,fetch,calls=evidence()
        report["checks"][0]["crossDomainEventVerified"]=False
        result,metrics=producer.build(report,catalogue,before,TODAY,fetch=fetch)
        self.assertEqual(result,before)
        self.assertEqual(metrics["examined"],0)
        self.assertEqual(calls,[])
        report["checks"][0]["crossDomainEventVerified"]=True
        report["checks"][0]["verifiedWitnesses"].pop()
        result,metrics=producer.build(report,catalogue,before,TODAY,fetch=fetch)
        self.assertEqual(result,before)
        self.assertEqual(metrics["stateCounts"]["held_missing_independent_evidence"],1)

    def test_fake_prior_publication_or_unsafe_claim_can_never_sign(self):
        report,catalogue,before,fetch,calls=evidence()
        for field in ("publishedAlreadyKnown","markedPossibleDuplicate",
                      "sourceOwnershipVerified","publisherAuthorityGranted",
                      "publicationAllowed"):
            altered=copy.deepcopy(report)
            altered["checks"][0][field]=True
            result,metrics=producer.build(altered,catalogue,before,TODAY,fetch=fetch)
            self.assertEqual(result,before,(field,metrics))

    def test_future_date_or_limit_and_slot_not_trusted_from_report(self):
        report,catalogue,before,fetch,calls=evidence()
        for limit in (0,-1,9,True):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                producer.build(report,catalogue,before,TODAY,limit=limit,fetch=fetch)
        for slot in (-1,3,True):
            with self.subTest(slot=slot),self.assertRaises(ValueError):
                producer.build(report,catalogue,before,TODAY,slot=slot,fetch=fetch)
        report["checks"][0]["date"]="2020-01-01"
        result,metrics=producer.build(report,catalogue,before,TODAY,fetch=fetch)
        self.assertEqual(result,before)
        self.assertEqual(metrics["stateCounts"]["held_missing_independent_evidence"],1)

if __name__=="__main__":
    unittest.main()
