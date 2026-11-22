"""Unknown official-page visible sessions: only private research, no approval."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_unlisted_visible_session_research import (
    visible_unlisted_sessions,
)


def fixture(title="Babilbeloola", venue="L'Étage", day="2027-02-07",
            hours=("11:00", "16:00")):
    lead = {"title": title, "venue_unverified": venue}
    slots = []
    for time in hours:
        start = datetime.fromisoformat(day + "T" + time + ":00+01:00")
        slots.append({"begin": start.isoformat(timespec="seconds"),
                      "end": (start + timedelta(minutes=30))
                      .isoformat(timespec="seconds")})
    return lead, slots


def html(title="Babilbeloola", display="07 Fév 2027",
         times="11:00 & 16:00", adult=False):
    public = "Réservé aux adultes" if adult else "Jeune Public"
    return ("<html><head><title>" + title + " - L'Étage</title></head>"
            "<body><header><h1>" + title + "</h1></header>"
            "<main><div>" + display + " " + times + "</div>"
            "<p>" + public + " à L'Étage.</p></main></body></html>")


class VisibleResearchTests(unittest.TestCase):
    def test_rennes_style_two_sessions_are_visible_but_not_approved(self):
        lead, slots = fixture()
        out = visible_unlisted_sessions(html(), lead, slots)
        self.assertEqual(out["exact_visible_session_claims_unverified"], 2)
        self.assertEqual(out["status"], "all_exact_visible_sessions_unverified")
        self.assertTrue(out["family_audience_visible"])
        self.assertFalse(out["source_author_independently_verified"])
        self.assertFalse(out["gps_independently_verified"])
        self.assertFalse(out["publication_ready"])
        self.assertEqual(out["public_writes"], 0)

    def test_mini_dancing_style_afternoon_sessions(self):
        lead, slots = fixture(
            "Le Mini-Dancing à Coquille", day="2027-04-11",
            hours=("15:00", "17:00"))
        out = visible_unlisted_sessions(
            html("Le Mini-Dancing à Coquille", "11 Avr 2027",
                 "15h00 et 17h00"), lead, slots)
        self.assertEqual(out["exact_visible_session_claims_unverified"], 2)

    def test_same_day_more_than_four_sessions_not_discarded(self):
        hours = tuple(f"{i:02d}:00" for i in range(9, 22))
        lead, slots = fixture(hours=hours)
        out = visible_unlisted_sessions(
            html(times=" ".join(hours)), lead, slots)
        self.assertEqual(out["exact_visible_session_claims_unverified"],
                         len(hours))

    def test_missing_or_other_date_clock_cannot_be_borrowed(self):
        lead, slots = fixture()
        out = visible_unlisted_sessions(
            html(times="11:00") +
            "<h2>8 Février 2027 à 16:00</h2>", lead, slots)
        self.assertEqual(out["exact_visible_session_claims_unverified"], 1)
        out = visible_unlisted_sessions(
            html(display="08 Fév 2027"), lead, slots)
        self.assertEqual(out["exact_visible_session_claims_unverified"], 0)

    def test_no_h1_title_or_no_venue_cannot_research_match(self):
        lead, slots = fixture()
        self.assertEqual(visible_unlisted_sessions(
            html(title="Spectacle sans rapport"), lead, slots
        )["exact_visible_session_claims_unverified"], 0)
        self.assertEqual(visible_unlisted_sessions(
            html().replace("L'Étage", "Autre salle"), lead, slots
        )["exact_visible_session_claims_unverified"], 0)

    def test_adult_only_and_script_fake_date_are_not_hints(self):
        lead, slots = fixture()
        self.assertEqual(visible_unlisted_sessions(
            html(adult=True), lead, slots
        )["exact_visible_session_claims_unverified"], 0)
        fake = ("<html><title>Babilbeloola</title><h1>Babilbeloola</h1>"
                "<p>Jeune public à L'Étage</p>"
                "<script>07 Fév 2027 11:00 16:00</script></html>")
        self.assertEqual(visible_unlisted_sessions(
            fake, lead, slots
        )["exact_visible_session_claims_unverified"], 0)


if __name__ == "__main__":
    unittest.main()
