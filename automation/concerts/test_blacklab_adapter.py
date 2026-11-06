"""Black Lab first-party concert proof tests, with fail-closed missing-year pages."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

import blacklab_adapter
import discover


SOURCE = {
    "name": "The Black Lab", "city": "Wasquehal", "department": "59",
    "priority": "P1", "url": "https://theblacklab.fr/agenda/",
    "adapter": "blacklab_official_detail_review",
    "maxDetailPagesPerRun": 10, "publish_automatically": False,
}
BLACK_DAHLIA = "https://theblacklab.fr/agenda/the-black-dahlia-murder/"
RHAPSODY = "https://theblacklab.fr/agenda/rhapsody-of-fire/"
CAGE = "https://theblacklab.fr/agenda/cage-fight-soul-splitter-kabbel/"
POP = "https://theblacklab.fr/agenda/morgan/"
PAGE2 = "https://theblacklab.fr/agenda/liste/page/2/"
AGENDA = f"""<html><body><nav>Le Black Lab</nav>
<a href="/agenda/rhapsody-of-fire/">Rhapsody of Fire</a>
<a href="/agenda/cage-fight-soul-splitter-kabbel/">Cage Fight</a>
<a href="/agenda/morgan/">Morgan</a>
<a href="{PAGE2}">Suivants</a>
<a href="/agenda/mois/">Mois</a>
<a href="/agenda/reporte-other/?utm=ad">Tracking</a>
<a href="https://evil.example/agenda/forged/">Fake</a>
</body></html>"""
AGENDA2 = """<html><body><a href="/agenda/the-black-dahlia-murder/">
THE BLACK DAHLIA MURDER</a></body></html>"""
DETAIL = """<html><head>Black Lab</head><body>
<nav>Programmation</nav><main>
<h1>{title}</h1><p>{date}</p>
<p>{organizer}</p><p>{description}</p>
</main><footer>THE BLACK LAB</footer></body></html>"""


def dahlia(**extra):
    values = {
        "title": "THE BLACK DAHLIA MURDER",
        "date": "mercredi 3 février 2027 @ 19h00 23h30",
        "organizer": "L’ONDE PRODUCTIONS x GARMONBOZIA",
        "description": "THE BLACK DAHLIA MURDER death metal (USA) + special guests",
    }
    values.update(extra)
    return DETAIL.format(**values)


def rhapsody(**extra):
    values = {
        "title": "RHAPSODY OF FIRE",
        "date": "jeudi 14 janvier 2027 @ 19h00 23h30",
        "organizer": "ACCESS LIVE",
        "description": "Le Motocultor Across Europe Tour power metal symphonique",
    }
    values.update(extra)
    return DETAIL.format(**values)


class BlackLabAdapterTests(unittest.TestCase):
    def test_only_exact_first_party_event_links(self):
        self.assertEqual(
            blacklab_adapter.detail_urls(AGENDA, SOURCE["url"]),
            [CAGE, POP, RHAPSODY])
        self.assertEqual(
            blacklab_adapter.detail_urls(AGENDA2, PAGE2),
            [BLACK_DAHLIA])
        self.assertIsNone(blacklab_adapter.official_slug(
            BLACK_DAHLIA + "?utm_source=forged"))
        self.assertIsNone(blacklab_adapter.official_slug(
            "https://evil.example/agenda/the-black-dahlia-murder/"))

    def test_official_year_and_genre_proof_preserves_unknown_start(self):
        row = blacklab_adapter.detail_candidate(
            dahlia(), BLACK_DAHLIA, SOURCE, "2026-11-03")
        self.assertEqual(row["date"], "2027-02-03")
        self.assertEqual(row["name"], "THE BLACK DAHLIA MURDER")
        self.assertEqual(row["classification"], ["metal"])
        self.assertIsNone(row["localTime"])
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["genreToConfirm"])
        self.assertEqual(row["sourceUrl"], BLACK_DAHLIA)

    def test_reject_no_year_pop_cancelled_and_bad_dates(self):
        variants = [
            ("no year", dahlia(date="mercredi 3 février @ 19h"), BLACK_DAHLIA, SOURCE),
            ("rap", dahlia(description="MORGAN Pop/Rap"), BLACK_DAHLIA, SOURCE),
            ("historic report slug", dahlia(), "https://theblacklab.fr/agenda/reporte-morgan/", SOURCE),
            ("wrong room", dahlia(), BLACK_DAHLIA, {**SOURCE, "name": "Another"}),
            ("cancel", dahlia(organizer="CONCERT ANNULÉ"), BLACK_DAHLIA, SOURCE),
            ("postponed", dahlia(organizer="REPORTÉ"), BLACK_DAHLIA, SOURCE),
            ("past", rhapsody(), RHAPSODY, SOURCE),
            ("fake URL", dahlia(), BLACK_DAHLIA.replace("theblacklab.fr", "fake.example"), SOURCE),
            ("bad date", dahlia(date="jeudi 31 février 2027"), BLACK_DAHLIA, SOURCE),
        ]
        for name, html, url, source in variants:
            today = "2027-02-05" if name == "past" else "2026-11-03"
            with self.subTest(name=name), self.assertRaises((ValueError,KeyError)):
                blacklab_adapter.detail_candidate(html,url,source,today)

    def test_scan_venue_keeps_missing_year_in_review(self):
        pages = {
            SOURCE["url"]: AGENDA, PAGE2: AGENDA2,
            RHAPSODY: rhapsody(), BLACK_DAHLIA: dahlia(),
            CAGE: DETAIL.format(title="CAGE FIGHT + SOUL SPLITTER + KABBEL",
                                date="15 novembre @ 20h00 23h30",
                                organizer="A GAUCHE DE LA LUNE",
                                description="Cage Fight hardcore metal"),
            POP: DETAIL.format(title="MORGAN", date="vendredi 5 février 2027",
                               organizer="MORGAN", description="Chanson pop")
        }
        def fetch(url, **_):
            return pages[url], url
        report = []
        with (patch.object(discover,"robots_allow",return_value=True),
              patch.object(discover,"download",side_effect=fetch),
              patch.object(discover.feeds,"feed_links",
                           return_value={"ics": [], "rss": []})):
            items = discover.scan_venues(
                {"venues":[SOURCE]}, {("officialUrl", RHAPSODY)},
                dt.date(2026,11,3), report)
        self.assertEqual(len(items),2)
        self.assertEqual({x["name"] for x in items},
                         {"RHAPSODY OF FIRE","THE BLACK DAHLIA MURDER"})
        self.assertTrue(all(x["publicationAllowed"] is False for x in items))
        self.assertTrue(all(x["localTime"] is None for x in items))
        self.assertEqual(sum(x["possibleExistingConcert"] for x in items),1)
        diagnostic = report[0]["adapterDiagnostic"]
        self.assertEqual(diagnostic["agendaPagesChecked"],2)
        self.assertEqual(diagnostic["datedGenreLeads"],2)


if __name__ == "__main__":
    unittest.main()
