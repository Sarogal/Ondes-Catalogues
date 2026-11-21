"""Offline regressions: official festival sites alone establish their own dates.

A URL taken from the discovery queue is an untrusted lead until BOTH the
private J/J+1 check and the independent cloud Publisher first-party reread.
Neither venue nor municipal calendar must contain or repeat the date.
"""
from copy import deepcopy
from pathlib import Path
import sys
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
for item in (str(ROOT / "scripts"), str(ROOT / "tests")):
    if item not in sys.path:
        sys.path.insert(0, item)

from grossesondes_first_party_direct_edition import (
    PROOF_MODE, branded_official_site, verify_first_party_edition,
    verify_first_party_claims, official_city_on_current_date,
    private_proposal, validate_private_proposal,
    independently_verify, validate_verified_row,
)
from national_generic_primary_domain_preflight import (
    examine, stable_first_party_direct_proposals,
)
from grossesondes_cloud_sync import collect_registered_direct_first_party_sources
from grossesondes_stage import stage
from test_grosses_stage import fixtures

DAY1 = "2026-11-21"
DAY2 = "2026-11-22"
SITE = "https://lasainterockfestival.fr/"
TITLE = "La Sainte Rock Festival 2027"
DATES = ("2027-04-23", "2027-04-24")
HOME = (
    "<main><h1>La Sainte Rock Festival 2027</h1>"
    "<p>Festival de rock et punk, notre nouvelle édition "
    "les 23 &amp; 24 avril 2027 à Aix-en-Provence.</p>"
    "<p>Infos pratiques : lieu annoncé, accès sur place.</p></main>")


def queue(today):
    return {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "as_of": today, "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "dossiers": [{
            "id": "national-0123456789abcdef1234",
            "name_hint": "La Sainte Rock Festival",
            "edition_year_hint": 2027,
            "publication_authorized": False, "safe_to_publish": False,
            "sources": [{
                "kind": "CURATED_PRIMARY_CANDIDATE",
                "url": SITE, "discovered_via": SITE,
                "firstSeen": DAY1, "lastSeen": today,
                "publication_authorized": False,
            }],
        }],
    }


class FirstPartyDirectTests(TestCase):
    def test_branded_unknown_site_with_official_dates_is_sufficient(self):
        self.assertTrue(branded_official_site(SITE, TITLE, HOME))
        self.assertEqual(verify_first_party_edition(
            SITE, TITLE, DAY1, fetch=lambda _: HOME), DATES)
        self.assertEqual(
            official_city_on_current_date(HOME, TITLE, DATES),
            "Aix-en-Provence")
        self.assertEqual(
            verify_first_party_claims(
                SITE, TITLE, DAY1, fetch=lambda _: HOME),
            (DATES, "Aix-en-Provence"))
        proposal = private_proposal(TITLE, SITE, DATES, DAY1)
        self.assertEqual(proposal["proofMode"], PROOF_MODE)
        self.assertEqual(proposal["evidence"], [SITE])
        self.assertFalse(proposal["showOnMap"])
        self.assertEqual(proposal["lineup"], [])
        accessed = []
        def reader(url):
            accessed.append(url)
            self.assertEqual(url, SITE)
            return HOME
        row = independently_verify(proposal, DAY1, fetch=reader)
        self.assertEqual(accessed, [SITE])
        self.assertEqual(validate_verified_row(proposal, row, DAY1), row)
        self.assertEqual(row["startDate"], DATES[0])
        self.assertEqual(row["endDate"], DATES[1])

    def test_no_independent_venue_or_municipal_confirmation_ever_needed(self):
        # These fixtures explicitly contain NO external hyperlinks.
        self.assertNotIn("href=", HOME)
        read = lambda url: HOME if url == SITE else self.fail(
            "Unexpected secondary source " + str(url))
        self.assertEqual(verify_first_party_edition(
            SITE, TITLE, DAY1, fetch=read), DATES)

    def test_city_only_from_same_official_edition_dates(self):
        bogus = HOME.replace(
            "à Aix-en-Provence", "dans notre village.")
        bogus = bogus.replace(
            "</main>",
            "<footer>Festival historique du 23 &amp; 24 avril 2026 "
            "à Marseille.</footer></main>")
        self.assertIsNone(official_city_on_current_date(
            bogus, TITLE, DATES))
        two = HOME.replace(
            "à Aix-en-Provence", "à Aix-en-Provence et à Marseille")
        self.assertIsNone(official_city_on_current_date(
            two, TITLE, DATES))

    def test_impostor_wrong_brand_or_vague_date_is_rejected(self):
        other_site = "https://other-festival.fr/"
        self.assertFalse(branded_official_site(other_site, TITLE, HOME))
        for body in (
            HOME.replace("2027", "2026"),
            HOME.replace("23 &amp; 24 avril 2027", "dates à venir"),
            HOME.replace("Festival de rock et punk",
                         "festival de gastronomie"),
            HOME.replace("La Sainte Rock Festival 2027",
                         "Festival complètement différent 2027"),
            HOME.replace("23 &amp; 24 avril 2027",
                         "24 &amp; 25 avril 2027"),
            HOME.replace("Festival de rock et punk",
                         "festival hardcore techno / hardstyle / EDM"),
        ):
            with self.subTest(body=body[:100]):
                dates = verify_first_party_edition(
                    SITE, TITLE, DAY1, fetch=lambda _: body)
                self.assertNotEqual(dates, DATES)
        for bad in ("https://127.0.0.1/",
                    "https://internal.local/",
                    "https://lasainterockfestival.fr/private",
                    "https://lasainterockfestival.fr@evil.fr/"):
            self.assertFalse(branded_official_site(bad, TITLE, HOME))

    def test_j1_is_stability_not_another_source(self):
        cat, _, _ = fixtures()
        state = {"schema": "grossesondes.source-watch.v1"}
        reader = lambda url: HOME if url == SITE else self.fail(
            "External date source forbidden")
        first = examine(state, queue(DAY1), cat, DAY1, fetch=reader)
        self.assertEqual(first["two_day_dates_count"], 0)
        self.assertEqual(stable_first_party_direct_proposals(
            state, queue(DAY1), cat, first, DAY1, fetch=reader), [])
        second = examine(state, queue(DAY2), cat, DAY2, fetch=reader)
        self.assertEqual(second["two_day_dates_count"], 1)
        proposed = stable_first_party_direct_proposals(
            state, queue(DAY2), cat, second, DAY2, fetch=reader)
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["officialSite"], SITE)
        self.assertEqual(proposed[0]["city"], "Aix-en-Provence")
        self.assertFalse(second["publication_authorized"])

    def test_missed_day_does_not_borrow_stale_observation(self):
        cat, _, _ = fixtures()
        state = {"schema": "grossesondes.source-watch.v1"}
        examine(state, queue(DAY1), cat, DAY1, fetch=lambda _: HOME)
        third = "2026-11-23"
        report = examine(
            state, queue(third), cat, third, fetch=lambda _: HOME)
        self.assertEqual(report["two_day_dates_count"], 0)
        self.assertEqual(stable_first_party_direct_proposals(
            state, queue(third), cat, report, third,
            fetch=lambda _: HOME), [])

    def test_publisher_rejects_forged_private_dates(self):
        proposal = private_proposal(TITLE, SITE, DATES, DAY1)
        self.assertEqual(validate_private_proposal(proposal, DAY2), proposal)
        for key, value in (
            ("showOnMap", True),
            ("lat", 43.1),
            ("lineup", ["Faux Groupe"]),
            ("officialSite", "https://fake-festival.fr/"),
            ("source", "https://fake-festival.fr/"),
            ("originSlug", "https://fake-festival.fr/"),
        ):
            with self.subTest(key=key):
                forged = deepcopy(proposal)
                forged[key] = value
                self.assertIsNone(validate_private_proposal(forged, DAY2))
        forged_city = private_proposal(
            TITLE, SITE, DATES, DAY1, city="Marseille")
        self.assertIsNotNone(forged_city)
        self.assertIsNone(independently_verify(
            forged_city, DAY2, fetch=lambda _: HOME))
        fake_date = private_proposal(
            TITLE, SITE, ("2027-04-22", "2027-04-24"), DAY1)
        self.assertIsNotNone(fake_date)
        self.assertIsNone(independently_verify(
            fake_date, DAY2, fetch=lambda _: HOME))

    def test_real_publisher_adds_only_verified_current_edition(self):
        cal, history, patch = fixtures()
        proposed = private_proposal(
            TITLE, SITE, DATES, DAY2, city="Aix-en-Provence")
        patch.update(generated_at=DAY2, additions=[proposed],
                     updates=[], history_additions=[], history_updates=[])
        seen = []
        def reader(url):
            seen.append(url)
            self.assertEqual(url, SITE)
            return HOME
        sources = collect_registered_direct_first_party_sources(
            patch, {r["slug"] for r in cal["festivals"]}, DAY2,
            fetch=reader)
        self.assertEqual(len(sources), 2)
        self.assertEqual(seen, [SITE])
        published, report = stage(
            cal, history, patch, sources, DAY2,
            published_calendar=cal, published_history=history)
        self.assertEqual(len(published["festivals"]),
                         len(cal["festivals"]) + 1)
        self.assertIn(proposed["slug"], report["accepted_additions"])
        self.assertEqual(cal["festivals"], fixtures()[0]["festivals"])
        self.assertFalse(published["festivals"][-1]["showOnMap"])
        self.assertEqual(published["festivals"][-1]["city"],
                         "Aix-en-Provence")
        self.assertIsNone(published["festivals"][-1]["lat"])
        # An inaccessible or changed official announcement is never
        # rescued by a venue article with unrelated or historic dates.
        rejected = collect_registered_direct_first_party_sources(
            patch, set(), DAY2,
            fetch=lambda _: HOME.replace(
                "23 &amp; 24 avril 2027", "22 &amp; 23 avril 2027"))
        self.assertEqual(rejected, {})
        no, held = stage(
            cal, history, patch, rejected, DAY2,
            published_calendar=cal, published_history=history)
        self.assertEqual(len(no["festivals"]), len(cal["festivals"]))
        self.assertIn(proposed["slug"], [x["slug"] for x in held["held"]])


if __name__ == "__main__":
    main()
