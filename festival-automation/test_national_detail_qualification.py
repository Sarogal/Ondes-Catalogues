"""Offline tests for bounded next-day live-index festival qualification."""
from copy import deepcopy
import unittest

from national_discovery_queue import build_queue
from national_detail_qualification import scan, build_review, _seen_again

TODAY = "2026-11-06"
YESTERDAY = "2026-11-05"
ORIGIN = "https://agenda.montpellier.fr/"
URL = "https://agenda.montpellier.fr/evenement/metal-des-garrigues-2027"
TITLE = "Festival Metal des Garrigues 2027"
HTML_INDEX = '<main><a href="/evenement/metal-des-garrigues-2027">Festival Metal des Garrigues 2027</a></main>'
HTML_DETAIL = '<main><h1>Festival Metal des Garrigues</h1><p>Les 4 et 5 juin 2027, au coeur de Montpellier ! Bienvenue au festival de musique.</p></main>'


class NationalDetailQualificationTests(unittest.TestCase):
    def data(self, first=YESTERDAY, title=TITLE, url=URL, year=None):
        state = {
            "schema": "grossesondes.source-watch.v1",
            "regional_festival_candidates_review_only": {
                url: {
                    "candidate_url": url, "title": title,
                    "source_index": ORIGIN, "region": "Occitanie",
                    "firstSeen": first, "lastSeen": TODAY,
                    "status": "UNVERIFIED_THEME_LINK",
                    "discovery_signal": "THEMATIC_NAME_ONLY",
                    "historical_name_slug": None,
                    "publication_authorized": False,
                },
            },
            "institutional_agenda_candidate_pages": {},
            "secondary_source_candidates_private": {},
        }
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": TODAY, "source_reference_leads_review_only": []}
        queue = build_queue(state, report, [], TODAY)
        return state, queue

    def test_municipal_accessible_event_link_reaches_private_detail_probe(self):
        """Regional aria-labelled discovery must survive independent revalidation."""
        origin = "https://www.angers.fr/actualites-sorties/agenda/index.html"
        url = "https://www.angers.fr/actualites-sorties/agenda/metal-fest-des-rives-2027"
        title = "Metal Fest des Rives 2027"
        html = (
            '<article><a href="/actualites-sorties/agenda/metal-fest-des-rives-2027" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest des Rives 2027">'
            'En savoir plus</a></article>'
        )
        state, _ = self.data(title=title, url=url)
        row = state["regional_festival_candidates_review_only"][url]
        row["source_index"] = origin
        row["region"] = "Pays de la Loire"
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": TODAY, "source_reference_leads_review_only": []}
        queue = build_queue(state, report, [], TODAY)
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        visits = []

        def fetch(target):
            visits.append(target)
            return (html if target == origin
                    else "<main><h1>Metal Fest des Rives 2027</h1>"
                         "<p>Une édition 2027 annoncée.</p></main>")

        outcome = scan(state, queue, TODAY, fetch=fetch)
        self.assertEqual(visits, [origin, url])
        self.assertEqual(outcome[0]["status"], "NAME_YEAR_VISIBLE_REVIEW_ONLY")
        review = build_review(state, queue, TODAY)
        self.assertEqual(review["observations_count"], 1)
        self.assertFalse(review["observations"][0]["publication_authorized"])
        self.assertFalse(review["observations"][0]["date_claim_verified"])
        self.assertEqual(review["publications"], 0)

    def test_municipal_accessible_label_keeps_exact_live_link_safeguards(self):
        origin = "https://www.angers.fr/actualites-sorties/agenda/index.html"
        url = "https://www.angers.fr/actualites-sorties/agenda/metal-fest-des-rives-2027"
        source = {"title": "Metal Fest des Rives 2027",
                  "index_url": origin, "url": url, "year": 2027}
        prefix = ('<a href="/actualites-sorties/agenda/metal-fest-des-rives-2027" '
                  'aria-label="Plus d’information sur l’évènement : '
                  'Metal Fest des Rives 2027">')
        valid = prefix + "En savoir plus</a>"
        self.assertTrue(_seen_again(valid, source))
        self.assertTrue(_seen_again(
            '<a href="/actualites-sorties/agenda/metal-fest-des-rives-2027" '
            'title="Plus d’information sur l’évènement : Metal Fest des Rives 2027">'
            'En savoir plus</a>', source))
        unsafe = (
            prefix + "Concert de jazz 2027</a>",  # specific visible title wins
            "<div hidden>" + valid + "</div>",
            '<div aria-hidden="true">' + valid + "</div>",
            "<script>" + valid + "</script>",
            valid.replace("/actualites-sorties/agenda/metal-fest-des-rives-2027",
                          "/actualites-sorties/agenda/metal-fest-des-rives-2028"),
            valid.replace('/actualites-sorties/agenda/metal-fest-des-rives-2027',
                          'https://www.angers.fr.evil.example/festival'),
            valid.replace('Plus d’information sur l’évènement : ',
                          'Voir cet évènement : '),
            valid.replace('Metal Fest des Rives 2027', 'Metal Fest des Rives 2028'),
            '<a href="/actualites-sorties/agenda/metal-fest-des-rives-2027">'
            'En savoir plus</a>',
        )
        for html in unsafe:
            with self.subTest(html=html):
                self.assertFalse(_seen_again(html, source))

    def test_next_day_fresh_index_then_one_detail_and_private_observation(self):
        state, queue = self.data()
        visited = []
        def fetch(url):
            visited.append(url)
            return {ORIGIN: HTML_INDEX, URL: HTML_DETAIL}[url]
        results = scan(state, queue, TODAY, fetch=fetch)
        self.assertEqual(visited, [ORIGIN, URL])
        self.assertEqual(results[0]["status"], "NAME_YEAR_VISIBLE_REVIEW_ONLY")
        proof = build_review(state, queue, TODAY)
        self.assertEqual(proof["observations_count"], 1)
        self.assertEqual(proof["name_year_visible_count"], 1)
        self.assertFalse(proof["observations"][0]["date_claim_verified"])
        self.assertFalse(proof["observations"][0]["organizer_verified"])
        self.assertFalse(proof["observations"][0]["independence_verified"])
        self.assertFalse(proof["publication_authorized"])
        self.assertEqual(proof["publications"], 0)
        self.assertEqual(scan(state, queue, TODAY, fetch=fetch), [])
        self.assertEqual(visited, [ORIGIN, URL])

    def test_first_seen_today_no_fetch_or_verified_fields(self):
        state, queue = self.data(first=TODAY)
        visited = []
        self.assertEqual(scan(state, queue, TODAY, fetch=lambda u: visited.append(u)), [])
        self.assertEqual(visited, [])
        self.assertEqual(build_review(state, queue, TODAY)["observations_count"], 0)

    def test_missing_live_link_never_fetches_detail_and_reschedules(self):
        state, queue = self.data()
        visited = []
        results = scan(state, queue, TODAY,
                       fetch=lambda u: (visited.append(u), "<h2>Aucun lien</h2>")[1])
        self.assertEqual(visited, [ORIGIN])
        self.assertEqual(results[0]["status"], "INDEX_LINK_NOT_FOUND")
        self.assertNotIn(URL, state["national_detail_observations_private"])

    def test_live_link_change_does_not_redirect_to_new_unapproved_url(self):
        state, queue = self.data()
        visited = []
        spoof = HTML_INDEX.replace("metal-des-garrigues-2027",
                                  "metal-des-garrigues-2027-edit")
        scan(state, queue, TODAY, fetch=lambda u: (visited.append(u), spoof)[1])
        self.assertEqual(visited, [ORIGIN])

    def test_name_and_year_must_be_visible_and_nearby(self):
        state, queue = self.data()
        html = ('<h1>Festival Metal des Garrigues</h1><p>Ancienne édition 2026.</p>'
                + '<div>' + ('Texte sans lien. ' * 50) + '2027</div>')
        scan(state, queue, TODAY,
             fetch=lambda url: HTML_INDEX if url == ORIGIN else html)
        proof = build_review(state, queue, TODAY)
        self.assertEqual(proof["observations_count"], 1)
        self.assertEqual(proof["name_year_visible_count"], 0)
        self.assertEqual(proof["qualified_source_count"], 0)

    def test_script_only_year_is_not_visible_evidence(self):
        state, queue = self.data()
        html = '<h1>Festival Metal des Garrigues</h1><script>2027</script>' + (
            "<p>La programmation de cette année reste à annoncer.</p>")
        scan(state, queue, TODAY,
             fetch=lambda url: HTML_INDEX if url == ORIGIN else html)
        self.assertEqual(build_review(state, queue, TODAY)["name_year_visible_count"], 0)

    def test_failed_detail_fetch_invalidates_previous_positive_observation(self):
        state, queue = self.data()
        scan(state, queue, TODAY,
             fetch=lambda u: HTML_INDEX if u == ORIGIN else HTML_DETAIL)
        self.assertEqual(build_review(state, queue, TODAY)["observations_count"], 1)
        # New day: the next attempt fails and old positive evidence must vanish.
        next_day = "2026-11-07"
        state["regional_festival_candidates_review_only"][URL]["lastSeen"] = next_day
        queue_next = build_queue(state, {"schema": "grossesondes.source-watch-report.v1",
                                        "date": next_day,
                                        "source_reference_leads_review_only": []}, [], next_day)
        def fail(url):
            if url == ORIGIN:
                return HTML_INDEX
            raise OSError("detail inaccessible")
        result = scan(state, queue_next, next_day, fetch=fail)
        self.assertEqual(result[0]["status"], "DETAIL_UNAVAILABLE")
        self.assertEqual(build_review(state, queue_next, next_day)["observations_count"], 0)

    def test_invalid_private_row_does_not_authorize_fetch(self):
        state, queue = self.data()
        state["regional_festival_candidates_review_only"][URL]["publication_authorized"] = True
        visited = []
        scan(state, queue, TODAY, fetch=lambda url: visited.append(url))
        self.assertEqual(visited, [])

    def test_forged_queue_external_url_never_authorizes_fetch(self):
        state, queue = self.data()
        queue["dossiers"][0]["sources"][0]["url"] = "https://evil.example/festival2027"
        visited = []
        scan(state, queue, TODAY, fetch=lambda url: visited.append(url))
        self.assertEqual(visited, [])

    def test_same_domain_lookalike_link_is_not_valid(self):
        state, queue = self.data()
        spoof = HTML_INDEX.replace('/evenement/', 'https://agenda.montpellier.fr.evil.example/')
        visited = []
        scan(state, queue, TODAY, fetch=lambda url: (visited.append(url), spoof)[1])
        self.assertEqual(visited, [ORIGIN])

    def test_yearless_dossier_not_promoted_to_festival_edition(self):
        state, queue = self.data(title="Festival Rock des Garrigues")
        visited = []
        scan(state, queue, TODAY, fetch=lambda url: visited.append(url))
        self.assertEqual(visited, [])

    def test_cap_one_pair_even_when_multiple_valid_festivals(self):
        state, queue = self.data()
        url2 = "https://agenda.montpellier.fr/evenement/rock-doccitanie-2027"
        title2 = "Festival Rock Occitanie 2027"
        state["regional_festival_candidates_review_only"][url2] = dict(
            state["regional_festival_candidates_review_only"][URL],
            candidate_url=url2, title=title2)
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": TODAY, "source_reference_leads_review_only": []}
        queue = build_queue(state, report, [], TODAY)
        visited = []
        scan(state, queue, TODAY,
             fetch=lambda u: (visited.append(u),
                              HTML_INDEX if u == ORIGIN else HTML_DETAIL)[1])
        self.assertLessEqual(len(visited), 2)
        self.assertEqual(len(state["national_detail_last_attempted_private"]), 1)

    def test_unknown_index_failure_has_no_old_positive_status(self):
        state, queue = self.data()
        def broken(_):
            raise OSError("rate limited")
        result = scan(state, queue, TODAY, fetch=broken)
        self.assertEqual(result[0]["status"], "INDEX_UNAVAILABLE")
        self.assertEqual(build_review(state, queue, TODAY)["observations_count"], 0)


if __name__ == "__main__":
    unittest.main()
