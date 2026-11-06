import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from ticket_candidates import ticket_proposal, merge_ticket_proposals, PROOF_MODE

ORIG={"slug":"metal-fest-2027","name":"Metal Fest 2027",
      "startDate":"2027-08-12","endDate":"2027-08-13",
      "officialSite":"https://festival.example.org/","status":"Annoncé"}
DAY="2026-11-05"
OBS={"slug":ORIG["slug"],"source":ORIG["officialSite"],
     "startDate":ORIG["startDate"],"endDate":ORIG["endDate"],
     "publication_authorized":False,"sensitive_event_status":None,
     "ticket_categories":[{"category":"Pass samedi","availability":"sold_out"},
                          {"category":"Pass dimanche","availability":"in_stock"}]}

def patch():
    return {"schema":"grossesondes.patch.v1","safe_to_publish":False,
            "source":{"festivals":{"url":"https://grosses-ondes.fr/data/festivals.json",
                                  "generatedAt":"2026-11-03","count":1}},
            "updates":[],"deferred":[{"slug":"preserve","evidence_kind":"legacy"}],
            "additions":[{"slug":"unknown","status":"Dates à venir"}],
            "history_additions":[],"history_updates":[]}


class TicketProposalTests(unittest.TestCase):
    def test_typed_proposal_only_per_category(self):
        result=ticket_proposal(ORIG,ORIG,OBS,DAY)
        self.assertEqual(result["proofMode"],PROOF_MODE)
        self.assertEqual([c["field"] for c in result["changes"]],["ticketAvailability"])
        self.assertEqual(result["changes"][0]["after"]["scope"],"per_category_only")
        self.assertEqual(result["changes"][0]["after"]["categories"][0]["status"],
                         "in_stock")
        self.assertEqual(result["evidence"],[ORIG["officialSite"]])

    def test_sensitive_or_conflicting_information_never_proposed(self):
        for value in ["cancelled","postponed","rescheduled"]:
            row=dict(OBS,sensitive_event_status=value)
            self.assertIsNone(ticket_proposal(ORIG,ORIG,row,DAY))
        for row in [
            dict(OBS,startDate="2027-08-14"),
            dict(OBS,source="https://attacker.example.org"),
            dict(OBS,publication_authorized=True),
            dict(OBS,ticket_categories=[]),
            dict(OBS,ticket_categories=[
                {"category":"Pass samedi","availability":"sold_out"},
                {"category":"Pass samedi","availability":"in_stock"}]),
        ]:
            self.assertIsNone(ticket_proposal(ORIG,ORIG,row,DAY))
        self.assertIsNone(ticket_proposal(
            ORIG,dict(ORIG,startDate="2027-08-14"),OBS,DAY))

    def test_replaces_only_older_typed_proposal(self):
        doc={"generatedAt":"2026-11-03","festivals":[ORIG]}
        p=patch()
        first=ticket_proposal(ORIG,ORIG,OBS,DAY)
        self.assertEqual(merge_ticket_proposals(p,[first],doc,DAY),1)
        old=copy.deepcopy(p["updates"])
        self.assertEqual(merge_ticket_proposals(p,[first],doc,DAY),0)
        self.assertEqual(p["updates"],old)
        newer=ticket_proposal(ORIG,ORIG,OBS,"2026-11-06")
        self.assertEqual(merge_ticket_proposals(p,[newer],doc,"2026-11-06"),1)
        self.assertEqual(p["updates"][0]["verified_at"],"2026-11-06")
        self.assertEqual(len(p["deferred"]),1)
        self.assertEqual(len(p["additions"]),1)

    def test_no_overwrite_of_manual_or_other_proof(self):
        doc={"generatedAt":"2026-11-03","festivals":[ORIG]}
        p=patch()
        existing={"slug":ORIG["slug"],"proofMode":"structured-roster.v1",
                  "changes":[]}
        p["updates"]=[existing]
        candidate=ticket_proposal(ORIG,ORIG,OBS,DAY)
        self.assertEqual(merge_ticket_proposals(p,[candidate],doc,DAY),0)
        self.assertEqual(p["updates"],[existing])
        p["safe_to_publish"]=True
        with self.assertRaises(ValueError):
            merge_ticket_proposals(p,[candidate],doc,DAY)

if __name__=="__main__":
    unittest.main()
