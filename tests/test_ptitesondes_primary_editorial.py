"""Regression tests based on 22 Nov 2026 OpenAgenda editorial incidents.

All tests are offline; no private source, venue or agenda allowlist.
"""
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from ptitesondes_primary_editorial import primary_out_of_scope
from ptitesondes_candidate_promotion import category_for
from ptitesondes_family_activity_classification import propose_family_activity
from ptitesondes_openagenda_national_event_research import propose_event
from ptitesondes_oa_first_party_admission import admit_live_openagenda
from test_ptitesondes_candidate_promotion import base
from test_ptitesondes_open_world_release_rehearsal import (
    TODAY, DAY, AGENDA, lead, oa_event,
)


def live_case(title, description, *, category=None):
    source = dict(oa_event(), title={"fr": title},
                  description={"fr": description}, age={"min": 5, "max": 13})
    item = dict(lead(), title=title)
    ref = base()
    if category:
        ref["events"][0]["category"] = category
        ref["events"][0]["category_label"] = {
            "atelier-musical": "Atelier musical",
            "concert": "Concert",
            "lecture-jeunesse": "Lecture jeunesse",
            "spectacle-jeunesse": "Spectacle jeune public",
        }[category]
    return admit_live_openagenda(item, DAY.isoformat(), AGENDA,
                                 source, ref, ref, TODAY)


class PrimaryEditorialTests(unittest.TestCase):
    def test_school_support_with_incidental_reading_is_not_storytelling(self):
        title = "Coup 2 Pouce - Accompagnement scolaire"
        desc = ("Public CE1 à 6ème : révisions et aide aux devoirs, "
                "lecture à voix haute, recherche documentaire et jeux.")
        self.assertEqual(primary_out_of_scope(title, desc),
                         "school_support_primary")
        self.assertIsNone(category_for(title, desc))
        self.assertIsNone(propose_family_activity(
            title, desc)["category_proposal"])
        candidate, reason = live_case(title, desc)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_primary_activity_outside_scope")

    def test_adult_focused_forum_with_incidental_concert_is_not_music_event(self):
        title = "Forum « lutte contre les violences faites aux femmes » dans le 11ème"
        desc = ("Jeunes et adultes. Deux tables rondes, accompagnement "
                "des associations, concert et danse. Enfants bienvenus.")
        self.assertEqual(primary_out_of_scope(title, desc),
                         "non_performance_gathering_primary")
        self.assertIsNone(category_for(title, desc))
        candidate, reason = live_case(title, desc)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_primary_activity_outside_scope")

    def test_generic_school_and_forum_wording_without_named_event_ids(self):
        for name in (
            "Soutien scolaire : ateliers et contes",
            "Aide aux devoirs et lecture à voix haute",
            "Révisions scolaires et chansons jeunesse",
            "Conférence : la musique chez les enfants",
            "Table ronde avec interlude musical pour les familles",
            "Réunion d'information autour des spectacles jeunesse",
            "Réservez un studio d'enregistrement pour vos projets",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(primary_out_of_scope(name))

    def test_child_friendly_mixed_audience_studio_can_be_legitimate(self):
        title = "Créez et enregistrez votre musique en studio"
        desc = ("Atelier musical dès 10 ans. Enfants et jeunes : "
                "une expérience ludique. Adultes et débutants bienvenus.")
        self.assertIsNone(primary_out_of_scope(title, desc))
        candidate, reason = live_case(title, desc, category="atelier-musical")
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["category"], "atelier-musical")

    def test_genuine_reading_and_intergenerational_concert_remain_eligible(self):
        story = propose_family_activity(
            "Lecture à voix haute pour les tout-petits",
            "Contes animés pour les enfants et leurs parents.")
        self.assertEqual(story["category_proposal"], "lecture-jeunesse")
        self.assertEqual(category_for(
            "Concert acoustique", "Un concert pour les enfants, "
            "les familles et les grands-parents."), ("concert", "Concert"))
        self.assertIsNone(primary_out_of_scope(
            "Spectacle de marionnettes pour enfants",
            "Le spectacle évoque le forum du quartier."))

    def test_official_children_storytelling_title_without_child_word_is_publishable(self):
        # Event title is a named performance; the same official source
        # explicitly says it is "pour enfants de tous âges".
        title = "Contes avec Aïdée"
        desc = "Association culturelle. Pour enfants de tous âges."
        proposed = propose_family_activity(title, desc)
        self.assertEqual(proposed["category_proposal"], "lecture-jeunesse")
        self.assertEqual(proposed["decision"],
                         "read_only_proposal_requires_full_proof")
        candidate, reason = live_case(
            title, desc, category="lecture-jeunesse")
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["category"], "lecture-jeunesse")
        self.assertEqual(candidate["title"], title)

    def test_named_youth_show_and_adult_only_storytelling_keep_scope_guards(self):
        title = "Spectacle des marionnettes de l'hiver"
        desc = "Un moment de spectacle pour les familles et les enfants."
        candidate, reason = live_case(
            title, desc, category="spectacle-jeunesse")
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["category"], "spectacle-jeunesse")
        for text in ("Réservé aux adultes uniquement.",
                     "Sans enfants, événement pour adultes."):
            with self.subTest(text=text):
                self.assertIsNone(propose_family_activity(
                    "Contes avec Aïdée", text)["category_proposal"])
        self.assertIsNone(propose_family_activity(
            "Atelier d'échecs", "Pour enfants de tous âges."
        )["category_proposal"])

    def test_incidental_school_word_in_genuine_performance_does_not_veto(self):
        self.assertIsNone(primary_out_of_scope(
            "Conte musical pour enfants",
            "Après les devoirs, venez découvrir des chansons."))
        candidate, reason = live_case(
            "Concert pour enfants", "Spectacle en famille, "
            "après la réunion d'information des parents.", category="concert")
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["category"], "concert")

    def test_discovery_rejects_primary_non_editorial_research(self):
        source = dict(oa_event(), title={"fr": "Aide aux devoirs : des histoires"},
                      description={"fr": "Lecture à voix haute pour enfants."})
        item, reason = propose_event(
            source, {"agenda_uid": AGENDA["uid"],
                     "agenda_slug": AGENDA["slug"]}, TODAY)
        self.assertIsNone(item)
        self.assertEqual(reason, "primary_activity_outside_editorial_scope")

    def test_mixed_umbrella_programme_does_not_publish_all_days_as_concerts(self):
        title = "Les Journées polyglottes"
        desc = ("Au programme : un atelier d'écriture en ukrainien, "
                "des lectures d'albums pour enfants, une animation autour "
                "de la culture vénézuélienne, un concert de chants du monde "
                "et des expositions.")
        self.assertEqual(primary_out_of_scope(title, desc),
                         "mixed_umbrella_programme_primary")
        self.assertIsNone(category_for(title, desc))
        candidate, reason = live_case(title, desc, category="concert")
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_primary_activity_outside_scope")
        self.assertIsNone(primary_out_of_scope(
            "Concert de chants du monde pour enfants", desc))
        self.assertIsNone(primary_out_of_scope(
            "Journées musicales pour enfants", desc))

    def test_park_opening_hours_are_not_concert_sessions(self):
        title = "Le Hameau Enchanté"
        desc = ("Un parc d'attractions version Noël. Le parc à thème "
                "accueille les visiteurs dans des décors féériques. Au fil "
                "de la visite, un bonhomme de neige automate offre un concert, "
                "des rennes chanteurs et des attractions.")
        self.assertEqual(primary_out_of_scope(title, desc),
                         "park_visit_programme_primary")
        self.assertIsNone(category_for(title, desc))
        self.assertIsNone(propose_family_activity(title, desc)["category_proposal"])
        candidate, reason = live_case(title, desc, category="concert")
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_primary_activity_outside_scope")
        self.assertIsNone(primary_out_of_scope(
            "Concert des rennes pour enfants", desc))
        self.assertIsNone(primary_out_of_scope(
            "Spectacle de marionnettes", desc))

    def test_park_real_source_signals_and_family_title(self):
        # Public OpenAgenda UID 23913876, French description: short
        # exact source fragments, not a fabricated event description.
        desc = ("parc à thème ... accueillir les visiteurs ... "
                "scénographie féérique ... Au fil de la visite ... "
                "bonhomme de neige automate")
        for title in ("Le Hameau Enchanté", "Noël au parc pour enfants"):
            with self.subTest(title=title):
                self.assertEqual(primary_out_of_scope(title, desc),
                                 "park_visit_programme_primary")
                self.assertIsNone(category_for(title, desc))
                self.assertIsNone(propose_family_activity(
                    title, desc)["category_proposal"])
                source = dict(oa_event(), title={"fr": title},
                              description={"fr": desc})
                item, reason = propose_event(
                    source, {"agenda_uid": AGENDA["uid"],
                             "agenda_slug": AGENDA["slug"]}, TODAY)
                self.assertIsNone(item)
                self.assertEqual(reason, "primary_activity_outside_editorial_scope")
                candidate, reason = live_case(title, desc, category="concert")
                self.assertIsNone(candidate)
                self.assertEqual(reason, "oa_direct_primary_activity_outside_scope")
        for title in ("Concert pour enfants", "Conte musical de Noël",
                      "Éveil musical au parc", "Spectacle de marionnettes"):
            self.assertIsNone(primary_out_of_scope(title, desc))

    def test_no_session_count_cap_on_real_youth_workshops(self):
        self.assertIsNone(primary_out_of_scope(
            "Éveil musical pour les tout-petits",
            "Atelier pour les familles, 35 représentations avec dates distinctes."))


if __name__ == "__main__":
    unittest.main()
