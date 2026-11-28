"""Independent professional provenance and Publisher negative tests."""
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from national_professional_publisher_provenance import lookup_path, prove
from grossesondes_openagenda_linked_edition import (
    private_proposal, validate_private_proposal, independently_verify,
    validate_verified_row,
)

DAY = "2026-11-26"
TITLE = "Festival des Rives 2027"
EVENT = "https://openagenda.com/agenda/events/festival-des-rives"
TICKET = "https://billetterie.fr/festivals/festival-des-rives"
SITE = "https://salle-des-rives.fr/festival-des-rives/"
DATES = ("2027-06-04", "2027-06-05")
PROOF = {"official_detail_url": SITE, "ticket_url": TICKET,
         "start_date": DATES[0], "end_date": DATES[1],
         "publication_authorized": False}
RECORD = {"title_fr": "Festival des Rives", "canonicalurl": EVENT,
          "firstdate_begin": "2027-06-04", "lastdate_begin": "2027-06-05",
          "location_countrycode": "FR", "location_region": "Île-de-France",
          "description_fr": "Festival metal et punk",
          "registration": [{"type": "link", "value": TICKET}]}

class ProfessionalPublisherTests(unittest.TestCase):
    def test_fixed_origin_and_exact_safe_selector(self):
        query = parse_qs(urlsplit(lookup_path(EVENT)).query)
        self.assertEqual(query["where"], ["canonicalurl = '" + EVENT + "'"])
        for bad in (EVENT + "?a=1", EVENT + "' or 1=1",
                    EVENT.replace("openagenda.com", "127.0.0.1")):
            self.assertIsNone(lookup_path(bad))

    def test_live_record_reconstructs_only_its_own_links(self):
        with patch("national_professional_publisher_provenance.discover") as discover, \
                patch("national_professional_publisher_provenance.examine") as examine:
            discover.return_value = {"review_only": True}
            examine.return_value = {"status": "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY",
                                    "proofs": [PROOF]}
            result = prove(EVENT, TITLE, DAY, record_fetch=lambda _: {
                "total_count": 1, "results": [RECORD]})
            self.assertEqual(result, [PROOF])
            self.assertEqual(discover.call_args.args[0]["links"],
                             [{"field": "registration", "url": TICKET}])
            for changed in (dict(RECORD, canonicalurl=EVENT+"-autre"),
                            dict(RECORD, title_fr="Autre Festival"),
                            dict(RECORD, firstdate_begin="2028-06-04",
                                 lastdate_begin="2028-06-05")):
                self.assertEqual(prove(EVENT, TITLE, DAY, record_fetch=lambda _: {
                    "total_count": 1, "results": [changed]}), [])
            self.assertEqual(prove(EVENT, TITLE, DAY, record_fetch=lambda _: {
                "total_count": 2, "results": [RECORD, RECORD]}), [])
            self.assertEqual(discover.call_count, 1)

    def test_venue_fallback_is_independent_of_rate_limited_ticket_host(self):
        from national_professional_official_detail import examine_openagenda_venue
        from national_openagenda_research import candidate
        lead = candidate(dict(RECORD, location_website=SITE), DAY)
        calls = []
        with patch("national_professional_official_detail.examine") as examine:
            def proof(research, title, year, today, fetch):
                self.assertEqual(research["websites"][0]["website_url"], SITE)
                self.assertEqual(research["websites"][0]["ticket_url"], TICKET)
                fetch(SITE)
                return {"status": "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY", "proofs": [PROOF]}
            examine.side_effect = proof
            result = examine_openagenda_venue(lead, TITLE, 2027, DAY,
                fetch=lambda url: calls.append(url) or "<main></main>")
            self.assertEqual(result["proofs"], [PROOF])
            self.assertEqual(calls, [SITE])
            self.assertFalse(result["publication_authorized"])
            self.assertEqual(examine_openagenda_venue(candidate(RECORD, DAY),
                TITLE, 2027, DAY)["proofs"], [])
        with patch("national_professional_publisher_provenance.discover") as discover, \
                patch("national_professional_publisher_provenance.examine") as examine, \
                patch("national_professional_publisher_provenance.examine_openagenda_venue") as venue:
            discover.return_value = {"status": "PROFESSIONAL_RATE_LIMITED"}
            examine.return_value = {"status": "NO_OFFICIAL_DETAIL_PROOF"}
            venue.return_value = {"status": "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY", "proofs": [PROOF]}
            self.assertEqual(prove(EVENT, TITLE, DAY, record_fetch=lambda _: {
                "total_count": 1, "results": [dict(RECORD, location_website=SITE)]}), [PROOF])
            self.assertEqual(venue.call_args.args[0]["professional_source_hints_review_only"]
                             ["links"][-1]["url"], SITE)

    def test_publisher_requires_exact_reconstructed_proof(self):
        proposal = private_proposal(TITLE, SITE, DATES, DAY, event_ref=EVENT,
                                    professional_ticket=TICKET)
        self.assertIsNotNone(proposal)
        self.assertIsNotNone(validate_private_proposal(proposal, DAY))
        with patch("national_professional_publisher_provenance.prove", return_value=[PROOF]) as read:
            accepted = independently_verify(proposal, DAY)
            self.assertIsNotNone(accepted)
            self.assertEqual(read.call_args.args, (EVENT, TITLE, DAY))
            self.assertIsNotNone(validate_verified_row(proposal, accepted, DAY))
            self.assertFalse(accepted["showOnMap"])
            self.assertEqual(accepted["lineup"], [])
            for site, ticket, dates in (
                    (SITE+"autre/", TICKET, DATES),
                    (SITE, TICKET+"-autre", DATES),
                    (SITE, TICKET, ("2027-06-11", "2027-06-12"))):
                other = private_proposal(TITLE, site, dates, DAY, event_ref=EVENT,
                                         professional_ticket=ticket)
                self.assertIsNone(independently_verify(other, DAY))
        with patch("national_professional_publisher_provenance.prove", return_value=[]):
            self.assertIsNone(independently_verify(proposal, DAY))

if __name__ == "__main__":
    unittest.main()
