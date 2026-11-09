"""Trabendo read-only watchdog: exact official two-band cards, no false alerts.

The official pages place the second act after the SECOND event date. A
mention in the band biography or recommendation carousel never counts.
"""
from __future__ import annotations

import copy
import unittest

import published_watch as watch


SHOWS = [
    ("go-c-20261112-paris-frankie-witch-fingers",
     "Frankie and the Witch Fingers", "Iguana Death Cult",
     "2026-11-12", "12", "novembre",
     "https://www.letrabendo.net/programmation/frankie-and-the-witch-fingers/"),
    ("go-c-20261128-paris-kid-kapichi",
     "Kid Kapichi", "Demob Happy",
     "2026-11-28", "28", "novembre",
     "https://www.letrabendo.net/programmation/kid-kapichi/"),
]


def page(headline, support, day, month="novembre",
         includes_support=True, extra_support=False):
    support_line = ("<p>+ " + support + "</p>") if includes_support else ""
    if extra_support:
        support_line += "<p>+ Surprise Act</p>"
    return f"""<html><head><title>{headline} – Trabendo</title></head>
<body><main><h2>Organisateur présente :</h2>
<p>{headline} a joué avec {support} lors d'une tournée lointaine.</p>
<section>
<p>{day} ― {month} 2026</p>
<h3>{headline}</h3>
<p>concert ― Punk Rock</p><p>→ Trabendo - Salle de concert</p>
</section><article>
<p>{day} ― {month} 2026</p>
<h3>{headline}</h3>{support_line}
<p>Ouverture des portes 19:00</p><p>Billetterie</p>
</article>
<section>Vous devriez aimer
<p>27 ― novembre 2026</p><p>{headline} + {support}</p>
</section></main></body></html>"""


def event(show):
    ident, head, support, day, *_ = show
    return {
        "id": ident, "title": head + " + " + support,
        "date": day, "venueId": "le-trabendo-paris",
        "artistIds": ["lead", "support"],
        "genres": ["Punk Rock"], "status": "confirmed",
        "officialUrl": show[-1], "sourceType": "salle", "time": None,
    }


class TrabendoExactTwoBillWatchTests(unittest.TestCase):
    def test_both_real_signed_two_band_bills_now_match(self):
        for show in SHOWS:
            _, head, support, date, day, month, _ = show
            original = event(show)
            previous = copy.deepcopy(original)
            official = page(head, support, day, month)
            result = watch.inspect(original, official,
                                   {"lead": head, "support": support})
            with self.subTest(date=date, support=support):
                self.assertEqual(result["status"], "matched")
                self.assertEqual(result["observedDate"], date)
                self.assertEqual(original, previous)

    def test_biography_or_recommendations_do_not_count_as_second_act(self):
        for show in SHOWS:
            _, head, support, _, day, month, _ = show
            result = watch.inspect(event(show), page(
                head, support, day, month, includes_support=False),
                {"lead": head, "support": support})
            with self.subTest(head=head):
                self.assertEqual(result["status"], "lineup_review")
            result = watch.inspect(event(show), page(
                head, support, day, month, extra_support=True),
                {"lead": head, "support": support})
            self.assertEqual(result["status"], "lineup_review")

    def test_changed_guest_date_genre_and_cancellation_stay_in_review(self):
        show = SHOWS[0]
        _, head, support, _, day, month, _ = show
        baseline = page(head, support, day, month)
        changed_guest = baseline.replace(
            "<p>+ Iguana Death Cult</p>", "<p>+ Different Act</p>")
        self.assertEqual(
            watch.inspect(event(show), changed_guest,
                          {"lead": head, "support": support})["status"],
            "lineup_review")
        moved = baseline.replace("12 ― novembre 2026", "13 ― novembre 2026")
        self.assertEqual(
            watch.inspect(event(show), moved,
                          {"lead": head, "support": support})["status"],
            "date_review")
        changed_style = baseline.replace("concert ― Punk Rock",
                                         "concert ― Metalcore")
        self.assertEqual(
            watch.inspect(event(show), changed_style,
                          {"lead": head, "support": support})["status"],
            "lineup_review")
        cancelled = baseline.replace(
            "<p>Billetterie</p>",
            "<p>CONCERT ANNULÉ, billetterie indisponible</p>")
        self.assertEqual(
            watch.inspect(event(show), cancelled,
                          {"lead": head, "support": support})["status"],
            "content_review")

    def test_only_exact_two_event_ids_urls_date_and_known_artists(self):
        show = SHOWS[1]
        _, head, support, _, day, month, _ = show
        p = page(head, support, day, month)
        original = event(show)
        for key, value in [
            ("id", "some-unknown-concert"),
            ("officialUrl", "https://www.letrabendo.net/programmation/other/"),
            ("date", "2026-11-29"),
            ("title", "Kid Kapichi"),
            ("artistIds", ["lead", "support", "extra"]),
            ("genres", ["Electro"]),
        ]:
            altered = copy.deepcopy(original)
            altered[key] = value
            with self.subTest(key=key):
                out = watch.inspect(altered, p,
                                    {"lead": head, "support": support,
                                     "extra": "Another Act"})
                self.assertNotEqual(out["status"], "matched")
        self.assertEqual(
            watch.inspect(original, p,
                          {"lead": head, "support": "Wrong Band"})["status"],
            "lineup_review")

    def test_no_door_time_is_ever_claimed_as_concert_start(self):
        show = SHOWS[0]
        _, head, support, _, day, month, _ = show
        p = page(head, support, day, month)
        x = watch.inspect(event(show), p,
                          {"lead": head, "support": support})
        self.assertNotIn("observedStartTime", x)
        self.assertNotIn("time", x)
        self.assertEqual(x["status"], "matched")


if __name__ == "__main__":
    unittest.main()
