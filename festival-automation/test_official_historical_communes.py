import csv
from datetime import date
import io
import unittest
from official_historical_communes import HEADER, historical_parent

DAY = date(2026, 11, 25)

def row(mod, day, old, new):
    return [mod, day, old[0], old[1], "0", old[2], old[2], old[2],
            new[0], new[1], "0", new[2], new[2], new[2]]

def fixture(*rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADER)
    writer.writerows(rows)
    return out.getvalue()

OLD = ("COM", "39161", "Village Ancien")
PARENT = ("COM", "39162", "Commune Nouvelle")
FINAL = ("COM", "39162", "Commune Actuelle")

class HistoricalCommuneTests(unittest.TestCase):
    def test_unique_merger_and_rename(self):
        data = fixture(row("10", "2020-01-01", PARENT, FINAL),
                       row("32", "2017-01-01", OLD, PARENT))
        self.assertEqual(historical_parent("Village Ancien", "39", data, DAY),
                         ("39161", "Commune Actuelle", "39162"))
        self.assertIsNone(historical_parent("Village Ancien", "75", data, DAY))
        self.assertIsNone(historical_parent("Village", "39", data, DAY))

    def test_reused_code_different_names(self):
        data = fixture(row("32", "2017-01-01",
                           ("COM", "39162", "Ancien Nom"), PARENT))
        self.assertEqual(historical_parent("Ancien Nom", None, data, DAY),
                         ("39162", "Commune Nouvelle", "39162"))

    def test_ambiguity_and_split(self):
        first = row("32", "2017-01-01", OLD, PARENT)
        second = row("32", "2017-01-01", OLD, FINAL)
        self.assertIsNone(historical_parent("Village Ancien", "39",
                                           fixture(first, second), DAY))
        other = row("32", "2018-01-01", ("COM", "75161", OLD[2]),
                    ("COM", "75162", "Autre Commune"))
        self.assertIsNone(historical_parent("Village Ancien", None,
                                           fixture(first, other), DAY))
        self.assertIsNone(historical_parent("Village Ancien", "39",
                                           fixture(row("21", "2017-01-01", OLD, PARENT)), DAY))
        self.assertIsNone(historical_parent("Village Ancien", "39",
                                           fixture(first).rstrip(), DAY))

    def test_future_movements_are_not_used(self):
        data = fixture(row("32", "2027-01-01", OLD, PARENT))
        self.assertIsNone(historical_parent("Village Ancien", "39", data, DAY))

if __name__ == "__main__":
    unittest.main()
