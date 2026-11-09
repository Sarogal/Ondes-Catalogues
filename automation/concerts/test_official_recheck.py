"""Offline regression tests for conservative official page recheck."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import official_recheck as v
import datetime as dt


PAGE = """<html><body>
<p>jeu 6 mai 2027 - 19H30</p>
<h2><strong>Example Band &amp; Another Band</strong></h2>
<p>Metal, Metalcore</p>
<p>✘ EXAMPLE BAND (Death metal)</p>
<p>✘ ANOTHER BAND (Metalcore)</p>
<p>15 avenue Honoré Serres<br/>31000 Toulouse</p>
</body></html>"""


def record():
    return {
        "candidateId": "rex:2027-05-06:example-another",
        "source": "agenda_officiel_rex_genre",
        "sourceUrl": "https://www.lerextoulouse.com/fr/programmation/example-band-another-band/",
        "name": "Example Band & Another Band",
        "date": "2027-05-06",
        "venue": "Le Rex",
        "city": "Toulouse",
        "classification": ["metal", "metalcore"],
        "genreEvidence": "tag_genre_source",
        "reviewBucket": "genre_tag_review",
        "possibleExistingConcert": False,
        "reviewRequired": True,
        "publicationAllowed": False,
    }


def catalogue():
    return {"schemaVersion": 1, "mode": "preview-public-unlisted",
            "venues": [{"id": "le-rex-toulouse", "name": "Le Rex", "city": "Toulouse"}],
            "artists": [{"id": "example-band", "name": "Example Band"}], "events": []}


class OfficialRecheckTests(unittest.TestCase):
    def test_verified_page_creates_documented_approval(self):
        a = v.verify(record(), PAGE, catalogue(), dt.date(2026, 11, 1))
        self.assertEqual(a["reviewedBy"], "automated-official-recheck")
        self.assertEqual(a["event"]["artistIds"], ["example-band", "another-band"])
        self.assertEqual(a["event"]["date"], "2027-05-06")
        self.assertEqual(a["newArtists"], [{"id": "another-band", "name": "Another Band"}])
        self.assertIsNone(a["event"]["time"])  # Official start time meaning not assumed.

    def test_official_title_only_for_existing_artists(self):
        page = PAGE.replace("<p>✘ EXAMPLE BAND (Death metal)</p>", "").replace(
            "<p>✘ ANOTHER BAND (Metalcore)</p>", "")
        c = catalogue()
        c["artists"].append({"id": "another-band", "name": "Another Band"})
        approved = v.verify(record(), page, c, dt.date(2026, 11, 1))
        self.assertEqual(approved["event"]["artistIds"], ["example-band", "another-band"])
        self.assertEqual(approved["newArtists"], [])

    def test_official_title_only_never_creates_unknown_artist(self):
        page = PAGE.replace("<p>✘ EXAMPLE BAND (Death metal)</p>", "").replace(
            "<p>✘ ANOTHER BAND (Metalcore)</p>", "")
        with self.assertRaisesRegex(ValueError, "artiste inconnu"):
            v.verify(record(), page, catalogue(), dt.date(2026, 11, 1))

    def test_changed_date_is_held(self):
        x = record()
        x["date"] = "2027-05-07"
        with self.assertRaisesRegex(ValueError, "Date"):
            v.verify(x, PAGE, catalogue(), dt.date(2026, 11, 1))

    def test_changed_title_is_held(self):
        x = record()
        x["name"] = "Different Band"
        with self.assertRaisesRegex(ValueError, "Intitulé"):
            v.verify(x, PAGE, catalogue(), dt.date(2026, 11, 1))

    def test_unverified_performer_is_held(self):
        html = PAGE.replace("✘ ANOTHER BAND", "✘ UNKNOWN")
        with self.assertRaisesRegex(ValueError, "Programmation"):
            v.verify(record(), html, catalogue(), dt.date(2026, 11, 1))

    def test_aggregator_is_never_approved(self):
        x = record()
        x["source"] = "third_party_calendar_lead"
        with self.assertRaisesRegex(ValueError, "Seul"):
            v.verify(x, PAGE, catalogue(), dt.date(2026, 11, 1))

    def test_mismatched_or_missing_genre_is_held(self):
        x = record()
        x["classification"] = ["pop"]
        with self.assertRaisesRegex(ValueError, "Genre incompatible"):
            v.verify(x, PAGE, catalogue(), dt.date(2026, 11, 1))

    def test_festival_and_guest_are_held(self):
        with self.assertRaises(ValueError):
            v.artist_names("Festival Metal & Example Band")
        with self.assertRaises(ValueError):
            v.artist_names("Example Band & Guest")

    def test_duplicate_artist_and_venue_day_is_held(self):
        c = catalogue()
        c["events"] = [{"id": "existing", "date": "2027-05-06",
                        "venueId": "le-rex-toulouse", "artistIds": ["example-band"]}]
        with self.assertRaisesRegex(ValueError, "déjà référencé"):
            v.verify(record(), PAGE, c, dt.date(2026, 11, 1))

    def test_molotov_candidate_is_rechecked_with_official_details(self):
        from test_molotov_official import PAGE as molotov_page
        from test_molotov_official import candidate as molotov_candidate
        from test_molotov_official import catalogue as molotov_catalogue
        cloud = molotov_catalogue()
        cloud["schemaVersion"] = 1
        cloud["mode"] = "preview-public-unlisted"
        approvals = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        registry = {"items": {"molotov": {
            "candidate": molotov_candidate(), "observations": 2
        }}}
        result, report = v.process(registry, cloud, approvals, dt.date(2026,11,1),
                                   fetch=lambda url, cache: molotov_page)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(result["approvals"][0]["event"]["venueId"],
                         "le-molotov-marseille")

    def test_ferrailleur_official_approval_with_two_new_artists(self):
        from test_ferrailleur_official import PAGE as ferrailleur_page
        from test_ferrailleur_official import candidate as ferrailleur_candidate
        from test_ferrailleur_official import catalogue as ferrailleur_catalogue
        cat=ferrailleur_catalogue()
        cat["schemaVersion"]=1
        cat["mode"]="preview-public-unlisted"
        cat["artists"]=[cat["artists"][0]]  # Arkona existing, Seth and TGO new
        queue={"schema":"grossesondes.concert.approvals.v1","approvals":[]}
        reg={"items":{"ferrailleur":{
            "candidate":ferrailleur_candidate(),"observations":3
        }}}
        updated,report=v.process(reg,cat,queue,dt.date(2026,11,1),
                                  fetch=lambda url,cache:ferrailleur_page)
        self.assertEqual(len(report["newApprovals"]),1)
        item=updated["approvals"][0]
        self.assertEqual(item["event"]["venueId"],"le-ferrailleur-nantes")
        self.assertEqual(item["event"]["artistIds"],
                         ["arkona","seth","the-great-old-ones"])
        self.assertEqual(item["officialEvidence"][0]["officialArtistNames"],
                         ["Arkona","Seth","The Great Old Ones"])
        self.assertEqual(len(item["newArtists"]),2)

    def test_ferrailleur_unknown_alias_is_held(self):
        from test_ferrailleur_official import PAGE as official_html
        from test_ferrailleur_official import candidate as record
        from test_ferrailleur_official import catalogue as cat_builder
        cat=cat_builder()
        cat["schemaVersion"]=1
        cat["mode"]="preview-public-unlisted"
        cat["artists"]=[cat["artists"][0]]
        cat["artists"][0]["aliases"]=["Seth"]
        queue={"schema":"grossesondes.concert.approvals.v1","approvals":[]}
        reg={"items":{"f":{"candidate":record(),"observations":4}}}
        updated,report=v.process(reg,cat,queue,dt.date(2026,11,1),
                                  fetch=lambda url,cache:official_html)
        self.assertEqual(updated,queue)
        self.assertEqual(len(report["newApprovals"]),0)
        self.assertTrue(report["held"])

    def test_rejected_and_superseded_private_rows_are_never_rechecked(self):
        approvals = {"schema": "grossesondes.concert.approvals.v1",
                     "approvals": []}
        registry = {"items": {
            "rejected": {"status": "rejected", "candidate": record(),
                         "observations": 9},
            "superseded": {"status": "superseded", "candidate": record(),
                           "observations": 9},
            "approved": {"status": "approved", "candidate": record(),
                         "observations": 9},
        }}
        def forbidden(*args):
            self.fail("A private decision must never be rechecked")
        unchanged, report = v.process(
            registry, catalogue(), approvals, dt.date(2026, 11, 9),
            fetch=forbidden)
        self.assertEqual(unchanged, approvals)
        self.assertEqual(report["evaluated"], 0)
        self.assertEqual(report["decidedSkipped"], 3)

    def test_single_observation_does_not_qualify(self):
        approvals = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        registry = {"items": {"x": {"candidate": record(), "observations": 1}}}
        result, report = v.process(registry, catalogue(), approvals, dt.date(2026, 11, 1),
                                   fetch=lambda url, cache: PAGE)
        self.assertEqual(report["evaluated"], 0)
        self.assertEqual(result, approvals)

    def test_dates_passees_ne_mobilisent_plus_de_reverification(self):
        approvals = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        expired = record()
        expired["candidateId"] = "rex:expired"
        expired["date"] = "2026-10-31"
        future = record()
        registry = {"items": {
            "expired": {"candidate": expired, "observations": 3},
            "future": {"candidate": future, "observations": 3},
        }}
        fetched = []
        def fetch(url, cache):
            fetched.append(url)
            return PAGE
        result, report = v.process(registry, catalogue(), approvals,
                                   dt.date(2026, 11, 7), fetch=fetch)
        self.assertEqual(report["expiredSkipped"], 1)
        self.assertEqual(report["totalEligible"], 1)
        self.assertEqual(report["evaluated"], 1)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(result["approvals"][0]["event"]["date"], "2027-05-06")
        self.assertIn("expired", registry["items"])
        self.assertEqual(registry["items"]["expired"]["candidate"]["date"],
                         "2026-10-31")

    def test_date_invalide_est_retenue_pas_passee_sous_silence(self):
        approvals = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        invalid = record()
        invalid["date"] = "date-illisible"
        registry = {"items": {"invalid": {"candidate": invalid,
                                             "observations": 2}}}
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return PAGE
        result, report = v.process(registry, catalogue(), approvals,
                                   dt.date(2026, 11, 7), fetch=fetch)
        self.assertEqual(report["expiredSkipped"], 0)
        self.assertEqual(report["evaluated"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(report["held"]), 1)
        self.assertEqual(result, approvals)

    def test_two_observations_accept_once_without_mutating_inputs(self):
        approvals = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        registry = {"items": {"x": {"candidate": record(), "observations": 2}}}
        original_catalogue = catalogue()
        saved = copy.deepcopy(original_catalogue)
        result, report = v.process(registry, original_catalogue, approvals,
                                   dt.date(2026, 11, 1), fetch=lambda url, cache: PAGE)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(len(result["approvals"]), 1)
        self.assertEqual(original_catalogue, saved)
        # Avoid even fetching the page again when this exact official
        # URL and date have already been approved and persisted.
        def should_never_fetch(url, cache):
            raise AssertionError("Redundant HTTP request for an approved event")
        result2, report2 = v.process(registry, original_catalogue, result,
                                     dt.date(2026, 11, 1), fetch=should_never_fetch)
        self.assertEqual(len(report2["newApprovals"]), 0)
        self.assertEqual(len(result2["approvals"]), 1)
        self.assertEqual(report2["evaluated"], 0)
        self.assertEqual(report2["alreadyApprovedSkipped"], 1)

    def test_changed_date_at_same_official_url_is_not_silently_skipped(self):
        approvals = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        registry = {"items": {"x": {"candidate": record(), "observations": 2}}}
        first, report = v.process(registry, catalogue(), approvals,
                                  dt.date(2026, 11, 1),
                                  fetch=lambda url, cache: PAGE)
        self.assertEqual(len(report["newApprovals"]), 1)
        changed = copy.deepcopy(registry)
        changed["items"]["x"]["candidate"]["date"] = "2027-05-07"
        calls = []
        def fetch_edited(url, cache):
            calls.append(url)
            return PAGE
        reviewed, status = v.process(changed, catalogue(), first,
                                     dt.date(2026, 11, 1), fetch=fetch_edited)
        self.assertEqual(len(calls), 1)
        self.assertEqual(status["evaluated"], 1)
        self.assertEqual(status["alreadyApprovedSkipped"], 0)
        self.assertEqual(len(status["newApprovals"]), 0)
        self.assertEqual(len(status["held"]), 1)
        self.assertEqual(reviewed, first)


if __name__ == "__main__":
    unittest.main()
