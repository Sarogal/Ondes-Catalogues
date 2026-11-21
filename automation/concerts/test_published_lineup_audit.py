"""Official published concert pages with missing opening acts: read-only audit."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import published_lineup_audit as audit

TODAY = dt.date(2026, 11, 21)
VENUE = {"id": "le-bikini-toulouse", "name": "Le Bikini",
         "city": "Ramonville-Saint-Agne", "department": "31"}
ARTISTS = [{"id": "marillion", "name": "Marillion", "aliases": []},
           {"id": "the-stranglers", "name": "The Stranglers", "aliases": []},
           {"id": "lazuli", "name": "Lazuli", "aliases": []},
           {"id": "brother-junior", "name": "Brother Junior", "aliases": []}]


def event(title, artist, date, url):
    return {"id": "go-c-" + date.replace("-", "") + "-toulouse-" + artist,
            "title": title, "date": date, "status": "confirmed",
            "officialUrl": url, "artistIds": [artist],
            "venueId": VENUE["id"], "genres": ["Rock"]}


MARILLION = event(
    "Marillion", "marillion", "2026-11-25",
    "https://lebikini.com/2026/11/25/marillion")
STRANGLERS = event(
    "The Stranglers", "the-stranglers", "2026-11-26",
    "https://lebikini.com/2026/11/26/the-stranglers")


def data(events):
    return {"schemaVersion": 1, "venues": [copy.deepcopy(VENUE)],
            "artists": copy.deepcopy(ARTISTS), "events": copy.deepcopy(events)}


def page(date, title, *, venue="Le Bikini", marker=None, extra=None):
    label = ("Mercredi 25 novembre 2026 à 19h15"
             if date == "2026-11-25"
             else "Jeudi 26 novembre 2026 à 19h30"
             if date == "2026-11-26"
             else date)
    return ("""<html><head><title>Faux autre concert</title></head>
        <body><nav><h1>Concert d'un groupe différent</h1></nav>
        <main><section><p>""" + label + "</p><p>" + venue
        + "</p><h1>" + title + "</h1></section>"
        + ("<div>1ère partie</div><div>" + extra + "</div>"
           if marker and extra else "")
        + "<article>" + "Biographie longue et recommandations sans concert." * 8
        + """</article></main><footer><h1>FAUX GROUPE</h1>
        <p>27 novembre 2026</p></footer></body></html>""")


class PublishedLineupAuditTests(unittest.TestCase):
    def test_real_bikini_marillion_lazuli_missing(self):
        d = data([MARILLION])
        original = copy.deepcopy(d)
        report = audit.build(d, TODAY, slot=2, fetch=lambda u, c:
                             page("2026-11-25", "MARILLION + LAZULI"))
        self.assertEqual(report["examinedConcerts"], 1)
        self.assertEqual(report["stateCounts"], {"published_lineup_incomplete": 1})
        self.assertEqual(report["checks"][0]["missingNamedArtists"], ["LAZULI"])
        self.assertTrue(report["checks"][0]["officialBillRechecked"])
        self.assertFalse(report["checks"][0]["correctionAuthorized"])
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(d, original)

    def test_real_bikini_stranglers_brother_junior_missing(self):
        result = audit.build(data([STRANGLERS]), TODAY, slot=2,
                             fetch=lambda u, c: page(
                                 "2026-11-26", "THE STRANGLERS + BROTHER JUNIOR"))
        self.assertEqual(result["stateCounts"], {"published_lineup_incomplete": 1})
        self.assertEqual(result["checks"][0]["missingNamedArtists"], ["BROTHER JUNIOR"])

    def test_support_below_headline_is_also_detected(self):
        r = audit.bill_from_page(
            page("2026-11-25", "MARILLION", marker=True, extra="LAZULI"),
            MARILLION, VENUE, {a["id"]: a for a in ARTISTS})
        self.assertEqual(r["missingNamedArtists"], ["LAZULI"])

    def test_complete_lineup_does_not_need_a_patch(self):
        full = copy.deepcopy(MARILLION)
        full["title"] = "Marillion + Lazuli"
        full["artistIds"] = ["marillion", "lazuli"]
        result = audit.build(data([full]), TODAY, slot=2, fetch=lambda u, c:
                             page("2026-11-25", "MARILLION + LAZULI"))
        self.assertEqual(result["stateCounts"],
                         {"published_lineup_matches_official_title": 1})

    def test_unannounced_guest_does_not_become_an_artist(self):
        r = audit.bill_from_page(
            page("2026-11-25", "MARILLION + Guest surprise"), MARILLION,
            VENUE, {a["id"]: a for a in ARTISTS})
        self.assertEqual(r["missingNamedArtists"], [])

    def test_no_headliner_or_band_cap_with_many_different_styles(self):
        names = [f"UNKNOWN GROUP {n:02d}" for n in range(45)]
        title = "MARILLION + " + " + ".join(names)
        r = audit.bill_from_page(page("2026-11-25", title), MARILLION,
                                 VENUE, {a["id"]: a for a in ARTISTS})
        self.assertEqual(r["missingNamedArtists"], names)
        self.assertEqual(len(r["officialNames"]), 46)

    def test_wrong_date_venue_and_multiple_headings_cannot_propose_patch(self):
        bad = [
            page("2026-11-26", "MARILLION + LAZULI"),
            page("2026-11-25", "MARILLION + LAZULI", venue="Autre Salle"),
            page("2026-11-25", "FAUX GROUP + LAZULI"),
            page("2026-11-25", "MARILLION + LAZULI").replace(
                "</main>", "<h1>SECOND CONCERT</h1></main>"),
            page("2026-11-25", "MARILLION + LAZULI").replace(
                "<main>", "<main><main>"),
            page("2026-11-25", "MARILLION + LAZULI").replace(
                "<main>", "<div>").replace("</main>", "</div>"),
        ]
        for fake in bad:
            with self.subTest(fake=fake[:120]), self.assertRaises(ValueError):
                audit.bill_from_page(fake, MARILLION, VENUE,
                                     {a["id"]: a for a in ARTISTS})

    def test_recommended_concert_outside_main_is_not_a_support(self):
        html = page("2026-11-25", "MARILLION")
        html = html.replace(
            "</main>", "</main><aside>1ère partie LAZULI</aside>")
        r = audit.bill_from_page(html, MARILLION, VENUE,
                                 {a["id"]: a for a in ARTISTS})
        self.assertEqual(r["missingNamedArtists"], [])

    def test_exact_aliases_do_not_create_duplicate_artists(self):
        artists = copy.deepcopy(ARTISTS)
        artists[0]["aliases"] = ["MARILLION BAND"]
        r = audit.bill_from_page(
            page("2026-11-25", "MARILLION BAND + LAZULI"), MARILLION,
            VENUE, {a["id"]: a for a in artists})
        self.assertEqual(r["missingNamedArtists"], ["LAZULI"])

    def test_numeric_iso_and_french_dates(self):
        art = {a["id"]: a for a in ARTISTS}
        for label in ("2026-11-25", "25/11/2026", "25.11.2026",
                      "mercredi 25 novembre 2026"):
            with self.subTest(label=label):
                doc = page("2026-11-25", "MARILLION + LAZULI")
                doc = doc.replace("Mercredi 25 novembre 2026 à 19h15", label)
                r = audit.bill_from_page(doc, MARILLION, VENUE, art)
                self.assertEqual(r["missingNamedArtists"], ["LAZULI"])

    def test_read_only_budget_rotation_across_venue_unlisted_sources(self):
        events = [event("Group " + str(n), "marillion",
                        f"2027-04-{n:02d}",
                        f"https://new-venue-{n:02d}.fr/agenda/metal/")
                  for n in range(1, 26)]
        catalogue = data(events)
        results = set()
        for n in range(3):
            for slot in (0, 1, 2):
                chosen, count = audit.select(
                    catalogue["events"], TODAY + dt.timedelta(days=n),
                    slot, 4)
                self.assertLessEqual(len(chosen), 4)
                results.update(e["id"] for e in chosen)
        self.assertEqual(len(results), 25)

    def test_network_failures_never_modify_public_catalogue(self):
        d = data([MARILLION])
        def network_failure(url, cache):
            raise OSError("blocked")
        out = audit.build(d, TODAY, slot=2, fetch=network_failure)
        self.assertEqual(out["stateCounts"],
                         {"held_unverifiable_official_bill": 1})
        self.assertFalse(out["publicationAllowed"])

    def test_unknown_catalogue_schema_fails_closed(self):
        for x in ({}, {"schemaVersion": 1, "events": [], "venues": []}):
            with self.assertRaises(ValueError):
                audit.build(x, TODAY)


if __name__ == "__main__":
    unittest.main()
