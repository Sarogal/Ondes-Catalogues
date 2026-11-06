"""Offline checks for the national private editorial reconciliation engine."""
from copy import deepcopy
from hashlib import sha256
import unittest

from national_editorial_reconciliation import build_review, SCHEMA
from national_discovery_queue import build_queue

TODAY = "2026-11-06"
MOZHELL = {
    "id": "mozhell-open-air-2027", "name": "MozHell Open Air",
    "source_url": "https://www.mozhell.fr/fr/le-mozhell-est-de-retour-pour-une-nouvelle-edition-en-2027",
    "official_home_candidate": "https://www.mozhell.fr/fr/",
    "date_phrase": "23 24 et 25 juillet 2027",
    "start_date": "2027-07-23", "end_date": "2027-07-25",
    "city_hint": "Insming", "region_hint": "Grand Est",
    "genre_hint": "Metal",
}


def fixtures(leads=None):
    leads = [MOZHELL] if leads is None else leads
    state = {
        "schema": "grossesondes.source-watch.v1",
        "curated_future_lead_observations": {},
        "regional_festival_candidates_review_only": {},
        "institutional_agenda_candidate_pages": {},
        "secondary_source_candidates_private": {},
    }
    report = {"schema": "grossesondes.source-watch-report.v1",
              "date": TODAY, "source_reference_leads_review_only": []}
    queue = build_queue(state, report, leads, TODAY)
    details = {"schema": "grossesondes.national-detail-qualification-private.v1",
               "as_of": TODAY, "review_only": True,
               "publication_authorized": False,
               "safe_to_publish": False, "observations": []}
    public = {"schema": 1, "festivals": []}
    archive = {"schema": 2, "knownFestivals": [
        {"slug": "mozhell-open-air", "name": "MozHell Open Air",
         "aliases": [], "region": "Grand Est", "city": "Insming",
         "startDate": "2026-07-24", "endDate": "2026-07-26",
         "lastKnownYear": 2026},
    ]}
    return state, queue, details, public, archive, leads


def review(f):
    state, queue, details, public, archive, leads = f
    return build_review(queue, details, state, leads, public, archive, TODAY)


def primary(row):
    return {
        "status": "UNVERIFIED_PRIMARY_EDITION",
        "firstSeen": "2026-11-05",
        "lastSeen": TODAY,
        "lastVisibleDigest": "b"*64,
        "claim": [row["name"], row["start_date"], row["end_date"],
                  row["date_phrase"], row["source_url"]],
        "publication_authorized": False,
    }


class EditorialReconciliationTests(unittest.TestCase):
    def test_archive_identity_not_future_edition_proof(self):
        result = review(fixtures())
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["dossiers_count"], 1)
        self.assertEqual(result["historical_identity_hints_count"], 1)
        archive = result["dossiers"][0]["archive_identity_hints"][0]
        self.assertEqual(archive["last_known_year"], 2026)
        self.assertFalse(archive["future_edition_verified"])
        self.assertFalse(result["dossiers"][0]["future_edition_confirmed"])
        self.assertEqual(result["editorial_drafts_count"], 0)
        self.assertEqual(result["publications"], 0)

    def test_archive_other_region_or_city_not_a_match(self):
        f = fixtures()
        f[4]["knownFestivals"][0]["region"] = "Bretagne"
        self.assertEqual(review(f)["historical_identity_hints_count"], 0)
        f = fixtures()
        f[4]["knownFestivals"][0]["city"] = "Nantes"
        self.assertEqual(review(f)["historical_identity_hints_count"], 0)

    def test_archive_year_same_as_candidate_does_not_create_prior_history(self):
        f = fixtures()
        f[4]["knownFestivals"][0].update(
            lastKnownYear=2027, startDate="2027-07-23", endDate="2027-07-25")
        self.assertEqual(review(f)["historical_identity_hints_count"], 0)

    def test_primary_observed_dated_edition_creates_private_draft(self):
        f = fixtures()
        f[0]["curated_future_lead_observations"][MOZHELL["id"]] = primary(MOZHELL)
        result = review(f)
        self.assertEqual(result["primary_observed_dossiers_count"], 1)
        self.assertEqual(result["editorial_drafts_count"], 1)
        self.assertEqual(result["dossiers"][0]["status"], "PRIMARY_DATE_CLAIM_REVIEW")
        draft = result["editorial_drafts_private"][0]
        self.assertFalse(draft["publication_authorized"])
        self.assertFalse(draft["safe_to_publish"])
        self.assertEqual(draft["candidate_fields_unverified"]["start_date_hint"], "2027-07-23")
        self.assertIsNone(draft["candidate_fields_unverified"]["city"])
        self.assertEqual(result["publications"], 0)

    def test_same_edition_published_prevents_private_addition(self):
        f = fixtures()
        f[0]["curated_future_lead_observations"][MOZHELL["id"]] = primary(MOZHELL)
        f[3]["festivals"] = [
            {"slug": "mozhell-open-air-new", "name": "MozHell Open Air 2027",
             "startDate": "2027-07-23", "endDate": "2027-07-25",
             "city": "Insming", "region": "Grand Est"}]
        result = review(f)
        self.assertEqual(result["published_duplicate_dossiers_count"], 1)
        self.assertEqual(result["editorial_drafts_count"], 0)
        self.assertEqual(result["dossiers"][0]["status"],
                         "PUBLISHED_EDITION_MATCH_REVIEW")

    def test_same_name_year_region_different_city_is_conflict_not_duplicate(self):
        f = fixtures()
        f[3]["festivals"] = [
            {"slug": "mozhell-copy-2027", "name": "MozHell Open Air 2027",
             "startDate": "2027-07-23", "endDate": "2027-07-25",
             "city": "Paris", "region": "Grand Est"}]
        result = review(f)
        self.assertEqual(result["published_duplicate_dossiers_count"], 0)
        self.assertEqual(result["dossiers"][0]["status"], "POTENTIAL_CONFLICT_REVIEW")
        self.assertEqual(result["editorial_drafts_count"], 0)

    def test_different_year_not_automatically_duplicate(self):
        f = fixtures()
        f[3]["festivals"] = [
            {"slug": "mozhell-2026", "name": "MozHell Open Air 2026",
             "startDate": "2026-07-23", "endDate": "2026-07-25",
             "city": "Insming", "region": "Grand Est"}]
        self.assertEqual(review(f)["published_duplicate_dossiers_count"], 0)

    def test_stale_primary_or_tampered_claim_cannot_create_draft(self):
        f = fixtures()
        obs = primary(MOZHELL)
        obs["lastSeen"] = "2026-09-01"
        f[0]["curated_future_lead_observations"][MOZHELL["id"]] = obs
        self.assertEqual(review(f)["editorial_drafts_count"], 0)
        obs["lastSeen"] = TODAY
        obs["claim"][1] = "2027-08-23"
        self.assertEqual(review(f)["editorial_drafts_count"], 0)

    def test_details_not_allowed_to_certify_dates_or_independence(self):
        f = fixtures()
        dossier = f[1]["dossiers"][0]
        url = "https://agenda.montpellier.fr/evenement/metal2027"
        origin = "https://agenda.montpellier.fr/"
        dossier["sources"].append({
            "url": url, "discovered_via": origin,
            "kind": "REGIONAL_INDEX_UNVERIFIED",
            "firstSeen": "2026-11-05", "lastSeen": TODAY,
            "independence_verified": False, "publication_authorized": False})
        dossier["name_variants"].append(MOZHELL["name"]+" 2027")
        f[2]["observations"] = [{
            "dossier_id": dossier["id"], "candidate_url": url,
            "index_url": origin, "name_hint": MOZHELL["name"]+" 2027",
            "edition_year_hint": 2027, "observed_at": TODAY,
            "status": "NAME_YEAR_VISIBLE_REVIEW_ONLY",
            "name_seen": True, "edition_year_near_name": True,
            "possible_cancellation_review_only": False,
            "visible_text_sha256": "c"*64, "date_claim_verified": False,
            "festival_verified": False, "organizer_verified": False,
            "independence_verified": False, "publication_authorized": False,
        }]
        result = review(f)
        self.assertEqual(result["regional_detail_observed_dossiers_count"], 1)
        self.assertEqual(result["dossiers"][0]["status"],
                         "REGIONAL_NAME_YEAR_REVIEW")
        self.assertEqual(result["editorial_drafts_count"], 0)
        self.assertFalse(result["dossiers"][0]["independence_verified"])
        f[2]["observations"][0]["date_claim_verified"] = True  # poisoned
        self.assertEqual(review(f)["regional_detail_observed_dossiers_count"], 0)

    def test_corrupt_queue_or_unsupported_public_snapshot_fails_closed(self):
        f = list(fixtures())
        f[1]["publication_authorized"] = True
        with self.assertRaises(ValueError):
            review(f)
        f = list(fixtures())
        f[3]["schema"] = 100
        with self.assertRaises(ValueError):
            review(f)

    def test_ambiguous_historical_identity_requires_review(self):
        f = fixtures()
        another = deepcopy(f[4]["knownFestivals"][0])
        another["slug"] = "mozhell-open-air-other"
        f[4]["knownFestivals"].append(another)
        result = review(f)
        self.assertEqual(result["dossiers"][0]["status"],
                         "POTENTIAL_CONFLICT_REVIEW")
        self.assertEqual(result["editorial_drafts_count"], 0)

    def test_name_alias_exact_only(self):
        f = fixtures()
        f[4]["knownFestivals"][0]["name"] = "Rock Something Else"
        f[4]["knownFestivals"][0]["aliases"] = ["MozHell Open Air"]
        self.assertEqual(review(f)["historical_identity_hints_count"], 1)
        f[4]["knownFestivals"][0]["aliases"] = ["The MozHell Open Air Jr"]
        self.assertEqual(review(f)["historical_identity_hints_count"], 0)


if __name__ == "__main__":
    unittest.main()
