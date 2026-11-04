"""No-network guards for prospective outings promotions; no production writes."""
from datetime import date, timedelta
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from ptitesondes_candidate_promotion import (
    api_record, category_for, confirmed_session, evaluate, main, make_event,
    permitted, registry_location, scheduled,
)
from merge_policy import ORIGIN, merge
from venue_registry import VENUES

TODAY = date(2026, 11, 4)
DAY = "2027-02-10"
URL = ("https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/"
       "events/jeune-public-concertconte-musical-un-animal-des-amis-mots")


def lead(day=DAY, venue="Théâtre de Jeanne"):
    return {"external_id": "77081258",
            "collector": "opendatasoft-index", "title": 'Jeune public - Concert/Conte musical - "Un animal, des amis mots"',
            "city": "Nantes", "venue": venue, "source_url": URL,
            "date_start": day, "date_end": day}


def record():
    return {
        "uid": "77081258", "title_fr": lead()["title"],
        "description_fr": "Un conte musical en famille à partir de 3 ans",
        "canonicalurl": URL, "originagenda_title": "Nantes Métropole",
        "location_city": "Nantes", "location_name": "Théâtre de Jeanne",
        "location_department": "Loire-Atlantique",
        "location_region": "Pays de la Loire", "location_countrycode": "FR",
        "location_coordinates": {"lat": 47.20457, "lon": -1.57551},
        "timings": '[{"begin":"2027-02-10T14:30:00+01:00", "end":"2027-02-10T15:20:00+01:00"}, '
                   '{"begin":"2027-02-14T15:00:00+01:00", "end":"2027-02-14T15:50:00+01:00"}]',
        "status": '{"id":1, "label":{"fr":"Programmé"}}',
    }


def base():
    events = []
    for i in range(100):
        events.append({
            "id": "old-" + str(i), "title": "Autre conte " + str(i),
            "category": "conte-musical", "category_label": "Conte musical",
            "date_start": "2026-11-13", "date_end": "2026-11-13",
            "time": "14:30", "city": "Nantes", "venue": "Théâtre de Jeanne",
            "department": "Loire-Atlantique", "region": "Pays de la Loire",
            "source_url": URL, "source_label": "Test", "verified_at": str(TODAY),
            "geo_verified_at": str(TODAY), "geo_precision": "venue",
            "lat": 47.20457, "lng": -1.57551,
        })
    return {"version": 3, "updated_at": "2026-10-22T21:00:00+02:00", "events": events}


class CandidatePromotionTests(unittest.TestCase):
    def test_cli_can_consume_only_local_private_files_without_github_token(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            backlog_file = root / "backlog.json"
            ref_file = root / "reference.json"
            catalogue_file = root / "catalogue.json"
            output = root / "output"
            backlog_file.write_text("[]", encoding="utf-8")
            ref_file.write_text(json.dumps(base()), encoding="utf-8")
            catalogue_file.write_text(json.dumps(base()), encoding="utf-8")
            argv = ["candidate_promotion.py", "--backlog-file", str(backlog_file),
                    "--reference-file", str(ref_file),
                    "--catalogue-file", str(catalogue_file),
                    "--output-dir", str(output), "--date", str(TODAY)]
            with patch.object(sys, "argv", argv):
                with patch.dict("os.environ", {"PRIVATE_INTAKE_READ_TOKEN": ""}):
                    main()
            candidate = json.loads((output / "preview-patch.json").read_text())
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(candidate["additions"], [])
            self.assertEqual(candidate["generated_at"], str(TODAY))
            self.assertFalse(candidate["safe_to_publish"])
            self.assertEqual(report["backlog_total"], 0)

    def test_exact_registry_alias_required(self):
        self.assertEqual(registry_location(lead())["city"], "Nantes")
        self.assertIsNone(registry_location(lead(venue="Théâtre de Jeanne imaginaire")))
        self.assertFalse(permitted(lead(venue="Théâtre de Jeanne imaginaire"), TODAY))

    def test_only_official_openagenda_leads(self):
        self.assertTrue(permitted(lead(), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url="https://example.org/valid"), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url="http://openagenda.com/fake"), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url="https://openagenda.com@evil.example/"), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url=URL + "?token=fake"), TODAY))
        self.assertFalse(permitted(dict(lead(), external_id="../../secret"), TODAY))
        self.assertFalse(permitted(dict(lead(), date_start="2025-02-10"), TODAY))

    def test_categorization_rejects_adult_music(self):
        self.assertEqual(category_for(lead()["title"], "")[0], "conte-musical")
        self.assertIsNone(category_for("Ciné-concert METROPOLIS", "Grand film muet"))
        self.assertIsNone(category_for("Concert Beethoven", "A l'Opéra"))
        self.assertEqual(category_for("Éveil musical", "Bibliothèque")[0], "eveil-musical")

    def test_only_exact_local_performance_days(self):
        times = record()["timings"]
        self.assertEqual(confirmed_session(times, DAY), "14:30")
        self.assertEqual(confirmed_session(times, "2027-02-14"), "15:00")
        with self.assertRaises(ValueError):
            confirmed_session(times, "2027-02-11")
        with self.assertRaises(ValueError):
            confirmed_session([{"begin":"2027-02-10T14:30"}], DAY)

    def test_require_programmed_status(self):
        self.assertTrue(scheduled(record()))
        self.assertFalse(scheduled(dict(record(), status='{"id":3}')))
        self.assertFalse(scheduled(dict(record(), status=None)))
        self.assertFalse(scheduled(dict(record(), status="garbage")))

    def test_refuse_changed_venue_or_wrong_coords(self):
        place = registry_location(lead())
        with self.assertRaisesRegex(ValueError, "Lieu différent"):
            make_event(lead(), dict(record(), location_name="Salle fictive"), place, TODAY)
        with self.assertRaisesRegex(ValueError, "Position source"):
            make_event(lead(), dict(record(), location_coordinates={"lat": 45, "lon": -1.57551}), place, TODAY)

    def test_build_does_not_invent_age_or_price(self):
        item = make_event(lead(), record(), registry_location(lead()), TODAY)
        self.assertEqual(item["id"], "openagenda-77081258-2027-02-10")
        self.assertEqual(item["time"], "14:30")
        self.assertEqual(item["date_start"], item["date_end"])
        self.assertEqual(item["source_url"], URL)
        self.assertNotIn("price", item)
        self.assertNotIn("age_min", item)
        self.assertNotIn("description", item)

    def test_synthesized_patch_compatible_with_existing_merge_policy(self):
        ref = base()
        p, report = evaluate([lead()], ref, ref, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda event, originals: (True, "verified"))
        self.assertEqual(report["accepted_preflight"], 1)
        self.assertEqual(p["safe_to_publish"], False)
        self.assertEqual(p["updates"], [])
        self.assertEqual(len(p["additions"]), 1)
        result, result_report = merge(ref, ref, p, TODAY,
                                      checker=lambda event, originals: (True, "verified"))
        self.assertEqual(result_report["ajoutes"], 1)
        self.assertEqual(result["events"][:100], ref["events"])

    def test_failed_independent_proof_keeps_deferred(self):
        ref = base()
        p, report = evaluate([lead()], ref, ref, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda event, originals: (False, "No date on organizer page"))
        self.assertEqual(len(p["additions"]), 0)
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(report["details"][0]["status"], "unverified")

    def test_cross_source_title_prefix_does_not_republish_existing_show(self):
        reference = base()
        existing = make_event(lead(), record(), registry_location(lead()), TODAY)
        official = dict(existing,
                        id="nantes-un-animal-des-amis-mots-2027-02-10",
                        title="Un animal, des amis mots",
                        source_url=("https://www.theatre-jeanne.com/spectacle/"
                                    "un-animal-des-amis-mots/2027-02-10/"))
        published = dict(reference, events=reference["events"] + [official])
        p, report = evaluate([lead()], reference, published, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda e, originals: (True, "proof"))
        self.assertEqual(p["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(report["details"][0]["status"], "already_published")

    def test_cross_source_title_does_not_mask_another_session_day(self):
        reference = base()
        existing = make_event(lead(), record(), registry_location(lead()), TODAY)
        official = dict(existing,
                        id="nantes-un-animal-des-amis-mots-2027-02-10",
                        title="Un animal, des amis mots",
                        source_url=("https://www.theatre-jeanne.com/spectacle/"
                                    "un-animal-des-amis-mots/2027-02-10/"))
        published = dict(reference, events=reference["events"] + [official])
        other_day = lead(day="2027-02-14")
        p, report = evaluate([other_day], reference, published, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda e, originals: (True, "proof"))
        self.assertEqual(report["accepted_preflight"], 1)
        self.assertEqual(p["additions"][0]["date_start"], "2027-02-14")

    def test_existing_id_and_semantic_duplication_blocked(self):
        ref = base()
        e = make_event(lead(), record(), registry_location(lead()), TODAY)
        public = dict(ref, events=ref["events"] + [e])
        p, report = evaluate([lead()], ref, public, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda event, originals: (True, "verified"))
        self.assertEqual(len(p["additions"]), 0)
        self.assertEqual(report["details"][0]["status"], "already_published")
        self.assertEqual(len(public["events"]), 101)

    def test_immutable_historical_baseline_required(self):
        ref = base()
        public = dict(ref, events=[dict(ref["events"][0], title="Falsifié")] + ref["events"][1:])
        with self.assertRaises(ValueError):
            evaluate([lead()], ref, public, TODAY, fetch=lambda uid: record())

    def test_reject_api_uid_collision(self):
        with self.assertRaisesRegex(ValueError, "UID"):
            api_record("not-a-number", get=lambda url: {})
        with self.assertRaisesRegex(ValueError, "non unique"):
            api_record("77081258", get=lambda url: {
                "results": [{"uid":"77081258"}, {"uid":"77081258"}]})
        record_from_network = api_record("77081258", get=lambda url: {
            "results": [record()]})
        self.assertEqual(record_from_network["uid"], "77081258")

    def test_nonconsecutive_days_get_separate_ids(self):
        ref = base()
        x, y = lead("2027-02-10"), lead("2027-02-14")
        p, report = evaluate([x, y], ref, ref, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda event, originals: (True, "verified"))
        self.assertEqual([e["date_start"] for e in p["additions"]],
                         ["2027-02-10", "2027-02-14"])
        self.assertEqual(len({e["id"] for e in p["additions"]}), 2)


if __name__ == "__main__":
    unittest.main()
