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
    def test_two_archive_homepage_date_mentions_are_private_editorial_review(self):
        from historical_future_lead_watch import APPROVED, scan
        f = list(fixtures())
        state, _, details, public, archive, leads = f
        name, region, url = APPROVED["les-gueules-de-bois"]
        roster = {"les-gueules-de-bois": {
            "slug": "les-gueules-de-bois", "name": name,
            "region": region, "url": url, "last_known_year": 2026}}
        scan(state, roster, TODAY, fetch=lambda _: (
            "<main><h1>Les Gueules de Bois winter 2027</h1>"
            "<p>samedi 13 février 2027 à Légna.</p>"
            "<h2>Les Gueules de Bois été 2027</h2>"
            "<p>19–21 août 2027 à Légna.</p></main>"))
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": TODAY, "source_reference_leads_review_only": [],
                  "historical_future_watch_archive_status_private": "CONSISTENT"}
        queue = build_queue(state, report, leads, TODAY)
        archive["knownFestivals"].append({
            "slug": "les-gueules-de-bois", "name": name,
            "region": region, "city": "Légna", "aliases": [],
            "startDate": "2026-08-20", "endDate": "2026-08-22",
            "lastKnownYear": 2026})
        result = build_review(queue, details, state, leads, public, archive, TODAY)
        self.assertEqual(result["historical_homepage_date_dossiers_private"], 1)
        self.assertEqual(result["historical_homepage_visible_date_hints_private"], 2)
        row = next(x for x in result["dossiers"] if
                   x["name_hint"] == "Les Gueules de Bois")
        self.assertEqual(row["status"], "ARCHIVAL_VISIBLE_DATE_HINT_REVIEW")
        self.assertEqual(len(row["historical_homepage_date_hints_review_only"]), 2)
        self.assertIn("possible_multiple_same_year_editions_need_review",
                      row["missing_checks"])
        self.assertFalse(row["future_edition_confirmed"])
        self.assertFalse(row["safe_to_publish"])
        self.assertEqual(result["editorial_drafts_count"], 0)
        self.assertEqual(result["publications"], 0)
        # Regression: a generic name/year public record of the winter edition
        # must never swallow a distinct summer mention as a published duplicate.
        public["festivals"] = [{
            "slug": "les-gueules-de-bois-winter-2027",
            "name": "Les Gueules de Bois 2027",
            "startDate": "2027-02-13", "endDate": "2027-02-13",
            "region": region, "city": "Légna",
        }]
        covered = build_review(queue, details, state, leads, public, archive, TODAY)
        other = next(x for x in covered["dossiers"]
                     if x["name_hint"] == "Les Gueules de Bois")
        self.assertEqual(other["status"], "POTENTIAL_CONFLICT_REVIEW")
        self.assertIn("published_same_year_may_hide_other_edition",
                      other["missing_checks"])
        self.assertEqual(len(other["historical_homepage_uncovered_dates_review_only"]), 1)
        self.assertEqual(other["historical_homepage_uncovered_dates_review_only"][0]
                         ["start_date_hint"], "2027-08-19")
        self.assertEqual(covered["historical_homepage_uncovered_date_hints_private"], 1)
        self.assertFalse(other["publication_authorized"])
        self.assertEqual(covered["publications"], 0)

    def test_gueules_press_article_does_not_certify_two_editions(self):
        from historical_future_lead_watch import APPROVED, scan as archive_scan
        from targeted_press_edition_watch import SOURCES as PRESS, scan as press_scan
        state, _, details, public, archive, leads = fixtures()
        name, region, url = APPROVED["les-gueules-de-bois"]
        archive["knownFestivals"].append({
            "slug": "les-gueules-de-bois", "name": name, "region": region,
            "city": "Légna", "aliases": [], "lastKnownYear": 2026,
            "startDate": "2026-08-20", "endDate": "2026-08-22",
            "officialSite": url,
        })
        roster = {"les-gueules-de-bois": {
            "slug": "les-gueules-de-bois", "name": name,
            "region": region, "url": url, "last_known_year": 2026}}
        archive_scan(state, roster, TODAY, fetch=lambda _: (
            "<main><h1>Les Gueules de Bois hiver 2027</h1>"
            "<p>Samedi 13 février 2027 à Légna.</p>"
            "<h2>Les Gueules de Bois été 2027</h2>"
            "<p>19 au 21 août 2027 à Légna.</p></main>"))
        press_scan(state, {"gueules-progres": PRESS["gueules-progres"]},
                   TODAY, fetch=lambda _: (
                       "<main><h1>Le festival Les Gueules de Bois 2027</h1>"
                       "<p>Premier rendez-vous le samedi 13 février 2027.</p>"
                       "<p>Les bénévoles préparent la septième édition du festival, "
                       "programmée les 19, 20 et 21 août 2027.</p></main>"))
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": TODAY, "source_reference_leads_review_only": [],
                  "historical_future_watch_archive_status_private": "CONSISTENT"}
        queue = build_queue(state, report, leads, TODAY)
        editorial = build_review(queue, details, state, leads, public, archive, TODAY)
        row = next(x for x in editorial["dossiers"] if x["name_hint"] == name)
        self.assertEqual(editorial["press_date_claim_dossiers_private"], 1)
        self.assertEqual(editorial["press_date_claims_private"], 2)
        self.assertEqual(len(row["press_date_observations_review_only"]), 1)
        self.assertEqual(len(row["press_date_observations_review_only"][0]["claims"]), 2)
        self.assertEqual(row["status"], "ARCHIVAL_VISIBLE_DATE_HINT_REVIEW")
        self.assertIn("press_article_origin_requires_editorial_review",
                      row["missing_checks"])
        self.assertIn("independent_date_confirmation", row["missing_checks"])
        self.assertIn("editorial_approval", row["missing_checks"])
        self.assertFalse(row["future_edition_confirmed"])
        self.assertFalse(row["publication_authorized"])
        self.assertFalse(row["safe_to_publish"])
        self.assertEqual(editorial["publications"], 0)

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

    def test_old_edition_organizer_and_place_are_review_hints_not_2027_proofs(self):
        f = fixtures()
        f[4]["knownFestivals"][0].update(
            organizer="Association des Amis du Metal",
            department="57", venue="Parc des concerts",
        )
        dossier = review(f)["dossiers"][0]
        historical = dossier["archive_identity_hints"][0]
        self.assertEqual(historical["last_known_year"], 2026)
        self.assertEqual(historical["prior_edition_organizer_review_only"],
                         "Association des Amis du Metal")
        self.assertEqual(historical["prior_edition_department_review_only"], "57")
        self.assertEqual(historical["prior_edition_city_review_only"], "Insming")
        self.assertEqual(historical["prior_edition_venue_review_only"],
                         "Parc des concerts")
        self.assertFalse(historical["organizer_verified_for_future"])
        self.assertFalse(historical["venue_verified_for_future"])
        self.assertFalse(historical["future_edition_verified"])
        self.assertIn("organizer_identity", dossier["missing_checks"])
        self.assertIn("venue_and_department", dossier["missing_checks"])
        self.assertFalse(dossier["publication_authorized"])
        self.assertFalse(dossier["safe_to_publish"])

    def test_malformed_old_metadata_is_not_exported_as_research_hint(self):
        f = fixtures()
        f[4]["knownFestivals"][0].update(
            organizer="<script>fake organizer</script>",
            department="63/69", venue="Festival\nForged",
        )
        archival = review(f)["dossiers"][0]["archive_identity_hints"][0]
        self.assertIsNone(archival["prior_edition_organizer_review_only"])
        self.assertIsNone(archival["prior_edition_department_review_only"])
        self.assertIsNone(archival["prior_edition_venue_review_only"])
        self.assertFalse(archival["organizer_verified_for_future"])

    def test_incorrect_archive_city_and_year_never_borrow_metadata(self):
        f = fixtures()
        f[4]["knownFestivals"][0].update(
            city="Other city", organizer="False Organizer", department="69")
        self.assertEqual(review(f)["dossiers"][0]["archive_identity_hints"], [])
        f = fixtures()
        f[4]["knownFestivals"][0].update(
            lastKnownYear=2027, startDate="2027-07-23",
            endDate="2027-07-25", organizer="False Organizer")
        self.assertEqual(review(f)["dossiers"][0]["archive_identity_hints"], [])

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


    def shred_fixture(self):
        # Regression: a regional "Shred Fest 2027" lead and the existing
        # published "Shred Fest 2027 — Limoges" have different full titles.
        f = list(fixtures())
        dossier = f[1]["dossiers"][0]
        dossier.update(
            name_hint="Shred Fest 2027", normalized_name="shred fest",
            name_variants=["Shred Fest 2027"],
            region_hint="Nouvelle-Aquitaine", city_hint=None)
        f[4]["knownFestivals"] = []
        f[3]["festivals"] = [{
            "slug": "shred-fest-2027-limoges",
            "name": "Shred Fest 2027 — Limoges",
            "startDate": "2027-02-12", "endDate": "2027-02-12",
            "city": "Limoges", "region": "Nouvelle-Aquitaine",
        }]
        return f

    def test_public_city_variant_is_suspicion_never_certain_duplicate(self):
        result = review(self.shred_fixture())
        self.assertEqual(result["published_duplicate_dossiers_count"], 0)
        self.assertEqual(result["published_title_city_variant_dossiers_count"], 1)
        row = result["dossiers"][0]
        self.assertEqual(row["status"], "POTENTIAL_CONFLICT_REVIEW")
        self.assertIn("published_title_city_variant_needs_review",
                      row["missing_checks"])
        self.assertEqual(row["published_title_city_variants_review_only"][0]["slug"],
                         "shred-fest-2027-limoges")
        self.assertFalse(row["published_title_city_variants_review_only"][0]
                         ["edition_already_published"])
        self.assertFalse(row["publication_authorized"])
        self.assertFalse(row["safe_to_publish"])
        self.assertEqual(result["editorial_drafts_count"], 0)
        self.assertEqual(result["publications"], 0)

    def test_city_variant_requires_verified_public_suffix_and_region_year(self):
        for field, value in (
            ("name", "Shred Fest 2027 — Nantes"),
            ("name", "Shred Fest 2027 — Limoges junior"),
            ("region", "Occitanie"),
            ("startDate", "2028-02-12"),
            ("city", "Paris"),
        ):
            with self.subTest(field=field, value=value):
                f = self.shred_fixture()
                f[3]["festivals"][0][field] = value
                result = review(f)
                self.assertEqual(result["published_title_city_variant_dossiers_count"], 0)
                self.assertEqual(result["published_duplicate_dossiers_count"], 0)
                self.assertEqual(result["editorial_drafts_count"], 0)

    def test_conflicting_candidate_city_cannot_be_masked_by_title_variant(self):
        f = self.shred_fixture()
        f[1]["dossiers"][0]["city_hint"] = "Nantes"
        result = review(f)
        self.assertEqual(result["published_title_city_variant_dossiers_count"], 0)
        self.assertEqual(result["published_duplicate_dossiers_count"], 0)
        self.assertEqual(result["publications"], 0)

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
