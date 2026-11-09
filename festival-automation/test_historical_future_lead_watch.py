"""Offline security and productivity checks for the archive-homepage pilot."""
from copy import deepcopy
import unittest

from historical_future_lead_watch import (
    APPROVED, HISTORY_GIT, HISTORY_PAGES, STATUS,
    choose_roster, load_verified_roster, scan, validated_hints,
    validated_roster, visible_future_years,
)
from national_discovery_queue import build_queue

TODAY = "2026-11-09"
TOMORROW = "2026-11-10"


def historical():
    return {
        "schema": 2,
        "knownFestivals": [
            {"slug": slug, "name": name, "region": region,
             "officialSite": url, "startDate": "2026-06-01",
             "endDate": "2026-06-02", "lastKnownYear": 2026}
            for slug, (name, region, url) in APPROVED.items()
        ],
    }


def state():
    return {"schema": "grossesondes.source-watch.v1",
            "regional_festival_candidates_review_only": {},
            "institutional_agenda_candidate_pages": {},
            "secondary_source_candidates_private": {}}


def report(day=TODAY, archive="CONSISTENT"):
    return {"schema": "grossesondes.source-watch-report.v1",
            "date": day, "source_reference_leads_review_only": [],
            "historical_future_watch_archive_status_private": archive}


class HistoricalHomepageTests(unittest.TestCase):
    def test_twelve_approved_historical_roots_valid_and_spread_across_regions(self):
        roster = validated_roster(historical(), TODAY)
        self.assertEqual(len(roster), 12)
        self.assertEqual(len({x["region"] for x in roster.values()}), 12)
        self.assertTrue(all(x["url"].startswith("https://") for x in roster.values()))

    def test_history_must_match_both_fixed_public_snapshots(self):
        doc = historical()
        visits = []
        roster, status = load_verified_roster(
            TODAY, fetch_json=lambda url: (visits.append(url), deepcopy(doc))[1])
        self.assertEqual(visits, [HISTORY_PAGES, HISTORY_GIT])
        self.assertEqual(len(roster), 12)
        self.assertEqual(status, "CONSISTENT")
        visits.clear()
        def divergent(url):
            visits.append(url)
            data = deepcopy(doc)
            if url == HISTORY_GIT:
                data["knownFestivals"][0]["name"] = "Forged Festival"
            return data
        roster, status = load_verified_roster(TODAY, fetch_json=divergent)
        self.assertEqual(roster, {})
        self.assertEqual(status, "DIVERGENT")
        self.assertEqual(visits, [HISTORY_PAGES, HISTORY_GIT])

    def test_historical_page_cannot_be_redirected_or_reassigned_by_catalogue(self):
        cases = (
            ("officialSite", "https://example.evil/admin"),
            ("name", "Fake As One Fest"),
            ("lastKnownYear", 2027),
            ("startDate", "2027-06-01"),
            ("region", "Paris"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                doc = historical()
                doc["knownFestivals"][0][field] = value
                with self.assertRaises(ValueError):
                    validated_roster(doc, TODAY)
        doc = historical()
        doc["knownFestivals"].append(deepcopy(doc["knownFestivals"][0]))
        with self.assertRaises(ValueError):
            validated_roster(doc, TODAY)
        doc = historical()
        doc["knownFestivals"].pop()
        with self.assertRaises(ValueError):
            validated_roster(doc, TODAY)

    def test_visible_explicit_year_near_identity_is_not_a_date_proof(self):
        name = "As One Fest"
        html = ('<main><h1>As One Fest</h1>'
                '<p>As One Fest 2027 : suivez nos annonces officielles.</p></main>')
        years, digest = visible_future_years(name, html, TODAY)
        self.assertEqual(years, [2027])
        self.assertEqual(len(digest), 64)
        for bad in (
            '<h1>As One Fest</h1><p>Dernière édition 2026 seulement.</p>',
            '<h1>As One Fest</h1><script>As One Fest 2027</script>',
            '<h1>As One Fest</h1><div hidden>As One Fest 2027</div>',
            '<h1>As One Fest</h1><div aria-hidden="true">As One Fest 2027</div>',
            ('<head><title>As One Fest 2027</title></head><body>'
             '<h1>As One Fest</h1><p>Édition historique de 2026.</p></body>'),
            ('<body><nav>As One Fest 2027</nav><main><h1>As One Fest</h1>'
             '<p>Archives de 2026 seulement.</p></main></body>'),
            ('<body><h1>As One Fest</h1><p>Archives 2026 uniquement.</p>'
             '<footer>As One Fest 2027</footer></body>'),
            '<h1>Autre festival 2027</h1><p>As One Fest saison 2026.</p>',
            '<h1>As One Fest</h1><p>Copyright 2027, tous droits réservés.</p>',
        ):
            with self.subTest(html=bad):
                try:
                    result, _ = visible_future_years(name, bad, TODAY)
                    self.assertEqual(result, [])
                except ValueError:  # little visible body is deliberately inconclusive
                    pass

    def test_two_future_years_do_not_create_an_ambiguous_dossier(self):
        roster = validated_roster(historical(), TODAY)
        s = state()
        who = {"As One Fest"}
        # This name is present only on its own first-party homepage.
        def fetch(url):
            match = next(x for x in roster.values() if x["url"] == url)
            if match["name"] in who:
                return ('<p>As One Fest 2027. As One Fest 2028. '
                        'Plus d’informations sur le festival.</p>')
            return '<p>Festival passé en 2026. Actualités à suivre.</p>'
        out = scan(s, {"as-one-fest": roster["as-one-fest"]},
                   TODAY, fetch=fetch)
        self.assertEqual(out[0]["status"], "AMBIGUOUS_YEARS_REVIEW_ONLY")
        self.assertEqual(validated_hints(s, TODAY), [])

    def test_rotation_only_fetches_approved_urls_under_budget(self):
        roster = validated_roster(historical(), TODAY)
        s = state()
        visited = []
        def fetch(url):
            visited.append(url)
            entry = next(x for x in roster.values() if x["url"] == url)
            return ('<p>' + entry["name"] + ' 2027. Édition à suivre '
                    'sur le site de l’événement.</p>')
        first = scan(s, roster, TODAY, fetch=fetch)
        second = scan(s, roster, TODAY, fetch=fetch)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(len(visited), 4)
        self.assertEqual(len(set(visited)), 4)
        self.assertEqual(set(visited).difference({x["url"] for x in roster.values()}), set())
        self.assertEqual(len(validated_hints(s, TODAY)), 4)
        self.assertEqual(scan(s, roster, TODAY, fetch=fetch, limit=0), [])
        self.assertEqual(len(visited), 4)

    def test_failed_recheck_removes_previously_seen_future_year(self):
        roster = validated_roster(historical(), TODAY)
        entry = roster["as-one-fest"]
        s = state()
        scan(s, {"as-one-fest": entry}, TODAY, fetch=lambda _: (
            "<h1>As One Fest 2027</h1><p>Nouvelles annonces très prochainement.</p>"))
        self.assertEqual(len(validated_hints(s, TODAY)), 1)
        seen = []
        def fail(url):
            seen.append(url)
            raise OSError("site indisponible")
        out = scan(s, {"as-one-fest": entry}, TOMORROW, fetch=fail)
        self.assertEqual(seen, [entry["url"]])
        self.assertEqual(out[0]["status"], "UNAVAILABLE")
        self.assertEqual(validated_hints(s, TOMORROW), [])

    def test_private_poison_cannot_create_fetch_destination_or_published_entry(self):
        roster = validated_roster(historical(), TODAY)
        s = state()
        bad = {"slug": "bad", "name": "Bad", "region": "Occitanie",
               "url": "https://evil.example/admin"}
        with self.assertRaises(ValueError):
            scan(s, {"bad": bad}, TODAY, fetch=lambda url: self.fail(url))
        scan(s, {"as-one-fest": roster["as-one-fest"]}, TODAY, fetch=lambda _: (
            "<main><h1>As One Fest 2027</h1><p>Réservez cette année.</p></main>"))
        s["historical_future_edition_hints_private"]["evil"] = {
            "source_url": "https://evil.example/admin",
            "name_hint": "Evil Metal Fest 2027",
            "edition_year_hint": 2027, "publication_authorized": True}
        s["historical_future_edition_hints_private"]["barbeuk-metal-fest"] = dict(
            s["historical_future_edition_hints_private"]["as-one-fest"],
            source_url="https://evil.example/admin")
        valid = validated_hints(s, TODAY)
        self.assertEqual([x["slug"] for x in valid], ["as-one-fest"])
        queue = build_queue(s, report(), [], TODAY)
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        self.assertEqual(queue["historical_homepage_dossiers_private"], 1)
        d = queue["dossiers"][0]
        self.assertEqual(d["sources"][0]["kind"], "HISTORICAL_HOMEPAGE_YEAR_HINT")
        self.assertEqual(d["sources"][0]["url"], roster["as-one-fest"]["url"])
        self.assertFalse(d["publication_authorized"])
        self.assertFalse(d["safe_to_publish"])
        self.assertEqual(queue["publications"], 0)
        self.assertEqual(queue["network_requests"], 0)
        # If archive integrity has failed, no stale archived source may join.
        queue = build_queue(s, report(archive="DIVERGENT"), [], TODAY)
        self.assertEqual(queue["candidate_dossiers_count"], 0)
        self.assertEqual(queue["historical_homepage_year_hints_private"], 0)


if __name__ == "__main__":
    unittest.main()
