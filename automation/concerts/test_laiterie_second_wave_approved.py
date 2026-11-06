"""Quatre affiches Artefact officiellement recoupees, heures non inferees."""
import json
import unittest
from pathlib import Path

CASES={
 "go-c-20270226-strasbourg-dynamite-shakers":("2027-02-26",["dynamite-shakers","johnny-mafia"],"dynamite-shakers-johnny-mafia/",3),
 "go-c-20270428-strasbourg-howlin-jaws":("2027-04-28",["howlin-jaws","komodor"],"howlin-jaws-komodor/",4),
 "go-c-20270514-strasbourg-didier-super-metal":("2027-05-14",["didier-super-metal"],"didier-super-metal/",4),
 "go-c-20271010-strasbourg-europe":("2027-10-10",["europe"],"europe-2027/",5)
}

class SecondWaveLaiterieTests(unittest.TestCase):
 def test_four_individually_verified_official_bills(self):
  data=json.loads(Path(__file__).with_name("approved.json").read_text(encoding="utf-8"))
  self.assertLessEqual(len(data["approvals"]),400)
  rows={a["event"]["id"]:a for a in data["approvals"]}
  for key,(date,artists,slug,page) in CASES.items():
   with self.subTest(key=key):
    row=rows[key];e=row["event"]
    self.assertEqual(e["date"],date)
    self.assertEqual(e["artistIds"],artists)
    self.assertEqual(e["venueId"],"la-laiterie-strasbourg")
    self.assertTrue(e["genres"])
    self.assertEqual(e["status"],"confirmed")
    self.assertEqual(row["reviewedBy"],"independent-official-verifier")
    self.assertEqual(row["reviewedAt"],"2026-11-03")
    self.assertIsNone(e["time"])
    self.assertEqual(e["officialUrl"],"https://www.artefact.org/la-laiterie/evenements/"+slug)
    evidence=row["officialEvidence"]
    self.assertEqual(len(evidence),2)
    self.assertEqual(evidence[0]["url"],e["officialUrl"])
    self.assertEqual(evidence[1]["url"],"https://www.artefact.org/la-laiterie/programmation/page/"+str(page)+"/")
    self.assertEqual({x["proofType"] for x in evidence},{"official-organizer-or-venue","first-party-venue-calendar"})
    self.assertTrue(all(x["checkedAt"]=="2026-11-03" for x in evidence))
    self.assertTrue(all({"artists","date","venue","genre"}.issubset(set(x["checkedFields"])) for x in evidence))
    self.assertTrue(all("startTime" not in x["checkedFields"] for x in evidence))
  self.assertEqual(sum(len(rows[k]["newArtists"]) for k in CASES),4)

if __name__=="__main__":
 unittest.main()
