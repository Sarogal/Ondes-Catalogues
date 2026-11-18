"""Regression: source-wide, read-only watch of future BBC / Cave concerts."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import published_watch as watch
import test_bbc_official_recheck as bbc
import test_cave_poetes_official_recheck as cave

def bbc_event(names):
    return {
        "id": "go-c-20270312-herouville-" + names[0].lower().replace(" ", "-"),
        "date": "2027-03-12", "officialUrl": bbc.URL,
        "title": " + ".join(names),
        "artistIds": [name.lower().replace(" ", "-") for name in names],
        "venueId": "big-band-cafe-herouville",
        "genres": ["Metal"], "time": None
    }

def cave_event(names):
    return {
        "id": "go-c-20270212-roubaix-" +
              cave.source.norm(names[0]).replace(" ", "-"),
        "date": "2027-02-12", "officialUrl": cave.URL,
        "title": " + ".join(names),
        "artistIds": [
            cave.source.norm(name).replace(" ", "-") for name in names],
        "venueId": "la-cave-aux-poetes-roubaix",
        "genres": ["Punk"], "time": "20:00"
    }

class WatchContractTests(unittest.TestCase):
    def test_bbc_independent_of_artist_count_or_new_id(self):
        for count in (2, 24):
            names = ["ACT %02d" % i for i in range(count)]
            ev = bbc_event(names)
            artists = dict(zip(ev["artistIds"], names))
            page = bbc.html_bill(names)
            with self.subTest(count=count):
                self.assertEqual(watch.source_kind(ev), "bbc")
                self.assertEqual(watch.inspect(ev, page, artists)["status"], "matched")
                delayed = page.replace("12 mars 2027", "13 mars 2027")
                self.assertEqual(watch.inspect(
                    ev, delayed, artists)["status"], "date_review")
                extra = bbc.html_bill(names + ["NEW SUPPORT ACT"])
                self.assertEqual(watch.inspect(
                    ev, extra, artists)["status"], "lineup_review")
        self.assertIsNone(watch.source_kind(
            dict(bbc_event(["ACT ONE"]), id="unrelated-event")))

    def test_cave_independent_of_artist_count_or_new_id(self):
        for count in (2, 24):
            names = tuple("CAVE ACT %02d" % i for i in range(count))
            ev = cave_event(names)
            artists = dict(zip(ev["artistIds"], names))
            page = cave.html(names)
            with self.subTest(count=count):
                self.assertEqual(watch.source_kind(ev), "cave")
                self.assertEqual(watch.inspect(ev, page, artists)["status"], "matched")
                delayed = page.replace("12 février 2027", "13 février 2027")
                self.assertEqual(watch.inspect(
                    ev, delayed, artists)["status"], "date_review")
                extra = cave.html(names + ("NEW SUPPORT ACT",))
                self.assertEqual(watch.inspect(
                    ev, extra, artists)["status"], "lineup_review")
                self.assertEqual(watch.inspect(
                    dict(ev, time="19:30"), page, artists)["status"],
                    "content_review")
        self.assertIsNone(watch.source_kind(
            dict(cave_event(("CAVE ONE",)), officialUrl="https://evil.example/")))

if __name__ == "__main__":
    unittest.main()
