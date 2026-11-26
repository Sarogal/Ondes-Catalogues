"""Offline security and J/J+1 regressions for the open-world OA publisher."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import patch

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
    prove_municipal_edition,
)
from national_openagenda_research import pass_edition_title, provider_title_matches
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

    def test_commercial_pass_is_a_research_alias_not_edition_dates(self):
        for suffix in ("4J PASS (4-events)", "Pass 3 jours", "Full Pass",
                       "Pass Weekend"):
            with self.subTest(suffix=suffix):
                raw = "Festival Ferrailles du Nord Festival 2027 - " + suffix
                self.assertEqual(pass_edition_title(raw, 2027), TITLE)
                self.assertTrue(provider_title_matches(raw, TITLE, 2027))
        commercial = "Festival Ferrailles du Nord Festival 2027 - 4J PASS (4-events)"
        q = queue()
        q["dossiers"][0]["name_hint"] = commercial
        catalogue = {"schema": 1, "festivals": []}
        self.assertEqual(eligible(q, catalogue, D1)[0]["title"], TITLE)
        oa = OA.replace(TITLE, commercial).replace(
            "Festival annoncé en 2027.", "Pass du 10 au 11 juin 2027.")
        self.assertEqual(attributed_site(oa, TITLE, EVENT), SITE)
        proposal = private_proposal(TITLE, SITE, DATES, D1, event_ref=EVENT)
        row = independently_verify(proposal, D2, event_fetch=lambda _: oa,
                                   organizer_fetch=lambda _: PRIMARY)
        self.assertEqual(row["startDate"], DATES[0])
        self.assertEqual(row["endDate"], DATES[1])
        forged = private_proposal(TITLE, SITE, ("2027-06-10", "2027-06-11"),
                                  D1, event_ref=EVENT)
        self.assertIsNone(independently_verify(
            forged, D2, event_fetch=lambda _: oa, organizer_fetch=lambda _: PRIMARY))

    def test_commercial_alias_does_not_remove_artist_or_wrong_year(self):
        for raw in ("Ferrailles du Nord Festival 2026 - Pass 3 jours",
                    "Ferrailles du Nord Festival 2027 - Pass 3 jours + autre groupe",
                    "Concert Ferrailles du Nord Festival 2027 - Pass 3 jours",
                    "Ferrailles du Nord Festival 2026 2027 - Full Pass",
                    "Autre Festival 2027 - Pass 3 jours"):
            with self.subTest(raw=raw):
                self.assertFalse(provider_title_matches(raw, TITLE, 2027))
                self.assertIsNone(attributed_site(OA.replace(TITLE, raw), TITLE, EVENT))

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

    def test_oldest_first_and_urgent_unknown_current_year(self):
        cal, _, _ = fixtures()
        q = queue()
        example = q["dossiers"][0]
        q["dossiers"] = []
        for index, (name, year, hint) in enumerate((
                ("A Future Festival", 2027, None),
                ("Z Current Festival", 2026, None),
                ("Y Imminent Festival", 2026, "2026-11-23"),
                ("B Future Festival", 2027, None))):
            d = deepcopy(example)
            d.update(id="national-priority-" + str(index), name_hint=name,
                     edition_year_hint=year,
                     date_hints=[{"start_date": hint}] if hint else [])
            d["sources"][0]["url"] = EVENT + "-" + str(index)
            q["dossiers"].append(d)
        state = {"schema": "grossesondes.source-watch.v1"}
        def read(_):
            raise OSError("Unavailable")
        order = []
        for _ in range(4):
            report = examine(state, q, cal, D1, event_fetch=read, limit=1)
            order.append(report["rows"][0]["event_ref_review_only"])
        self.assertEqual(order, [EVENT + "-" + str(i) for i in (2, 1, 0, 3)])
        self.assertTrue(all(row["lastChecked"] == D1
                            for row in state[STATE_KEY].values()))

    def test_first_day_can_prepare_but_never_authorize_publication(self):
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
        first_proposals = stable_private_proposals(
            state, queue(D1), cal, first, D1)
        self.assertEqual(len(first_proposals), 1)
        self.assertEqual(first_proposals[0]["name"], TITLE)
        self.assertFalse(first_proposals[0]["showOnMap"])
        self.assertIsNotNone(independently_verify(
            first_proposals[0], D1, event_fetch=oa,
            organizer_fetch=primary))
        self.assertIsNone(independently_verify(
            first_proposals[0], D1, event_fetch=oa,
            organizer_fetch=lambda _: "<main>Programme non confirmé</main>"))
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
        self.assertEqual(len(stable_private_proposals(
            state, queue(day3), cal, changed, day3)), 1)
        # A forged report still cannot use a different first-party date.
        changed["rows"][0]["start_date_hint"] = "2027-01-01"
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




class MunicipalDirectEditionTests(TestCase):
    CITY = "Ville Culturelle"
    ROOT = "https://www.ville-culturelle.fr/"
    DETAIL = ROOT + "agenda/ferrailles-du-nord-festival"

    def commune(self, city):
        self.assertEqual(city, self.CITY)
        return {"city": city, "codeInsee": "12345"}

    def directory(self, url):
        return {"total_count": 1, "results": [{
            "nom": "Mairie - " + self.CITY, "code_insee_commune": "12345",
            "statut_de_diffusion": True,
            "pivot": [{"type_service_local": "mairie",
                       "code_insee_commune": ["12345"]}],
            "site_internet": [{"valeur": self.ROOT}],
        }]}

    def read(self, url):
        if url == self.ROOT:
            return '<a href="/agenda/ferrailles-du-nord-festival">' + TITLE + '</a>'
        self.assertEqual(url, self.DETAIL)
        return PRIMARY

    def proof(self, city, title, today, *, fetch):
        return prove_municipal_edition(
            city, title, today, fetch=fetch, commune_lookup=self.commune,
            directory_fetch=self.directory)

    def test_direct_municipal_page_without_external_festival_website(self):
        self.assertEqual(self.proof(self.CITY, TITLE, D1, fetch=self.read),
                         (self.DETAIL, DATES))
        proposal = private_proposal(
            TITLE, self.DETAIL, DATES, D1, event_ref=EVENT,
            municipality=self.CITY)
        self.assertIsNotNone(proposal)
        with patch("grossesondes_openagenda_linked_edition.prove_municipal_edition",
                   side_effect=self.proof):
            public = independently_verify(proposal, D2, organizer_fetch=self.read,
                                          event_fetch=lambda _: self.fail("OA not authority"))
            self.assertEqual(validate_verified_row(proposal, public, D2), public)
            self.assertIsNotNone(public)
            self.assertEqual(public["officialSite"], self.DETAIL)
            self.assertIsNone(public["city"])
            self.assertFalse(public["showOnMap"])
            forged = private_proposal(TITLE, "https://evil.example/event", DATES,
                                      D1, event_ref=EVENT, municipality=self.CITY)
            self.assertIsNone(independently_verify(forged, D2, organizer_fetch=self.read))

    def test_genre_and_wrong_heading_fail(self):
        for changed in (PRIMARY.replace("metal, punk et hard rock", "techno"),
                        PRIMARY.replace("Ferrailles du Nord", "Autre Nom")):
            def read(url):
                return changed if url == self.DETAIL else self.read(url)
            self.assertIsNone(self.proof(self.CITY, TITLE, D1, fetch=read))

    def test_numbered_h2_with_adjacent_single_day_date(self):
        title = "Les Forges Fest 2027"
        detail = self.ROOT + "evenement/les-forges-fest-3/"
        html = ('<main><h1>Agenda</h1><h2>Les Forges Fest #3</h2>'
                '<h3>28 juin 2027 de 20:00 à 21:30</h3>'
                '<p>Troisième édition du Les Forges Fest. '
                'Une soirée de metal avec quatre groupes.</p><h2>Détails</h2></main>')
        def read(url):
            if url == self.ROOT:
                return '<a href="' + detail + '">Les Forges Fest #3</a>'
            self.assertEqual(url, detail)
            return html
        self.assertEqual(self.proof(self.CITY, title, D1, fetch=read),
                         (detail, ("2027-06-28", "2027-06-28")))
        for invalid in (
                html.replace('28 juin 2027', '28 juin 2025'),
                html.replace('<h3>28', '<h3 hidden>28'),
                html.replace('28 juin 2027', 'Ouverture billetterie 28 juin 2027'),
                html.replace('28 juin 2027', '28 juin 2027 et 30 juillet 2027'),
                html.replace('Troisième édition', 'Édition annulée'),
                html.replace('Une soirée de metal', 'Une soirée de techno'),
                html.replace('Les Forges Fest #3</h2>',
                             'Autre événement #3</h2>'),
                html.replace('Une soirée de metal', 'Une tournée itinérante de metal'),
                html.replace('<p>Troisième', '<h2>Autre spectacle</h2><p>Troisième')):
            def bad_read(url):
                return read(url) if url == self.ROOT else invalid
            self.assertIsNone(self.proof(self.CITY, title, D1, fetch=bad_read))

    def test_no_municipal_override_of_attributed_organizer(self):
        cal, _, _ = fixtures()
        q = queue(D1)
        q["dossiers"][0]["city_hint"] = self.CITY
        state = {"schema": "grossesondes.source-watch.v1"}
        with patch("national_openagenda_linked_primary_preflight.prove_municipal_edition",
                   side_effect=AssertionError("Cannot bypass primary source")):
            result = examine(state, q, cal, D1, event_fetch=lambda _: OA,
                             organizer_fetch=lambda _: "<h1>Festival annulé</h1>")
        self.assertEqual(stable_private_proposals(state, q, cal, result, D1), [])

    def test_discovery_handoff_on_unavailable_oa(self):
        cal, _, _ = fixtures()
        dossier_queue = queue(D1)
        dossier_queue["dossiers"][0]["city_hint"] = self.CITY
        state = {"schema": "grossesondes.source-watch.v1"}
        def unavailable(_):
            raise OSError("OpenAgenda unavailable")
        with patch("national_openagenda_linked_primary_preflight.prove_municipal_edition",
                   side_effect=self.proof):
            report = examine(state, dossier_queue, cal, D1,
                             event_fetch=unavailable, organizer_fetch=self.read)
        proposals = stable_private_proposals(state, dossier_queue, cal, report, D1)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["evidence"], [EVENT, self.DETAIL, self.CITY])
        self.assertFalse(report["publication_authorized"])

if __name__ == "__main__":
    main()
