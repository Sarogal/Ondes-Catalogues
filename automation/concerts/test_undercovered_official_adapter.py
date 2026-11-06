"""Regression and integration tests: municipal French concert collectors (68/87).

Fixtures reproduce official first-party page structure; no external network.
All leads remain private, no fake year or musical start hour.
"""
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import undercovered_official_adapter as u
import discover

TODAY = "2026-11-04"
COLMAR = {"name": "Le Grillen", "city": "Colmar", "department": "68",
          "priority": "P1", "url": u.GRILLEN_AGENDA,
          "adapter": "grillen_official_detail_review",
          "maxDetailPagesPerRun": 8}
LIMOGES = {"name": "Espace John Lennon", "city": "Limoges",
           "department": "87", "priority": "P1", "url": u.LIMOGES_AGENDA,
           "adapter": "limoges_municipal_card_detail_review",
           "maxDetailPagesPerRun": 5}
G_URL = u.GRILLEN + "/programmation/darvaza-merrimack-helleruin-detresse"
L_URL = u.LIMOGES + "/agenda/gwendoline-jessica93"
G_PAGE = """<html><main><h1>DARVAZA + MERRIMACK + HELLERUIN + DETRESSE par</h1>
<p>Métal</p><p>09 décembre<hr>18h30</p><p>Le GRILLEN</p>
<h2>DARVAZA + MERRIMACK + HELLERUIN + DETRESSE</h2>
<p>Black Solstice 2026 : Headbang présente Darvaza, en concert au Grillen
(Colmar, 68) le 9 décembre 2026 !</p>
<p>Le groupe s'est formé en 2002. Black metal.</p></main></html>"""
G_WITHOUT_YEAR = G_PAGE.replace("le 9 décembre 2026", "le 9 décembre")
G_LISTING = """<html><main>
<a href="/programmation/darvaza-merrimack-helleruin-detresse">Darvaza</a>
<a href="/programmation/86-crew-wunderbach-hors-controle">8'6 Crew</a>
<a href="https://evil.example/programmation/forged">Étranger</a>
<a href="/programmation/darvaza-merrimack-helleruin-detresse">Dupliqué</a>
</main></html>"""
L_LISTING = """<html><main><ul>
<li><article><p>Du <time>06 Nov 2026</time></p>
<p>Musique / Concert</p>
<h2><a href="/agenda/release-party-7-weeks-dirty-deep-earth-inc">
Release party : 7 Weeks + Dirty Deep + Earth Inc.</a></h2>
<p>Lieu CCM John-Lennon</p></article></li>
<li><article><p>Du <time>12 Nov 2026</time></p>
<p>Musique / Concert</p>
<h2><a href="/agenda/19a21-michel-cloup">19A21 Michel Cloup</a></h2>
<p>Lieu CCM Jean-Gagnant - Petite salle</p></article></li>
<li><article><p>Du <time>27 Nov 2026</time></p>
<p>Musique / Concert</p>
<h2><a href="/agenda/gwendoline-jessica93">Gwendoline + Jessica93</a></h2>
<p>Lieu CCM John-Lennon</p></article></li>
</ul></main></html>"""
L_DETAIL = """<html><head><title>Gwendoline + Jessica93 - Centres culturels</title></head>
<h1>Gwendoline + Jessica93</h1><main><article>
<p>Un concert en coproduction avec Megablast Prod. Hiero et le
CCM John Lennon fêtent les 20 ans de Born Bad Records.</p>
<p>Gwendoline, collectif cold wave, partage la scène avec Jessica93
et son rock expérimental.</p></article></main></html>"""
L_RELEASE = """<html><h1>Release party : 7 Weeks + Dirty Deep + Earth Inc.</h1>
<main><article><p>Un concert Hiero Limoges. 7 Weeks : heavy rock.
Dirty Deep : heavy blues. Earth Inc : rock.</p></article></main></html>"""


class UndercoveredOfficialAdapterTests(unittest.TestCase):
    def test_strict_first_party_urls_and_limited_pagination(self):
        self.assertTrue(u.valid_agenda(u.GRILLEN_AGENDA, "grillen"))
        self.assertTrue(u.valid_agenda(u.GRILLEN_AGENDA+"&page=2", "grillen"))
        self.assertTrue(u.valid_agenda(u.LIMOGES_AGENDA, "limoges"))
        for url in (u.GRILLEN_AGENDA+"&page=3",
                    u.GRILLEN_AGENDA+"&sort=asc",
                    u.GRILLEN_AGENDA+"&page=1&page=1",
                    u.LIMOGES_AGENDA+"&page=2",
                    "https://evil.example/agenda?keys=hiero"):
            self.assertFalse(u.valid_agenda(url, "grillen")
                             or u.valid_agenda(url, "limoges"))
        self.assertEqual(u.grillen_links(G_LISTING, u.GRILLEN_AGENDA)[0], G_URL)
        self.assertEqual(len(u.grillen_links(G_LISTING, u.GRILLEN_AGENDA)), 2)
        for url in (G_URL+"?utm_campaign=abc",
                    "http://grillen.colmar.fr/programmation/test",
                    "https://evil.example/programmation/test",
                    "https://grillen.colmar.fr/agenda?date=toutes"):
            self.assertIsNone(u.exact_detail(url, "grillen"))

    def test_named_grillen_detail_has_full_year_and_no_fake_hour(self):
        row = u.grillen_detail(G_PAGE, G_URL, COLMAR, TODAY)
        self.assertEqual(row["date"], "2026-12-09")
        self.assertEqual(row["venue"], "Le Grillen")
        self.assertEqual(row["classification"], ["metal"])
        self.assertEqual(row["leadArtist"], "DARVAZA")
        self.assertIsNone(row["localTime"])
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])

    def test_official_category_as_sibling_not_false_biography_genre(self):
        # Some live Drupal pages do not wrap the category in a valid <p>.
        # A short explicit category immediately after H1 is still first-party.
        sibling = G_PAGE.replace(
            "<p>Métal</p>", "<div><span>Métal</span></div>", 1)
        record = u.grillen_detail(sibling, G_URL, COLMAR, TODAY)
        self.assertEqual(record["date"], "2026-12-09")
        self.assertEqual(record["classification"], ["metal"])
        self.assertFalse(record["publicationAllowed"])
        category_only_in_bio = G_PAGE.replace(
            "<p>Métal</p>", "<div>Variété</div>", 1)
        # The later artist biography does mention black metal; this is
        # not an official masthead category and cannot rescue the record.
        with self.assertRaisesRegex(ValueError, "music category"):
            u.grillen_detail(category_only_in_bio, G_URL, COLMAR, TODAY)

    def test_grillen_must_not_infer_year_from_biography_or_future_month(self):
        invalid = {
            "no_year": G_WITHOUT_YEAR,
            "year_wrong_day": G_PAGE.replace("le 9 décembre 2026", "le 10 décembre 2026"),
            "year_in_past": G_PAGE.replace("le 9 décembre 2026", "le 9 décembre 2025"),
            "other_venue": G_PAGE.replace("Le GRILLEN", "La Laiterie").replace(
                "au Grillen", "à la Laiterie").replace("(Colmar, 68)", "(Strasbourg, 67)"),
            "category_missing": G_PAGE.replace("<p>Métal</p>", "<p>Variété</p>"),
            "cancelled": G_PAGE.replace("<h1>DARVAZA", "<h1>ANNULÉ DARVAZA"),
            "forged_bio_year": G_WITHOUT_YEAR.replace(
                "Le groupe s'est formé en 2002.",
                "Le groupe a joué au Grillen le 9 décembre 2024."),
        }
        for label, body in invalid.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                u.grillen_detail(body, G_URL, COLMAR, TODAY)
        with self.assertRaises(ValueError):
            u.grillen_detail(G_PAGE, G_URL, {**COLMAR, "city":"Strasbourg"}, TODAY)

    def test_limited_unknown_url_rotation_and_known_recheck(self):
        urls = u.grillen_links(G_LISTING, u.GRILLEN_AGENDA)
        selected = u.select_urls(urls, {("officialUrl", G_URL)}, TODAY, limit=2)
        self.assertEqual(set(selected), set(urls))
        self.assertEqual(selected[0], next(x for x in urls if x != G_URL))
        self.assertEqual(len(u.select_urls(urls*3, set(), TODAY, limit=1)), 1)

    def test_municipal_card_correlates_full_date_venue_and_link(self):
        cards = u.limoges_cards(L_LISTING, u.LIMOGES_AGENDA, TODAY)
        self.assertEqual(len(cards), 2)
        self.assertEqual([c["date"] for c in cards], ["2026-11-06", "2026-11-27"])
        self.assertTrue(all(c["venue"] == "CCM John-Lennon" for c in cards))
        self.assertEqual(cards[1]["url"], L_URL)
        row = u.limoges_detail(L_DETAIL, cards[1], LIMOGES, TODAY)
        self.assertEqual(row["name"], "Gwendoline + Jessica93")
        self.assertEqual(row["date"], "2026-11-27")
        self.assertEqual(row["leadArtist"], "Gwendoline")
        self.assertIsNone(row["localTime"])
        self.assertFalse(row["publicationAllowed"])
        release = u.limoges_detail(L_RELEASE, cards[0], LIMOGES, TODAY)
        self.assertEqual(release["leadArtist"], "7 Weeks")

    def test_municipal_rejects_missing_year_foreign_room_genre_or_title(self):
        for malformed in (
            L_LISTING.replace("27 Nov 2026", "27 Nov"),
            L_LISTING.replace("27 Nov 2026", "27 Nov 2025"),
            L_LISTING.replace("CCM John-Lennon", "CCM Jean-Gagnant"),
            L_LISTING.replace('href="/agenda/gwendoline-jessica93"',
                              'href="https://evil.example/agenda/gwendoline-jessica93"'),
        ):
            rows = u.limoges_cards(malformed, u.LIMOGES_AGENDA, TODAY)
            self.assertFalse(any(x["url"] == L_URL for x in rows))
        card = u.limoges_cards(L_LISTING, u.LIMOGES_AGENDA, TODAY)[1]
        for page in (
            L_DETAIL.replace("cold wave", "chanson").replace("rock", "chanson"),
            L_DETAIL.replace("Gwendoline + Jessica93", "Concert différent"),
        ):
            with self.assertRaises(ValueError):
                u.limoges_detail(page, card, LIMOGES, TODAY)
        with self.assertRaises(ValueError):
            u.limoges_detail(L_DETAIL, card, {**LIMOGES, "city":"Bordeaux"}, TODAY)

    def test_integration_discover_two_adapters_are_private_leads_only(self):
        sources = json.loads((Path(__file__).parent/"sources.json").read_text(
            encoding="utf-8"))["venues"]
        g = next(x for x in sources if x["id"].endswith("grillen-colmar"))
        l = next(x for x in sources if x["id"].endswith("ccm-john-lennon-limoges"))
        self.assertEqual(g["adapter"], "grillen_official_detail_review")
        self.assertEqual(l["adapter"], "limoges_municipal_card_detail_review")
        lookup = {
            u.GRILLEN_AGENDA: G_LISTING,
            u.GRILLEN_AGENDA+"&page=1": G_LISTING,
            u.GRILLEN_AGENDA+"&page=2": G_LISTING,
            G_URL: G_PAGE,
            u.GRILLEN+"/programmation/86-crew-wunderbach-hors-controle": G_WITHOUT_YEAR,
            u.LIMOGES_AGENDA: L_LISTING,
            L_URL: L_DETAIL,
            u.LIMOGES+"/agenda/release-party-7-weeks-dirty-deep-earth-inc": L_RELEASE,
        }
        def download(url, **kwargs):
            if url not in lookup:
                raise RuntimeError("Unexpected cross-origin or unbounded download")
            return lookup[url], url
        checks = []
        with patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover, "download", side_effect=download):
            rows = discover.scan_venues({"venues":[g,l]}, set(),
                                        dt.date.fromisoformat(TODAY), checks)
        ids = {x["candidateId"] for x in rows}
        self.assertTrue(any(x.startswith("grillen:2026-12-09") for x in ids))
        self.assertTrue(any(x.startswith("limoges-john-lennon:2026-11-27") for x in ids))
        self.assertTrue(all(not x["publicationAllowed"] and x["reviewRequired"]
                            for x in rows))
        self.assertEqual({x["venue"] for x in checks},
                         {"Le Grillen", "Espace John Lennon"})
        self.assertTrue(all(x["adapterDiagnostic"]["publicationAllowed"] is False
                            for x in checks))


if __name__ == "__main__":
    unittest.main()
