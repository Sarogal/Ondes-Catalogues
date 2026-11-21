"""Offline security and J/J+1 regressions for the open-world OA publisher."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT / "scripts"), str(ROOT / "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

from national_openagenda_linked_primary_preflight import (
    examine, eligible, stable_private_proposals, STATE_KEY,
)
from grossesondes_openagenda_linked_edition import (
    PROOF_MODE, event_url, attributed_site, private_proposal,
    validate_private_proposal, validate_verified_row, independently_verify,
)
from grossesondes_cloud_sync import collect_registered_openagenda_sources
from grossesondes_stage import stage
from test_grosses_stage import fixtures

D1 = "2026-11-21"
D2 = "2026-11-22"
TITLE = "Ferrailles du Nord Festival 2027"
EVENT = "https://openagenda.com/ville-culturelle/events/ferrailles-du-nord-festival"
SITE = "https://www.ferrailles-festival.fr/"
DATES = ("2027-06-12", "2027-06-13")
OA = ('<main><h1>Ferrailles du Nord Festival 2027</h1>'
      '<p>Festival annoncé en 2027.</p>'
      '<a href="https://www.ferrailles-festival.fr/">Site officiel</a>'
      '</main>')
PRIMARY = ('<main><h1>Ferrailles du Nord Festival 2027</h1>'
           '<p>Notre festival metal, punk et hard rock '
           'les 12 et 13 juin 2027.</p></main>')


def queue(day=D1):
    return {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "as_of": day, "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "dossiers": [
            {
                "id": "national-1234567890abcdef1234",
                "name_hint": "Ferrailles du Nord Festival",
                "edition_year_hint": 2027,
                "safe_to_publish": False, "publication_authorized": False,
                "sources": [{
                    "kind": "OPENAGENDA_PUBLIC_RESEARCH_ONLY",
                    "url": EVENT,
                    "discovered_via": (
                        "https://public.opendatasoft.com/api/explore/v2.1/"
                        "catalog/datasets/evenements-publics-openagenda/records"),
                    "firstSeen": D1, "lastSeen": day,
                    "publication_authorized": False,
                }],
            },
        ],
    }


class OpenAgendaLinkedPublisherTests(TestCase):
    def readers(self):
        touched = []
        def oa(url):
            touched.append(url)
            self.assertEqual(url, EVENT)
            return OA
        def primary(url):
            touched.append(url)
            self.assertEqual(url, SITE)
            return PRIMARY
        return touched, oa, primary

    def test_open_world_attributed_site_and_no_directory_whitelist(self):
        self.assertEqual(event_url(EVENT), EVENT)
        self.assertEqual(attributed_site(OA, TITLE, EVENT), SITE)
        proposal = private_proposal(TITLE, SITE, DATES, D1,
                                    event_ref=EVENT)
        self.assertEqual(proposal["proofMode"], PROOF_MODE)
        self.assertEqual(validate_private_proposal(proposal, D2), proposal)
        touched, oa, primary = self.readers()
        row = independently_verify(
            proposal, D2, event_fetch=oa, organizer_fetch=primary)
        self.assertEqual(touched, [EVENT, SITE])
        self.assertEqual(validate_verified_row(proposal, row, D2), row)
        self.assertEqual(row["startDate"], DATES[0])
        self.assertFalse(row["showOnMap"])
        self.assertEqual(row["lineup"], [])
        self.assertIsNone(row["lat"])

    def test_no_unsafe_openagenda_url_or_embedded_authority(self):
        for url in (
            "http://openagenda.com/ville-culturelle/events/ferrailles",
            "https://evil.example/ville-culturelle/events/ferrailles",
            "https://openagenda.com/ville-culturelle/events/ferrailles?url=evil",
            "https://openagenda.com/ville-culturelle/events/../private",
            "https://openagenda.com/ville-culturelle/events/%2e%2e",
            "https://openagenda.com@evil.example/test/events/foo",
            "https://openagenda.com/ville-culturelle/events/ferrailles#fragment",
        ):
            with self.subTest(url=url):
                self.assertIsNone(event_url(url))
                self.assertIsNone(private_proposal(
                    TITLE, SITE, DATES, D1, event_ref=url))

    def test_no_unrelated_hidden_ticketing_or_ambiguous_sites(self):
        forged = (
            OA.replace("Ferrailles du Nord Festival 2027",
                       "Un autre festival 2027"),
            OA.replace("<h1>", "<h1 hidden>"),
            OA.replace('https://www.ferrailles-festival.fr/',
                       'https://127.0.0.1/'),
            OA.replace('https://www.ferrailles-festival.fr/',
                       'https://www.shotgun.live/'),
            OA.replace('Site officiel', 'Billetterie'),
            OA.replace("</main>",
                       '<a href="https://different-festival.fr/">'
                       "Site officiel</a></main>"),
            OA.replace("2027", "2026"),
            OA.replace('<a href=', '<a hidden href='),
        )
        for html in forged:
            with self.subTest(html=html[:110]):
                self.assertIsNone(attributed_site(html, TITLE, EVENT))

    def test_forged_private_fields_and_mismatched_primary_dates_fail(self):
        original = private_proposal(
            TITLE, SITE, DATES, D1, event_ref=EVENT)
        self.assertIsNotNone(original)
        mutations = (
            ("officialSite", "https://evil.example/"),
            ("source", "https://evil.example/"),
            ("showOnMap", True),
            ("lineup", ["Faux artiste"]),
            ("originSlug", "https://evil.example/events/ferrailles"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                altered = deepcopy(original)
                altered[field] = value
                self.assertIsNone(validate_private_proposal(altered, D2))
        shifted = deepcopy(original)
        shifted["startDate"] = "2027-06-11"
        # Claimed dates are untrusted hints, not a structural contradiction.
        # The publisher MUST recheck the actual printed dates independently.
        self.assertIsNotNone(validate_private_proposal(shifted, D2))
        self.assertIsNone(independently_verify(
            shifted, D2, event_fetch=lambda _: OA,
            organizer_fetch=lambda _: PRIMARY))
        mismatched = private_proposal(
            TITLE, SITE, ("2027-06-11", "2027-06-12"), D1,
            event_ref=EVENT)
        self.assertIsNone(independently_verify(
            mismatched, D2, event_fetch=lambda _: OA,
            organizer_fetch=lambda _: PRIMARY))
        self.assertIsNone(independently_verify(
            original, D2, event_fetch=lambda _: OA,
            organizer_fetch=lambda _: PRIMARY.replace(
                "festival metal, punk et hard rock",
                "festival de cuisine traditionnelle")))

    def test_electronic_hardcore_is_not_metal_punk_but_crossover_is_valid(self):
        original = private_proposal(
            TITLE, SITE, DATES, D1, event_ref=EVENT)
        techno = ('<main><h1>Ferrailles du Nord Festival 2027</h1>'
                  '<p>Festival hardcore, hardstyle, rawstyle, techno, '
                  'EDM les 12 et 13 juin 2027.</p></main>')
        crossover = techno.replace(
            'hardcore, hardstyle', 'hardcore punk, hardstyle')
        self.assertIsNone(independently_verify(
            original, D2, event_fetch=lambda _: OA,
            organizer_fetch=lambda _: techno))
        self.assertIsNotNone(independently_verify(
            original, D2, event_fetch=lambda _: OA,
            organizer_fetch=lambda _: crossover))

    def test_first_day_does_not_publish_second_day_can_be_prepared(self):
        cal, _, _ = fixtures()
        state = {"schema": "grossesondes.source-watch.v1"}
        touched, oa, primary = self.readers()
        first = examine(
            state, queue(D1), cal, D1,
            event_fetch=oa, organizer_fetch=primary)
        self.assertEqual(first["two_day_count"], 0)
        self.assertFalse(first["publication_authorized"])
        self.assertEqual(first["rows"][0]["status"],
                         "FIRST_DAY_OPENAGENDA_FIRST_PARTY_PRIVATE")
        self.assertEqual(stable_private_proposals(
            state, queue(D1), cal, first, D1), [])
        second = examine(
            state, queue(D2), cal, D2,
            event_fetch=oa, organizer_fetch=primary)
        self.assertEqual(second["two_day_count"], 1)
        self.assertEqual(second["rows"][0]["status"],
                         "TWO_DAY_OPENAGENDA_FIRST_PARTY_PRIVATE")
        proposed = stable_private_proposals(
            state, queue(D2), cal, second, D2)
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]["name"], TITLE)
        self.assertEqual(state[STATE_KEY][EVENT]["firstSeen"], D1)
        self.assertEqual(state[STATE_KEY][EVENT]["lastSeen"], D2)
        # No J/J+1 report can authorize a publisher; the private proposal
        # itself is still only an untrusted object to independently recheck.
        self.assertFalse(second["publication_authorized"])
        self.assertFalse(proposed[0]["showOnMap"])

    def test_no_two_day_proof_after_gap_or_changed_dates(self):
        cal, _, _ = fixtures()
        state = {"schema": "grossesondes.source-watch.v1"}
        examine(state, queue(D1), cal, D1,
                event_fetch=lambda _: OA,
                organizer_fetch=lambda _: PRIMARY)
        day3 = "2026-11-23"
        changed = examine(
            state, queue(day3), cal, day3,
            event_fetch=lambda _: OA,
            organizer_fetch=lambda _: PRIMARY)
        self.assertEqual(changed["two_day_count"], 0)
        self.assertEqual(stable_private_proposals(
            state, queue(day3), cal, changed, day3), [])

    def test_cloud_collector_and_staged_append_preserve_history(self):
        cal, history, patch = fixtures()
        proposal = private_proposal(
            TITLE, SITE, DATES, D2, event_ref=EVENT)
        patch.update(additions=[proposal], updates=[],
                     generated_at=D2, history_additions=[], history_updates=[])
        visited, event, primary = self.readers()
        sources = collect_registered_openagenda_sources(
            patch, {x["slug"] for x in cal["festivals"]}, D2,
            event_fetch=event, organizer_fetch=primary)
        self.assertEqual(len(sources), 2)
        accepted, report = stage(
            cal, history, patch, sources, D2,
            published_calendar=cal, published_history=history)
        self.assertEqual(len(accepted["festivals"]),
                         len(cal["festivals"]) + 1)
        self.assertIn(proposal["slug"], report["accepted_additions"])
        added = next(r for r in accepted["festivals"]
                     if r["slug"] == proposal["slug"])
        self.assertFalse(added["showOnMap"])
        self.assertEqual(added["startDate"], DATES[0])
        # If OA suddenly names a different domain, the Publisher refuses it
        # rather than treating proposed officialSite as a fetch authority.
        fake_oa = OA.replace(SITE, "https://different-festival.fr/")
        denied = collect_registered_openagenda_sources(
            patch, set(), D2, event_fetch=lambda _: fake_oa,
            organizer_fetch=lambda _: self.fail(
                "Cannot fetch a privately nominated site"))
        self.assertEqual(denied, {})
        held, held_report = stage(
            cal, history, patch, denied, D2,
            published_calendar=cal, published_history=history)
        self.assertEqual(len(held["festivals"]), len(cal["festivals"]))
        self.assertIn(proposal["slug"], [
            r["slug"] for r in held_report["held"]])


if __name__ == "__main__":
    main()
