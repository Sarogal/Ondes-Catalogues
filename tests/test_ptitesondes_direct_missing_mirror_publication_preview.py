"""End-to-end offline: ODS UID absent -> exact OA/organizer/municipal venue
-> existing publication SCHEMA candidate, never an approved/publishable patch.
All sources synthetic, no network, tokens, scheduled workflow or public writes.
"""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_direct_missing_mirror_publication_preview import (
    SCHEMA, preview_missing_mirror_proposal,
)
from ptitesondes_candidate_promotion import registry_location
from merge_policy import valid
from test_ptitesondes_shared_venue_location_evidence import (
    mint, GROUP, POINT,
)

TODAY = date(2026, 11, 21)
DAY = "2026-12-05"
UID = "12345678"
SOURCE = (
    "https://openagenda.com/ville-des-bois/events/"
    "12345678_conte-musical-des-petits"
)
OFFICIAL = "https://www.ville-des-bois.fr"
REGISTRY = {
    "agenda_uid": "919191", "agenda_slug": "ville-des-bois",
    "timezone": "Europe/Paris", "institution_url": OFFICIAL + "/",
    "authority_reference_url": OFFICIAL + "/agenda",
}
FIRST_PARTY = {
    "approved_host": "www.ville-des-bois.fr",
    "exact_url": OFFICIAL + "/agenda/conte-musical-des-petits",
}
OFFICIAL_HTML = (
    "<html><body><h1>Conte musical des petits</h1>"
    "<section>Maison des enfants — Ville-des-Bois. "
    "Pour les enfants et familles de 3 à 6 ans.</section>"
    "<ul><li>5 décembre 2026 à 14:30 : conte musical jeunesse</li></ul>"
    "</body></html>"
)
LEAD = {
    "collector": "openagenda-v2",
    "external_id": UID, "source_url": SOURCE,
    "date_start": DAY, "date_end": DAY,
    "title": "Conte musical des petits",
    "city": GROUP["city"], "venue": GROUP["venue"],
}
EVENT = {
    "uid": 12345678, "state": 2, "status": 1, "removed": False,
    "attendanceMode": 1, "timezone": "Europe/Paris",
    "title": {"fr": LEAD["title"]},
    "description": {"fr": "Conte musical pour enfants de 3 à 6 ans"},
    "rights": {
        "license": {"id": "etalab-2.0"},
        "licensor": {"name": "Ville-des-Bois - test"},
    },
    "location": {
        "name": GROUP["venue"], "adminLevel4": GROUP["city"],
        "adminLevel2": "Aveyron", "adminLevel1": "Occitanie",
        "countryCode": "FR", "latitude": POINT[0],
        "longitude": POINT[1],
    },
    "timings": [{
        "begin": "2026-12-05T14:30:00+0100",
        "end": "2026-12-05T15:30:00+0100",
    }],
}
OLD = {
    "id": "historic-conte", "title": "Conte musical historique",
    "category": "conte-musical", "category_label": "Conte musical",
    "date_start": "2026-10-21", "date_end": "2026-10-21",
    "time": "14:30", "city": "Nantes", "venue": "Maison du conte",
    "department": "Loire-Atlantique", "region": "Pays de la Loire",
    "source_url": "https://openagenda.com/nantes/events/999_conte",
    "source_label": "Agenda de Nantes", "verified_at": "2026-10-20",
    "geo_verified_at": "2026-10-20", "geo_precision": "venue",
    "lat": 47.0, "lng": -1.0,
}
BASE = {"version": 3, "updated_at": "2026-11-17T08:49:57+01:00",
        # The real publisher requires at least 100 immutable historic records.
        "events": [dict(OLD, id=f"historic-conte-{i}",
                        title=f"Conte historique {i}") for i in range(100)]}


class ODSMissingToProposalContract(unittest.TestCase):
    def preview(self, *, lead=None, event=None, proof=None, ods="uid_absent",
                official_html=OFFICIAL_HTML, official_page=None, public=None,
                baseline=None, organizer=None, agenda=None, on_read=None):
        identity = deepcopy(LEAD if lead is None else lead)
        source = deepcopy(EVENT if event is None else event)
        certified_venue = mint() if proof is None else proof
        site = ({"url": REGISTRY["authority_reference_url"],
                 "text": '<a href="https://openagenda.com/ville-des-bois">'
                         'Programme officiel</a>'}
                if official_page is None else official_page)
        first_party = ({"url": FIRST_PARTY["exact_url"],
                        "html": official_html})
        def reader(agenda_uid, event_uid, key):
            if on_read:
                on_read()
            return deepcopy(source)
        return preview_missing_mirror_proposal(
            identity, deepcopy(REGISTRY), certified_venue, TODAY, "dummy-read-key",
            deepcopy(BASE if baseline is None else baseline),
            deepcopy(BASE if public is None else public),
            deepcopy(FIRST_PARTY if organizer is None else organizer),
            first_party, institutional_page=site,
            ods_probe=lambda uid: ods,
            agenda_reader=lambda uid, key: (
                {"uid": 919191, "slug": "ville-des-bois"}
                if agenda is None else agenda),
            event_reader=reader,
        )

    def test_ods_absent_to_schema_compatible_unknown_venue_preview(self):
        # This venue is not in any hand-maintained list. It was minted from a
        # DILA municipality plus independent exact IGN/BAN source in tests.
        self.assertIsNone(registry_location(GROUP))
        r = self.preview()
        self.assertEqual(r["schema"], SCHEMA)
        self.assertEqual(r["state"], "candidate_requires_final_gates")
        event = r["proposal"]
        self.assertEqual(event["id"], "openagenda-" + UID + "-" + DAY)
        self.assertEqual(event["category"], "conte-musical")
        self.assertEqual(event["venue"], GROUP["venue"])
        self.assertEqual((event["lat"], event["lng"]), POINT)
        self.assertEqual(event["time"], "14:30")
        fields = set(OLD)
        self.assertEqual(valid(event, {"conte-musical"}, fields, TODAY),
                         (True, "structure conforme"))
        for name in ("publisher_connected", "approval_granted",
                     "publication_ready"):
            self.assertFalse(r[name])
        self.assertEqual(r["public_writes"], 0)
        self.assertNotIn("additions", r)
        self.assertNotIn("safe_to_publish", r)

    def test_ods_panne_ambiguous_or_found_never_reads_direct_api(self):
        for state in ("uid_unique", "uid_nonunique", "network_error",
                      "http_429", "unexpected_uid", "invalid_json_or_schema"):
            reads = []
            with self.subTest(state=state):
                r = self.preview(ods=state, on_read=lambda: reads.append(1))
                self.assertEqual(r["state"], "hold")
                self.assertFalse(reads)
                self.assertNotIn("proposal", r)

    def test_wrong_uid_cancelled_wrong_place_and_stale_proof_hold(self):
        cases = [
            {"event": dict(EVENT, uid=12345679)},
            {"event": dict(EVENT, removed=True)},
            {"event": dict(EVENT, status=0)},
            {"event": dict(EVENT, location=dict(EVENT["location"],
                                                 latitude=46.5))},
            {"event": dict(EVENT, location=dict(EVENT["location"],
                                                 adminLevel4="Other city"))},
            {"event": dict(EVENT, timings=[])},
            {"lead": dict(LEAD, source_url="https://openagenda.com.evil.test/a")},
            {"lead": dict(LEAD, collector="other")},
            {"agenda": {"uid": 999999, "slug": "ville-des-bois"}},
            {"proof": {"verified": True, "lat": POINT[0], "lng": POINT[1]}},
        ]
        for options in cases:
            with self.subTest(options=options):
                result = self.preview(**options)
                self.assertEqual(result["state"], "hold")
                self.assertNotIn("proposal", result)

    def test_independent_official_session_and_institution_authenticity_required(self):
        fake_institution = {
            "url": "https://evil.test/agenda",
            "text": '<a href="https://openagenda.com/ville-des-bois">Fake</a>',
        }
        # A valid municipal link alone does not replace the organiser
        # confirmation for constructing a private proposal.
        for arg in (
            {"official_page": fake_institution,
             "official_html": OFFICIAL_HTML.replace("14:30", "15:30")},
            {"official_html": OFFICIAL_HTML.replace("14:30", "15:30")},
            {"official_html": OFFICIAL_HTML.replace("Pour les enfants", "Public adultes uniquement")},
            {"official_html": OFFICIAL_HTML.replace("Maison des enfants", "Maison inconnue")},
            {"official_html": OFFICIAL_HTML.replace("2026", "2027")},
            {"organizer": {"approved_host": "evil.test",
                           "exact_url": "https://evil.test/agenda"}},
        ):
            with self.subTest(arg=arg):
                self.assertEqual(self.preview(**arg)["state"], "hold")

    def test_duplicate_catalogue_and_historical_mutation_hold(self):
        event = deepcopy(OLD)
        event.update({
            "id": "other-catalogue-id", "title": LEAD["title"],
            "city": GROUP["city"], "venue": GROUP["venue"],
            "date_start": DAY, "date_end": DAY,
        })
        published = deepcopy(BASE)
        published["events"].append(event)
        self.assertEqual(self.preview(public=published)["state"], "hold")
        public_history_modified = deepcopy(BASE)
        public_history_modified["events"][0]["title"] = "Mutated"
        self.assertEqual(self.preview(public=public_history_modified)["reason"],
                         "historical_catalogue_mismatch")

    def test_nonmusical_outside_scope_and_unknown_category_remain_held(self):
        source = deepcopy(EVENT)
        source["title"] = {"fr": "Goûter au parc"}
        source["description"] = {"fr": "Goûter avec les familles"}
        self.assertEqual(self.preview(event=source)["state"], "hold")
        lead = dict(LEAD, title="Goûter au parc")
        # Make the first-party page corroborate this different title: the
        # rejection must come from editorial policy, not from a title error.
        html = (OFFICIAL_HTML.replace("Conte musical des petits", "Goûter au parc")
                .replace("conte musical jeunesse", "goûter familial"))
        self.assertEqual(self.preview(event=source, lead=lead,
                                      official_html=html)["reason"],
                         "outside_historic_music_editorial_categories")

    def test_two_source_sessions_but_insufficient_organizer_detail_hold(self):
        source = deepcopy(EVENT)
        source["timings"].append({
            "begin": "2026-12-05T16:00:00+0100",
            "end": "2026-12-05T16:30:00+0100",
        })
        self.assertEqual(self.preview(event=source)["state"], "hold")
        html = OFFICIAL_HTML.replace(
            "</ul>", "<li>5 décembre 2026 à 16:00 : deuxième conte musical</li></ul>")
        r = self.preview(event=source, official_html=html)
        self.assertEqual(r["state"], "candidate_requires_final_gates")
        self.assertEqual(r["proposal"]["time"], "14:30, 16:00")
        self.assertEqual(r["public_writes"], 0)

    def test_public_square_without_street_number_can_be_proposed(self):
        from test_ptitesondes_unnumbered_official_geo_proof import (
            mint as mint_square, CITY, VENUE, POINT as SQUARE_POINT,
        )
        location_proof = mint_square()
        lead = dict(
            LEAD, city=CITY, venue=VENUE,
            source_url=("https://openagenda.com/ville-les-bois/events/"
                        "12345678_conte-musical-des-petits"),
        )
        event = deepcopy(EVENT)
        event["location"] = dict(
            EVENT["location"], name=VENUE, adminLevel4=CITY,
            latitude=SQUARE_POINT[0], longitude=SQUARE_POINT[1],
        )
        official = "https://www.ville-les-bois.fr"
        registry = dict(
            REGISTRY, agenda_slug="ville-les-bois",
            institution_url=official + "/",
            authority_reference_url=official + "/agenda",
        )
        organizer = {
            "approved_host": "www.ville-les-bois.fr",
            "exact_url": official + "/agenda/conte-musical-des-petits",
        }
        html = (OFFICIAL_HTML.replace("Maison des enfants", VENUE)
                .replace("Ville-des-Bois", CITY))
        result = preview_missing_mirror_proposal(
            lead, registry, location_proof, TODAY, "dummy-read-key",
            deepcopy(BASE), deepcopy(BASE), organizer,
            {"url": organizer["exact_url"], "html": html},
            institutional_page={
                "url": registry["authority_reference_url"],
                "text": '<a href="https://openagenda.com/ville-les-bois">Agenda</a>',
            },
            ods_probe=lambda uid: "uid_absent",
            agenda_reader=lambda uid, key: {
                "uid": 919191, "slug": "ville-les-bois"},
            event_reader=lambda uid, event_uid, key: deepcopy(event),
        )
        self.assertEqual(result["state"], "candidate_requires_final_gates")
        self.assertEqual(result["proposal"]["venue"], "Place du village")
        self.assertEqual(
            (result["proposal"]["lat"], result["proposal"]["lng"]),
            SQUARE_POINT,
        )
        self.assertEqual(result["public_writes"], 0)
        self.assertFalse(result["publication_ready"])

    def test_multi_day_uid_is_not_silently_split_into_cards(self):
        source = deepcopy(EVENT)
        source["timings"].append({
            "begin": "2026-12-06T14:30:00+0100",
            "end": "2026-12-06T15:30:00+0100",
        })
        self.assertEqual(self.preview(event=source)["state"], "hold")


if __name__ == "__main__":
    unittest.main()
