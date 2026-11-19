"""Generic national source research: synthetic, offline, no publication."""
from copy import deepcopy
import json
import unittest

from national_generic_primary_domain_preflight import examine, SCHEMA

DAY1, DAY2, DAY3 = "2026-11-06", "2026-11-07", "2026-11-08"
URL_A = "https://foudre-metal.fr/programmation"
URL_B = "https://nuit-acier.fr/"
NAMES = ("Festival Foudre du Nord", "Festival Nuit d Acier")


def source(url, today, kind="CURATED_PRIMARY_CANDIDATE", origin=None):
    return {
        "url": url, "kind": kind, "discovered_via": origin or url,
        "firstSeen": DAY1, "lastSeen": today,
        "publication_authorized": False,
        "independence_verified": False,
    }


def dossier(name, url, today):
    return {
        "id": "national-" + name.lower().replace(" ", "-"),
        "name_hint": name, "edition_year_hint": 2027,
        "publication_authorized": False, "safe_to_publish": False,
        "sources": [source(url, today)],
    }


def fixture(today=DAY1):
    state = {"schema": "grossesondes.source-watch.v1"}
    queue = {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "as_of": today, "review_only": True, "safe_to_publish": False,
        "publication_authorized": False,
        "dossiers": [dossier(NAMES[0], URL_A, today),
                     dossier(NAMES[1], URL_B, today)],
    }
    published = {"schema": 1, "festivals": []}
    return state, queue, published


def page(url):
    name = NAMES[0] if url == URL_A else NAMES[1]
    return f"<main><h1>{name} 2027</h1><p>Les 4 et 5 juin 2027, festival metal.</p></main>"


class GenericNationalFirstPartyTests(unittest.TestCase):
    def test_two_distinct_days_recheck_dates_without_publication(self):
        state, queue, published = fixture()
        visits = []
        read = lambda u: visits.append(u) or page(u)
        first = examine(state, queue, published, DAY1, fetch=read)
        self.assertEqual(first["schema"], SCHEMA)
        self.assertEqual(first["eligible_source_count"], 2)
        self.assertEqual(first["checked_count"], 2)
        self.assertEqual(first["two_day_dates_count"], 0)
        self.assertFalse(first["publication_authorized"])
        self.assertEqual(first["publications"], 0)
        same = examine(state, queue, published, DAY1, fetch=read)
        self.assertEqual(same["two_day_dates_count"], 0)
        next_state, next_queue, _ = fixture(DAY2)
        next_state.update(state)
        verified = examine(next_state, next_queue, published, DAY2, fetch=read)
        self.assertEqual(verified["two_day_dates_count"], 2)
        self.assertTrue(all(x["two_day_dates"] for x in verified["rows"]))
        self.assertEqual({x["start_date_hint"] for x in verified["rows"]},
                         {"2027-06-04"})
        self.assertEqual({x["end_date_hint"] for x in verified["rows"]},
                         {"2027-06-05"})
        self.assertEqual(len(visits), 6)
        self.assertFalse(verified["ownership_proven"])
        self.assertFalse(verified["official_site_authorized"])
        self.assertNotIn("showOnMap", json.dumps(verified))

    def test_malformed_and_untrusted_sources_never_fetched(self):
        for changed in (
            lambda s: s.update(kind="PRESS_ARTICLE_DATE_CLAIM_REVIEW"),
            lambda s: s.update(url="https://127.0.0.1/internal"),
            lambda s: s.update(url="https://foudre-metal.fr@evil.net/"),
            lambda s: s.update(discovered_via="https://wrong-domain.fr/"),
            lambda s: s.update(publication_authorized=True),
            lambda s: s.update(lastSeen="2026-10-01"),
        ):
            with self.subTest(changed=changed):
                state, queue, published = fixture(DAY1)
                for d in queue["dossiers"]:
                    d["sources"].clear()
                src = source(URL_A, DAY1)
                changed(src)
                queue["dossiers"][0]["sources"] = [src]
                visited = []
                result = examine(state, queue, published, DAY1,
                                 fetch=lambda u: visited.append(u))
                self.assertEqual(result["checked_count"], 0)
                self.assertEqual(visited, [])

    def test_ampersand_dates_recover_both_days_from_official_markup(self):
        state, queue, published = fixture()
        queue["dossiers"] = queue["dossiers"][:1]
        html = ("<main><h1>Festival Foudre du Nord 2027</h1>"
                "<p>25 &amp; 26 Juin 2027</p></main>")
        result = examine(state, queue, published, DAY1, fetch=lambda u: html)
        self.assertEqual(result["checked_count"], 1)
        self.assertEqual(result["rows"][0]["start_date_hint"], "2027-06-25")
        self.assertEqual(result["rows"][0]["end_date_hint"], "2027-06-26")
        self.assertFalse(result["rows"][0]["two_day_dates"])
        self.assertFalse(result["publication_authorized"])

    def test_same_host_homepage_recovers_dates_without_approving_domain(self):
        state, queue, published = fixture()
        queue["dossiers"] = queue["dossiers"][:1]
        deep = "<main><h1>Festival Foudre du Nord 2027</h1><p>Programmation à venir</p></main>"
        home = "https://foudre-metal.fr/"
        visits = []
        def fetch(url):
            visits.append(url)
            return page(URL_A) if url == home else deep
        first = examine(state, queue, published, DAY1, fetch=fetch)
        self.assertEqual(visits, [URL_A, home])
        self.assertEqual(first["rows"][0]["date_source_mode"], "SAME_HOST_HOME")
        self.assertEqual(first["rows"][0]["start_date_hint"], "2027-06-04")
        self.assertEqual(first["rows"][0]["end_date_hint"], "2027-06-05")
        self.assertFalse(first["official_site_authorized"])
        self.assertFalse(first["publication_authorized"])
        second_state, second_queue, _ = fixture(DAY2)
        second_state.update(state)
        second = examine(second_state, second_queue, published, DAY2,
                         fetch=fetch)
        self.assertEqual(second["two_day_dates_count"], 1)
        self.assertEqual(second["rows"][0]["date_source_mode"], "SAME_HOST_HOME")
        self.assertEqual(second["publications"], 0)

    def test_homepage_fallback_never_overrides_visible_date_or_jsonld_conflict(self):
        deep = "<main><h1>Festival Foudre du Nord 2027</h1><p>Programmation</p></main>"
        broken = [
            deep.replace("Programmation", "Annulé 25 et 26 juillet 2027"),
            deep.replace("Programmation", "4 et 5 juin 2027, puis 25 et 26 juillet 2027"),
        ]
        for detail in broken:
            with self.subTest(detail=detail):
                state, queue, published = fixture()
                queue["dossiers"] = queue["dossiers"][:1]
                visited = []
                result = examine(state, queue, published, DAY1,
                                 fetch=lambda u: visited.append(u) or detail)
                self.assertEqual(visited, [URL_A])
                self.assertEqual(result["rows"][0]["status"],
                                 "EXPLICIT_CURRENT_EDITION_DATES_NOT_FOUND")
        # Hidden structured data cannot certify dates, but a same-edition
        # contradictory JSON-LD document vetoes the later homepage proof.
        conflict = deep + ('<script type="application/ld+json">'
            '{"@type":"MusicEvent","name":"Festival Foudre du Nord 2027",'
            '"startDate":"2027-07-04","endDate":"2027-07-05"}</script>')
        state, queue, published = fixture()
        queue["dossiers"] = queue["dossiers"][:1]
        visited = []
        result = examine(
            state, queue, published, DAY1,
            fetch=lambda url: visited.append(url) or
                (page(URL_A) if url == "https://foudre-metal.fr/" else conflict))
        self.assertEqual(visited, [URL_A, "https://foudre-metal.fr/"])
        self.assertEqual(result["rows"][0]["status"],
                         "EXPLICIT_CURRENT_EDITION_DATES_NOT_FOUND")

    def test_no_extra_fetch_for_home_source_or_valid_detail(self):
        for source_url, detail_html in (
                (URL_A, page(URL_A)),
                (URL_B, "<h1>Festival Nuit d Acier 2027</h1><p>Dates à venir</p>")):
            with self.subTest(source_url=source_url):
                state, queue, published = fixture()
                queue["dossiers"] = [dossier(
                    NAMES[0] if source_url == URL_A else NAMES[1],
                    source_url, DAY1)]
                visited = []
                result = examine(state, queue, published, DAY1,
                                 fetch=lambda url: visited.append(url) or detail_html)
                self.assertEqual(visited, [source_url])
                if source_url == URL_A:
                    self.assertEqual(result["rows"][0]["date_source_mode"],
                                     "SOURCE_PAGE")
                else:
                    self.assertIsNone(result["rows"][0]["date_source_mode"])

    def test_mode_change_resets_two_day_evidence(self):
        state, queue, published = fixture()
        queue["dossiers"] = queue["dossiers"][:1]
        deep = "<h1>Festival Foudre du Nord 2027</h1><p>Programme en cours</p>"
        home = "https://foudre-metal.fr/"
        examine(state, queue, published, DAY1,
                fetch=lambda u: page(URL_A) if u == home else deep)
        changed_state, changed_queue, _ = fixture(DAY2)
        changed_state.update(state)
        changed = examine(changed_state, changed_queue, published, DAY2,
                          fetch=lambda u: page(URL_A))
        self.assertEqual(changed["two_day_dates_count"], 0)
        self.assertEqual(changed["rows"][0]["date_source_mode"], "SOURCE_PAGE")
        final_queue = fixture(DAY3)[1]
        stable = examine(changed_state, final_queue, published, DAY3,
                         fetch=lambda u: page(URL_A))
        self.assertEqual(stable["two_day_dates_count"], 1)

    def test_bad_dates_annulations_jsonld_conflicts_do_not_stabilize(self):
        cases = (
            "<h1>Festival Foudre du Nord 2027</h1><p>Dates à venir</p>",
            page(URL_A).replace("4 et 5", "4 et 6") +
                '<script type="application/ld+json">' +
                '{"@type":"MusicEvent","name":"Festival Foudre du Nord 2027",'
                '"startDate":"2027-06-04","endDate":"2027-06-05"}</script>',
            page(URL_A).replace("festival metal", "festival annulé"),
        )
        for html in cases:
            with self.subTest(html=html[:80]):
                state, queue, published = fixture()
                queue["dossiers"] = queue["dossiers"][:1]
                result = examine(state, queue, published, DAY1, fetch=lambda u: html)
                self.assertEqual(result["two_day_dates_count"], 0)
                self.assertEqual(result["rows"][0]["status"],
                                 "EXPLICIT_CURRENT_EDITION_DATES_NOT_FOUND")

    def test_published_edition_is_not_probed_as_duplicate(self):
        state, queue, published = fixture()
        published["festivals"] = [{
            "name": NAMES[0] + " 2027", "startDate": "2027-06-04",
            "slug": "festival-foudre-du-nord-2027",
        }]
        visits = []
        result = examine(state, queue, published, DAY1,
                         fetch=lambda url: visits.append(url) or page(url))
        self.assertEqual(visits, [URL_B])
        self.assertEqual(result["eligible_source_count"], 1)

    def test_changed_dates_reset_stability_and_failed_fetch_resets_state(self):
        state, queue, published = fixture()
        examine(state, queue, published, DAY1, fetch=page)
        other, next_queue, _ = fixture(DAY2)
        other.update(state)
        changed = examine(
            other, next_queue, published, DAY2,
            fetch=lambda url: page(url).replace("4 et 5", "5 et 6"))
        self.assertEqual(changed["two_day_dates_count"], 0)
        self.assertTrue(all(x["status"] ==
            "FIRST_DAY_GENERIC_PRIMARY_DATES_REVIEW_ONLY" for x in changed["rows"]))
        queue3 = fixture(DAY3)[1]
        unavailable = examine(
            other, queue3, published, DAY3,
            fetch=lambda u: (_ for _ in ()).throw(OSError("test network offline")))
        self.assertEqual(unavailable["two_day_dates_count"], 0)
        self.assertTrue(all(x["status"] ==
            "GENERIC_PRIMARY_HTTPS_UNAVAILABLE" for x in unavailable["rows"]))
        self.assertEqual(other["national_generic_primary_date_observations_private"], {})

    def test_forged_favorable_input_flags_fail_before_network(self):
        state, queue, published = fixture()
        for key, value in (
            ("publication_authorized", True),
            ("safe_to_publish", True),
            ("as_of", DAY2),
        ):
            with self.subTest(key=key):
                bad = dict(queue, **{key: value})
                with self.assertRaises(ValueError):
                    examine(state, bad, published, DAY1,
                            fetch=lambda u: self.fail("forged queue fetched"))

    def test_twice_daily_passes_discover_eight_distinct_sources(self):
        state, queue, published = fixture()
        queue["dossiers"].extend([
            dossier("Festival Granit et Feu", "https://granit-feu.fr/", DAY1),
            dossier("Festival Lames de Nuit", "https://lames-nuit.fr/", DAY1),
            dossier("Festival Roche et Riff", "https://roche-riff.fr/", DAY1),
            dossier("Festival Poussiere Rouge", "https://poussiere-rouge.fr/", DAY1),
            dossier("Festival Coups de Tonnerre", "https://coups-tonnerre.fr/", DAY1),
            dossier("Festival Sons Nocturnes", "https://sons-nocturnes.fr/", DAY1),
        ])
        visited = []
        def html(url):
            visited.append(url)
            name = next(d["name_hint"] for d in queue["dossiers"]
                        if d["sources"][0]["url"] == url)
            return f"<main><h1>{name} 2027</h1><p>Les 4 et 5 juin 2027.</p></main>"
        morning = examine(state, queue, published, DAY1, fetch=html)
        self.assertEqual(morning["checked_count"], 4)
        first_four = set(visited)
        visited.clear()
        evening = examine(state, queue, published, DAY1, fetch=html)
        self.assertEqual(evening["checked_count"], 4)
        self.assertFalse(first_four.intersection(visited))
        self.assertEqual(len(first_four.union(visited)), 8)
        self.assertEqual(evening["two_day_dates_count"], 0)
        queue["as_of"] = DAY2
        for d in queue["dossiers"]:
            d["sources"][0]["lastSeen"] = DAY2
        early = examine(state, queue, published, DAY2, fetch=html)
        late = examine(state, queue, published, DAY2, fetch=html)
        self.assertEqual(early["two_day_dates_count"], 4)
        self.assertEqual(late["two_day_dates_count"], 4)

    def test_two_day_rotation_prioritizes_stable_next_day(self):
        state, queue, published = fixture()
        queue["dossiers"].extend([
            dossier("Festival Granit et Feu", "https://granit-feu.fr/", DAY1),
            dossier("Festival Lames de Nuit", "https://lames-nuit.fr/", DAY1),
        ])
        visited = []
        def html(url):
            visited.append(url)
            name = next(d["name_hint"] for d in queue["dossiers"]
                        if d["sources"][0]["url"] == url)
            return f"<main><h1>{name} 2027</h1><p>Les 4 et 5 juin 2027.</p></main>"
        first = examine(state, queue, published, DAY1, fetch=html)
        self.assertEqual(first["checked_count"], 4)
        before = set(visited)
        queue["as_of"] = DAY2
        for d in queue["dossiers"]:
            d["sources"][0]["lastSeen"] = DAY2
        visited.clear()
        second = examine(state, queue, published, DAY2, fetch=html)
        self.assertEqual(set(visited), before)
        self.assertEqual(second["two_day_dates_count"], 4)


if __name__ == "__main__":
    unittest.main()
