"""Synthetic first-party festival + unknown venue reciprocal publisher contracts."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "scripts"), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from grossesondes_venue_reciprocal_edition import (
    safe_root, safe_link, candidate_venue_roots, venue_detail_matches,
    verified_venue_reciprocity, private_proposal, validate_private_proposal,
    independently_verify, validate_verified_row, PROOF_MODE,
)
from grossesondes_cloud_sync import collect_registered_venue_reciprocal_sources
from grossesondes_stage import stage
from national_generic_primary_domain_preflight import (
    examine, stable_reciprocal_venue_proposals,
)
from test_grosses_stage import fixtures

DAY1 = "2026-11-21"
DAY2 = "2026-11-22"
TITLE = "La Sainte Rock Festival 2027"
SITE = "https://lasainterockfestival.fr/"
VENUE = "https://www.6mic-aix.fr/"
DATES = ("2027-04-23", "2027-04-24")
PRIMARY = ('<main><h1>La Sainte Rock Festival 2027</h1>'
           '<p>La Sainte Rock Festival 2027 : festival de rock et punk '
           'les 23 &amp; 24 avril 2027.</p>'
           '<a href="/infos-pratiques">Infos pratiques</a></main>')
INFO = ('<main><h1>Infos pratiques</h1>'
        '<p>Le lieu est 6MIC Aix-en-Provence, une salle de rock.</p>'
        '<a href="https://www.6mic-aix.fr/nos-engagements/">'
        'Plus d’infos sur le lieu</a></main>')
VENUE_HOME = ('<main><h1>Notre salle</h1>'
              '<a href="/agenda/">Agenda</a></main>')
VENUE_AGENDA = ('<main><h1>Agenda de notre salle</h1>'
                '<a href="/evenements/la-sainte-rock-festival-jour-1/">'
                'LA SAINTE ROCK FESTIVAL JOUR 1</a>'
                '<a href="/evenements/la-sainte-rock-festival-jour-2/">'
                'LA SAINTE ROCK FESTIVAL JOUR 2</a></main>')
VENUE_DAY = ('<main><h1>LA SAINTE ROCK FESTIVAL JOUR 1</h1>'
             '<p>Vendredi 23 Avril 2027, concert au 6MIC.</p>'
             '<a href="https://lasainterockfestival.fr/">'
             'INFOS &amp; PROGRAMMATION</a></main>')


def http(pages=None):
    visited = []
    docs = {
        SITE: PRIMARY,
        SITE + "infos-pratiques": INFO,
        VENUE: VENUE_HOME,
        VENUE + "agenda/": VENUE_AGENDA,
        VENUE + "evenements/la-sainte-rock-festival-jour-1/": VENUE_DAY,
        VENUE + "evenements/la-sainte-rock-festival-jour-2/": VENUE_DAY,
    }
    docs.update(pages or {})
    def fetch(url):
        visited.append(url)
        if url not in docs:
            raise ValueError("Unexpected or cross-domain URL:" + str(url))
        return docs[url]
    return fetch, visited


def queue(day):
    return {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "as_of": day, "review_only": True,
        "publication_authorized": False, "safe_to_publish": False,
        "dossiers": [{
            "id": "national-0123456789abcdef1234",
            "name_hint": "La Sainte Rock Festival",
            "edition_year_hint": 2027,
            "publication_authorized": False, "safe_to_publish": False,
            "sources": [{
                "kind": "CURATED_PRIMARY_CANDIDATE",
                "url": SITE, "discovered_via": SITE,
                "firstSeen": DAY1, "lastSeen": day,
                "publication_authorized": False,
            }]
        }],
    }


class DynamicVenueBacklinkProofs(TestCase):
    def test_venue_host_is_rederived_without_approved_venue_list(self):
        read, visited = http()
        self.assertEqual(
            candidate_venue_roots(SITE, PRIMARY, fetch=read), [VENUE])
        self.assertEqual(
            verified_venue_reciprocity(SITE, TITLE, DATES, DAY1, fetch=read),
            VENUE)
        self.assertIn(VENUE + "agenda/", visited)
        self.assertIn(VENUE + "evenements/la-sainte-rock-festival-jour-1/",
                      visited)
        self.assertNotIn("festivalenfrance.com", " ".join(visited))

    def test_reject_hidden_footer_event_wrong_dates_or_wrong_backlink(self):
        for label, venue_detail in {
            "wrong date": VENUE_DAY.replace("23 Avril 2027", "22 Avril 2027"),
            "wrong name": VENUE_DAY.replace(
                "<h1>LA SAINTE ROCK FESTIVAL JOUR 1</h1>",
                "<h1>Un autre festival</h1>"),
            "footer only": VENUE_DAY.replace(
                "<h1>LA SAINTE ROCK FESTIVAL JOUR 1</h1>",
                "<h1>Un autre festival</h1>"
                "<footer>LA SAINTE ROCK FESTIVAL JOUR 1</footer>"),
            "hidden heading": VENUE_DAY.replace(
                "<h1>LA SAINTE ROCK FESTIVAL JOUR 1</h1>",
                "<h1 hidden>LA SAINTE ROCK FESTIVAL JOUR 1</h1>"),
            "other official site": VENUE_DAY.replace(
                SITE, "https://different-festival.fr/"),
            "cancelled": VENUE_DAY.replace(
                "</main>", "<p>Festival 2027 annulé</p></main>"),
        }.items():
            with self.subTest(label=label):
                bad, _ = http({
                    VENUE + "evenements/la-sainte-rock-festival-jour-1/":
                        venue_detail,
                    VENUE + "evenements/la-sainte-rock-festival-jour-2/":
                        venue_detail,
                })
                self.assertIsNone(verified_venue_reciprocity(
                    SITE, TITLE, DATES, DAY1, fetch=bad))

    def test_reject_wrong_primary_genre_period_or_host(self):
        for page in (
            PRIMARY.replace("festival de rock et punk",
                            "festival de musique classique"),
            PRIMARY.replace("23 &amp; 24 avril 2027",
                            "22 &amp; 23 avril 2027"),
            PRIMARY.replace("La Sainte Rock Festival 2027",
                            "Festival différent 2027"),
        ):
            with self.subTest(html=page):
                fetch, _ = http({SITE: page})
                self.assertIsNone(verified_venue_reciprocity(
                    SITE, TITLE, DATES, DAY1, fetch=fetch))

    def test_venue_cannot_be_a_ticketing_or_unrelated_footer_host(self):
        only_tickets = INFO.replace("https://www.6mic-aix.fr/nos-engagements/",
                                    "https://www.weezevent.com/montherme/")
        read, visited = http({SITE + "infos-pratiques": only_tickets})
        self.assertEqual(candidate_venue_roots(
            SITE, PRIMARY, fetch=read), [])
        self.assertIsNone(verified_venue_reciprocity(
            SITE, TITLE, DATES, DAY1, fetch=read))
        self.assertNotIn("https://www.weezevent.com/", visited)

    def test_no_arbitrary_redirect_or_private_ip(self):
        self.assertIsNone(safe_root("http://www.6mic-aix.fr/"))
        self.assertIsNone(safe_root("https://127.0.0.1/"))
        self.assertIsNone(safe_root("https://www.6mic-aix.fr/private"))
        for s in ("https://internal.local/private",
                  "/../admin", "/%2e%2e/admin", "//evil.example/a",
                  "/agenda?url=localhost", "https://evil.example/agenda"):
            self.assertIsNone(safe_link(s, VENUE, VENUE))

    def test_private_claim_does_not_authorize_a_row(self):
        prop = private_proposal(
            TITLE, SITE, DATES, DAY1, venue_root=VENUE)
        self.assertIsNotNone(prop)
        self.assertEqual(prop["proofMode"], PROOF_MODE)
        self.assertFalse(prop["showOnMap"])
        self.assertIsNone(prop["city"])
        self.assertEqual(prop["lineup"], [])
        self.assertEqual(validate_private_proposal(prop, DAY2), prop)
        for key, forged in (
            ("officialSite", "https://fake-festival.fr/"),
            ("source", "https://fake-festival.fr/"),
            ("originSlug", "https://untrusted-venue.fr/"),
            ("showOnMap", True),
            ("lineup", ["fake group"]),
            ("lat", 43.1),
        ):
            with self.subTest(key=key):
                bad = deepcopy(prop)
                bad[key] = forged
                self.assertIsNone(validate_private_proposal(bad, DAY2))

    def test_first_day_is_not_a_proposal_then_j1_can_reverify(self):
        cat, _, _ = fixtures()
        state = {"schema": "grossesondes.source-watch.v1"}
        fetch, _ = http()
        one = examine(state, queue(DAY1), cat, DAY1, fetch=fetch)
        self.assertEqual(one["two_day_dates_count"], 0)
        self.assertEqual(stable_reciprocal_venue_proposals(
            state, queue(DAY1), cat, one, DAY1, fetch=fetch), [])
        two = examine(state, queue(DAY2), cat, DAY2, fetch=fetch)
        self.assertEqual(two["two_day_dates_count"], 1)
        proposals = stable_reciprocal_venue_proposals(
            state, queue(DAY2), cat, two, DAY2, fetch=fetch)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["officialSite"], SITE)
        self.assertEqual(proposals[0]["originSlug"], VENUE)
        self.assertFalse(two["publication_authorized"])

    def test_real_publisher_rebuilds_reciprocity_then_stage_append_only(self):
        cat, hist, patch = fixtures()
        proposal = private_proposal(
            TITLE, SITE, DATES, DAY2, venue_root=VENUE)
        patch.update(generated_at=DAY2, additions=[proposal],
                     updates=[], history_additions=[], history_updates=[])
        fetch, visited = http()
        sources = collect_registered_venue_reciprocal_sources(
            patch, {r["slug"] for r in cat["festivals"]}, DAY2,
            fetch=fetch)
        self.assertEqual(len(sources), 2)
        self.assertEqual(visited.count(SITE), 1)
        verified = independently_verify(proposal, DAY2, fetch=fetch)
        self.assertIsNotNone(verified)
        self.assertEqual(validate_verified_row(proposal, verified, DAY2),
                         verified)
        updated, report = stage(
            cat, hist, patch, sources, DAY2,
            published_calendar=cat, published_history=hist)
        self.assertEqual(len(updated["festivals"]), len(cat["festivals"]) + 1)
        self.assertIn(proposal["slug"], report["accepted_additions"])
        self.assertEqual(cat["festivals"], fixtures()[0]["festivals"])
        evil, _ = http({
            VENUE + "evenements/la-sainte-rock-festival-jour-1/":
                VENUE_DAY.replace(SITE, "https://fake-festival.fr/"),
            VENUE + "evenements/la-sainte-rock-festival-jour-2/":
                VENUE_DAY.replace(SITE, "https://fake-festival.fr/"),
        })
        denied = collect_registered_venue_reciprocal_sources(
            patch, set(), DAY2, fetch=evil)
        self.assertEqual(denied, {})
        held, held_report = stage(
            cat, hist, patch, denied, DAY2,
            published_calendar=cat, published_history=hist)
        self.assertEqual(len(held["festivals"]), len(cat["festivals"]))
        self.assertIn(proposal["slug"],
                      [row["slug"] for row in held_report["held"]])


if __name__ == "__main__":
    main()
