"""Regression tests for all-stage, nonpublishing, open-world festival inventory."""
from copy import deepcopy
from unittest import TestCase, main
from national_blocker_inventory import build_inventory, safe_failure_code, SCHEMA

TODAY = "2026-11-21"


def fixture():
    names = [
        ("national-colombin-2027", "Colomb'in Rock Festival", 2027),
        ("national-shred-2027", "Shred Fest", 2027),
        ("national-mozhell-2027", "MozHell Open Air", 2027),
    ]
    defaults = {"as_of": TODAY, "review_only": True,
                "publication_authorized": False}
    discovery = dict(defaults, dossiers=[
        {"id": ident, "name_hint": name, "edition_year_hint": year,
         "city_hint": None, "region_hint": None,
         "sources": [{"kind": "UNTRUSTED_RESEARCH",
                      "url": "https://unfamiliar-organizer.fr/"}]}
        for ident, name, year in names])
    editorial = dict(defaults, dossiers=[
        {"id": ident, "status": "PRIVATE_EDITORIAL_DRAFT",
         "primary_observation": {
             "dates_visible_in_primary": ident == "national-colombin-2027",
             "start_date_hint": "2027-08-13", "end_date_hint": "2027-08-14",
         }, "missing_checks": ["independent_date_confirmation",
                               "coordinates_review"]}
        for ident, name, year in names])
    funnel = dict(defaults, dossiers=[
        {"dossier_id": ident,
         "status": ("EXACT_EDITION_IN_PUBLIC_SNAPSHOT" if "mozhell" in ident
                    else "NO_GENERIC_PUBLISHER_PROPOSAL"),
         "independent_publisher_recheck_completed": False}
        for ident, name, year in names])
    handoff = dict(defaults, dossiers=[
        {"id": ident, "status": "PRIMARY_EVIDENCE_PENDING"}
        for ident, name, year in names])
    municipal = dict(defaults, schema="grossesondes.national-municipal-pages-private.v1", rows=[
        {"dossier_id": names[0][0],
         "unknown_music_links_review_only": [
             {"title_hint": "Festival sans mots-clés 2027",
              "detail_url_review_only": "https://mairie.fr/agenda/event",
              "classification": "POSSIBLE_FESTIVAL_REVIEW_ONLY"},
             {"title_hint": "Festival sans mots-clés 2027",
              "detail_url_review_only": "https://mairie.fr/agenda/event",
              "classification": "POSSIBLE_FESTIVAL_REVIEW_ONLY"}],
         "untyped_event_links_review_only": []}])
    concerts = dict(defaults, referrals=[
        {"dossierId": names[1][0], "classification": "EXPLICIT_TOURING_CONCERT_STOP"}])
    catalogue = {"schema": 1, "festivals": [
        {"slug": "mozhell-open-air-2027", "name": "MozHell Open Air 2027",
         "startDate": "2027-07-23"}]}
    return dict(discovery=discovery, editorial=editorial, funnel=funnel,
                handoff=handoff, municipal=municipal, concerts=concerts), catalogue


class BlockerInventoryTests(TestCase):
    def test_safe_diagnostics_never_echo_private_exceptions(self):
        self.assertEqual(
            safe_failure_code(ValueError(
                "Invalid intermediate municipal lead for private "
                "secret-festival-identity https://private.example/secret")),
            "MUNICIPAL_LINK_INVALID")
        self.assertEqual(
            safe_failure_code(ValueError(
                "Unsafe private patch slug private-sensitive-url")),
            "PRIVATE_PATCH_SLUG_INVALID")
        self.assertEqual(
            safe_failure_code(RuntimeError(
                "private raw URL and internal site vanished")),
            "INVENTORY_UNEXPECTED_FAILURE")
        self.assertEqual(
            safe_failure_code(ValueError("unclassified secret marker")),
            "INVENTORY_UNCLASSIFIED_INVALID_INPUT")
        # Every public marker remains a closed-vocabulary uppercase token.
        for error in (
            ValueError("Publisher funnel/public snapshot mismatch"),
            KeyError("private-api-token"),
            OSError("https://private.example/"),
        ):
            result = safe_failure_code(error)
            self.assertRegex(result, r"^[A-Z_]+$")
            self.assertNotIn("private", result.lower())

    def test_openagenda_pass_alias_is_not_an_unpublished_blocker(self):
        reports, catalogue = fixture()
        dossier = reports["discovery"]["dossiers"][2]
        dossier["name_hint"] = "Festival MozHell Open Air 2027 - 3J PASS (3-events)"
        dossier["sources"] = [{"kind": "OPENAGENDA_PUBLIC_RESEARCH_ONLY",
                               "url": "https://openagenda.com/example/events/pass"}]
        result = build_inventory(reports, catalogue, TODAY)
        self.assertTrue(result["dossiers"][2]["in_signed_public_catalogue"])
        self.assertFalse(result["dossiers"][2]["generic_proposal_missing"])
        self.assertEqual(result["dossiers_already_in_public_snapshot"], 1)
        self.assertFalse(result["publication_authorized"])
        dossier["sources"][0]["kind"] = "UNTRUSTED_RESEARCH"
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            build_inventory(reports, catalogue, TODAY)

    def test_signed_undated_year_matches_funnel_without_inventing_dates(self):
        reports, catalogue = fixture()
        # A real announced 2027 edition may have a signed year but no dates.
        # Funnel already counts it as present; inventory must agree.
        catalogue["festivals"].append({
            "slug": "colomb-in-rock-festival-2027",
            "name": "Colomb'in Rock Festival 2027",
            "startDate": None, "endDate": None,
            "status": "Dates à venir", "showOnMap": False,
        })
        reports["funnel"]["dossiers"][0]["status"] = (
            "EXACT_EDITION_IN_PUBLIC_SNAPSHOT")
        result = build_inventory(reports, catalogue, TODAY)
        self.assertEqual(result["dossiers_already_in_public_snapshot"], 2)
        self.assertTrue(result["dossiers"][0]["in_signed_public_catalogue"])
        self.assertIsNone(catalogue["festivals"][-1]["startDate"])
        # A mismatched slug year or non-announced status cannot masquerade
        # as the published edition; keep the independent snapshot check.
        for change in (
            {"slug": "colomb-in-rock-festival-2026"},
            {"status": "Recherche nécessaire"},
            {"endDate": "2027-08-13"},
        ):
            with self.subTest(change=change):
                invalid = deepcopy(catalogue)
                invalid["festivals"][-1].update(change)
                with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
                    build_inventory(reports, invalid, TODAY)

    def test_unknown_names_survive_and_published_referrals_stay_separate(self):
        reports, catalogue = fixture()
        out = build_inventory(reports, catalogue, TODAY)
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["dossiers_count"], 3)
        self.assertEqual(out["dossiers_without_generic_proposal"], 2)
        self.assertEqual(out["dossiers_already_in_public_snapshot"], 1)
        self.assertEqual(out["dossiers_with_first_party_dates_without_proposal"], 1)
        self.assertEqual(out["municipal_intermediate_leads_count"], 1)
        self.assertEqual(out["total_named_leads"], 4)
        self.assertEqual([v["name"] for v in out["dossiers"]],
                         ["Colomb'in Rock Festival", "Shred Fest", "MozHell Open Air"])
        self.assertTrue(out["dossiers"][0]["first_party_dates_without_generic_proposal"])
        self.assertEqual(out["dossiers"][1]["concert_referral_types"],
                         ["EXPLICIT_TOURING_CONCERT_STOP"])
        self.assertTrue(out["dossiers"][2]["in_signed_public_catalogue"])
        self.assertEqual(out["dossiers"][0]["editorial_fit"],
                         "UNASSESSED_BY_AUTOMATION")
        self.assertFalse(out["publication_authorized"])
        self.assertFalse(out["safe_to_publish"])
        self.assertFalse(out["dossiers"][0]["publication_authorized"])
        self.assertEqual(out["publications"], 0)

    def test_current_route_diagnostics_distinguish_unchecked_and_failed(self):
        reports, catalogue = fixture()
        route = {"schema": "grossesondes.national-openagenda-linked-private.v1",
                 "as_of": TODAY, "review_only": True, "safe_to_publish": False,
                 "publication_authorized": False, "rows": [
                     {"dossier_id": "national-colombin-2027",
                      "review_only": True, "publication_authorized": False,
                      "status": "OPENAGENDA_OFFICIAL_LINK_UNPROVEN"}]}
        out = build_inventory(reports, catalogue, TODAY, route_reports={"openagenda": route})
        self.assertEqual(out["unpublished_dossiers_with_current_route_observations"], 1)
        self.assertEqual(out["unpublished_dossiers_with_tour_referral"], 1)
        self.assertEqual(out["dossiers"][0]["current_route_observations_review_only"],
                         [{"route": "openagenda", "status": "OPENAGENDA_OFFICIAL_LINK_UNPROVEN"}])
        self.assertEqual(out["dossiers"][1]["current_route_observations_review_only"], [])
        self.assertEqual(out["dossiers_without_generic_proposal"], 2)
        self.assertFalse(out["publication_authorized"])
        for mutation in ({"as_of": "2026-11-20"}, {"publication_authorized": True},
                         {"rows": [dict(route["rows"][0], dossier_id="unknown")]},
                         {"rows": [dict(route["rows"][0], status="private raw text")]}):
            invalid = dict(route, **mutation)
            with self.assertRaisesRegex(ValueError, "Invalid private route diagnostics"):
                build_inventory(reports, catalogue, TODAY, route_reports={"openagenda": invalid})

    def test_persisted_attempts_are_diagnostic_and_bound_to_current_source(self):
        reports, catalogue = fixture()
        url = "https://openagenda.com/example/events/test"
        target = reports["discovery"]["dossiers"][0]
        target["sources"] = [{"kind": "OPENAGENDA_PUBLIC_RESEARCH_ONLY", "url": url}]
        entry = {"lastChecked": TODAY, "lastResultStatus": "OPENAGENDA_OFFICIAL_LINK_UNPROVEN",
                 "lastProfessionalStatus": "PROFESSIONAL_RATE_LIMITED",
                 "lastProfessionalDetailStatus": "NO_OFFICIAL_DETAIL_PROOF",
                 "digest": "secret-private-proof"}
        state = {"schema": "grossesondes.source-watch.v1",
                 "national_openagenda_linked_first_party_observations_private": {url: entry}}
        result = build_inventory(reports, catalogue, TODAY, watch_state=state)
        self.assertEqual(result["unpublished_dossiers_with_recent_route_attempts"], 1)
        self.assertEqual(result["unpublished_dossiers_with_professional_rate_limit"], 1)
        self.assertEqual(result["dossiers_without_generic_proposal"], 2)
        self.assertEqual(result["dossiers"][0]["recent_persisted_route_attempts_review_only"],
                         [{"route": "openagenda", "last_checked": TODAY,
                           "status": "OPENAGENDA_OFFICIAL_LINK_UNPROVEN",
                           "professional_status": "PROFESSIONAL_RATE_LIMITED",
                           "professional_detail_status": "NO_OFFICIAL_DETAIL_PROOF"}])
        self.assertNotIn("secret-private-proof", str(result))
        self.assertFalse(result["publication_authorized"])
        for bad_day in ("2026-11-13", "2026-11-22", "invalid"):
            entry["lastChecked"] = bad_day
            self.assertEqual(build_inventory(reports, catalogue, TODAY, watch_state=state)
                             ["unpublished_dossiers_with_recent_route_attempts"], 0)
        entry["lastChecked"] = TODAY
        target["sources"][0]["url"] += "-other"
        self.assertEqual(build_inventory(reports, catalogue, TODAY, watch_state=state)
                         ["unpublished_dossiers_with_recent_route_attempts"], 0)

    def test_unfamiliar_festival_is_never_dropped_by_a_closed_registry(self):
        reports, catalogue = fixture()
        target = reports["discovery"]["dossiers"][0]
        target["name_hint"] = "Les Riffs du Bout du Monde"
        self.assertEqual(
            build_inventory(reports, catalogue, TODAY)["dossiers"][0]["name"],
            "Les Riffs du Bout du Monde")


    def test_patch_deferred_festival_names_not_lost_outside_discovery(self):
        reports, catalogue = fixture()
        patch = {
            "schema": "grossesondes.patch.v1", "generated_at": TODAY,
            "safe_to_publish": False,
            "additions": [{"slug": "mozhell-open-air-2027",
                           "name": "MozHell Open Air 2027"}],
            "deferred": [
                {"slug": "betizfest-2027",
                 "issue": "Future edition announced secondarily, not proven",
                 "sources": ["https://betizfest.info/"]},
                {"slug": "festival-metal-vouziers-2027",
                 "issue": "Tourist listing without official edition announcement"},
                {"slug": "festival-d-hiver-faverock-2026",
                 "issue": "Precise site of earlier edition not located"},
                {"slug": "rock-in-bourlon",
                 "issue": "Archived registry differs from published history"},
                {"slug": "heavy-metal-breizh",
                 "issue": "Archived registry differs from published history"},
                {"slug": "bully-on-rocks",
                 "issue": "Archived registry differs from published history"},
                {"slug": "mozhell-open-air-2027", "issue": "Already signed"},
                {"slug": "betizfest-2027",
                 "issue": "Do not duplicate a second deferral"},
            ],
        }
        out = build_inventory(reports, catalogue, TODAY, patch=patch)
        self.assertEqual(out["patch_only_unpublished_references_count"], 6)
        self.assertEqual(out["total_named_leads"], 10)
        self.assertEqual(len({r["slug"] for r in
                              out["patch_only_unpublished_references"]}), 6)
        self.assertIn("betizfest-2027", {r["slug"] for r in
                      out["patch_only_unpublished_references"]})
        self.assertTrue(all(not r["publication_authorized"]
                            for r in out["patch_only_unpublished_references"]))
        self.assertEqual(out["publications"], 0)

    def test_private_patch_only_addition_is_not_automatically_approved(self):
        reports, catalogue = fixture()
        patch = {
            "schema": "grossesondes.patch.v1", "generated_at": TODAY,
            "safe_to_publish": False,
            "additions": [{"slug": "festival-jamais-repertorie-2027",
                           "name": "Festival jamais repertorie 2027",
                           "startDate": "2027-12-12"}],
            "deferred": [],
        }
        out = build_inventory(reports, catalogue, TODAY, patch=patch)
        self.assertEqual(out["patch_only_unpublished_references_count"], 1)
        lead = out["patch_only_unpublished_references"][0]
        self.assertEqual(lead["record_kinds"],
                         ["PRIVATE_ADDITION_NOT_PUBLISHED"])
        self.assertFalse(lead["publication_authorized"])

    def test_forged_or_stale_private_patch_fails_closed(self):
        reports, catalogue = fixture()
        template = {
            "schema": "grossesondes.patch.v1", "generated_at": TODAY,
            "safe_to_publish": False, "deferred": [], "additions": [],
        }
        for change in (
            {"safe_to_publish": True},
            {"generated_at": "2026-11-20"},
            {"deferred": [{"slug": "other/secret"}]},
            {"additions": ["wrong-shape"]},
        ):
            with self.subTest(change=change):
                patch = {**template, **change}
                with self.assertRaises(ValueError):
                    build_inventory(reports, catalogue, TODAY, patch=patch)

    def test_municipal_links_survive_rotating_away_from_earlier_city(self):
        reports, catalogue = fixture()
        before = deepcopy(reports["municipal"])
        before["rows"][0]["unknown_music_links_review_only"].append({
            "title_hint": "Festival jamais connu 2027",
            "detail_url_review_only": "https://new-city.fr/agenda/new-festival",
            "classification": "POSSIBLE_FESTIVAL_REVIEW_ONLY",
        })
        reports["municipal"]["rows"] = []
        result = build_inventory(reports, catalogue, TODAY,
                                 municipal_history=[before])
        self.assertEqual(result["municipal_current_cycle_leads_count"], 0)
        self.assertEqual(result["municipal_historical_carryover_count"], 2)
        self.assertEqual(result["municipal_intermediate_leads_count"], 2)
        self.assertEqual(result["total_named_leads"], 5)
        self.assertIn("Festival jamais connu 2027", [
            row["name"] for row in result["municipal_intermediate_leads"]])
        self.assertTrue(all(row["publication_authorized"] is False
                            for row in result["municipal_intermediate_leads"]))

    def test_municipal_history_deduplicated_and_does_not_count_ancient_clues(self):
        reports, catalogue = fixture()
        previous = deepcopy(reports["municipal"])
        expired = deepcopy(previous)
        expired["as_of"] = "2026-09-01"
        result = build_inventory(
            reports, catalogue, TODAY, municipal_history=[previous, expired])
        self.assertEqual(result["municipal_intermediate_leads_count"], 1)
        self.assertEqual(result["municipal_current_cycle_leads_count"], 1)
        self.assertEqual(result["municipal_historical_carryover_count"], 0)

    def test_untrusted_historical_municipal_cannot_authorize_publication(self):
        reports, catalogue = fixture()
        old = deepcopy(reports["municipal"])
        old["publication_authorized"] = True
        with self.assertRaises(ValueError):
            build_inventory(reports, catalogue, TODAY,
                            municipal_history=[old])

    def test_never_accepts_missing_stale_or_colliding_pipeline_stage(self):
        reports, catalogue = fixture()
        cases = []
        mismatch = deepcopy(reports)
        mismatch["editorial"]["dossiers"].pop()
        cases.append(mismatch)
        stale = deepcopy(reports)
        stale["funnel"]["as_of"] = "2026-11-20"
        cases.append(stale)
        forged = deepcopy(reports)
        forged["discovery"]["publication_authorized"] = True
        cases.append(forged)
        repeated = deepcopy(reports)
        repeated["handoff"]["dossiers"].append(
            deepcopy(repeated["handoff"]["dossiers"][0]))
        cases.append(repeated)
        for candidate in cases:
            with self.subTest(candidate=list(candidate)):
                with self.assertRaises(ValueError):
                    build_inventory(candidate, catalogue, TODAY)

    def test_signed_catalogue_is_the_only_exact_publication_authority(self):
        reports, catalogue = fixture()
        catalogue["festivals"] = []
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            build_inventory(reports, catalogue, TODAY)


if __name__ == "__main__":
    main()
