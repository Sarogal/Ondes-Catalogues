"""Tests ensuring signed publication rechecks an old cumulative patch."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from grossesondes_preview import load_patch,FOLDER


class PatchFreshnessPolicyTests(unittest.TestCase):
    def test_old_patch_still_rejected_by_default(self):
        with patch("grossesondes_preview.fetch_json") as fetch:
            fetch.return_value=[{"name":"patch-2026-10-01.json","type":"file",
                                 "path":FOLDER+"/patch-2026-10-01.json"}]
            with self.assertRaisesRegex(ValueError,"plus de 7 jours"):
                load_patch("token",date(2026,11,4))

    def test_explicit_stale_read_permitted_but_not_a_proof(self):
        import base64,json
        payload={"schema":"grossesondes.patch.v1","generated_at":"2026-10-01",
                 "safe_to_publish":False}
        listing=[{"name":"patch-2026-10-01.json","type":"file",
                  "path":FOLDER+"/patch-2026-10-01.json"}]
        response={"encoding":"base64",
                  "content":base64.b64encode(json.dumps(payload).encode()).decode()}
        with patch("grossesondes_preview.fetch_json",side_effect=[listing,response]):
            result,path=load_patch("token",date(2026,11,4),
                                   allow_stale_for_reproof=True)
        self.assertEqual(result,payload)
        self.assertTrue(path.endswith("2026-10-01.json"))

    def test_future_patch_rejected_even_when_stale_allowed(self):
        with patch("grossesondes_preview.fetch_json") as fetch:
            fetch.return_value=[{"name":"patch-2027-01-01.json","type":"file",
                                 "path":FOLDER+"/patch-2027-01-01.json"}]
            with self.assertRaisesRegex(ValueError,"aucun patch quotidien"):
                load_patch("token",date(2026,11,4),allow_stale_for_reproof=True)


if __name__=="__main__":
    unittest.main()
