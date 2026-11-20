"""No-network regressions for official visible concert evidence.

The HTML signal is private, untrusted REVIEW evidence only. Neither a CSS
genre badge nor a matching headline may trigger a publisher approval.
"""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import official_html_evidence as html
import structured_first_party_preflight as preflight

SOURCE = {"name": "La Rayonne", "city": "Villeurbanne",
          "department": "69", "url": "https://larayonne.org/"}
URL = "https://larayonne.org/evenement/eisbrecher/"
CANDIDATE = {
    "source": "agenda_officiel_structuré", "sourceUrl": URL,
    "sourcePage": URL, "candidateId": "synthetic-eisbrecher",
    "name": "EISBRECHER", "leadArtist": "EISBRECHER",
    "venue": "La Rayonne", "city": "Villeurbanne", "department": "69",
    "date": "2027-09-18", "reviewBucket": "genre_unknown",
    "publicationAllowed": False, "reviewRequired": True,
}
PAGE = """<html><body>
  <header><nav><p>Metal</p><p>Rock</p></nav></header>
  <main><h1>EISBRECHER</h1>
    <strong>samedi 18 septembre 2027</strong>
    <p>à partir de 19h</p>
    La Rayonne
    <p>7 rue Henri Legay</p><p>69100 Villeurbanne</p>
    <h3>Sounds Like Hell Productions présente</h3>
    <h4>► EISBRECHER – Metal Indus –</h4>
    <p>Le groupe a influencé plusieurs générations de musiciens metal.</p>
    <p>Ouverture des portes : 18h</p>
  </main>
  <h2>Vous aimerez aussi</h2>
  <p>CONCERT DIFFÉRENT</p><p>Death Metal</p>
</body></html>"""


def check(page=PAGE, candidate=None, url=URL, source=None):
    return html.inspect(candidate or CANDIDATE, page, url, source or SOURCE)


class VisibleHtmlEvidenceTests(unittest.TestCase):
    def test_realistic_artist_genre_heading_supports_safe_private_signal(self):
        result = check()
        self.assertEqual(result["status"],
                         "html_explicit_event_genre_correlated")
        self.assertEqual(result["genres"], ["Metal Indus"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["approvalsProposed"], 0)

    def test_explicit_event_badge_near_title_is_supported(self):
        src = {"name": "Le Metronum", "city": "Toulouse",
               "department": "31", "url": "https://lemetronum.fr/"}
        lead = {**CANDIDATE,
                "name": "Kamelot + Exit Eden + Temperance",
                "leadArtist": "Kamelot + Exit Eden + Temperance",
                "sourceUrl":
                    "https://lemetronum.fr/evenement/kamelot-exit-eden-temperance/",
                "sourcePage":
                    "https://lemetronum.fr/evenement/kamelot-exit-eden-temperance/",
                "date": "2026-11-20", "venue": "Le Metronum",
                "city": "Toulouse", "department": "31"}
        body = """<main>
          <h1>Kamelot + Exit Eden + Temperance</h1>
          <p>Vendredi 20 Novembre 2026 - 20h</p>
          <p>metal</p>
          <p>Une soirée de musique symphonique...</p>
          <h3>Le Metronum</h3><p>31200 Toulouse</p>
          <h2>Vous aimerez aussi</h2>
          <p>Jazz</p></main>"""
        report = check(body, lead, lead["sourceUrl"], src)
        self.assertEqual(report["status"],
                         "html_explicit_event_genre_correlated")
        self.assertEqual(report["genres"], ["metal"])

    def test_related_only_genre_is_not_evidence(self):
        body = PAGE.replace(
            "<h4>► EISBRECHER – Metal Indus –</h4>",
            "<p>Artiste de la scène alternative.</p>")
        self.assertEqual(check(body)["status"],
                         "html_event_genre_unconfirmed")

    def test_biography_genre_not_a_tag_even_when_metal_in_prose(self):
        body = PAGE.replace(
            "<h4>► EISBRECHER – Metal Indus –</h4>",
            "<p>Le groupe joue du death metal depuis plusieurs années.</p>")
        self.assertEqual(check(body)["status"],
                         "html_event_genre_unconfirmed")

    def test_sitewide_navigation_and_footer_genres_are_ignored(self):
        body = PAGE.replace(
            "<h4>► EISBRECHER – Metal Indus –</h4>", "")
        self.assertEqual(check(body)["status"],
                         "html_event_genre_unconfirmed")

    def test_date_and_title_must_match_event(self):
        self.assertEqual(check(PAGE.replace(
            "18 septembre 2027", "19 septembre 2027"))["status"],
            "html_event_date_not_correlated")
        self.assertEqual(check(PAGE.replace(
            "<h1>EISBRECHER</h1>", "<h1>DIFFERENT BAND</h1>"))["status"],
            "html_event_heading_mismatch")

    def test_forged_or_moved_source_cannot_be_html_proof(self):
        self.assertEqual(check(url="https://evil.example/show")["status"],
                         "html_official_url_not_correlated")
        self.assertEqual(check(candidate={
            **CANDIDATE, "city": "Paris"})["status"],
            "html_source_venue_not_correlated")
        self.assertEqual(check(PAGE.replace(
            "69100 Villeurbanne", "75000 Paris"))["status"],
            "html_visible_venue_or_city_missing")

    def test_multiple_headlines_are_ambiguous(self):
        self.assertEqual(check(PAGE.replace(
            "<h1>EISBRECHER</h1>",
            "<h1>EISBRECHER</h1><h1>Un autre spectacle</h1>"))["status"],
            "html_event_heading_ambiguous")

    def test_generic_rock_badge_and_unannounced_guest_are_not_inferred(self):
        self.assertEqual(check(PAGE.replace(
            "<h4>► EISBRECHER – Metal Indus –</h4>",
            "<p>Rock</p>"))["status"], "html_event_genre_unconfirmed")
        lead = {**CANDIDATE, "leadArtist": "EISBRECHER + Unknown Band"}
        self.assertEqual(check(candidate=lead)["status"],
                         "html_named_bill_not_correlated")

    def test_missing_date_untrusted_body_and_network_oversize_fail_closed(self):
        self.assertEqual(check("<h1>EISBRECHER</h1>")["status"],
                         "html_event_date_not_correlated")
        self.assertEqual(check("a" * 1_000_001)["status"],
                         "html_evidence_unreadable")
        self.assertEqual(check(candidate={**CANDIDATE, "date": "2027-99-99"})[
            "status"], "html_event_date_unavailable")

    def test_generic_evidence_never_mutates_discovery_input(self):
        candidate = copy.deepcopy(CANDIDATE)
        result = check(candidate=candidate)
        self.assertEqual(candidate, CANDIDATE)
        self.assertFalse(result["publicationAllowed"])
        self.assertNotIn("reviewDecision", result)
        self.assertNotIn("event", result)


    def test_structured_organization_placeholder_with_named_heading_stays_review_only(self):
        row = {**CANDIDATE, "structuredPerformerProof": "missing_review_only"}
        result = check(candidate=row)
        self.assertEqual(result["status"],
                         "html_explicit_named_artist_headings_review_only")
        self.assertEqual(result["genres"], ["Metal Indus"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["approvalsProposed"], 0)

    def test_multi_artist_heading_corroboration_requires_every_named_artist(self):
        row = {**CANDIDATE,
               "name": "EISBRECHER + HELDMASCHINE",
               "leadArtist": "EISBRECHER + HELDMASCHINE",
               "structuredPerformerProof": "missing_review_only"}
        page = PAGE.replace("<h1>EISBRECHER</h1>",
                            "<h1>EISBRECHER + HELDMASCHINE</h1>")
        missing_support = check(page, row)
        self.assertEqual(missing_support["status"],
                         "html_event_genre_visible_lineup_unverified")
        both = page.replace(
            "<h4>► EISBRECHER – Metal Indus –</h4>",
            "<h4>► EISBRECHER – Metal Indus –</h4>"
            "<h4>► HELDMASCHINE – Industrial Metal –</h4>")
        complete = check(both, row)
        self.assertEqual(complete["status"],
                         "html_explicit_named_artist_headings_review_only")
        self.assertEqual(complete["genres"], ["Metal Indus", "Industrial Metal"])
        self.assertFalse(complete["publicationAllowed"])





    def test_complete_html_time_attribute_iso_and_numeric_dates(self):
        variants = (
            '<time datetime="2027-09-18">Samedi, 19 h</time>',
            '<p>2027-09-18 à 19:00</p>',
            '<strong>18/09/2027</strong>',
            '<time datetime="2027-09-18T20:00:00+02:00">Samedi</time>',
        )
        for replacement in variants:
            with self.subTest(replacement=replacement):
                body = PAGE.replace(
                    '<strong>samedi 18 septembre 2027</strong>',
                    replacement)
                evidence = check(body)
                self.assertEqual(
                    evidence["status"], "html_explicit_event_genre_correlated")
                self.assertEqual(evidence["genres"], ["Metal Indus"])
                self.assertIs(evidence["publicationAllowed"], False)
                self.assertEqual(evidence["approvalsProposed"], 0)

    def test_conflicting_machine_and_visible_date_are_not_evidence(self):
        body = PAGE.replace(
            '<strong>samedi 18 septembre 2027</strong>',
            '<time datetime="2027-09-19">18 septembre 2027</time>')
        result = check(body)
        self.assertEqual(result["status"], "html_event_date_not_correlated")
        self.assertFalse(result["publicationAllowed"])

    def test_early_ticket_sale_date_is_not_concert_date(self):
        body = PAGE.replace(
            '<strong>samedi 18 septembre 2027</strong>',
            '<p>Ouverture billetterie : 2027-01-07</p>'
            '<time datetime="2027-09-18">Samedi</time>')
        self.assertEqual(check(body)["status"],
                         "html_event_date_not_correlated")

    def test_hardcore_techno_html_badge_is_not_accepted(self):
        body = PAGE.replace(
            '<h4>► EISBRECHER – Metal Indus –</h4>',
            '<p>Hardcore Techno</p>')
        result = check(body)
        self.assertEqual(result["status"], "html_event_genre_unconfirmed")
        self.assertIs(result["publicationAllowed"], False)

    def test_partial_yearless_date_does_not_count_as_show_date(self):
        body = PAGE.replace(
            '<strong>samedi 18 septembre 2027</strong>',
            '<time>samedi 18 septembre</time>')
        self.assertEqual(check(body)["status"],
                         "html_event_date_not_correlated")

    def test_navigation_datetime_is_not_event_evidence(self):
        body = PAGE.replace(
            '<strong>samedi 18 septembre 2027</strong>',
            '<time>samedi</time>').replace(
            '<header><nav>', '<header><nav><time datetime="2027-09-18">samedi</time>')
        self.assertEqual(check(body)["status"],
                         "html_event_date_not_correlated")



class PrivatePreflightHtmlIntegrationTests(unittest.TestCase):
    def test_structure_missing_but_visible_html_evidence_is_quarantined(self):
        row = copy.deepcopy(CANDIDATE)
        reg = {"schema": "grossesondes.concert.intake.v1",
               "items": {"one": {
                   "candidate": row, "stableObservations": 2,
                   "status": "pending_review"}}}
        sources = {"schema": "grossesondes.concert.sourcelist.v1",
                   "venues": [SOURCE]}
        cat = {"schemaVersion": 1, "mode": "preview-public-unlisted",
               "events": [], "venues": [], "artists": []}
        approved = {"schema": "grossesondes.concert.approvals.v1",
                    "approvals": []}
        report = preflight.build(
            reg, sources, cat, approved, dt.date(2026, 11, 19),
            fetch=lambda url, **kw: (PAGE, url),
            robots=lambda url, cache: True, limit=8)
        self.assertEqual(report["exploratoryAttempted"], 1)
        self.assertEqual(report["htmlGenreEvidenceFound"], 1)
        self.assertEqual(report["htmlEvidenceReasonCounts"],
                         {"html_explicit_event_genre_correlated": 1})
        self.assertEqual(report["approvalsProposed"], 0)
        self.assertFalse(report["publicationAllowed"])
        self.assertFalse(report["results"][0]["publicationAllowed"])
        self.assertEqual(report["results"][0]["htmlGenreLabels"],
                         ["Metal Indus"])
        self.assertEqual(report["results"][0]["status"], "held")
        self.assertEqual(row["reviewBucket"], "genre_unknown")


    def test_full_named_html_lineup_is_counted_but_never_signed(self):
        row = {**CANDIDATE, "structuredPerformerProof": "missing_review_only"}
        registry = {"schema": "grossesondes.concert.intake.v1",
                    "items": {"item": {"candidate": row,
                                       "stableObservations": 2,
                                       "status": "pending_review"}}}
        sources = {"schema": "grossesondes.concert.sourcelist.v1",
                   "venues": [SOURCE]}
        catalogue = {"schemaVersion": 1, "mode": "preview-public-unlisted",
                     "events": [], "venues": [], "artists": []}
        approved = {"schema": "grossesondes.concert.approvals.v1",
                    "approvals": []}
        report = preflight.build(
            registry, sources, catalogue, approved, dt.date(2026, 11, 19),
            fetch=lambda url, **kwargs: (PAGE, url),
            robots=lambda url, cache: True, limit=8)
        self.assertEqual(report["htmlFullyNamedArtistHeadingReviewOnly"], 1)
        self.assertEqual(report["htmlGenreEvidenceFound"], 0)
        self.assertEqual(report["approvalsProposed"], 0)
        self.assertFalse(report["publicationAllowed"])




if __name__ == "__main__":
    unittest.main()
