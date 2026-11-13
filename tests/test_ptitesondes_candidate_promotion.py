"""No-network guards for prospective outings promotions; no production writes."""
from datetime import date, timedelta
from urllib.error import HTTPError
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from ptitesondes_candidate_promotion import (
    api_record, category_for, confirmed_session, evaluate, main, make_event,
    permitted, reconciled_openagenda_url, registry_location, scheduled,
    covered_by_published_range, public_run_summary,
    admission_failure_group, private_admission_diagnostics,
)
from merge_policy import ORIGIN, merge
from venue_registry import VENUES, verified_location
from proof import meters

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

    def test_public_diagnostic_output_never_exposes_private_reasons(self):
        source = {
            "date": "2026-11-09", "backlog_total": 229,
            "eligible_with_reviewed_venue": 29,
            "eligible_raw": 36, "duplicate_collector_leads_skipped": 7,
            "conflicting_uid_days_deferred": 0,
            "checked": 15, "accepted_preflight": 0,
            "reason_counts": {
                "deferred: PRIVATE_TOKEN=https://private.invalid": 15
            },
            "details": [{"source_url": "https://private.invalid/secret",
                         "reason": "PRIVATE_TOKEN"}],
        }
        result = public_run_summary(source)
        self.assertEqual(result["duplicate_collector_leads_skipped"], 7)
        self.assertEqual(result["eligible_raw"], 36)
        self.assertEqual(result["mode"], "preview_no_public_write")
        encoded = json.dumps(result)
        self.assertNotIn("private.invalid", encoded)
        self.assertNotIn("PRIVATE_TOKEN", encoded)
        self.assertNotIn("reason_counts", encoded)
        self.assertNotIn("details", encoded)
        with self.assertRaises(ValueError):
            public_run_summary(dict(source, date="secret"))

    def test_exact_registry_alias_required(self):
        self.assertEqual(registry_location(lead())["city"], "Nantes")
        self.assertIsNone(registry_location(lead(venue="Théâtre de Jeanne imaginaire")))
        self.assertFalse(permitted(lead(venue="Théâtre de Jeanne imaginaire"), TODAY))


    def test_three_official_venues_from_new_agendas_require_exact_identity(self):
        audited = (
            ("Tourcoing", "Médiathèque André Malraux",
             50.716504, 3.159680),
            ("Tourcoing", "Tourcoing/Médiathèque André Malraux",
             50.716504, 3.159680),
            ("Nantes", "Centre socioculturel des Bourderies - ACCOORD",
             47.206794, -1.596206),
            ("Tourcoing", "Tourcoing/Médiathèque Aimé Césaire",
             50.695554, 3.151515),
        )
        for city, venue, source_lat, source_lng in audited:
            with self.subTest(city=city, venue=venue):
                item = {"city": city, "venue": venue}
                location = registry_location(item)
                self.assertIsNotNone(location)
                self.assertLessEqual(
                    meters((source_lat, source_lng),
                           (location["lat"], location["lng"])), 65)
                self.assertTrue(verified_location(
                    dict(item, lat=location["lat"], lng=location["lng"]))[0])
                self.assertIsNone(registry_location(dict(
                    item, venue=venue + " autre bâtiment")))
        # IGN BAN est à ~90 m du point OA Andrée Chedid : ne pas admettre.
        self.assertIsNone(registry_location({
            "city": "Tourcoing", "venue": "Médiathèque Andrée Chedid"}))
        self.assertFalse(verified_location({
            "city": "Tourcoing", "venue": "Médiathèque Andrée Chedid",
            "lat": 50.729135, "lng": 3.145110})[0])

    def test_only_official_openagenda_leads(self):
        self.assertTrue(permitted(lead(), TODAY))
        # Les pistes de l’API OpenAgenda v2 doivent passer les mêmes contrôles
        # indépendants que celles de l’index ODS, sans passe-droit.
        self.assertTrue(permitted(dict(lead(), collector="openagenda-v2"), TODAY))
        self.assertFalse(permitted(dict(lead(), collector="untrusted-source"), TODAY))
        self.assertFalse(permitted(dict(lead(), collector="openagenda-v2",
                                        external_id="invalid"), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url="https://example.org/valid"), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url="http://openagenda.com/fake"), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url="https://openagenda.com@evil.example/"), TODAY))
        self.assertFalse(permitted(dict(lead(), source_url=URL + "?token=fake"), TODAY))
        self.assertFalse(permitted(dict(lead(), external_id="../../secret"), TODAY))
        self.assertFalse(permitted(dict(lead(), date_start="2025-02-10"), TODAY))

    def test_private_admission_diagnostics_are_exact_and_never_authority(self):
        valid_lead = lead()
        bad_venue = lead(venue="Médiathèque fictive de test")
        cases = [
            (valid_lead, "eligible"),
            (bad_venue, "venue_gps_unverified"),
            (dict(bad_venue, venue=""), "missing_venue"),
            (dict(valid_lead, collector="untrusted"), "collector"),
            (dict(valid_lead, external_id="../fake"), "uid"),
            (dict(valid_lead, source_url="http://openagenda.com/fake"), "source_url"),
            (dict(valid_lead, date_start="2025-11-01"), "session_date"),
            (dict(valid_lead, city=""), "missing_identity"),
        ]
        for entry, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(admission_failure_group(entry, TODAY), expected)
                self.assertEqual(permitted(entry, TODAY), expected == "eligible")
        report = private_admission_diagnostics([x for x, _ in cases] +
                                               [dict(bad_venue)], TODAY)
        self.assertEqual(report["raw_leads"], 9)
        self.assertEqual(report["reason_counts"]["venue_gps_unverified"], 2)
        self.assertEqual(report["reason_counts"]["eligible"], 1)
        self.assertEqual(report["top_unverified_venues"][0]["lead_occurrences"], 2)
        self.assertEqual(report["top_unverified_venues"][0]["city"], "Nantes")
        self.assertEqual(report["top_unverified_venues"][0]["venue"],
                         "Médiathèque fictive de test")

    def test_private_venue_diagnostics_never_leak_through_public_allowlist(self):
        report = {"date": "2026-11-12", "backlog_total": 366,
                  "eligible_with_reviewed_venue": 53, "checked": 15,
                  "accepted_preflight": 0,
                  "admission_diagnostics": {
                      "top_unverified_venues": [
                          {"city": "VILLE PRIVEE TEST", "venue": "LIEU PRIVE TEST"}
                      ]},
                  "reason_counts": {"private evidence": 1}}
        safe = json.dumps(public_run_summary(report), ensure_ascii=False)
        self.assertNotIn("VILLE PRIVEE TEST", safe)
        self.assertNotIn("LIEU PRIVE TEST", safe)
        self.assertNotIn("admission_diagnostics", safe)
        self.assertNotIn("private evidence", safe)

    def test_categorization_rejects_adult_music(self):
        self.assertEqual(category_for(lead()["title"], "")[0], "conte-musical")
        self.assertIsNone(category_for("Ciné-concert METROPOLIS", "Grand film muet"))
        self.assertIsNone(category_for("Concert Beethoven", "A l'Opéra"))
        self.assertEqual(category_for("Éveil musical", "Bibliothèque")[0], "eveil-musical")

    def test_official_family_description_can_classify_a_short_work_title(self):
        self.assertEqual(category_for("Momo, l'enfant pêche",
                         "Famille | Conte musical à partir de 6 ans")[0],
                         "conte-musical")
        self.assertEqual(category_for("Les Drôles de petites bêtes",
                         "Famille | Ciné-concert dès 4 ans")[0],
                         "cine-concert")
        self.assertEqual(category_for("Ici, là-bas",
                         "Famille | Concert à partir de 18 mois")[0],
                         "concert")
        self.assertIsNone(category_for("Momo, l'enfant pêche",
                          "Une aventure racontée aux visiteurs adultes"))
        self.assertIsNone(category_for("Concert classique pour adultes",
                          "Concert classique sans public familial identifié"))

    def test_only_exact_local_performance_days(self):
        times = record()["timings"]
        self.assertEqual(confirmed_session(times, DAY), "14:30")
        self.assertEqual(confirmed_session(times, "2027-02-14"), "15:00")
        with self.assertRaises(ValueError):
            confirmed_session(times, "2027-02-11")
        with self.assertRaises(ValueError):
            confirmed_session([{"begin":"2027-02-10T14:30"}], DAY)

    def test_curated_school_only_slots_are_never_published_as_family_outings(self):
        # First-party organizer schedules differentiate schools and family seats.
        momo = [
            {"begin": "2027-01-22T14:30:00+01:00"},
            {"begin": "2027-01-22T19:00:00+01:00"},
        ]
        self.assertEqual(confirmed_session(momo, "2027-01-22", "54065371"), "19:00")
        scolaire = [{"begin": "2027-01-28T14:30:00+01:00"}]
        with self.assertRaisesRegex(ValueError, "scolaire"):
            confirmed_session(scolaire, "2027-01-28", "66367832")
        self.assertEqual(confirmed_session(
            [{"begin": "2027-01-29T19:00:00+01:00"}],
            "2027-01-29", "66367832"), "19:00")
        # A different UID must never inherit the school's exclusion.
        self.assertEqual(confirmed_session(scolaire, "2027-01-28", "11111"), "14:30")

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

    def test_openagenda_v2_lead_still_requires_independent_proof(self):
        ref = base()
        direct = dict(lead(), collector="openagenda-v2")
        p, report = evaluate([direct], ref, ref, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda event, originals: (False, "No official session proof"))
        self.assertEqual(p["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(report["details"][0]["status"], "unverified")
        p, report = evaluate([direct], ref, ref, TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda event, originals: (True, "verified"))
        self.assertEqual(report["accepted_preflight"], 1)
        self.assertEqual(len(p["additions"]), 1)
        self.assertFalse(p["safe_to_publish"])
        self.assertTrue(p["checks"]["official_sources_verified"])

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

    def test_existing_multi_day_public_card_blocks_later_single_day_duplicate(self):
        ref = base()
        same = make_event(lead(), record(), registry_location(lead()), TODAY)
        existing = dict(same, id="family-nantes-combined-2027-02-09",
                        date_start="2027-02-09", date_end="2027-02-10")
        public = dict(ref, events=ref["events"] + [existing])
        self.assertTrue(covered_by_published_range(lead(), public["events"]))
        def never_fetch(uid):
            self.fail("A published multi-day range must stop the query upstream")
        patch_doc, report = evaluate([lead()], ref, public, TODAY, fetch=never_fetch)
        self.assertEqual(patch_doc["additions"], [])
        # Full/forensic audits intentionally retain their old semantics:
        # only the scheduled intake opts into pre-batch skipping.
        self.assertEqual(report["already_published_before_batch"], 0)
        self.assertEqual(report["details"][0]["status"], "already_published")
        self.assertIn("couverte", report["details"][0]["reason"])

    def test_prebatch_skip_frees_slot_for_future_unpublished_date(self):
        # Five already-published dates used to waste the entire small review
        # window. Their identity must remain strict; the distinct 10 February
        # performance retains the same independent proof chain.
        ref = base()
        published_days = [
            (date(2027, 1, 6) + timedelta(days=i)).isoformat()
            for i in range(5)
        ]
        known = [
            dict(ref["events"][i], id="published-family-" + str(i),
                 title=lead()["title"], venue="Théâtre de Jeanne",
                 date_start=day, date_end=day)
            for i, day in enumerate(published_days)
        ]
        public = dict(ref, events=ref["events"] + known)
        candidates = [lead(day=day) for day in published_days] + [lead()]
        patch_doc, report = evaluate(
            candidates, ref, public, TODAY,
            fetch=lambda uid: record(),
            verifier=lambda event, originals: (True, "official proof"),
            limit=1, slot=0, skip_published_prebatch=True)
        self.assertEqual(report["eligible_raw"], 6)
        self.assertEqual(report["already_published_before_batch"], 5)
        self.assertEqual(report["eligible_with_reviewed_venue"], 1)
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["accepted_preflight"], 1)
        self.assertEqual(report["deferred_or_duplicates"], 0)
        self.assertEqual([item["date_start"] for item in patch_doc["additions"]],
                         [DAY])
        self.assertFalse(patch_doc["safe_to_publish"])

    def test_prebatch_cannot_mask_new_date_or_different_venue(self):
        published = [{"id": "openagenda-77081258-2027-02-09",
                      "title": lead()["title"], "city": "Nantes",
                      "venue": "Théâtre de Jeanne", "date_start": "2027-02-09",
                      "date_end": "2027-02-09"}]
        self.assertFalse(covered_by_published_range(lead(), published))
        self.assertFalse(covered_by_published_range(
            lead(day="2027-02-09", venue="Autre salle"), published))
        self.assertFalse(covered_by_published_range(
            dict(lead(), title="Titre différent", date_start="2027-02-09"),
            published))

    def test_range_dedup_checks_date_title_city_and_venue_exactly(self):
        existing = {"title":"Momo, l’enfant pêche", "city":"Bordeaux",
                    "venue":"Auditorium de Bordeaux",
                    "date_start":"2027-01-21", "date_end":"2027-01-22"}
        candidate = {"title":"Momo, l'enfant pêche", "city":"Bordeaux",
                     "venue":"Auditorium de Bordeaux", "date_start":"2027-01-22"}
        self.assertTrue(covered_by_published_range(candidate, [existing]))
        other = {"title":"Ici, là-bas", "city":"Bordeaux",
                 "venue":"Grand Théâtre - Foyer rouge",
                 "date_start":"2027-02-07"}
        published = {"title":"Ici, là-bas", "city":"Bordeaux",
                     "venue":"Grand-Théâtre – Foyer rouge",
                     "date_start":"2027-02-06", "date_end":"2027-02-07"}
        self.assertTrue(covered_by_published_range(other, [published]))
        for different in (
            dict(candidate, title="Un autre spectacle"),
            dict(candidate, city="Paris"),
            dict(candidate, venue="Autre salle"),
            dict(candidate, date_start="2027-01-23"),
        ):
            with self.subTest(different=different):
                self.assertFalse(covered_by_published_range(different, [existing]))
        self.assertFalse(covered_by_published_range(
            candidate, [dict(existing, date_end="not-a-date")]))

    def test_school_only_time_takes_priority_over_missing_family_description(self):
        school = dict(lead(), external_id="66367832",
                      date_start="2027-01-28", date_end="2027-01-28")
        details = dict(record(), uid="66367832",
                       title_fr=school["title"],
                       description_fr="Ciné-concert",
                       timings='[{"begin":"2027-01-28T14:30:00+01:00"}]')
        with self.assertRaisesRegex(ValueError, "scolaire"):
            make_event(school, details, registry_location(school), TODAY)

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

    def test_exact_momo_historical_time_fix_preserves_preflight(self):
        ref = base()
        original = ref["events"][0]
        original.update(
            id="bordeaux-momo-enfant-peche-2027-01-21",
            date_start="2027-01-21", date_end="2027-01-22",
            source_url="https://www.opera-bordeaux.com/famille-orchestre-momo-lenfant-peche-86301",
            time="21 janv. 19:00 ; 22 janv. 14:30 (scolaires) et 19:00")
        edited = dict(original, time="21 janv. 19:00 ; 22 janv. 19:00")
        public = dict(ref, events=[edited] + ref["events"][1:])
        patch_doc, report = evaluate([], ref, public, TODAY)
        self.assertEqual(patch_doc["additions"], [])
        self.assertEqual(report["checked"], 0)
        malformed = dict(ref, events=[dict(edited, title="Falsifié")] + ref["events"][1:])
        with self.assertRaisesRegex(ValueError, "historique"):
            evaluate([], ref, malformed, TODAY)

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

    def test_two_collectors_retry_only_strict_canonical_alias_for_one_uid_day(self):
        ref = base()
        ods = dict(lead(), source_url=URL + "-old-index-slug")
        canonical_oa = dict(lead(), collector="openagenda-v2",
            source_url=("https://openagenda.com/"
                        "contributions-evenements-culturels-nantes-et-metropole-nantaise/"
                        "events/77081258_jeune-public-concertconte-musical-un-animal-des-amis-mots"))
        # The ODS lead's old slug is not canonical; the OA-v2 UID-prefixed
        # alias MUST still pass the same-agenda and exact-UID checks.
        result, report = evaluate([ods, canonical_oa], ref, ref, TODAY,
                                   fetch=lambda uid: record(),
                                   verifier=lambda ev, old: (True, "proved"))
        self.assertEqual(report["eligible_raw"], 2)
        self.assertEqual(report["duplicate_collector_leads_skipped"], 1)
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["accepted_preflight"], 1)
        self.assertEqual(result["additions"][0]["source_url"], URL)

    def test_cross_agenda_fallback_cannot_bypass_canonical_policy(self):
        ref = base()
        ods = dict(lead(), source_url=URL + "-old-index-slug")
        unreviewed = dict(lead(), collector="openagenda-v2",
                          source_url="https://openagenda.com/untrusted/events/77081258_jeune-public-concertconte-musical-un-animal-des-amis-mots")
        result, report = evaluate([ods, unreviewed], ref, ref, TODAY,
                                   fetch=lambda uid: record(),
                                   verifier=lambda ev, old: (True, "proved"))
        self.assertEqual(result["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(report["details"][0]["status"], "deferred")

    def test_conflicting_same_collector_sources_are_not_a_fallback(self):
        ref = base()
        first = lead()
        conflicting = dict(lead(), source_url=URL + "-different")
        result, report = evaluate([first, conflicting], ref, ref, TODAY,
                                   fetch=lambda uid: self.fail("Conflicting URL must never be fetched"),
                                   verifier=lambda ev, old: (True, "proved"))
        self.assertEqual(result["additions"], [])
        self.assertEqual(report["conflicting_uid_days_deferred"], 1)
        self.assertEqual(report["checked"], 0)

    def test_oa_v2_url_alias_requires_uid_and_agenda(self):
        alias = dict(lead(), collector="openagenda-v2",
                     source_url=("https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/events/"
                                 "77081258_jeune-public-concertconte-musical-un-animal-des-amis-mots"))
        self.assertEqual(reconciled_openagenda_url(alias, record()), URL)
        item = make_event(alias, record(), registry_location(alias), TODAY)
        self.assertEqual(item["source_url"], URL)
        p, report = evaluate([alias], base(), base(), TODAY,
                             fetch=lambda uid: record(),
                             verifier=lambda event, originals: (False, "official proof absent"))
        self.assertEqual(p["additions"], [])
        self.assertEqual(report["details"][0]["status"], "unverified")

    def test_oa_v2_alias_rejects_cross_identity_or_unsafe_destination(self):
        alias = dict(lead(), collector="openagenda-v2",
                     source_url="https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/events/77081258_generated-path")
        invalid = (
            dict(alias, external_id="99999"),
            dict(alias, collector="opendatasoft-index"),
            dict(alias, source_url=alias["source_url"].replace("/77081258_", "/999999_")),
            dict(alias, source_url=alias["source_url"].replace("openagenda.com", "evil.example")),
            dict(alias, source_url=alias["source_url"] + "?q=1"),
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    reconciled_openagenda_url(candidate, record())
        for target in (
            "https://openagenda.com/other-agenda/events/slug",
            "https://openagenda.com.evil.example/other/events/slug",
            "https://openagenda.com:444/contributions-evenements-culturels-nantes-et-metropole-nantaise/events/slug",
            "https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/events/slug#fragment",
            "http://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/events/slug",
        ):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    reconciled_openagenda_url(alias, dict(record(), canonicalurl=target))

    def test_reviewed_marseille_alcazar_syndication_requires_exact_uid_and_slug(self):
        # OpenAgenda's official Marseille library network has a dedicated
        # Alcazar subagenda and an aggregate municipal library agenda.
        uid = "95978351"
        slug = "1001-jeux-sonores-avec-les-animaux-dillustration-jeunesse-4575496"
        subagenda = ("https://openagenda.com/bibliotheque-lalcazar-marseille/events/"
                     + uid + "_" + slug)
        city_agenda = "https://openagenda.com/bibliotheques-de-marseille/events/" + slug
        candidate = dict(lead(), collector="openagenda-v2", external_id=uid,
                         source_url=subagenda)
        self.assertEqual(
            reconciled_openagenda_url(candidate, dict(record(), canonicalurl=city_agenda)),
            city_agenda)
        # The same matching URL from the ODS index alone is not an alias.
        for forbidden in (
            dict(candidate, collector="opendatasoft-index"),
            dict(candidate, external_id="99999999"),
            dict(candidate, source_url=subagenda.replace(uid + "_", "")),
            dict(candidate, source_url=subagenda.replace("bibliotheque-lalcazar-marseille",
                                                       "unreviewed-marseille-agenda")),
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(ValueError, "canonique différente"):
                    reconciled_openagenda_url(forbidden,
                                              dict(record(), canonicalurl=city_agenda))
        for forbidden_target in (
            city_agenda.replace("bibliotheques-de-marseille", "unreviewed-aggregate"),
            city_agenda.replace(slug, "unrelated-event"),
        ):
            with self.subTest(target=forbidden_target):
                with self.assertRaisesRegex(ValueError, "canonique différente"):
                    reconciled_openagenda_url(candidate,
                                              dict(record(), canonicalurl=forbidden_target))

    def test_reviewed_bordeaux_syndication_requires_exact_slug_and_uid(self):
        # Public ODS mirror records inspected on 2026-11-05: the three
        # immutable UIDs are identical, while syndication changes the agenda.
        pairs = (
            ("54065371", "momo-lenfant-peche-3216479"),
            ("66367832", "les-droles-de-petites-betes-8323158"),
            ("30568209", "ici-la-bas-5324637"),
        )
        for uid, slug in pairs:
            private = dict(lead(),
                           collector="openagenda-v2",
                           external_id=uid,
                           source_url=("https://openagenda.com/operanationalbordeaux/events/"
                                       + uid + "_" + slug))
            ods = dict(record(), uid=uid,
                       canonicalurl="https://openagenda.com/ville-de-bordeaux/events/" + slug)
            with self.subTest(uid=uid):
                self.assertEqual(reconciled_openagenda_url(private, ods),
                                 ods["canonicalurl"])
                # Even an accepted alias does not bypass first-party proof.
                clone = dict(ods, title_fr=private["title"])
                public, report = evaluate([private], base(), base(), TODAY,
                                          fetch=lambda _: clone,
                                          verifier=lambda ev, old: (False, "organizer proof absent"))
                self.assertEqual(public["additions"], [])
                # Venue and family category checks remain in place.
                self.assertGreaterEqual(report["deferred_or_duplicates"], 1)
                for changed in (
                    dict(private, external_id="99999"),
                    dict(private, source_url=private["source_url"].replace(
                         uid + "_", uid + "_different-")),
                    dict(private, source_url=private["source_url"].replace(
                         "operanationalbordeaux", "untrusted-agenda")),
                    dict(private, collector="opendatasoft-index"),
                ):
                    with self.assertRaises(ValueError):
                        reconciled_openagenda_url(changed, ods)
                with self.assertRaises(ValueError):
                    reconciled_openagenda_url(private, dict(ods,
                        canonicalurl=ods["canonicalurl"].replace(slug, "another-title")))

    def test_ods_retry_transient_reset_and_bounded_permanent_timeout(self):
        calls = []
        def recovering(url):
            calls.append(url)
            if len(calls) == 1:
                raise ConnectionResetError("connection reset by peer")
            return {"results": [record()]}
        with patch("ptitesondes_candidate_promotion.time.sleep") as sleep:
            self.assertEqual(api_record("77081258", get=recovering)["uid"], "77081258")
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(0.4)

        calls = []
        def unavailable(url):
            calls.append(url)
            raise TimeoutError("unavailable")
        with patch("ptitesondes_candidate_promotion.time.sleep") as sleep:
            with self.assertRaises(TimeoutError):
                api_record("77081258", get=unavailable)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_ods_no_retry_for_http_404_or_malformed_payload(self):
        calls = []
        def missing(url):
            calls.append(url)
            raise HTTPError(url, 404, "Not Found", {}, None)
        with patch("ptitesondes_candidate_promotion.time.sleep") as sleep:
            with self.assertRaises(HTTPError):
                api_record("77081258", get=missing)
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()
        calls = []
        def malformed(url):
            calls.append(url)
            return {"results": "invalid"}
        with self.assertRaisesRegex(ValueError, "malformée"):
            api_record("77081258", get=malformed)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
