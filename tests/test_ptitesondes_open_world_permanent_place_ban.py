from copy import deepcopy
import unittest

from test_ptitesondes_dila_municipal_domains import CITY, PAGE, mairie, payload
from ptitesondes_open_world_permanent_place_ban import (
    official_facts, corroborate_official_ban, discover_official_ban,
)

VENUE = "Ludothèque des enfants"
HTML = f"<main><h1>{VENUE}</h1><p>12 Rue des Jeux, 12345 {CITY}</p><p>Ouverte à tous, espace de jeux pour enfants.</p></main>"
DIR = payload(mairie())
BAN = {"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "properties": {"type": "housenumber", "score": .99, "citycode": "12345",
                   "postcode": "12345", "city": CITY, "housenumber": "12",
                   "street": "Rue des Jeux", "label": f"12 Rue des Jeux 12345 {CITY}"},
    "geometry": {"type": "Point", "coordinates": [3.1, 45.1]}}]}
ADMIN = [{"nom": CITY, "code": "12345", "codesPostaux": ["12345"],
          "codeDepartement": "12", "departement": {"code": "12", "nom": "Test"},
          "codeRegion": "76", "region": {"code": "76", "nom": "Test"}}]


class OfficialPlaceBANTests(unittest.TestCase):
    def check(self, html=HTML, directory=DIR, ban=BAN, admin=ADMIN, url=PAGE):
        return corroborate_official_ban(CITY, VENUE, url, html, directory,
                                      lambda _: ban, lambda *_: admin)

    def test_independent_precise_address_without_osm_or_event_uid(self):
        d = self.check()
        self.assertIsNotNone(d)
        self.assertEqual((d["lat"], d["lng"]), (45.1, 3.1))
        self.assertEqual(d["category"], "ludotheque")
        self.assertFalse(d["public_eligible"])
        self.assertFalse(d["publication_ready"])
        self.assertEqual(d["public_writes"], 0)

    def test_unofficial_host_or_wrong_city_rejected_before_geocoding(self):
        for url, directory in (("https://other.example/lieu", DIR),
                               (PAGE, payload(mairie(city="Autre ville")))):
            self.assertIsNone(corroborate_official_ban(
                CITY, VENUE, url, HTML, directory,
                lambda _: self.fail("unexpected BAN fetch"),
                lambda *_: self.fail("unexpected admin fetch")))

    def test_hidden_or_conflicting_or_numberless_address_does_not_pass_ban(self):
        for html in (
            HTML.replace("<p>12", "<p hidden>12"),
            HTML.replace("12 Rue", "Rue"),
            HTML.replace("</main>", f"<p>14 Rue des Jeux, 12345 {CITY}</p></main>"),
            HTML.replace("Ouverte à tous", "Pas ouverte à tous"),
            HTML.replace("espace de jeux pour enfants", "informations"),
            HTML.replace("</main>", "<p>Fermeture définitive</p></main>"),
            HTML.replace(f"<h1>{VENUE}</h1>", "").replace("<main>", f"<h1>{VENUE}</h1><main>"),
        ):
            self.assertIsNone(official_facts(CITY, VENUE, PAGE, html, DIR), html)

    def test_wrong_ban_citycode_postcode_score_or_centroid(self):
        for key, value in (("citycode", "99999"), ("postcode", "99999"),
                           ("score", .80), ("type", "street"), ("housenumber", "14")):
            ban = deepcopy(BAN)
            ban["features"][0]["properties"][key] = value
            self.assertIsNone(self.check(ban=ban))
        ban = deepcopy(BAN)
        ban["features"] *= 2
        self.assertIsNone(self.check(ban=ban))

    def test_administrative_identity_must_agree(self):
        self.assertIsNone(self.check(admin=[dict(ADMIN[0], code="99999")]))
        self.assertIsNone(self.check(admin=[]))

    def test_live_discovery_revalidates_hint_and_never_reads_untrusted_url(self):
        read = []
        def page(url):
            read.append(url)
            if url == PAGE:
                return HTML
            return f'<a href="{PAGE}">{VENUE}</a>'
        row = {"city": CITY, "venue": VENUE,
               "possible_website_unverified": "https://other.example/lieu"}
        proof = discover_official_ban(row, directory_fetch=lambda _: DIR,
            page_read=page, ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        self.assertIsNotNone(proof)
        self.assertEqual(read, ["https://www.ville-les-bois.fr/", PAGE])
        read.clear()
        row["possible_website_unverified"] = PAGE
        proof = discover_official_ban(row, directory_fetch=lambda _: DIR,
            page_read=page, ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        self.assertIsNotNone(proof)
        self.assertEqual(read, [PAGE])
        row["historical_address_unverified"] = {"postal_code": "99999"}
        self.assertIsNone(discover_official_ban(row, directory_fetch=lambda _: DIR,
            page_read=page, ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN))

    def test_production_dila_code_fallback_requires_fresh_identity_and_exact_page(self):
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345",
                  "site_internet_et_autres_liens": PAGE}
        calls = []
        def lookup(city, venue):
            calls.append(("culture", city, venue))
            return record
        def by_code(city, code):
            calls.append(("dila", city, code))
            return DIR
        def read(url):
            calls.append(("page", url))
            return HTML
        kwargs = dict(directory_fetch=lambda _: payload(), cultural_lookup=lookup,
                      code_directory_fetch=by_code, page_read=read,
                      ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        row = {"city": CITY, "venue": VENUE}
        from ptitesondes_open_world_permanent_place_ban import ban_diagnostics
        before = ban_diagnostics()
        proof = discover_official_ban(row, **kwargs)
        after = ban_diagnostics()
        for key in ("directory_code_fallback_attempted", "directory_code_fallback_found"):
            self.assertEqual(after.get(key, 0) - before.get(key, 0), 1)
        self.assertIsNotNone(proof)
        self.assertFalse(proof["publication_ready"])
        self.assertEqual(calls, [("culture", CITY, VENUE), ("dila", CITY, "12345"), ("page", PAGE)])
        for bad in (dict(record, code_commune="99999"), dict(record, nom_du_lieu="Autre lieu")):
            calls.clear()
            self.assertIsNone(discover_official_ban(row, **dict(kwargs, cultural_lookup=lambda *_: bad)))
            self.assertFalse(any(x[0] == "page" for x in calls))

    def test_publisher_reconstructs_insee_fallback_without_trusting_saved_code_or_coordinates(self):
        from datetime import date
        from ptitesondes_open_world_permanent_place_research import STATE_SCHEMA
        from ptitesondes_open_world_permanent_place_publisher_preview import review_drafts
        from ptitesondes_place_preflight import merge_open_world_drafts
        day = date(2026, 11, 28)
        private = {"schema": STATE_SCHEMA, "records": [{
            "city": CITY, "venue": VENUE, "status": "independent_evidence_found",
            "public_eligible": False, "evidence": {"public_eligible": False,
                "method": "dila_official_place_address_plus_ban",
                "official_url": PAGE, "lat": 0, "lng": 0, "code_commune": "99999"}}]}
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345"}
        calls = []
        def by_code(city, code):
            calls.append((city, code))
            return DIR
        kwargs = dict(directory_fetch=lambda _: payload(), cultural_lookup=lambda *_: record,
                      code_directory_fetch=by_code, page_read=lambda _: HTML,
                      ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN,
                      osm_fetch=lambda *_: self.fail("must not call Overpass"))
        drafts, summary = review_drafts(private, day, **kwargs)
        self.assertEqual(calls, [(CITY, "12345")])
        self.assertEqual(summary["complete_draft_records"], 1)
        self.assertEqual((drafts[0]["lat"], drafts[0]["lng"]), (45.1, 3.1))
        current = {"version": 1, "updated_at": day.isoformat(), "places": []}
        out, counts = merge_open_world_drafts(current, drafts, day)
        self.assertEqual(counts["open_world_added"], 1)
        self.assertEqual(len(out["places"]), 1)
        drafts, summary = review_drafts(private, day,
            **dict(kwargs, code_directory_fetch=lambda *_: payload()))
        self.assertEqual(drafts, [])
        self.assertEqual(summary["counts"]["fresh_ban_evidence_unavailable"], 1)

    def test_outage_does_not_stop_independent_ban_rotation(self):
        from datetime import date
        from ptitesondes_open_world_permanent_place_research import cycle
        from test_ptitesondes_open_world_permanent_place_research import report, row
        candidates = report(*(row(f"Lieu {i}", CITY) for i in range(8)))
        calls, fallback = [], []
        def down(*args):
            calls.append(args)
            raise OSError("map offline")
        def alternative(lead):
            fallback.append(lead["venue"])
            return {"city": lead["city"], "venue": lead["venue"],
                    "method": "dila_official_place_address_plus_ban",
                    "public_eligible": False, "publication_ready": False,
                    "public_writes": 0}
        state, summary = cycle(candidates, None, date(2026, 11, 26),
                               osm_fetch=down, stop_on_outage=True,
                               limit=8, ban_research=alternative)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(fallback), 8)
        self.assertEqual(summary["map_skipped_after_outage"], 5)
        self.assertEqual(summary["ban_fallback_matches"], 8)
        self.assertEqual(summary["unattempted"], 0)
        self.assertTrue(all(r["public_eligible"] is False for r in state["records"]))

    def test_publisher_rebuilds_fresh_ban_draft_and_append_only(self):
        from datetime import date
        from ptitesondes_open_world_permanent_place_research import STATE_SCHEMA
        from ptitesondes_open_world_permanent_place_publisher_preview import review_drafts
        from ptitesondes_place_preflight import merge_open_world_drafts
        from ptitesondes_places import validate
        day = date(2026, 11, 26)
        private = {"schema": STATE_SCHEMA, "records": [{
            "city": CITY, "venue": VENUE, "status": "independent_evidence_found",
            "public_eligible": False,
            "evidence": {"public_eligible": False,
                         "method": "dila_official_place_address_plus_ban",
                         "official_url": PAGE, "lat": 0, "lng": 0,
                         "postcode": "99999", "admission": "invented"}}]}
        kwargs = dict(directory_fetch=lambda _: DIR, page_read=lambda _: HTML,
                      ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN,
                      osm_fetch=lambda *_: self.fail("must not call Overpass"))
        drafts, summary = review_drafts(private, day, **kwargs)
        self.assertEqual(summary["complete_draft_records"], 1)
        draft = drafts[0]
        self.assertEqual((draft["lat"], draft["lng"]), (45.1, 3.1))
        self.assertEqual(draft["postal_code"], "12345")
        self.assertNotEqual(draft["admission"], "invented")
        self.assertIsNone(draft["age_min"])
        self.assertTrue(draft["id"].startswith("ban-place-"))
        current = {"version": 1, "updated_at": day.isoformat(), "places": []}
        out, counts = merge_open_world_drafts(current, drafts, day)
        self.assertEqual(counts["open_world_added"], 1)
        self.assertEqual(validate(out), 1)
        same, counts = merge_open_world_drafts(out, drafts, day)
        self.assertEqual(same, out)
        self.assertEqual(counts["open_world_duplicate"], 1)
        forged = dict(draft, geo_source_url="https://data.geopf.fr/geocodage/search?q=wrong")
        _, counts = merge_open_world_drafts(current, [forged], day)
        self.assertEqual(counts["open_world_invalid"], 1)
        kwargs["ban_fetch"] = lambda _: {"type": "FeatureCollection", "features": []}
        drafts, summary = review_drafts(private, day, **kwargs)
        self.assertEqual(drafts, [])
        self.assertEqual(summary["counts"]["fresh_ban_evidence_unavailable"], 1)

    def test_discovery_through_culture_section_without_external_crawling(self):
        home = "https://www.ville-les-bois.fr/"
        section = home + "culture"
        calls = []
        def page(url):
            calls.append(url)
            return {home: '<a href="/culture">Culture</a><a href="https://untrusted.example/jeunesse">Jeunesse</a>',
                    section: f'<a href="{PAGE}">{VENUE}</a>',
                    PAGE: HTML}[url]
        proof = discover_official_ban({"city": CITY, "venue": VENUE},
            directory_fetch=lambda _: DIR, page_read=page,
            ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        self.assertIsNotNone(proof)
        self.assertEqual(calls, [home, section, PAGE])

    def test_nested_municipal_sections_bounded_and_exact(self):
        home = "https://www.ville-les-bois.fr/"
        culture, library = home + "culture", home + "bibliotheques"
        calls = []
        pages = {
            home: '<a href="/culture">Culture</a>',
            culture: '<a href="/bibliotheques">Bibliothèques</a><a href="/culture">Culture</a><a href="https://foreign.example/jeunesse">Jeunesse</a>',
            library: f'<a href="{PAGE}">{VENUE}</a>',
            PAGE: HTML,
        }
        def read(url):
            calls.append(url)
            return pages[url]
        kwargs = dict(directory_fetch=lambda _: DIR, page_read=read,
                      ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        row = {"city": CITY, "venue": VENUE}
        self.assertIsNotNone(discover_official_ban(row, **kwargs))
        self.assertEqual(calls, [home, culture, library, PAGE])
        calls.clear()
        pages[library] += f'<a href="{home}autre-lieu">{VENUE}</a>'
        self.assertIsNone(discover_official_ban(row, **kwargs))
        self.assertEqual(calls, [home, culture, library])

    def test_diagnostics_distinguish_transport_identity_and_ban_failures(self):
        from ptitesondes_open_world_permanent_place_ban import ban_diagnostics
        from ptitesondes_open_world_permanent_place_research import public_diagnostic_lines
        before = ban_diagnostics()
        def down(_):
            raise OSError("private URL must not be logged")
        row = {"city": CITY, "venue": VENUE, "possible_website_unverified": PAGE}
        self.assertIsNone(discover_official_ban(row, directory_fetch=down))
        self.assertIsNone(self.check(html=HTML.replace(VENUE, "Autre lieu")))
        self.assertIsNone(self.check(ban={"type": "FeatureCollection", "features": []}))
        after = ban_diagnostics()
        for label in ("directory_unavailable", "official_identity_unmatched", "ban_exact_address_unmatched"):
            self.assertEqual(after[label] - before.get(label, 0), 1)
        lines = public_diagnostic_lines({"ban_diagnostics": {
            "directory_unavailable": 2, "private URL": 3,
            "ban_unavailable": "secret", "admin_unavailable": True}})
        self.assertEqual(lines, ["ban_diagnostics.directory_unavailable: 2"])

    def test_municipal_https_redirects_recheck_scope_and_dns(self):
        from ptitesondes_unlisted_source_safe_recheck import read_municipal_https, read_unknown_https
        from test_ptitesondes_unlisted_source_safe_recheck import FakeResponse, FakeConnection, dns
        home = "https://www.ville-les-bois.fr/"
        class Redirect(FakeResponse):
            def __init__(self, destination):
                super().__init__(status=302)
                self.destination = destination
            def getheader(self, key):
                return self.destination if key == "Location" else super().getheader(key)
        calls = []
        def factory(host, ip):
            calls.append((host, ip))
            return FakeConnection(Redirect(PAGE) if len(calls) == 1 else FakeResponse(HTML))
        final, html = read_municipal_https(home, CITY, DIR, resolver=dns("8.8.8.8"),
                                         connection_factory=factory)
        self.assertEqual((final, html), (PAGE, HTML))
        self.assertEqual(len(calls), 2)
        for target in ("https://other.example/", "http://www.ville-les-bois.fr/",
                       "https://127.0.0.1/", home):
            calls.clear()
            def blocked(host, ip):
                calls.append(host)
                return FakeConnection(Redirect(target))
            with self.assertRaises(ValueError):
                read_municipal_https(home, CITY, DIR, resolver=dns("8.8.8.8"),
                                     connection_factory=blocked)
            self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError):
            read_unknown_https(home, resolver=dns("8.8.8.8"),
                               connection_factory=lambda *_: FakeConnection(Redirect(PAGE)))

    def test_municipal_redirect_preserves_final_page_identity(self):
        from unittest.mock import patch
        home = "https://www.ville-les-bois.fr/"
        canonical_home = home + "accueil/"
        canonical_page = home + "accueil/lieu"
        reads = []
        def municipal_read(url, city, directory):
            reads.append(url)
            if url == home:
                return canonical_home, f'<a href="lieu">{VENUE}</a>'
            self.assertEqual(url, canonical_page)
            return PAGE, HTML
        with patch("ptitesondes_unlisted_source_safe_recheck.read_municipal_https", municipal_read):
            proof = discover_official_ban({"city": CITY, "venue": VENUE},
                directory_fetch=lambda _: DIR, ban_fetch=lambda _: BAN,
                admin_fetch=lambda *_: ADMIN)
        self.assertIsNotNone(proof)
        self.assertEqual(proof["official_url"], PAGE)
        self.assertEqual(reads, [home, canonical_page])

    def test_national_directory_hint_requires_authenticated_municipal_scope(self):
        seen = []
        def read(url):
            seen.append(url)
            self.assertEqual(url, PAGE)
            return HTML
        def lookup(city, venue):
            self.assertEqual((city, venue), (CITY, VENUE))
            return {"site_internet_et_autres_liens": [
                "https://external.example/lieu", PAGE]}
        proof = discover_official_ban({"city": CITY, "venue": VENUE},
            directory_fetch=lambda _: DIR, page_read=read,
            cultural_lookup=lookup, ban_fetch=lambda _: BAN,
            admin_fetch=lambda *_: ADMIN)
        self.assertIsNotNone(proof)
        self.assertEqual(seen, [PAGE])
        self.assertFalse(proof["public_eligible"])

    def test_independent_cultural_route_and_fresh_publisher_without_dila(self):
        from datetime import date
        from ptitesondes_open_world_permanent_place_ban import discover_independent_cultural_ban
        from ptitesondes_open_world_permanent_place_research import STATE_SCHEMA, cycle
        from ptitesondes_open_world_permanent_place_publisher_preview import review_drafts
        from test_ptitesondes_open_world_permanent_place_research import report, row
        url = "https://lieu-independant.example/"
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345",
                  "code_postal": "12345", "numero_et_libelle_voie": "12 Rue des Jeux",
                  "adresse_complete": f"12 Rue des Jeux, 12345 {CITY}",
                  "site_internet_et_autres_liens": url,
                  "latitude": 0, "longitude": 0}
        def read(value):
            self.assertEqual(value, url)
            return HTML
        kwargs = dict(cultural_lookup=lambda *_: record, page_read=read,
                      ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        lead = {"city": CITY, "venue": VENUE}
        proof = discover_independent_cultural_ban(lead, **kwargs)
        self.assertEqual(proof["method"], "culture_directory_official_place_address_plus_ban")
        self.assertEqual((proof["lat"], proof["lng"]), (45.1, 3.1))
        self.assertFalse(proof["public_eligible"])
        def offline(*_):
            raise OSError("Overpass unavailable")
        day = date(2026, 11, 27)
        state, summary = cycle(report(row(VENUE, CITY)), None, day,
            osm_fetch=offline, ban_research=lambda r: discover_independent_cultural_ban(r, **kwargs))
        self.assertEqual(summary["ban_fallback_matches"], 1)
        state["records"][0]["evidence"].update(lat=0, lng=0, official_url="https://forged.example/")
        drafts, summary = review_drafts(state, day,
            directory_fetch=lambda _: self.fail("DILA not needed"),
            osm_fetch=lambda *_: self.fail("OSM not needed"), **kwargs)
        self.assertEqual(summary["complete_draft_records"], 1)
        self.assertEqual(drafts[0]["official_url"], url)
        self.assertEqual((drafts[0]["lat"], drafts[0]["lng"]), (45.1, 3.1))
        for changed in (
            dict(record, adresse_complete=f"14 Rue des Jeux, 12345 {CITY}"),
            dict(record, site_internet_et_autres_liens="https://127.0.0.1/"),
        ):
            self.assertIsNone(discover_independent_cultural_ban(lead,
                **dict(kwargs, cultural_lookup=lambda *_: changed,
                       page_read=lambda _: self.fail("unverified URL must not be read"))))
        drafts, summary = review_drafts(state, day, **dict(kwargs, cultural_lookup=lambda *_: None))
        self.assertEqual(drafts, [])

    def test_cultural_canonical_page_keeps_exact_authority(self):
        from ptitesondes_open_world_permanent_place_ban import discover_independent_cultural_ban
        from unittest.mock import patch
        home = "https://culture.fr/"
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345",
                  "code_postal": "12345", "numero_et_libelle_voie": "12 Rue des Jeux",
                  "adresse_complete": f"12 Rue des Jeux, 12345 {CITY}",
                  "site_internet_et_autres_liens": home}
        kwargs = dict(cultural_lookup=lambda *_: record, ban_fetch=lambda _: BAN,
                      admin_fetch=lambda *_: ADMIN)
        lead = {"city": CITY, "venue": VENUE}
        with patch("ptitesondes_unlisted_source_safe_recheck.read_cultural_https",
                   return_value=(home+"lieu/", HTML)):
            self.assertEqual(discover_independent_cultural_ban(lead, **kwargs)["official_url"],
                             home+"lieu/")
        with patch("ptitesondes_unlisted_source_safe_recheck.read_cultural_https",
                   return_value=("https://www.culture.fr/lieu/", HTML)):
            self.assertEqual(discover_independent_cultural_ban(lead, **kwargs)["official_url"],
                             "https://www.culture.fr/lieu/")
        with patch("ptitesondes_unlisted_source_safe_recheck.read_cultural_https",
                   return_value=("https://other.example/", HTML)):
            self.assertIsNone(discover_independent_cultural_ban(lead, **kwargs))

    def test_cultural_explicit_main_landmark_not_whole_body(self):
        from ptitesondes_open_world_permanent_place_ban import discover_independent_cultural_ban
        url = "https://culture.fr/lieu/"
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345",
                  "code_postal": "12345", "numero_et_libelle_voie": "12 Rue des Jeux",
                  "adresse_complete": f"12 Rue des Jeux, 12345 {CITY}",
                  "site_internet_et_autres_liens": url}
        lead = {"city": CITY, "venue": VENUE}
        def qualify(html):
            return discover_independent_cultural_ban(lead, cultural_lookup=lambda *_: record,
                page_read=lambda _: html, ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        body = HTML.replace("<main>", '<div role="main">').replace("</main>", "</div>")
        self.assertIsNotNone(qualify(body))
        for bad in (body.replace('role="main"', 'class="main"'),
                    body.replace('role="main"', 'role="main" hidden'),
                    body+'<div role="main"><p>Other</p></div>',
                    body.replace(f"<h1>{VENUE}</h1>", "")+f"<h1>{VENUE}</h1>",
                    body.replace("12 Rue", "14 Rue")):
            self.assertIsNone(qualify(bad))
        self.assertIsNone(official_facts(CITY, VENUE, PAGE, body, DIR))

    def test_cultural_exact_official_alias_not_fuzzy_identity(self):
        from ptitesondes_open_world_permanent_place_ban import discover_independent_cultural_ban
        url = "https://culture.fr/lieu/"
        alias = "La Maison des Jeux"
        record = {"commune": CITY, "nom_du_lieu": VENUE, "nom_usuel_du_lieu": alias,
                  "code_commune": "12345", "code_postal": "12345",
                  "numero_et_libelle_voie": "12 Rue des Jeux",
                  "adresse_complete": f"12 Rue des Jeux, 12345 {CITY}",
                  "site_internet_et_autres_liens": url}
        lead = {"city": CITY, "venue": VENUE}
        def qualify(html):
            return discover_independent_cultural_ban(lead, cultural_lookup=lambda *_: record,
                page_read=lambda _: html, ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
        self.assertEqual(qualify(HTML.replace(VENUE, alias))["venue"], VENUE)
        for bad in (HTML.replace(VENUE, alias+" autre"),
                    HTML.replace("</main>", f"<h1>{alias}</h1></main>"),
                    HTML.replace(VENUE, alias).replace("12 Rue", "14 Rue")):
            self.assertIsNone(qualify(bad))

    def test_cultural_homepage_exact_dedicated_link_only(self):
        from ptitesondes_open_world_permanent_place_ban import discover_independent_cultural_ban
        home = "https://culture.example/"
        target = home+"lieu/"
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345",
                  "code_postal": "12345", "numero_et_libelle_voie": "12 Rue des Jeux",
                  "adresse_complete": f"12 Rue des Jeux, 12345 {CITY}",
                  "site_internet_et_autres_liens": home}
        lead = {"city": CITY, "venue": VENUE}
        for link, expected in (
            (f'<a href="/lieu/">{VENUE}</a>', True),
            (f'<a href="https://other.example/lieu/">{VENUE}</a>', False),
            (f'<a hidden href="/lieu/">{VENUE}</a>', False),
            (f'<a href="/lieu/">{VENUE}</a><a href="/autre/">{VENUE}</a>', False),
        ):
            calls = []
            def read(url):
                calls.append(url)
                return ("<main><h1>Accueil culturel</h1>"+link+"</main>") if url == home else HTML
            proof = discover_independent_cultural_ban(lead, cultural_lookup=lambda *_: record,
                page_read=read, ban_fetch=lambda _: BAN, admin_fetch=lambda *_: ADMIN)
            self.assertEqual(proof is not None, expected)
            self.assertEqual(calls, [home, target] if expected else [home])
            if expected:
                self.assertEqual(proof["official_url"], target)

    def test_cultural_identity_failure_stages_are_distinct(self):
        from ptitesondes_open_world_permanent_place_ban import discover_independent_cultural_ban, ban_diagnostics
        lead = {"city": CITY, "venue": VENUE}
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345",
                  "code_postal": "12345", "numero_et_libelle_voie": "12 Rue des Jeux",
                  "adresse_complete": f"12 Rue des Jeux, 12345 {CITY}"}
        for data, reason in (
            (None, "record_missing"),
            (dict(record, numero_et_libelle_voie="Rue des Jeux"), "numbered_street_missing"),
            (dict(record, adresse_complete=f"14 Rue des Jeux, 12345 {CITY}"), "complete_address_mismatch"),
            (record, "url_missing"),
        ):
            before = ban_diagnostics()
            self.assertIsNone(discover_independent_cultural_ban(lead, cultural_lookup=lambda *_: data,
                         page_read=lambda _: self.fail("must not read")))
            after = ban_diagnostics()
            key = "culture_independent_" + reason
            self.assertEqual(after[key] - before.get(key, 0), 1)

    def test_multiple_cultural_links_require_exact_consistent_proof(self):
        from ptitesondes_open_world_permanent_place_ban import discover_independent_cultural_ban
        a, b = "https://a.example/lieu", "https://b.example/lieu"
        row = {"city": CITY, "venue": VENUE}
        record = {"commune": CITY, "nom_du_lieu": VENUE, "code_commune": "12345",
                  "code_postal": "12345", "numero_et_libelle_voie": "12 Rue des Jeux",
                  "adresse_complete": f"12 Rue des Jeux, 12345 {CITY}",
                  "site_internet_et_autres_liens": [a, b]}
        def find(other, ban_fetch=lambda _: BAN):
            return discover_independent_cultural_ban(row, cultural_lookup=lambda *_: record,
                page_read=lambda url: HTML if url == a else other,
                ban_fetch=ban_fetch, admin_fetch=lambda *_: ADMIN)
        self.assertEqual(find(HTML.replace(VENUE, "Autre lieu"))["official_url"], a)
        self.assertEqual(find(HTML)["official_url"], a)
        for contradictory in (HTML.replace("12 Rue", "14 Rue"),
                              HTML.replace("</main>", "<p>Fermeture définitive</p></main>"),
                              HTML.replace("Ouverte à tous", "Pas ouverte à tous")):
            self.assertIsNone(find(contradictory, lambda _: self.fail("contradiction before BAN")))
        record["site_internet_et_autres_liens"] = [f"https://a{i}.example/lieu" for i in range(5)]
        self.assertIsNone(discover_independent_cultural_ban(row, cultural_lookup=lambda *_: record,
            page_read=lambda _: self.fail("bounded list must not be read")))

    def test_ban_unavailable_is_not_publication_permission(self):
        def down(_):
            raise OSError("provider unavailable")
        self.assertIsNone(corroborate_official_ban(CITY, VENUE, PAGE, HTML, DIR,
                                                  down, lambda *_: ADMIN))


if __name__ == "__main__":
    unittest.main()
