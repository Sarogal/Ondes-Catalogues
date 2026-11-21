"""Fail-closed offline tests for generic national Festival publisher routing."""
from copy import deepcopy
from unittest import TestCase, main
from unittest.mock import patch

from national_generic_publisher_funnel import build_report, SCHEMA
from grossesondes_generic_directory_edition import private_proposal

DAY = "2026-11-21"
NAME = "Festival Foudre Imaginaire"
TITLE = NAME + " 2027"
SITE = "https://foudre-imaginaire.fr/"
DATES = ("2027-06-25", "2027-06-26")


def fixture():
    discovery = {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "as_of": DAY,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False,
        "dossiers": [{
            "id": "national-inconnue-foudre-2027",
            "name_hint": NAME,
            "edition_year_hint": 2027,
            "safe_to_publish": False, "publication_authorized": False,
            "sources": [{
                "kind": "OPENAGENDA_PUBLIC_RESEARCH_ONLY",
                "url": "https://127.0.0.1/private-wrong-candidate",
                "publication_authorized": False,
            }],
        }],
    }
    patch = {
        "schema": "grossesondes.patch.v1",
        "generated_at": DAY, "safe_to_publish": False,
        "additions": [private_proposal(TITLE, SITE, DATES, DAY)],
    }
    assert patch["additions"][0] is not None
    signed = {"schema": 1, "festivals": []}
    return discovery, patch, signed


class GenericPublisherFunnelTests(TestCase):
    def test_new_unknown_festival_is_routed_without_named_registry(self):
        discovery, source, signed = fixture()
        # This is a STRUCTURAL proposal, not a source authorization.
        with patch("dns_pinned_https.fetch_public_html",
                   side_effect=AssertionError("no network in private audit")):
            result = build_report(discovery, source, signed, DAY)
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["dossiers_total"], 1)
        self.assertEqual(result["generic_publisher_recheck_pending_count"], 1)
        self.assertEqual(result["structurally_valid_private_generic_additions"], 1)
        self.assertIs(result["legacy_named_entity_registry_required"], False)
        self.assertFalse(result["publication_authorized"])
        self.assertFalse(result["publisher_recheck_executed_by_this_report"])
        self.assertEqual(result["publications"], 0)
        dossier = result["dossiers"][0]
        self.assertEqual(dossier["status"], "GENERIC_PUBLISHER_RECHECK_PENDING")
        self.assertEqual(
            dossier["candidate_proof_modes"],
            ["generic-directory-first-party-edition.v1"])
        self.assertFalse(dossier["publication_authorized"])
        self.assertFalse(dossier["independent_publisher_recheck_completed"])
        self.assertNotIn("officialSite", str(dossier))
        self.assertNotIn("127.0.0.1", str(result))

    def test_already_signed_editions_do_not_look_like_new_publications(self):
        discovery, source, signed = fixture()
        signed["festivals"].append({
            "name": TITLE,
            "slug": "festival-foudre-imaginaire-2027",
            "startDate": DATES[0],
            "endDate": DATES[1],
        })
        result = build_report(discovery, source, signed, DAY)
        self.assertEqual(result["already_signed_count"], 1)
        self.assertEqual(result["generic_publisher_recheck_pending_count"], 0)
        self.assertEqual(result["dossiers"][0]["status"],
                         "EXACT_EDITION_ALREADY_SIGNED")
        self.assertEqual(
            result["valid_generic_additions_not_linked_to_unpublished_national_dossier"], 1)

    def test_unknown_broken_or_forged_proof_does_not_enter_publisher_queue(self):
        for mutate in (
            lambda p: p["additions"][0].update(
                officialSite="https://attacker.example/"),
            lambda p: p["additions"][0].update(
                startDate="2027-06-27"),
            lambda p: p["additions"][0].update(
                proofMode="unreviewed-new-source.v9"),
            lambda p: p["additions"][0].update(
                lat=48.8, showOnMap=True),
            lambda p: p["additions"][0].update(
                verified_at="2026-10-01"),
        ):
            with self.subTest(mutate=mutate):
                discovery, source, signed = fixture()
                mutate(source)
                result = build_report(discovery, source, signed, DAY)
                self.assertEqual(
                    result["generic_publisher_recheck_pending_count"], 0)
                self.assertFalse(result["publication_authorized"])

    def test_plausible_forged_date_is_only_a_recheck_lead(self):
        # A date can remain STRUCTURALLY consistent after tampering. This
        # private audit never declares the source proof complete: only the
        # independent Publisher can fetch the true first-party announcement.
        discovery, source, signed = fixture()
        source["additions"][0]["startDate"] = "2027-06-24"
        output = build_report(discovery, source, signed, DAY)
        self.assertEqual(output["generic_publisher_recheck_pending_count"], 1)
        self.assertFalse(output["publication_authorized"])
        self.assertFalse(
            output["dossiers"][0]["independent_publisher_recheck_completed"])

    def test_same_identity_duplicate_private_proposals_must_not_advance(self):
        discovery, source, signed = fixture()
        source["additions"].append(deepcopy(source["additions"][0]))
        result = build_report(discovery, source, signed, DAY)
        self.assertEqual(result["ambiguous_generic_proposals_count"], 1)
        self.assertEqual(result["generic_publisher_recheck_pending_count"], 0)
        self.assertFalse(result["dossiers"][0]["publication_authorized"])

    def test_forged_favorable_status_or_stale_queue_is_rejected(self):
        mutations = [
            lambda d,p,s: d.update(publication_authorized=True),
            lambda d,p,s: d.update(safe_to_publish=True),
            lambda d,p,s: d.update(as_of="2026-11-20"),
            lambda d,p,s: p.update(safe_to_publish=True),
            lambda d,p,s: p.update(generated_at="2026-11-20"),
            lambda d,p,s: p["additions"].append("not a proposal"),
            lambda d,p,s: s.update(schema=99),
            lambda d,p,s: d["dossiers"][0].update(
                publication_authorized=True),
            lambda d,p,s: d["dossiers"].append(deepcopy(d["dossiers"][0])),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                bundle = list(fixture())
                mutate(*bundle)
                with self.assertRaises(ValueError):
                    build_report(*bundle, DAY)

    def test_missing_or_unregistered_dossier_stays_pending_source_proof(self):
        d, p, s = fixture()
        p["additions"] = []
        result = build_report(d, p, s, DAY)
        self.assertEqual(result["still_without_generic_proposal_count"], 1)
        self.assertEqual(result["generic_publisher_recheck_pending_count"], 0)
        self.assertFalse(result["publication_authorized"])


if __name__ == "__main__":
    main()
