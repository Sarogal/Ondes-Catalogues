"""Synthetic fail-closed proofs for unknown festival directory attribution."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from grossesondes_cloud_sync import collect_registered_directory_sources
from national_generic_primary_domain_preflight import (
    stable_directory_proposals, _digest, SCHEMA as PRIVATE_REVIEW_SCHEMA,
)
from grossesondes_stage import stage
from test_grosses_stage import fixtures
from grossesondes_generic_directory_edition import (
    directory_url, directory_urls, discover_directory_website,
    trusted_linked_site, verify_primary, visible_adjacent_edition_dates,
    private_proposal,
    validate_private_proposal, independently_verify, validate_verified_row,
    PROOF_MODE,
)

DAY = "2026-11-21"
TITLE = "Festibarock'in 2027"
SITE = "https://www.festibarockin.fr/"
DIRECTORY = "https://www.festivalenfrance.com/festival/festibarockin"
DATES = ("2027-06-25", "2027-06-26")
ENTRY = ("<main><h1>Festibarock'in</h1><p>Festival de rock français."
         "</p><ul><li>Site web : "
         '<a href="https://www.festibarockin.fr">www.festibarockin.fr</a>'
         "</li></ul></main>")
OFFICIAL = ("<main><h1>Festibarock'in</h1>"
            "<p>25 et 26 juin 2027 : notre festival de rock "
            "avec l'association organisatrice.</p></main>")


class GenericDirectoryProofTests(TestCase):
    def test_adjacent_first_party_festival_hero_dates_can_be_proven(self):
        # Real homepages frequently print a headline and dates as separate
        # visible blocks instead of repeating them in one paragraph.
        home = ('<main><section><h2>FESTIBAROCK\'IN</h2>'
                '<div>25 &amp; 26 Juin 2027</div>'
                '<p>Un festival de rock pour tous, avec concerts.</p>'
                '</section></main>')
        # Assert that the NEW alternate structural reader really works;
        # the legacy near-title reader may sometimes reach the same result.
        self.assertEqual(
            visible_adjacent_edition_dates(home, TITLE, 2027, DAY), DATES)
        self.assertEqual(
            verify_primary(home, TITLE, 2027, DAY), DATES)
        route = private_proposal(TITLE, SITE, DATES, DAY)
        self.assertIsNotNone(route)
        visited = []
        published = independently_verify(
            route, DAY,
            directory_fetch=lambda url: visited.append(url) or ENTRY,
            organizer_fetch=lambda url: visited.append(url) or home)
        self.assertIsNotNone(published)
        self.assertEqual(visited, [DIRECTORY, SITE])
        self.assertFalse(published["showOnMap"])
        self.assertEqual(published["lineup"], [])

    def test_hero_proof_rejects_unrelated_hidden_cancelled_and_forged_dates(self):
        head = "<main><h2>FESTIBAROCK'IN</h2>"
        date = "<p>25 &amp; 26 Juin 2027</p>"
        tail = "<p>Festival de rock et metal.</p></main>"
        valid = head + date + tail
        cases = {
            "hidden_date": head +
                "<p hidden>25 &amp; 26 Juin 2027</p>" + tail,
            "hidden_title": "<main><h2 hidden>FESTIBAROCK'IN</h2>" +
                date + tail,
            "other_year": head + "<p>25 &amp; 26 Juin 2026</p>" + tail,
            "ticket_on_sale": head +
                "<p>Ouverture billetterie 25 &amp; 26 Juin 2027</p>" + tail,
            "mixed_date": head +
                "<p>25 &amp; 26 Juin 2027; 01 &amp; 02 Juillet 2027</p>" + tail,
            "cancelled": head + date +
                "<p>Festival 2027 annulé.</p></main>",
            "tour": head + date +
                "<p>Festival de rock: tournée itinérante de concerts en 2027.</p></main>",
            "jsonld_conflict": valid + (
                '<script type="application/ld+json">'
                '{"@type":"MusicEvent","name":"Festibarock\'in 2027",'
                '"startDate":"2027-07-25","endDate":"2027-07-26"}'
                "</script>"),
            "script_only": head +
                "<script>25 &amp; 26 Juin 2027</script>" + tail,
            "identity_mismatch": valid.replace(
                "FESTIBAROCK'IN", "Festival totalement étranger"),
            "other_festival_between": head +
                "<h3>Un autre festival</h3>" + date + tail,
        }
        for kind, html in cases.items():
            with self.subTest(kind=kind):
                self.assertIsNone(verify_primary(html, TITLE, 2027, DAY))
        # A different, explicitly announced FUTURE date is not invalid on
        # its own. The signed candidate dates must still match EXACTLY.
        shifted = head + "<p>24 &amp; 25 Juin 2027</p>" + tail
        self.assertEqual(
            verify_primary(shifted, TITLE, 2027, DAY),
            ("2027-06-24", "2027-06-25"))
        proposal = private_proposal(TITLE, SITE, DATES, DAY)
        self.assertIsNotNone(proposal)
        self.assertIsNone(independently_verify(
            proposal, DAY,
            directory_fetch=lambda _url: ENTRY,
            organizer_fetch=lambda _url: shifted))

    def test_directory_derived_from_identity_not_patch_url(self):
        self.assertEqual(directory_url(TITLE), DIRECTORY)
        for bad in ("Other Name", "Festival 2027/../../../private",
                    "Rock 2027", "", "A 2027"):
            with self.subTest(bad=bad):
                self.assertIsNone(directory_url(bad))

    def test_exact_visible_heading_and_attributed_https_site(self):
        self.assertEqual(trusted_linked_site(ENTRY, TITLE), SITE)
        for html in (
            ENTRY.replace("<h1>Festibarock'in</h1>", "<h1>Other Fest</h1>"),
            ENTRY.replace('href="https://www.festibarockin.fr"',
                          'href="http://www.festibarockin.fr"'),
            ENTRY.replace('www.festibarockin.fr</a>',
                          'festival-info.fr</a>'),
            ENTRY.replace('www.festibarockin.fr</a>',
                          'www.festibarockin.fr</a>'
                          '<a href="https://www.autrefestival.fr/">Site web</a>'),
        ):
            with self.subTest(html=html[:90]):
                self.assertIsNone(trusted_linked_site(html, TITLE))

    def test_hidden_heading_cannot_claim_festival_identity(self):
        html = ENTRY.replace(
            "<h1>Festibarock'in</h1>",
            '<div hidden><h1>Festibarock\'in</h1></div>')
        self.assertIsNone(trusted_linked_site(html, TITLE))
        script = '<script><h1>Festibarock\'in</h1></script>' + ENTRY
        self.assertEqual(trusted_linked_site(script, TITLE), SITE)

    def test_real_directory_slug_variants_and_local_web_attribution(self):
        # Live directory pages use BOTH /mozhell-open-air and
        # /festibarockin. They display the external site as "Web" in a
        # local contact block, rather than always as "Site officiel".
        title = "MozHell Open Air 2027"
        compact, hyphen = directory_urls(title)
        self.assertEqual(
            compact, "https://www.festivalenfrance.com/festival/mozhellopenair")
        self.assertEqual(
            hyphen, "https://www.festivalenfrance.com/festival/mozhell-open-air")
        site = "https://www.mozhell.fr/"
        page = ('<main><h1>MozHell Open Air</h1>'
                '<section><p>Festival metal en Moselle</p>'
                '<div>Contact</div><div>Web : '
                '<a href="https://www.mozhell.fr/">www.mozhell.fr</a>'
                '</div></section></main>')
        self.assertEqual(trusted_linked_site(page, title), site)
        calls = []
        def directory_read(url):
            calls.append(url)
            if url == compact:
                raise OSError("Compact path absent on the directory")
            self.assertEqual(url, hyphen)
            return page
        self.assertEqual(
            discover_directory_website(title, directory_read),
            (hyphen, site))
        self.assertEqual(calls, [compact, hyphen])
        proposal = private_proposal(
            title, site, ("2027-07-23", "2027-07-25"), DAY,
            directory_ref=hyphen)
        self.assertEqual(validate_private_proposal(proposal, DAY), proposal)
        checked = []
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=("2027-07-23", "2027-07-25")):
            proof = independently_verify(
                proposal, DAY,
                directory_fetch=lambda url: checked.append(url) or page,
                organizer_fetch=lambda url: checked.append(url) or
                    "<main><h1>MozHell Open Air 2027</h1>"
                    "<p>23 au 25 juillet 2027, festival metal.</p></main>")
        self.assertEqual(checked, [hyphen, site])
        self.assertIsNotNone(proof)
        self.assertFalse(proof["showOnMap"])

    def test_real_directory_variant_cannot_be_forged_as_arbitrary_host(self):
        title = "MozHell Open Air 2027"
        compact, hyphen = directory_urls(title)
        site = "https://www.mozhell.fr/"
        dates = ("2027-07-23", "2027-07-25")
        self.assertIsNone(private_proposal(
            title, site, dates, DAY, directory_ref="https://example.net/"))
        proper = private_proposal(title, site, dates, DAY,
                                  directory_ref=hyphen)
        for bad_url in ("https://evil.example/festival/mozhell-open-air",
                        "https://www.festivalenfrance.com/admin",
                        "https://www.festivalenfrance.com/festival/../private"):
            with self.subTest(bad_url=bad_url):
                changed = deepcopy(proper)
                changed["originSlug"] = bad_url
                changed["evidence"][0] = bad_url
                self.assertIsNone(validate_private_proposal(changed, DAY))
                self.assertIsNone(independently_verify(
                    changed, DAY,
                    directory_fetch=lambda url: self.fail(
                        "Forged URL cannot reach the network")))
        self.assertIsNone(trusted_linked_site(
            "<main><h1>MozHell Open Air</h1>"
            '<div>Billetterie : <a href="https://tickets.example.net">'
            "tickets.example.net</a></div></main>", title))
        self.assertIsNone(trusted_linked_site(
            "<main><h1>MozHell Open Air</h1>"
            '<div hidden>Web : <a href="https://www.mozhell.fr/">'
            "www.mozhell.fr</a></div></main>", title))

    def test_only_map_free_minimal_private_proposal_is_valid(self):
        p = private_proposal(TITLE, SITE, DATES, DAY)
        self.assertEqual(p["proofMode"], PROOF_MODE)
        self.assertEqual(validate_private_proposal(p, DAY), p)
        self.assertFalse(p["showOnMap"])
        self.assertEqual(p["lineup"], [])
        for field, value in [
            ("lat", 48.0), ("region", "Grand Est"),
            ("source", "https://evil.example/"),
            ("officialSite", "https://evil.example/"),
            ("verificationStatus", "Confirmé"),
        ]:
            with self.subTest(field=field):
                q = deepcopy(p)
                q[field] = value
                self.assertIsNone(validate_private_proposal(q, DAY))
        self.assertIsNone(private_proposal(
            TITLE, "https://127.0.0.1/", DATES, DAY))

        # A structurally valid but forged date remains only a private hint:
        # the publisher's independent HTTP proof must refuse it.
        tampered = deepcopy(p)
        tampered["startDate"] = "2027-06-24"
        self.assertIsNotNone(validate_private_proposal(tampered, DAY))
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            self.assertIsNone(independently_verify(
                tampered, DAY, directory_fetch=lambda _: ENTRY,
                organizer_fetch=lambda _: OFFICIAL))

    def test_publisher_independently_rediscovers_directory_before_site(self):
        p = private_proposal(TITLE, SITE, DATES, DAY)
        visited = []
        def directory_fetch(url):
            visited.append(url)
            self.assertEqual(url, DIRECTORY)
            return ENTRY
        def organizer_fetch(url):
            visited.append(url)
            self.assertEqual(url, SITE)
            return OFFICIAL
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            row = independently_verify(p, DAY, directory_fetch,
                                       organizer_fetch)
        self.assertEqual(visited, [DIRECTORY, SITE])
        self.assertEqual(validate_verified_row(p, row, DAY), row)
        self.assertFalse(row["showOnMap"])
        self.assertNotIn("proofMode", row)
        self.assertEqual(row["lineup"], [])

    def test_directory_mismatch_cannot_trigger_external_request(self):
        p = private_proposal(TITLE, SITE, DATES, DAY)
        for directory in (
            ENTRY.replace('www.festibarockin.fr', 'www.faux-festival.fr'),
            '<h1>Festibarock\'in</h1><p>Site web : '
            '<a href="https://127.0.0.1/private">Site officiel</a></p>',
        ):
            with self.subTest(directory=directory[:60]):
                self.assertIsNone(independently_verify(
                    p, DAY, directory_fetch=lambda _: directory,
                    organizer_fetch=lambda _: self.fail(
                        "private site cannot authorize outbound request")))

    def test_independent_primary_genre_and_dates_are_mandatory(self):
        with patch("grossesondes_generic_directory_edition.prove_dates",
                   return_value=DATES):
            self.assertEqual(verify_primary(OFFICIAL, TITLE, 2027, DAY), DATES)
            self.assertIsNone(verify_primary(
                "<main>Festival jazz 2027</main>", TITLE, 2027, DAY))


    def test_publisher_collector_and_stage_accept_only_independently_verified(self):
        candidate = private_proposal(TITLE, SITE, DATES, DAY)
        cal, hist, patch_data = fixtures()
        patch_data["additions"] = [candidate]
        patch_data["updates"] = []
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            proven = collect_registered_directory_sources(
                patch_data, set(), DAY,
                directory_fetch=lambda url: ENTRY,
                organizer_fetch=lambda url: OFFICIAL)
        self.assertTrue(proven.get(
            "registered-directory-verified:" + candidate["slug"]))
        staged, report = stage(
            cal, hist, patch_data, proven, DAY,
            published_calendar=cal, published_history=hist)
        self.assertEqual(report["accepted_additions"], [candidate["slug"]])
        self.assertEqual(len(staged["festivals"]), len(cal["festivals"]) + 1)
        self.assertIs(staged["festivals"][-1]["showOnMap"], False)

    def test_absent_independent_recheck_and_existing_duplicate_are_held(self):
        candidate = private_proposal(TITLE, SITE, DATES, DAY)
        cal, hist, patch_data = fixtures()
        patch_data["additions"] = [candidate]
        patch_data["updates"] = []
        attempts = []
        absent = collect_registered_directory_sources(
            patch_data, set(), DAY,
            directory_fetch=lambda url: attempts.append(url) or
                                     "<h1>Different Event</h1>",
            organizer_fetch=lambda url: self.fail(
                "No website request without independent link"))
        self.assertEqual(attempts, [DIRECTORY])
        self.assertFalse(absent)
        staged, held = stage(
            cal, hist, patch_data, absent, DAY,
            published_calendar=cal, published_history=hist)
        self.assertNotIn(candidate["slug"], [
            row["slug"] for row in staged["festivals"]])
        self.assertEqual(len(held["held"]), 1)
        duplicate_cal = deepcopy(cal)
        duplicate_cal["festivals"][3].update(
            officialSite=SITE, startDate=DATES[0], endDate=DATES[1])
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            trusted = collect_registered_directory_sources(
                patch_data, set(), DAY,
                directory_fetch=lambda _: ENTRY,
                organizer_fetch=lambda _: OFFICIAL)
        _, rejected = stage(
            cal, hist, patch_data, trusted, DAY,
            published_calendar=duplicate_cal, published_history=hist)
        self.assertEqual(rejected["accepted_additions"], [])
        self.assertTrue(rejected["held"])

    def test_forged_site_cannot_be_dereferenced_by_publisher_collector(self):
        candidate = private_proposal(TITLE, SITE, DATES, DAY)
        candidate["officialSite"] = "https://127.0.0.1/"
        patch_data = {"additions": [candidate]}
        sources = collect_registered_directory_sources(
            patch_data, set(), DAY,
            directory_fetch=lambda _: self.fail("Untrusted proposal"),
            organizer_fetch=lambda _: self.fail("Untrusted organizer"))
        self.assertEqual(sources, {})


    def test_private_j_plus_one_handoff_wont_trust_report_or_unknown_source(self):
        source = {
            "dossier_id": "national-testing-dossier",
            "title": TITLE, "year": 2027, "url": SITE,
            "kind": "CURATED_PRIMARY_CANDIDATE",
        }
        state = {
            "schema": "grossesondes.source-watch.v1",
            "national_generic_primary_date_observations_private": {
                SITE: {"digest": _digest(
                    source, *DATES, "SOURCE_PAGE"),
                    "firstSeen": "2026-11-20",
                    "lastSeen": DAY, "lastChecked": DAY, "stable": True}
            },
        }
        queue = {
            "schema": "grossesondes.national-festival-discovery-private.v1",
            "as_of": DAY, "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
            "dossiers": [{
                "id": source["dossier_id"],
                "name_hint": "Festibarock'in", "edition_year_hint": 2027,
                "publication_authorized": False, "safe_to_publish": False,
                "sources": [{
                    "url": SITE, "discovered_via": SITE,
                    "kind": "CURATED_PRIMARY_CANDIDATE",
                    "firstSeen": "2026-11-20", "lastSeen": DAY,
                    "publication_authorized": False,
                }],
            }],
        }
        report = {
            "schema": PRIVATE_REVIEW_SCHEMA, "as_of": DAY,
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False, "publications": 0,
            "rows": [{
                "dossier_id": source["dossier_id"],
                "status": "TWO_DAY_GENERIC_PRIMARY_DATES_RECHECKED_PRIVATE",
                "two_day_dates": True, "start_date_hint": DATES[0],
                "end_date_hint": DATES[1], "date_source_mode": "SOURCE_PAGE",
                "publication_authorized": False, "ownership_proven": False,
            }],
        }
        catalog = {"schema": 1, "festivals": []}
        fetch = lambda url: (self.assertEqual(url, DIRECTORY) or ENTRY)
        result = stable_directory_proposals(
            state, queue, catalog, report, DAY, directory_fetch=fetch)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["officialSite"], SITE)
        self.assertFalse(result[0]["showOnMap"])

        negative = [
            lambda st, qu, rp: st[
                "national_generic_primary_date_observations_private"][SITE].update(
                    stable=False),
            lambda st, qu, rp: st[
                "national_generic_primary_date_observations_private"][SITE].update(
                    digest="0"*64),
            lambda st, qu, rp: qu["dossiers"][0]["sources"][0].update(
                kind="PRESS_ARTICLE_DATE_CLAIM_REVIEW"),
            lambda st, qu, rp: rp["rows"][0].update(
                start_date_hint="2027-06-24"),
            lambda st, qu, rp: rp["rows"][0].update(
                publication_authorized=True),
        ]
        for mutation in negative:
            with self.subTest(mutation=mutation):
                st, qu, rp = (deepcopy(state), deepcopy(queue),
                              deepcopy(report))
                mutation(st, qu, rp)
                self.assertEqual(stable_directory_proposals(
                    st, qu, catalog, rp, DAY,
                    directory_fetch=fetch), [])


if __name__ == "__main__":
    main()
