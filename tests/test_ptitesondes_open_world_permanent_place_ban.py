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

    def test_ban_unavailable_is_not_publication_permission(self):
        def down(_):
            raise OSError("provider unavailable")
        self.assertIsNone(corroborate_official_ban(CITY, VENUE, PAGE, HTML, DIR,
                                                  down, lambda *_: ADMIN))


if __name__ == "__main__":
    unittest.main()
