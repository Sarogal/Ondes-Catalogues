"""One precise, officially re-reviewed correction of an existing public bill."""
import json
import unittest
from pathlib import Path

from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/"docs/grossesondes/concerts.json"
REFERENCE=ROOT/"docs/grossesondes/concerts-reference.json"
IDENT="go-c-20261107-cenon-gwendoline"


class GwendolinePublishedCorrectionTests(unittest.TestCase):
    def test_precise_first_party_lineup_update_preserves_event_identity(self):
        current=json.loads(PUBLIC.read_text(encoding="utf-8"))
        reference=json.loads(REFERENCE.read_text(encoding="utf-8"))
        sync.protect_reference(reference,current)
        sync.validate_catalogue(current)
        self.assertNotIn(IDENT,{e["id"] for e in reference["events"]})
        events=[e for e in current["events"] if e["id"]==IDENT]
        self.assertEqual(len(events),1)
        e=events[0]
        self.assertEqual(
            (e["title"],e["date"],e["time"],e["timeMeaning"]),
            ("Gwendoline + Bleu Panique","2026-11-07","20:30",
             "début du concert"))
        self.assertEqual(e["artistIds"],["gwendoline","bleu-panique"])
        self.assertEqual(e["genres"],["Post Punk"])
        self.assertEqual(e["venueId"],"le-rocher-de-palmer-cenon")
        self.assertEqual(e["officialUrl"],
                         "https://lerocherdepalmer.fr/agenda/gwendoline")
        self.assertEqual(e["lastVerified"],"2026-11-06")
        self.assertEqual(e["history"][0]["date"],"2026-11-02")
        self.assertEqual(e["history"][-1]["date"],"2026-11-06")
        self.assertIn("Bleu Panique",e["history"][-1]["change"])
        ids={x["id"]:x for x in current["artists"]}
        self.assertEqual(ids["gwendoline"]["name"],"Gwendoline")
        self.assertEqual(ids["bleu-panique"],
                         {"id":"bleu-panique","name":"Bleu Panique","aliases":[]})
        self.assertEqual(sum(a["id"]=="bleu-panique"
                             for a in current["artists"]),1)
        spec=sync.ROCHER_PALMER_VERIFIED[IDENT]
        for key in ("title","date","time","artistIds","genres","officialUrl"):
            self.assertEqual(e[key],spec[key])


if __name__=="__main__":
    unittest.main()
