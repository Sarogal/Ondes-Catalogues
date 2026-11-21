"""Regression tests for all-stage, nonpublishing, open-world festival inventory."""
from copy import deepcopy
from unittest import TestCase, main
from national_blocker_inventory import build_inventory, SCHEMA

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
    municipal = dict(defaults, rows=[
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
        {"name": "MozHell Open Air 2027", "startDate": "2027-07-23"}]}
    return dict(discovery=discovery, editorial=editorial, funnel=funnel,
                handoff=handoff, municipal=municipal, concerts=concerts), catalogue


class BlockerInventoryTests(TestCase):
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

    def test_unfamiliar_festival_is_never_dropped_by_a_closed_registry(self):
        reports, catalogue = fixture()
        target = reports["discovery"]["dossiers"][0]
        target["name_hint"] = "Les Riffs du Bout du Monde"
        self.assertEqual(
            build_inventory(reports, catalogue, TODAY)["dossiers"][0]["name"],
            "Les Riffs du Bout du Monde")

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
