"""Antipode Rennes is discoverable, but cannot publish concerts automatically."""
import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit
import discover

ROOT=Path(__file__).resolve().parent
DATA=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
SOURCE_ID="official-gap-20261103-antipode-rennes"

class AntipodeSourceSafety(unittest.TestCase):
    def test_first_party_source_and_brittany_priority(self):
        matches=[s for s in DATA["venues"] if s["id"]==SOURCE_ID]
        self.assertEqual(len(matches),1)
        s=matches[0]
        self.assertEqual((s["name"],s["city"],s["department"]),
                         ("Antipode","Rennes","35"))
        self.assertEqual(s["priority"],"P1")
        self.assertEqual(s["url"],"https://antipode-rennes.fr/agenda")
        self.assertEqual(s["officialAgendaUrl"],s["url"])
        self.assertEqual(urlsplit(s["url"]).hostname,"antipode-rennes.fr")
        self.assertFalse(s["publish_automatically"])
        self.assertEqual(s["status"],"official_detail_adapter_read_only")
        self.assertEqual(s["adapter"],"antipode_official_detail_review")
        self.assertFalse(s["publicationAllowed"])
        self.assertEqual(s["maxAgendaPagesPerRun"],1)
        self.assertLessEqual(s["maxDetailPagesPerRun"],10)

    def test_review_marker_keeps_proposal_unpublished(self):
        lead={"candidateId":"private:antipode:test","date":"2027-03-09",
              "leadArtist":"The Pineapple Thief","sourceUrl":
              "https://antipode-rennes.fr/agenda/pineapple-thief-2027",
              "city":"Rennes","publicationAllowed":True}
        marked=discover.mark_match(lead,set())
        self.assertFalse(marked["publicationAllowed"])
        self.assertTrue(marked["reviewRequired"])

    def test_no_source_duplicates(self):
        ids=[s["id"] for s in DATA["venues"]]
        self.assertEqual(len(ids),len(set(ids)))

if __name__=="__main__":
    unittest.main()
