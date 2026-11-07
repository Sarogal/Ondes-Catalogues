"""Independent organizer fallback: scoped dates, times, title and GPS fail closed."""
from datetime import date
from pathlib import Path
from unittest.mock import patch
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from official_organizer_proof import PROGRAMS, organizer_url, reviewed_schedule, reviewed_family_category
from proof_text import verify_event
from ptitesondes_candidate_promotion import evaluate
from merge_policy import merge

JAN_URL = ("https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/"
           "events/jeune-public-concert-quand-le-chat-nest-pas-laca-part-en-live")
FEB_URL = ("https://openagenda.com/contributions-evenements-culturels-nantes-et-metropole-nantaise/"
           "events/jeune-public-concertconte-musical-un-animal-des-amis-mots")
JAN_TITLE = 'Jeune public - Concert - "Quand le chat n\'est pas là...ça part en live !"'
FEB_TITLE = 'Jeune public - Concert/Conte musical - "Un animal, des amis mots"'
OA_SHELL = "<html><title>OpenAgenda</title><body>Loading...</body></html>"
JAN_PAGE = """<html><head><title>QUAND LE CHAT N’EST PAS LÀ…ça part en LIVE !</title></head>
<h1>QUAND LE CHAT N’EST PAS LÀ…ça part en LIVE !</h1>
<div>Théâtre de Jeanne - Nantes</div><div>Conseillé de 3 à 8 ans</div>
<div>Un concert pour les enfants</div>
<p>LES MERCREDIS À 14H30</p><p>LES 13 ET 20 JANVIER 2027</p>
<p>Mercredi 13 janv. à 14h30</p><p>Mercredi 20 janv. à 14h30</p>
<p>+ séance sup. jeudi 14 janv. à 10h30</p></html>"""
FEB_PAGE = """<html><head><title>UN ANIMAL, DES AMIS MOTS</title></head>
<h1>UN ANIMAL, DES AMIS MOTS</h1>
<div>Théâtre de Jeanne - Nantes</div><div>Conseillé de 3 à 10 ans</div>
<div>Un conte musical pour les enfants</div>
<p>LES MERCREDIS À 14H30</p><p>LES DIMANCHES À 15H</p>
<p>Du 10 au 17 février 2027</p></html>"""

BORDEAUX_MOMO_URL = "https://openagenda.com/ville-de-bordeaux/events/momo-lenfant-peche-3216479"
BORDEAUX_DROLES_URL = "https://openagenda.com/ville-de-bordeaux/events/les-droles-de-petites-betes-8323158"
BORDEAUX_MOMO_HTML = """<html><head><title>Momo, l'enfant pêche - Opéra National de Bordeaux</title></head>
<h1>Momo, l'enfant pêche</h1><p>Auditorium - Opéra National de Bordeaux</p>
<p>Famille | Conte musical à partir de 6 ans</p><p>21 Jan 2027 à 19H00</p>
<p>22 Jan 2027 à 14H30 Séance pour les scolaires</p><p>22 Jan 2027 à 19H00</p>
<p>Accueil enfants, réservation obligatoire</p></html>"""
BORDEAUX_DROLES_HTML = """<html><head><title>Les Drôles de petites bêtes - Opéra National de Bordeaux</title></head>
<h1>Les Drôles de petites bêtes</h1><p>Auditorium - Opéra National de Bordeaux</p>
<p>Famille | Concert illustré à partir de 4 ans. Un ciné-concert pour les enfants.</p>
<p>28 Jan 2027 à 14H30 Séance pour les scolaires + Séance détente</p>
<p>29 Jan 2027 à 14H30 Séance pour les scolaires</p>
<p>29 Jan 2027 à 19H00 Je réserve</p></html>"""


def bordeaux_event(url=BORDEAUX_MOMO_URL, day="2027-01-22", hour="19:00"):
    momo = url == BORDEAUX_MOMO_URL
    return {
        "title": "Momo, l'enfant pêche" if momo else "Les Drôles de petites bêtes",
        "source_url": url, "category": "conte-musical" if momo else "cine-concert",
        "city": "Bordeaux", "venue": "Auditorium de Bordeaux",
        "lat": 44.8421883, "lng": -0.5801358,
        "date_start": day, "date_end": day, "time": hour,
    }


def bordeaux_mock_source(url):
    if url in (BORDEAUX_MOMO_URL, BORDEAUX_DROLES_URL):
        return OA_SHELL, ""
    if url == PROGRAMS[BORDEAUX_MOMO_URL]["organizer_url"]:
        return BORDEAUX_MOMO_HTML, ""
    if url == PROGRAMS[BORDEAUX_DROLES_URL]["organizer_url"]:
        return BORDEAUX_DROLES_HTML, ""
    return None, "not a pinned organizer"


def event(day="2027-01-13", time="14:30", feb=False):
    return {
        "title": FEB_TITLE if feb else JAN_TITLE,
        "source_url": FEB_URL if feb else JAN_URL,
        "category": "conte-musical" if feb else "concert",
        "city": "Nantes", "venue": "Théâtre de Jeanne",
        "lat": 47.20457, "lng": -1.57551,
        "date_start": day, "date_end": day, "time": time,
    }


def evidence(url):
    if url == JAN_URL or url == FEB_URL:
        return OA_SHELL, ""
    if url == PROGRAMS[JAN_URL]["organizer_url"]:
        return JAN_PAGE, ""
    if url == PROGRAMS[FEB_URL]["organizer_url"]:
        return FEB_PAGE, ""
    return None, "unknown official source"


class ApprovedOrganizerTests(unittest.TestCase):
    def test_pinned_bordeaux_family_programme_verifies_only_bookable_times(self):
        for event in (
            bordeaux_event(), bordeaux_event(day="2027-01-21"),
            bordeaux_event(BORDEAUX_DROLES_URL, "2027-01-29", "19:00"),
        ):
            with self.subTest(event=event):
                with patch("proof_text.read", side_effect=bordeaux_mock_source) as fetched:
                    good, reason = verify_event(event, [])
                self.assertTrue(good, reason)
                self.assertEqual(fetched.call_count, 2)
        for blocked in (
            bordeaux_event(day="2027-01-22", hour="14:30"),
            bordeaux_event(day="2027-01-23"),
            bordeaux_event(BORDEAUX_DROLES_URL, "2027-01-28", "14:30"),
            bordeaux_event(BORDEAUX_DROLES_URL, "2027-01-29", "14:30"),
            bordeaux_event(BORDEAUX_DROLES_URL, "2027-01-29", "20:00"),
        ):
            with self.subTest(blocked=blocked):
                with patch("proof_text.read", side_effect=bordeaux_mock_source):
                    self.assertFalse(verify_event(blocked, [])[0])

    def test_bordeaux_source_missing_title_age_venue_date_fails_closed(self):
        for body in (
            BORDEAUX_MOMO_HTML.replace("22 Jan 2027 à 19H00", ""),
            BORDEAUX_MOMO_HTML.replace("à partir de 6 ans", "pour les adultes"),
            BORDEAUX_MOMO_HTML.replace("Auditorium", "Salle imaginaire"),
            BORDEAUX_MOMO_HTML.replace("2027", "2026"),
            BORDEAUX_MOMO_HTML + "<p>Annulé</p>",
        ):
            with self.subTest(body=body[:100]):
                def source(url, html=body):
                    if url == PROGRAMS[BORDEAUX_MOMO_URL]["organizer_url"]:
                        return html, ""
                    return OA_SHELL, ""
                with patch("proof_text.read", side_effect=source):
                    self.assertFalse(verify_event(bordeaux_event(), [])[0])
        self.assertIsNone(organizer_url(dict(bordeaux_event(), source_url=BORDEAUX_MOMO_URL+"?q=1")))
        self.assertIsNone(organizer_url(dict(bordeaux_event(), venue="Lieu inconnu")))
        self.assertIsNone(organizer_url(dict(bordeaux_event(), category="concert")))

    def test_pinned_bordeaux_family_category_requires_exact_identity(self):
        args=("54065371", BORDEAUX_MOMO_URL, "Momo, l'enfant pêche",
              "Bordeaux", "Auditorium de Bordeaux")
        self.assertEqual(reviewed_family_category(*args), ("conte-musical", "Conte musical"))
        for wrong in (
            ("wrong-uid", *args[1:]),
            (args[0], BORDEAUX_MOMO_URL+"?redirect=1", *args[2:]),
            (args[0], args[1], "Autre titre", args[3], args[4]),
            (args[0], args[1], args[2], "Paris", args[4]),
            (args[0], args[1], args[2], args[3], "Autre salle"),
        ):
            self.assertIsNone(reviewed_family_category(*wrong))

    def test_exact_approved_official_sources_only(self):
        self.assertEqual(organizer_url(event()), PROGRAMS[JAN_URL]["organizer_url"])
        self.assertIsNone(organizer_url(dict(event(), source_url=JAN_URL + "?x=1")))
        self.assertIsNone(organizer_url(dict(event(), title="Un autre spectacle")))
        self.assertIsNone(organizer_url(dict(event(), city="Paris")))
        self.assertIsNone(organizer_url(dict(event(), venue="Théâtre imaginaire")))
        self.assertIsNone(organizer_url(dict(event(), category="conte-musical")))

    def test_three_january_sessions_verified_independently(self):
        with patch("proof_text.read", side_effect=evidence) as fetch:
            for day, time in [("2027-01-13", "14:30"),
                              ("2027-01-14", "10:30"),
                              ("2027-01-20", "14:30")]:
                with self.subTest(day=day):
                    ok, why = verify_event(event(day, time), [])
                    self.assertTrue(ok, why)
            self.assertEqual(fetch.call_count, 6)

    def test_three_february_sessions_verified_independently(self):
        with patch("proof_text.read", side_effect=evidence):
            for day, time in [("2027-02-10", "14:30"),
                              ("2027-02-14", "15:00"),
                              ("2027-02-17", "14:30")]:
                with self.subTest(day=day):
                    ok, why = verify_event(event(day, time, feb=True), [])
                    self.assertTrue(ok, why)

    def test_approved_source_with_long_dynamic_html_still_checks_organizer(self):
        long_html = ('<html><title>OpenAgenda</title><body>'
                     'Aide Français Loading... Agenda culturel Evénements à venir '
                     + 'Informations sur les propositions publiques ' * 15
                     + '</body></html>')
        def response(url):
            if url == JAN_URL:
                return long_html, ""
            return evidence(url)
        with patch("proof_text.read", side_effect=response) as fetch:
            ok, why = verify_event(event("2027-01-13", "14:30"), [])
            self.assertTrue(ok, why)
            self.assertEqual(fetch.call_count, 2)

    def test_approved_openagenda_explicit_cancellation_blocks_fallback(self):
        cancelled = ('<html><title>OpenAgenda</title><body>'
                     'Cet événement est annulé.</body></html>')
        with patch("proof_text.read", return_value=(cancelled, "")) as fetch:
            ok, why = verify_event(event(), [])
            self.assertFalse(ok)
            self.assertIn("annulation", why)
            fetch.assert_called_once()

    def test_reject_unknown_dates_and_incorrect_hours(self):
        with patch("proof_text.read", side_effect=evidence):
            for ev in [event("2027-01-15", "14:30"),
                       event("2027-01-13", "10:30"),
                       event("2027-01-14", "14:30"),
                       event("2027-02-11", "14:30", feb=True),
                       event("2027-02-14", "14:30", feb=True),
                       event("2027-02-18", "14:30", feb=True)]:
                with self.subTest(date=ev["date_start"], time=ev["time"]):
                    self.assertFalse(verify_event(ev, [])[0])

    def test_missing_year_or_different_year_not_approved(self):
        with patch("proof_text.read", side_effect=lambda url:
                   (FEB_PAGE.replace("2027", "2026"), "") if "theatre-jeanne" in url
                   else (OA_SHELL, "")):
            self.assertFalse(verify_event(event("2027-02-10", "14:30", feb=True), [])[0])
        with patch("proof_text.read", side_effect=lambda url:
                   (JAN_PAGE.replace("JANVIER 2027", "JANVIER 2026"), "")
                   if "theatre-jeanne" in url else (OA_SHELL, "")):
            self.assertFalse(verify_event(event(), [])[0])

    def test_absent_or_cancelled_organizer_page_keeps_pending(self):
        with patch("proof_text.read", side_effect=lambda url:
                   (None, "429") if "theatre-jeanne" in url else (OA_SHELL, "")):
            ok, why = verify_event(event(), [])
            self.assertFalse(ok)
            self.assertIn("secondaire", why)
        with patch("proof_text.read", side_effect=lambda url:
                   (JAN_PAGE + "<p>Annulé</p>", "") if "theatre-jeanne" in url
                   else (OA_SHELL, "")):
            self.assertFalse(verify_event(event(), [])[0])

    def test_no_venue_or_age_or_title_proof(self):
        for altered in [JAN_PAGE.replace("Conseillé de 3 à 8 ans", ""),
                        JAN_PAGE.replace("Nantes", "Bordeaux"),
                        JAN_PAGE.replace("QUAND LE CHAT N’EST PAS LÀ…ça part en LIVE !",
                                         "Le concert imaginaire")]:
            with self.subTest(altered=altered[:50]):
                with patch("proof_text.read", side_effect=lambda url, a=altered:
                           (a, "") if "theatre-jeanne" in url else (OA_SHELL, "")):
                    self.assertFalse(verify_event(event(), [])[0])

    def test_multi_day_range_or_multiple_times_rejected(self):
        e = event()
        e["date_end"] = "2027-01-20"
        self.assertFalse(reviewed_schedule(e, JAN_TITLE, JAN_PAGE)[0])
        e = event(time="14:30, 10:30")
        self.assertFalse(reviewed_schedule(e, JAN_TITLE, JAN_PAGE)[0])

    def test_no_unknown_openagenda_bypass(self):
        e = event()
        e["source_url"] = "https://openagenda.com/other-agenda/events/unknown"
        with patch("proof_text.read", return_value=(OA_SHELL, "")) as read:
            ok, why = verify_event(e, [])
            self.assertFalse(ok)
            self.assertIn("dynamique", why)
            read.assert_called_once()

    def test_promotion_contract_and_merge_preserve_history(self):
        d = date(2026, 11, 4)
        day = "2027-01-13"
        lead = dict(event(day), external_id="25603859",
                    collector="opendatasoft-index")
        # The live ODS result must remain an independent corroborating source.
        row = {
            "uid": lead["external_id"], "title_fr": lead["title"],
            "description_fr": "Concert jeune public pour enfants",
            "canonicalurl": lead["source_url"],
            "location_city": "Nantes", "location_name": "Théâtre de Jeanne",
            "location_department": "Loire-Atlantique",
            "location_region": "Pays de la Loire",
            "location_countrycode": "FR",
            "location_coordinates": {"lat":47.20457, "lon":-1.57551},
            "originagenda_title": "Nantes Métropole",
            "timings": '[{"begin":"2027-01-13T14:30:00+01:00"}]',
            "status": '{"id":1}',
        }
        base = {"version":3, "updated_at":"2026-10-22T21:00:00+02:00",
                "events":[{
                    "id":f"historique-{i}", "title":f"Autre spectacle {i}",
                    "category":"concert", "category_label":"Concert",
                    "date_start":"2026-12-01", "date_end":"2026-12-01",
                    "time":"14:30", "city":"Nantes",
                    "department":"Loire-Atlantique", "region":"Pays de la Loire",
                    "venue":"Théâtre de Jeanne", "source_url":JAN_URL,
                    "source_label":"Théâtre de Jeanne", "verified_at":str(d),
                    "geo_verified_at":str(d), "geo_precision":"venue",
                    "lat":47.20457, "lng":-1.57551
                } for i in range(100)]}
        # Include the verified category and time columns in the baseline schema.
        with patch("proof_text.read", side_effect=evidence):
            patch_doc, report = evaluate([lead], base, base, d,
                                         fetch=lambda uid:row)
            self.assertEqual(report["accepted_preflight"], 1)
            self.assertFalse(patch_doc["safe_to_publish"])
            self.assertEqual(patch_doc["updates"], [])
            pub, result = merge(base, base, patch_doc, d)
            self.assertEqual(result["ajoutes"], 1)
            self.assertEqual(pub["events"][:100], base["events"])
            self.assertEqual(pub["events"][-1]["date_start"], day)
            self.assertEqual(len(base["events"]), 100)


if __name__ == "__main__":
    unittest.main()
