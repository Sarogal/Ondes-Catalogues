"""Two-day, zero-authority national linked website preflight tests."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from national_institutional_linked_primary_preflight import (
    run, stable_private_proposals, append_private_proposals,
)
from test_national_institutional_edition_preflight import fixture, INDEX, DETAIL, TITLE
from test_grosses_institutional_linked_publisher import (
    INDEX_HTML, DETAIL_HTML, DATES_HTML, SITE, SPEC,
)

DAY1, DAY2, DAY3 = "2026-11-06", "2026-11-07", "2026-11-08"


def institution(url):
    return INDEX_HTML if url == INDEX else DETAIL_HTML


def site(url):
    if url != SITE:
        raise AssertionError("Unexpected network site")
    return DATES_HTML


def follow(prior, today):
    state, queue = fixture(today)
    state["national_institutional_linked_dates_private"] = deepcopy(
        prior["national_institutional_linked_dates_private"])
    return state, queue


class LinkedNationalPreflightTests(unittest.TestCase):
    def test_two_distinct_days_are_required_for_private_patch(self):
        state, queue = fixture(DAY1)
        first = run(state, queue, DAY1, institution_fetch=institution,
                    organizer_fetch=site)
        self.assertEqual(first["checked_count"], 1)
        self.assertEqual(first["two_day_observations_count"], 0)
        self.assertEqual(first["rows"][0]["start_date_hint"], "2027-06-04")
        self.assertEqual(first["rows"][0]["end_date_hint"], "2027-06-05")
        self.assertEqual(first["rows"][0]["website_review_only"], SITE)
        same_day = run(state, queue, DAY1, institution_fetch=institution,
                       organizer_fetch=site)
        self.assertEqual(same_day["two_day_observations_count"], 0)
        other, q2 = follow(state, DAY2)
        second = run(other, q2, DAY2, institution_fetch=institution,
                     organizer_fetch=site)
        self.assertEqual(second["two_day_observations_count"], 1)
        self.assertEqual(second["rows"][0]["status"],
                         "TWO_DAY_INSTITUTION_LINKED_DATES_PRIVATE")
        proposals = stable_private_proposals(other, q2, second, DAY2)
        self.assertEqual(len(proposals), 1)
        self.assertFalse(proposals[0]["showOnMap"])
        self.assertIsNone(proposals[0]["lat"])
        self.assertEqual(proposals[0]["lineup"], [])
        self.assertEqual(proposals[0]["source"], DETAIL)
        self.assertEqual(proposals[0]["officialSite"], SITE)
        self.assertFalse(second["publication_authorized"])
        self.assertEqual(second["publications"], 0)

        with TemporaryDirectory() as path:
            folder = Path(path)
            patch = {
                "schema": "grossesondes.patch.v1", "generated_at": DAY1,
                "safe_to_publish": False, "source": {},
                "additions": [], "updates": [],
                "history_additions": [], "history_updates": [], "deferred": [],
            }
            (folder / ("patch-"+DAY1+".json")).write_text(json.dumps(patch))
            catalog = {"schema": 1, "festivals": []}
            history = {"schema": 2, "knownFestivals": []}
            self.assertEqual(append_private_proposals(
                folder, catalog, history, other, q2, second, DAY2), 1)
            written = json.loads(
                (folder / ("patch-"+DAY2+".json")).read_text())
            self.assertEqual(written["additions"][0]["proofMode"],
                             "institutional-linked-organizer-edition.v1")
            self.assertFalse(written["safe_to_publish"])
            self.assertEqual(append_private_proposals(
                folder, catalog, history, other, q2, second, DAY2), 0)

    def test_unsafe_or_disappearing_institutional_link_never_fetches_site(self):
        pages = (
            "<main>Festival Metal des Garrigues 2027 sans lien</main>",
            INDEX_HTML.replace(DETAIL, "https://evil-domain.fr/"),
            '<main><a href="/evenement/unrelated-2027">'
            'Festival Metal des Garrigues 2027</a></main>',
        )
        for index in pages:
            state, queue = fixture(DAY1)
            visits = []
            result = run(
                state, queue, DAY1,
                institution_fetch=lambda url: visits.append(url) or
                    (index if url == INDEX else DETAIL_HTML),
                organizer_fetch=lambda url: self.fail("Unreviewed domain"))
            self.assertEqual(result["two_day_observations_count"], 0)
            self.assertEqual(result["rows"][0]["status"],
                             "TRUSTED_INDEX_DETAIL_LINK_NOT_PROVEN")
            self.assertEqual(visits, [INDEX])
        for detail in (
            DETAIL_HTML.replace(SITE, "https://evil-domain.fr/"),
            "<p>Site officiel d'un autre festival: <a href='" + SITE + "'>site</a></p>",
            DETAIL_HTML.replace("site officiel</a>", "tickets</a>")
                       .replace("Site officiel du", "Billets du"),
        ):
            state, queue = fixture(DAY1)
            visited = []
            result = run(
                state, queue, DAY1,
                institution_fetch=lambda url: visited.append(url) or
                    (INDEX_HTML if url == INDEX else detail),
                organizer_fetch=lambda url: self.fail("Unsupported link"))
            self.assertEqual(result["two_day_observations_count"], 0)
            self.assertEqual(visited, [INDEX, DETAIL])

    def test_changing_link_or_date_resets_evidence(self):
        state, queue = fixture(DAY1)
        run(state, queue, DAY1, institution_fetch=institution, organizer_fetch=site)
        second_state, second_queue = follow(state, DAY2)
        changed = run(
            second_state, second_queue, DAY2,
            institution_fetch=institution,
            organizer_fetch=lambda u: DATES_HTML.replace("4 et 5", "4 et 6"))
        self.assertEqual(changed["two_day_observations_count"], 0)
        self.assertEqual(changed["rows"][0]["status"],
                         "FIRST_DAY_INSTITUTION_LINKED_DATES_PRIVATE")
        third_state, third_queue = follow(second_state, DAY3)
        verified = run(
            third_state, third_queue, DAY3, institution_fetch=institution,
            organizer_fetch=lambda u: DATES_HTML.replace("4 et 5", "4 et 6"))
        self.assertEqual(verified["two_day_observations_count"], 1)

    def test_forged_report_and_state_not_enough_to_create_patch(self):
        state, queue = fixture(DAY1)
        first = run(state, queue, DAY1, institution_fetch=institution,
                    organizer_fetch=site)
        forged = deepcopy(first)
        forged["rows"][0]["status"] = "TWO_DAY_INSTITUTION_LINKED_DATES_PRIVATE"
        forged["rows"][0]["two_day_observation"] = True
        self.assertEqual(stable_private_proposals(state, queue, forged, DAY1), [])
        forged["publication_authorized"] = True
        with self.assertRaises(ValueError):
            stable_private_proposals(state, queue, forged, DAY1)
        day2, q2 = follow(state, DAY2)
        good = run(day2, q2, DAY2, institution_fetch=institution,
                   organizer_fetch=site)
        forged = deepcopy(good)
        forged["rows"][0]["website_review_only"] = "https://evil-domain.fr/"
        self.assertEqual(stable_private_proposals(day2, q2, forged, DAY2), [])
        forged = deepcopy(good)
        forged["rows"][0]["start_date_hint"] = "2027-01-01"
        self.assertEqual(stable_private_proposals(day2, q2, forged, DAY2), [])
        tampered = deepcopy(day2)
        tampered["national_institutional_linked_dates_private"][DETAIL]["digest"] = "0"*64
        self.assertEqual(stable_private_proposals(tampered, q2, good, DAY2), [])


if __name__ == "__main__":
    unittest.main()
