import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from grossesondes_bootstrap import check, SOURCES
def make(name):
    rule=SOURCES[name]
    return {"schema":rule["schema"],rule["date_field"]:rule["reference_date"],
            rule["array"]:[{"slug":f"edition-{i}","startDate":"2027-05-01",
                            "endDate":"2027-05-02"} for i in range(rule["expected_count"])]}
class TestGrossesBaseline(unittest.TestCase):
    def test_calendar(self):
        self.assertEqual(check("festivals.json",make("festivals.json")),123)
    def test_history(self):
        self.assertEqual(check("festival-history.json",make("festival-history.json")),170)
    def test_wrong_size_rejected(self):
        doc=make("festivals.json");doc["festivals"].pop()
        with self.assertRaises(ValueError):check("festivals.json",doc)
    def test_wrong_schema_rejected(self):
        doc=make("festivals.json");doc["schema"]=2
        with self.assertRaises(ValueError):check("festivals.json",doc)
    def test_wrong_version_rejected(self):
        doc=make("festival-history.json");doc["updatedAt"]="2026-10-29"
        with self.assertRaises(ValueError):check("festival-history.json",doc)
    def test_missing_slug_rejected(self):
        doc=make("festivals.json");doc["festivals"][0].pop("slug")
        with self.assertRaises(ValueError):check("festivals.json",doc)
    def test_duplicate_rejected(self):
        doc=make("festival-history.json")
        doc["knownFestivals"][0]["slug"]=doc["knownFestivals"][1]["slug"]
        with self.assertRaises(ValueError):check("festival-history.json",doc)
    def test_inverted_date_rejected(self):
        doc=make("festivals.json")
        doc["festivals"][0]["endDate"]="2027-01-01"
        with self.assertRaises(ValueError):check("festivals.json",doc)
if __name__=="__main__":
    unittest.main()
