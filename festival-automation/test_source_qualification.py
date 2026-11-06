"""Qualification remains a private editorial dossier even on matching sources."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from source_qualification import (assess_candidate, choose_checks, classify,
                                  clean_url, matches_date, matches_slash_date_range, qualify,
                                  organizer_links, organizer_aliases, with_curated_leads)


def lead(slug="in-your-face-6-2026", name="In Your Face #6",
         start="2026-11-06", urls=None, end=None, organizer=None):
    return {
        "slug": slug, "name": name, "start_date": start,
        "end_date": end or start,
        "organizer": organizer,
        "official_status": "NOT_VERIFIED", "allowed_to_publish": False,
        "candidate_urls": urls if urls is not None else [
            "https://www.helloasso.com/associations/in-your-face/evenements/in-your-face-6",
            "https://zinor.fr/concerts/in-your-face-6/"],
    }


def report(leads):
    return {"schema": "grossesondes.source-watch-report.v1",
            "date": "2026-11-04",
            "source_reference_leads_review_only": leads}


class QualificationTests(unittest.TestCase):
    def test_ticketing_page_matching_name_and_day_never_verifies_organizer(self):
        row = lead()
        html = "<h1>In Your Face #6</h1><p>Vendredi 6 et samedi 7 novembre 2026 à 19h</p>"
        result = assess_candidate(row, row["candidate_urls"][0], "2026-11-04",
                                  html=html)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["role"], "TICKETING")
        self.assertEqual(result["association_account_hint_unverified"], "in-your-face")
        self.assertTrue(result["date_match"])
        self.assertTrue(result["name_match"])
        self.assertFalse(result["official_site_authorized"])
        self.assertFalse(result["publication_authorized"])
        self.assertNotIn("officialSite", result)
        self.assertNotIn("ticketAvailability", result)

    def test_venue_municipality_and_social_remain_review_only(self):
        row = lead()
        html = "<h1>In Your Face #6</h1><p>6 novembre 2026 à la salle</p>"
        urls = [
            ("https://zinor.fr/concerts/in-your-face-6/", "VENUE"),
            ("https://www.pevelecarembault.fr/agenda/fest", "INSTITUTION"),
            ("https://www.facebook.com/festivallantredulion/", "SOCIAL"),
        ]
        for url, role in urls:
            with self.subTest(url=url):
                result = assess_candidate(row, url, "2026-11-04", html=html)
                self.assertEqual(result["status"], "REVIEW_REQUIRED")
                self.assertEqual(result["role"], role)
                self.assertFalse(result["official_site_authorized"])

    def test_false_name_wrong_year_or_mismatched_dates_block_qualification(self):
        row = lead()
        for html in (
            "<h1>In Your Face #7</h1><p>6 novembre 2026, ouverture 18h</p>",
            "<h1>In Your Face #60</h1><p>6 novembre 2026, ouverture 18h</p>",
            "<h1>In Your Face #6</h1><p>6 novembre 2025, ouverture 18h</p>",
            "<h1>In Your Face #6</h1><p>7 novembre 2026, ouverture 18h</p>",
            "<script>In Your Face #6, 6 novembre 2026</script>"
            "<main>Visitez notre programme complet depuis un navigateur</main>",
        ):
            with self.subTest(html=html):
                result = assess_candidate(row, row["candidate_urls"][0],
                                          "2026-11-04", html=html)
                self.assertEqual(result["status"], "NOT_VERIFIED")
                self.assertFalse(result["publication_authorized"])

    def test_municipal_organizer_link_is_private_lead_not_ownership_proof(self):
        row = lead(
            "festival-de-noel-xxxiv-2026", "Festival de Noël # XXXIV",
            "2026-12-11",
            ["https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv"],
            organizer="Association EXECUTION Mgt")
        html = (
            "<h1>Festival de Noël # XXXIV</h1>"
            "<p>Concert du vendredi 11 décembre 2026 à Limoges</p>"
            "<a href='https://execution-mgt.fr/'>Proposé par Execution MGT</a>"
            "<a href='https://www.helloasso.com/associations/execution'>Billets</a>"
            "<a href='https://execution-mgt.fr.evil.fr/'>Lien non fiable</a>"
        )
        found = assess_candidate(row, row["candidate_urls"][0],
                                 "2026-11-05", html=html)
        self.assertEqual(found["role"], "INSTITUTION")
        self.assertEqual(found["status"], "REVIEW_REQUIRED")
        self.assertEqual(found["organizer_links_review_only"],
                         ["https://execution-mgt.fr/"])
        self.assertFalse(found["official_site_authorized"])
        self.assertFalse(found["publication_authorized"])
        self.assertNotIn("officialSite", found)
        self.assertEqual(classify("https://execution-mgt.fr/"),
                         "ORGANIZER_CANDIDATE")

    def test_organizer_link_needs_matching_label_and_safe_domain(self):
        html = (
            "<h1>Festival de Noël # XXXIV</h1>"
            "<a href='https://bad.fr/'>Proposé par un autre organisateur</a>"
            "<a href='https://example.test/'>Proposé par Execution MGT</a>"
            "<a href='http://execution-mgt.fr/'>Proposé par Execution MGT</a>"
            "<a href='https://www.facebook.com/execution/'>Proposé par Execution MGT</a>"
        )
        self.assertEqual(organizer_links(html,
            "https://sortir.limoges.fr/agenda/example",
            "Association EXECUTION Mgt"), [])
        self.assertEqual(organizer_links(html,
            "https://sortir.limoges.fr/agenda/example",
            None), [])

    def test_unknown_domain_from_matching_municipality_is_private_lead(self):
        row = lead("dawn-metal-festival-2026", "Dawn Metal Festival",
                   "2026-11-14", ["https://www.phalempin.fr/agenda/dawn"],
                   organizer="Association Le Refuge 59")
        html = (
            "<h1>Dawn Metal Festival</h1><p>14 novembre 2026 à Phalempin</p>"
            "<a href='https://refuge59.fr/'>Organisateur : Le Refuge 59</a>"
            "<a href='https://www.facebook.com/Refuge59'>Organisateur : Le Refuge 59</a>"
            "<a href='https://www.helloasso.com/associations/le-refuge-59'>"
            "Organisateur : Le Refuge 59</a>"
        )
        found = assess_candidate(row, row["candidate_urls"][0], "2026-11-05",
                                 html=html)
        self.assertEqual(found["status"], "REVIEW_REQUIRED")
        self.assertEqual(classify("https://refuge59.fr/"), "UNKNOWN")
        self.assertEqual(found["organizer_links_review_only"],
                         ["https://refuge59.fr/"])
        self.assertFalse(found["publication_authorized"])
        self.assertFalse(found["official_site_authorized"])
        self.assertNotIn("officialSite", found)

    def test_rejects_unverified_edition_and_invisible_organizer_links(self):
        row = lead("dawn-metal-festival-2026", "Dawn Metal Festival",
                   "2026-11-14", ["https://www.phalempin.fr/agenda/dawn"],
                   organizer="Association Le Refuge 59")
        link = "<a href='https://refuge59.fr/'>Organisateur : Le Refuge 59</a>"
        html = ("<h1>Dawn Metal Festival</h1><p>15 novembre 2026</p>"
                + link)
        found = assess_candidate(row, row["candidate_urls"][0], "2026-11-05",
                                 html=html)
        self.assertEqual(found["status"], "NOT_VERIFIED")
        self.assertNotIn("organizer_links_review_only", found)
        html = (
            "<h1>Dawn Metal Festival</h1><p>14 novembre 2026</p>"
            "<noscript>" + link + "</noscript>"
            "<template>" + link + "</template>"
            "<a hidden href='https://refuge59.fr/'>Organisateur : Le Refuge 59</a>"
            "<a aria-hidden='true' href='https://refuge59.fr/'>"
            "Organisateur : Le Refuge 59</a>"
            "<a style='display:none' href='https://refuge59.fr/'>"
            "Organisateur : Le Refuge 59</a>"
        )
        found = assess_candidate(row, row["candidate_urls"][0], "2026-11-05",
                                 html=html)
        self.assertEqual(found["status"], "REVIEW_REQUIRED")
        self.assertEqual(found["organizer_links_review_only"], [])

    def test_cross_domain_organizer_candidate_is_not_the_venue_domain(self):
        html = (
            "<h1>In Your Face #6</h1><p>6 novembre 2026</p>"
            "<a href='https://zinor.fr/salle'>Organisateur : In Your Face</a>"
            "<a href='https://www.zinor.fr/info'>Organisateur : In Your Face</a>"
            "<a href='https://festivalin-your-face.example.org/'>"
            "Organisateur : In Your Face</a>"
            "<a href='https://artist-photos.fr/'>Organisateur : In Your Face</a>"
        )
        found = assess_candidate(lead(organizer="In Your Face"),
                                 "https://zinor.fr/concerts/in-your-face-6/",
                                 "2026-11-05", html=html)
        self.assertEqual(found["organizer_links_review_only"],
                         ["https://festivalin-your-face.example.org/",
                          "https://artist-photos.fr/"])
        self.assertFalse(found["official_site_authorized"])

    def test_new_organizer_link_metadata_remains_link_only(self):
        row = lead("dawn-metal-festival-2026", "Dawn Metal Festival",
                   "2026-11-14", ["https://www.phalempin.fr/agenda/dawn"],
                   organizer="Association Le Refuge 59")
        info = report([row])
        info["date"] = "2026-11-05"
        state = {}
        qualify(info, state, limit=1, fetch=lambda _:
                "<h1>Dawn Metal Festival</h1><p>14 novembre 2026</p>"
                "<a href='https://refuge59.fr/'>Organisateur : Le Refuge 59</a>")
        leads = info["organizer_domain_leads_review_only"]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["candidate_role"], "UNKNOWN")
        self.assertEqual(leads[0]["source_role"], "INSTITUTION")
        self.assertIs(leads[0]["link_only"], True)
        self.assertIs(leads[0]["publication_authorized"], False)
        self.assertNotIn("officialSite", str(info))
        self.assertNotIn("officialSite", str(state))

    def test_primary_association_name_before_parenthesis_is_exact_alias(self):
        aliases = organizer_aliases("Association Le Refuge (Le Refuge 59)")
        self.assertIn("le refuge", aliases)
        self.assertIn("le refuge 59", aliases)
        source = "https://www.phalempin.fr/agenda/dawn"
        html = (
            "<p>Organisateur : "
            "<a href='https://refuge59.fr/'>Le Refuge</a></p>"
        )
        self.assertEqual(
            organizer_links(html, source,
                            "Association Le Refuge (Le Refuge 59)"),
            ["https://refuge59.fr/"])
        self.assertEqual(
            organizer_links(html.replace(">Le Refuge</a>", ">Le Refuge International</a>"),
                            source, "Association Le Refuge (Le Refuge 59)"), [])
        # The bare legal name remains unchanged without parenthetical variants.
        self.assertEqual(organizer_aliases("Association Le Refuge"),
                         ["le refuge"])

    def test_parenthesized_association_name_matches_explicit_alias_only(self):
        row = lead("dawn-metal-festival-2026", "Dawn Metal Festival",
                   "2026-11-14", ["https://www.phalempin.fr/agenda/dawn"],
                   organizer="Association Le Refuge (Le Refuge 59)")
        html = (
            "<h1>Dawn Metal Festival</h1><p>14 novembre 2026</p>"
            "<a href='https://refuge59.fr/'>Organisateur : Le Refuge 59</a>"
        )
        result = assess_candidate(row, row["candidate_urls"][0],
                                  "2026-11-05", html=html)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["organizer_links_review_only"],
                         ["https://refuge59.fr/"])
        self.assertFalse(result["official_site_authorized"])
        self.assertFalse(result["publication_authorized"])
        self.assertNotIn("officialSite", result)

    def test_attribution_immediately_before_link_in_same_visible_block(self):
        row = lead("dawn-metal-festival-2026", "Dawn Metal Festival",
                   "2026-11-14", ["https://www.phalempin.fr/agenda/dawn"],
                   organizer="Association Le Refuge (Le Refuge 59)")
        source = row["candidate_urls"][0]
        for html in (
            "<p>Organisateur : <a href='https://refuge59.fr/'>Le Refuge 59</a></p>",
            "<div><strong>Proposé par : </strong>"
            "<a href='https://refuge59.fr/'>Le Refuge 59</a></div>",
            "<dl><dt>Organisateur :</dt><dd>"
            "<a href='https://refuge59.fr/'>Le Refuge 59</a></dd></dl>",
        ):
            with self.subTest(html=html):
                self.assertEqual(organizer_links(html, source, row["organizer"]),
                                 ["https://refuge59.fr/"])

    def test_unrelated_block_or_other_organizer_never_promotes_a_link(self):
        source = "https://www.phalempin.fr/agenda/dawn"
        org = "Association Le Refuge (Le Refuge 59)"
        html_samples = (
            "<p>Organisateur :</p><p><a href='https://refuge59.fr/'>"
            "Le Refuge 59</a></p>",
            "<p>Organisateur : une autre association "
            "<a href='https://refuge59.fr/'>Le Refuge 59</a></p>",
            "<p>Organisateur : <a href='https://wrong.fr/'>Autre Association"
            "</a></p>",
            "<p>Proposé par <a href='https://www.helloasso.com/x'>"
            "Le Refuge 59</a></p>",
            "<p>Organisateur : <a href='https://www.facebook.com/refuge59'>"
            "Le Refuge 59</a></p>",
            "<p>Organisateur : <a href='http://refuge59.fr/'>"
            "Le Refuge 59</a></p>",
        )
        for html in html_samples:
            with self.subTest(html=html):
                self.assertEqual(organizer_links(html, source, org), [])

    def test_hidden_parent_containers_cannot_create_organizer_links(self):
        source = "https://www.phalempin.fr/agenda/dawn"
        organizer = "Association Le Refuge (Le Refuge 59)"
        hidden_cases = (
            "<div hidden><p>Organisateur : <a href='https://refuge59.fr/'>"
            "Le Refuge 59</a></p></div>",
            "<div aria-hidden='true'><p>Organisateur : "
            "<a href='https://refuge59.fr/'>Le Refuge 59</a></p></div>",
            "<div style='display: none'><p>Proposé par "
            "<a href='https://refuge59.fr/'>Le Refuge 59</a></p></div>",
            "<noscript><p>Organisateur : "
            "<a href='https://refuge59.fr/'>Le Refuge 59</a></p></noscript>",
        )
        for html in hidden_cases:
            with self.subTest(html=html):
                self.assertEqual(organizer_links(html, source, organizer), [])
        visible = (
            "<section hidden><p>Organisateur : "
            "<a href='https://refuge59.fr/'>Le Refuge 59</a></p></section>"
            "<p>Proposé par : <a href='https://refuge59.fr/'>Le Refuge 59</a></p>"
        )
        self.assertEqual(organizer_links(visible, source, organizer),
                         ["https://refuge59.fr/"])

    def test_source_selection_prefers_primary_pages_only_for_named_organizer(self):
        ticket = "https://www.helloasso.com/associations/le-refuge-59/evenements/dawn"
        venue = "https://zinor.fr/concerts/dawn"
        institution = "https://www.phalempin.fr/agenda/dawn"
        row = lead("dawn-metal-festival-2026", "Dawn Metal Festival",
                   "2026-11-14", [ticket, venue, institution],
                   organizer="Association Le Refuge (Le Refuge 59)")
        selected = choose_checks([row], {}, "2026-11-05", limit=1)
        self.assertEqual(selected[0][1], institution)
        # After the institution has been visited, untouched venue precedes
        # the still-unvisited ticketing page.
        history = {row["slug"]: {
            institution: {"lastChecked": "2026-11-05"}}}
        self.assertEqual(choose_checks([row], history, "2026-11-05", 1)[0][1],
                         venue)
        # Once each URL has been visited, oldest-first fairness remains.
        history[row["slug"]].update({
            venue: {"lastChecked": "2026-11-04"},
            ticket: {"lastChecked": "2026-11-03"}})
        self.assertEqual(choose_checks([row], history, "2026-11-06", 1)[0][1],
                         ticket)
        anonymous = dict(row, organizer=None)
        self.assertEqual(choose_checks([anonymous], {}, "2026-11-05", 1)[0][1],
                         ticket)

    def test_curated_urls_extend_review_only_and_retire_after_certification(self):
        row = lead("festival-de-noel-xxxiv-2026",
                   "Festival de Noël # XXXIV", "2026-12-11",
                   ["https://helloasso.com/associations/execution/noel"])
        curated = {row["slug"]: ["https://execution-mgt.fr/",
                                  "https://sortir.limoges.fr/agenda/festival-de-noel-xxxiv"]}
        copied = with_curated_leads([row], curated)
        self.assertEqual(copied[0]["candidate_urls"], row["candidate_urls"] +
                         curated[row["slug"]])
        self.assertEqual(len(row["candidate_urls"]), 1)
        self.assertFalse(copied[0]["allowed_to_publish"])
        # When the approved site exists, source_leads no longer includes this slug.
        self.assertEqual(with_curated_leads([], curated), [])
        with self.assertRaises(ValueError):
            with_curated_leads([row],
                {row["slug"]: ["https://localhost.local/private"]})

    def test_zinor_short_month_and_original_edition_remain_review_only(self):
        row = lead()
        url = "https://zinor.fr/concerts/in-your-face-6/"
        html = (
            "<article><h1>In your Face #6</h1>"
            "<p>6 Nov 2026 - 18h30 / 2h00</p>"
            "<p>Festival les 6 et 7 novembre 2026 au Zinor.</p>"
            "<p>Vendredi IGNITE CANCER BATS AURORE MEAN SEASON GAME CHANGER DOZE.</p>"
            "<p>Samedi MURPHY'S LAW GRAIL GUARD HARD MIND CLAIMED CHOICE "
            "CALCINE OFFENSIVE CROVERCOPS.</p>"
            "<h3>Organisateur</h3><p>Collectif Icroacoa</p></article>"
        )
        found = assess_candidate(row, url, "2026-11-05", html=html)
        self.assertEqual(found["role"], "VENUE")
        self.assertEqual(found["status"], "REVIEW_REQUIRED")
        self.assertTrue(found["date_match"])
        self.assertTrue(found["name_match"])
        self.assertFalse(found["official_site_authorized"])
        self.assertFalse(found["publication_authorized"])
        self.assertNotIn("officialSite", found)
        self.assertNotIn("ticketAvailability", found)
        # Le Zinor lists its hosting collective, not proof that the
        # collective owns the distinct In Your Face association.
        self.assertEqual(found.get("organizer_links_review_only", []), [])

    def test_wix_shared_domain_only_exact_festival_account_and_path(self):
        real = "https://backinblackasso.wixsite.com/metalfest09/home"
        self.assertEqual(classify(real), "ORGANIZER_CANDIDATE")
        for fake in (
            "https://someother.wixsite.com/metalfest09/home",
            "https://backinblackasso.wixsite.com/otherfestival/home",
            "https://backinblackasso.wixsite.com/metalfest09/home-phishing",
            "https://backinblackasso.wixsite.com.evil.fr/metalfest09/home",
        ):
            self.assertEqual(classify(fake), "UNKNOWN")
        row = lead("metal-fest-09-2026", "Metal Fest 09", "2026-11-06",
                   [real], end="2026-11-07",
                   organizer="Association Back In Black")
        result = assess_candidate(row, real, "2026-11-05",
                    html="<h1>Metal Fest 09</h1><p>6 novembre 2026</p>" +
                         "<p>Festival Back In Black à Saverdun, Ariège.</p>" * 3)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["role"], "ORGANIZER_CANDIDATE")
        self.assertFalse(result["official_site_authorized"])
        self.assertFalse(result["publication_authorized"])

    def test_urgent_curated_sources_are_private_and_do_not_leak_into_publication(self):
        row = lead()
        curated = {
            row["slug"]: [
                "https://zinor.fr/concerts/in-your-face-6/",
                "https://www.vendeebocage.fr/agenda/in-your-face-6-festival/",
            ],
        }
        new = with_curated_leads([row], curated)
        self.assertEqual(new[0]["candidate_urls"][-1], curated[row["slug"]][1])
        self.assertEqual(classify(curated[row["slug"]][1]), "INSTITUTION")
        self.assertFalse(new[0]["allowed_to_publish"])
        self.assertEqual(new[0]["official_status"], "NOT_VERIFIED")
        self.assertEqual(row["candidate_urls"], lead()["candidate_urls"])

    def test_http_403_and_dynamic_content_unknown_not_sold_out(self):
        row = lead()
        url = row["candidate_urls"][0]
        for params in ({"error": "HTTPError"},
                       {"html": "<div>Activez JavaScript</div>"}):
            result = assess_candidate(row, url, "2026-11-04", **params)
            self.assertEqual(result["status"], "NOT_VERIFIED")
            self.assertNotIn("stock", result)
            self.assertNotIn("sold_out", str(result))

    def test_bad_domains_embedded_credentials_ips_and_http_rejected(self):
        row = lead()
        for url in (
            "http://www.helloasso.com/event",
            "https://127.0.0.1/admin",
            "https://localhost.local/a",
            "https://trusted.fr@evil.invalid/data",
            "https://example.test/internal",
            "https://example.fr:4443/data",
        ):
            with self.subTest(url=url):
                self.assertIsNone(clean_url(url))
                self.assertEqual(assess_candidate(
                    row, url, "2026-11-04")["status"], "REJECTED")
        self.assertEqual(classify("https://helloasso.com.evil.fr/events"), "UNKNOWN")

    def test_dates_require_day_month_year_and_allow_punctuation(self):
        self.assertTrue(matches_date("festival 6 et 7 novembre 2026", "2026-11-06"))
        self.assertFalse(matches_date("in your face 6 7 novembre 2026", "2026-11-06"))
        self.assertTrue(matches_date("festival 6 novembre 2026", "2026-11-06"))
        self.assertTrue(matches_date("6 nov 2026", "2026-11-06"))
        self.assertTrue(matches_date("vendredi 6 et samedi 7 nov 2026", "2026-11-06"))
        self.assertFalse(matches_date("in your face 6 7 nov 2026", "2026-11-06"))
        self.assertFalse(matches_date("6 nov 2025", "2026-11-06"))
        self.assertTrue(matches_date("festival 2026 11 06", "2026-11-06"))
        self.assertFalse(matches_date("festival en novembre 2026", "2026-11-06"))
        self.assertFalse(matches_date("festival 6 novembre 2027", "2026-11-06"))

    def test_private_rotation_covers_distinct_editions_and_urls(self):
        first = lead()
        second = lead("festival-de-noel-xxxiv-2026", "Festival de Noël # XXXIV",
                      "2026-12-11", ["https://helloasso.com/a/2"])
        third = lead("xion-metal-night", "Xion Metal Night", "2027-05-22",
                     ["https://helloasso.com/a/3"])
        history = {}
        checked = []
        def mock_fetch(url):
            checked.append(url)
            return "<main>Test avec des sources insuffisantes sur les concerts à venir</main>"
        data = report([first, second, third])
        state = {}
        qualify(data, state, fetch=mock_fetch, limit=2)
        self.assertEqual(len(data["source_qualification_review_only"]), 2)
        self.assertEqual(data["source_qualification_review_required"], 0)
        self.assertEqual(len({r["slug"] for r in
                              data["source_qualification_review_only"]}), 2)
        self.assertEqual(len(checked), 2)
        self.assertEqual(len(state["source_qualification_last_checked"]), 2)
        # The new edition takes priority over revisiting already checked pages.
        data = report([first, second, third])
        qualify(data, state, fetch=mock_fetch, limit=2)
        self.assertIn("xion-metal-night",
                      [r["slug"] for r in data["source_qualification_review_only"]])
        # A second URL for the first edition is examined before its first one
        # is retried; it is never treated as an organizer proof.
        prior_first = [r for r in data["source_qualification_review_only"]
                       if r["slug"] == first["slug"]]
        self.assertEqual(prior_first[0]["url"], first["candidate_urls"][1])

    def test_blocks_duplicate_editions_and_unauthorized_input(self):
        with self.assertRaises(ValueError):
            choose_checks([lead(), lead()], {}, "2026-11-04")
        with self.assertRaises(ValueError):
            choose_checks([{**lead(), "allowed_to_publish": True}],
                          {}, "2026-11-04")
        with self.assertRaises(ValueError):
            choose_checks([lead()], {}, "2026-11-04", limit=100)

    def test_old_edition_is_skipped_not_removed(self):
        historic = lead(start="2026-07-01")
        self.assertEqual(choose_checks([historic], {}, "2026-11-04"), [])

    def test_unvisited_editions_take_priority_over_secondary_urls(self):
        long = lead("rise-fall-festival-8-2026", "Rise & Fall Festival #8",
                    "2026-10-16", ["https://camji.com/evenements/rise-fall",
                                    "https://camji.com/billetterie/other"],
                    end="2026-11-08")
        never = lead("festival-de-noel-xxxiv-2026", "Festival de Noël # XXXIV",
                     "2026-12-11", ["https://helloasso.com/associations/execution/noel"])
        history = {long["slug"]: {
            long["candidate_urls"][0]: {"lastChecked": "2026-11-04"}}}
        first = choose_checks([long, never], history, "2026-11-04", limit=1)
        self.assertEqual(first[0][0]["slug"], never["slug"])
        second = choose_checks([long, never], history, "2026-11-04", limit=2)
        self.assertEqual(second[1][1], long["candidate_urls"][1])
        history[never["slug"]] = {
            never["candidate_urls"][0]: {"lastChecked": "2026-11-04"}}
        history[long["slug"]][long["candidate_urls"][0]] = {
            "lastChecked": "2026-11-03"}
        oldest = choose_checks([long, never], history, "2026-11-04", limit=1)
        self.assertEqual(oldest[0][0]["slug"], long["slug"])

    def test_source_precedes_audit_reference_even_if_url_sorts_later(self):
        row = lead(urls=["https://z-festival.fr/official-edition",
                         "https://a-tickets.fr/ticketing"])
        first = choose_checks([row], {}, "2026-11-04")
        self.assertEqual(first[0][1], row["candidate_urls"][0])
        state = {row["slug"]: {
            row["candidate_urls"][0]: {"lastChecked": "2026-11-04"}}}
        second = choose_checks([row], state, "2026-11-04")
        self.assertEqual(second[0][1], row["candidate_urls"][1])
        state[row["slug"]][row["candidate_urls"][1]] = {
            "lastChecked": "2026-11-03"}
        third = choose_checks([row], state, "2026-11-04")
        self.assertEqual(third[0][1], row["candidate_urls"][1])

    def test_priority_excludes_ended_events_even_if_recent(self):
        past = lead("sidifest-2026", "Sidifest", "2026-10-29",
                    ["https://lebikini.com/2026/10/29/sidifest"])
        active = lead("rise-fall-festival-8-2026", "Rise & Fall Festival #8",
                      "2026-10-16", ["https://camji.com/evenements/rise-and-fall/"],
                      end="2026-11-08")
        future = lead("in-your-face-6-2026", "In Your Face #6",
                      "2026-11-06")
        selected = choose_checks([past, active, future], {}, "2026-11-04", limit=3)
        self.assertEqual([lead["slug"] for lead, _ in selected],
                         ["in-your-face-6-2026", "rise-fall-festival-8-2026"])
        self.assertEqual(choose_checks([active], {}, "2026-11-09"), [])

    def test_imminent_editions_get_priority_without_starving_unvisited(self):
        first = lead("in-your-face-6-2026", "In Your Face #6",
                     "2026-11-06", ["https://zinor.fr/concerts/in-your-face-6/"])
        second = lead("metal-fest-09-2026", "Metal Fest 09",
                      "2026-11-06", ["https://backinblackasso.wixsite.com/metalfest09/home"])
        far = lead("lothbrock-fest-2027", "Lothbrock Fest",
                   "2027-06-05", ["https://saintes-tourisme.fr/some-event"])
        later = lead("charitable-metal-fest-2026", "Charitable Metal Fest",
                     "2026-12-12", ["https://savigny-le-temple.fr/some-event"])
        history = {first["slug"]: {first["candidate_urls"][0]: {
                    "lastChecked": "2026-11-04"}},
                   second["slug"]: {second["candidate_urls"][0]: {
                    "lastChecked": "2026-11-04"}}}
        selected = choose_checks([far, first, later, second], history,
                                 "2026-11-05", limit=3)
        self.assertEqual(
            [item[0]["slug"] for item in selected],
            ["in-your-face-6-2026", "metal-fest-09-2026", "charitable-metal-fest-2026"])
        # Beyond the 48-hour window, normal first-visit fairness returns.
        selected_later = choose_checks([far, first, later, second], history,
                                       "2026-11-09", limit=3)
        self.assertEqual(selected_later[0][0]["slug"], later["slug"])

    def test_wix_slash_range_is_visible_but_never_certifies_official_site(self):
        url = "https://backinblackasso.wixsite.com/metalfest09/home"
        row = lead("metal-fest-09-2026", "Metal Fest 09",
                   "2026-11-06", [url])
        html = "<h1>Metal Fest 09</h1><p>Saverdun - 06/07 NOVEMBRE 2026</p>"
        result = assess_candidate(row, url, "2026-11-05", html=html)
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(result["role"], "ORGANIZER_CANDIDATE")
        self.assertTrue(result["date_match"])
        self.assertFalse(result["official_site_authorized"])
        self.assertFalse(result["publication_authorized"])
        self.assertTrue(matches_slash_date_range(html, "2026-11-07"))
        self.assertFalse(matches_slash_date_range(html, "2026-11-08"))
        hidden = ("<h1>Metal Fest 09</h1><script>06/07 novembre 2026</script>"
                  "<p>Un festival metal a Saverdun</p>")
        self.assertFalse(assess_candidate(row, url, "2026-11-05", html=hidden)["date_match"])
        self.assertFalse(matches_slash_date_range(
            "<p>6 7 novembre 2026</p>", "2026-11-06"))
        self.assertFalse(matches_slash_date_range(
            "<p>06/07 novembre 2027</p>", "2026-11-06"))

    def test_same_day_source_is_not_retried_and_next_url_can_advance(self):
        row = lead(urls=["https://one.example.org/a", "https://two.example.org/b"])
        state = {}
        data = report([row])
        fetched = []
        def fetch(url):
            fetched.append(url)
            return "<h1>In Your Face #6</h1><p>6 novembre 2026</p>"
        qualify(data, state, fetch=fetch, limit=1)
        self.assertEqual(fetched, [row["candidate_urls"][0]])
        again = report([row])
        qualify(again, state, fetch=fetch, limit=1)
        self.assertEqual(fetched, row["candidate_urls"])
        self.assertEqual(again["source_qualification_scheduler_review_only"]
                         ["already_checked_today"], 1)
        self.assertFalse(again["source_qualification_scheduler_review_only"]
                         ["publication_authorized"])
        third = report([row])
        qualify(third, state, fetch=fetch, limit=1)
        self.assertEqual(fetched, row["candidate_urls"])
        self.assertEqual(third["source_qualification_checked"], 0)
        self.assertEqual(third["source_qualification_scheduler_review_only"]
                         ["already_checked_today"], 2)
        self.assertEqual(third["source_qualification_scheduler_review_only"]
                         ["eligible_editions"], 0)
        self.assertFalse(third.get("organizer_domain_leads_review_only"))

    def test_inaccessible_sources_wait_one_extra_day_without_abandonment(self):
        row = lead(urls=["https://www.helloasso.com/a/1"])
        url = row["candidate_urls"][0]
        history = {row["slug"]: {url: {
            "lastChecked": "2026-11-04", "status": "NOT_VERIFIED",
            "reason": "INACCESSIBLE_OR_UNKNOWN"}}}
        skipped = {}
        self.assertEqual(choose_checks([row], history, "2026-11-05",
                                       diagnostics=skipped), [])
        self.assertEqual(skipped["inaccessible_backoff"], 1)
        self.assertEqual(choose_checks([row], history, "2026-11-06"),
                         [(row, url)])

    def test_access_backoff_prefers_other_source_and_preserves_fairness(self):
        unavailable = lead("in-your-face-6-2026", "In Your Face #6",
                           "2026-11-06", ["https://www.helloasso.com/a/1",
                                          "https://zinor.fr/concerts/in-your-face-6/"])
        later = lead("charitable-metal-fest-2026", "Charitable Metal Fest",
                     "2026-12-12", ["https://savigny-le-temple.fr/agenda"])
        only = lead("metal-fest-09-2026", "Metal Fest 09", "2026-11-06",
                    ["https://www.helloasso.com/a/metal"])
        history = {
            unavailable["slug"]: {unavailable["candidate_urls"][0]: {
                "lastChecked": "2026-11-04", "reason": "INACCESSIBLE_OR_UNKNOWN"}},
            only["slug"]: {only["candidate_urls"][0]: {
                "lastChecked": "2026-11-04", "reason": "INACCESSIBLE_OR_UNKNOWN"}},
        }
        stats = {}
        selected = choose_checks([unavailable, only, later], history,
                                 "2026-11-05", limit=3, diagnostics=stats)
        self.assertEqual([r["slug"] for r, _ in selected],
                         ["in-your-face-6-2026", "charitable-metal-fest-2026"])
        self.assertEqual(selected[0][1], unavailable["candidate_urls"][1])
        self.assertEqual(stats["inaccessible_backoff"], 2)
        self.assertEqual(stats["eligible_editions"], 2)

    def test_legacy_non_inaccessible_and_future_state_handling(self):
        row = lead(urls=["https://www.helloasso.com/a/legacy"])
        url = row["candidate_urls"][0]
        history = {row["slug"]: {url: {"lastChecked": "2026-11-04",
                                        "reason": "INSUFFICIENT_EDITION_MATCH"}}}
        self.assertEqual(choose_checks([row], history, "2026-11-05"),
                         [(row, url)])
        history[row["slug"]][url]["lastChecked"] = "2026-11-08"
        with self.assertRaises(ValueError):
            choose_checks([row], history, "2026-11-05")

    def test_metal_fest_wix_groups_are_corroboration_not_lineup_approval(self):
        url = "https://backinblackasso.wixsite.com/metalfest09/groupes"
        row = {**lead("metal-fest-09-2026", "Metal Fest 09",
                      "2026-11-06", [url]),
               "lineup": ["Noveria", "Point Mort", "Death Awaits",
                          "My Own Private Alaska", "Tarchon Fist",
                          "Ashed Winter", "Faith In Agony",
                          "Severed Soul", "Seven Metal Sins"]}
        html = (
            "<h1>Metal Fest 09</h1><p>06/07 novembre 2026</p>"
            "<h2>NOVERIA</h2><h2>POINT MORT</h2>"
            "<h2>DEATH AWAITS</h2><h2>MY OWN PRIVATE ALASKA</h2>"
            "<h2>TARCHON FIST</h2><h2>ASHED WNTER</h2>"
            "<h2>FAITH IN AGONY</h2><h2>SEVERED SOUL</h2>"
            "<h2>SEVEN METAL SINS</h2>"
        )
        found = assess_candidate(row, url, "2026-11-05", html=html)
        self.assertEqual(classify(url), "ORGANIZER_CANDIDATE")
        self.assertEqual(found["status"], "REVIEW_REQUIRED")
        self.assertEqual(len(found["roster_names_mentioned_review_only"]), 8)
        self.assertEqual(found["roster_names_unmentioned_review_only"],
                         ["Ashed Winter"])
        self.assertIs(found["roster_evidence_is_complete"], False)
        self.assertIs(found["artist_update_authorized"], False)
        self.assertIs(found["publication_authorized"], False)
        self.assertNotIn("lineup", found)
        self.assertNotIn("ticketAvailability", found)
        self.assertNotIn("officialSite", found)

    def test_partial_or_wrong_date_roster_does_not_become_evidence(self):
        url = "https://backinblackasso.wixsite.com/metalfest09/groupes"
        row = {**lead("metal-fest-09-2026", "Metal Fest 09",
                      "2026-11-06", [url]), "lineup": ["Noveria", "Point Mort"]}
        wrong = assess_candidate(row, url, "2026-11-05", html=(
            "<h1>Metal Fest 09</h1><p>06/07 novembre 2025</p>"
            "<p>Noveria, Point Mort, Tarchon Fist</p>"))
        self.assertEqual(wrong["status"], "NOT_VERIFIED")
        self.assertNotIn("roster_names_mentioned_review_only", wrong)
        partial = assess_candidate(row, url, "2026-11-05", html=(
            "<h1>Metal Fest 09</h1><p>06/07 novembre 2026</p>"
            "<p>Noveria — autres annonces bientôt</p>"))
        self.assertEqual(partial["roster_names_mentioned_review_only"], ["Noveria"])
        self.assertEqual(partial["roster_names_unmentioned_review_only"], ["Point Mort"])
        self.assertIs(partial["artist_update_authorized"], False)
        platform = assess_candidate(
            row, "https://www.helloasso.com/associations/back-in-black/evenements/metal-fest-09-2",
            "2026-11-05", html=(
                "<h1>Metal Fest 09</h1><p>06/07 novembre 2026 "
                "Noveria, Point Mort</p>"))
        self.assertNotIn("roster_names_mentioned_review_only", platform)

    def test_wix_groups_path_exact_other_accounts_unknown(self):
        self.assertEqual(classify(
            "https://backinblackasso.wixsite.com/metalfest09/groupes"),
            "ORGANIZER_CANDIDATE")
        for bad in (
            "https://evil.wixsite.com/metalfest09/groupes",
            "https://backinblackasso.wixsite.com/otherfest/groupes",
            "https://backinblackasso.wixsite.com/metalfest09/groupes-copy",
        ):
            self.assertEqual(classify(bad), "UNKNOWN")

    def test_sanitizes_query_tokens_and_deduplicates_candidates(self):
        url = "https://www.helloasso.com/a/1?secret=abc#purchase"
        row = lead(urls=[url, "https://www.helloasso.com/a/1"])
        selected = choose_checks([row], {}, "2026-11-04")
        self.assertEqual(selected[0][1], "https://www.helloasso.com/a/1")
        data = report([row])
        state = {}
        qualify(data, state, fetch=lambda u: "<main>Evenement public valide ici</main>")
        self.assertNotIn("secret", str(state))
        self.assertNotIn("secret", str(data["source_qualification_review_only"]))


if __name__ == "__main__":
    unittest.main()
