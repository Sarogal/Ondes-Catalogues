"""Non-publication, provenance, exact-host, dedup and rotation regression tests."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from regional_festival_discovery import (load_indexes, candidate_links,
                                         select_indexes, scan_regional_indexes,
                                         SCHEMA, APPROVED, archive_hints,
                                         load_verified_archive_hints, ARCHIVE_SIGNAL,
                                         curated_count_pages)
LIMOGES="https://sortir.limoges.fr/agenda"
ANGERS="https://www.angers.fr/actualites-sorties/agenda/index.html"
TARGET="https://sortir.limoges.fr/agenda/shred-fest-2027"
A={"id":"na-limoges","region":"Nouvelle-Aquitaine","url":LIMOGES}
B={"id":"pdl-angers","region":"Pays de la Loire","url":ANGERS}
DAY="2026-11-05"
def page(label="Shred Fest 2027",target=TARGET):
    return '<div><a href="'+target+'">'+label+'</a></div>'
def report(day=DAY):
    return {"schema":"grossesondes.source-watch-report.v1","date":day}
class RegionalTests(unittest.TestCase):
    def test_municipal_event_label_recovers_archive_identity_not_navigation(self):
        # Municipal agenda labels are longer than the event's real title.
        source = ANGERS
        label = "Plus d'information sur l'évènement : Hellfest 2027"
        html = '<a href="/actualites-sorties/agenda/hellfest-2027">' + label + '</a>'
        archive = {"hellfest": {"slug": "hellfest", "last_known_year": 2026}}
        found = candidate_links(html, source, "2026-11-06", archive)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Hellfest 2027")
        self.assertEqual(found[0]["archive_slug"], "hellfest")
        self.assertEqual(found[0]["signal"], ARCHIVE_SIGNAL)
        self.assertEqual(found[0]["candidate_url"],
                         "https://www.angers.fr/actualites-sorties/agenda/hellfest-2027")
        self.assertNotIn("date_verified", found[0])

    def test_visible_generic_button_can_use_explicit_municipal_aria_label(self):
        html = (
            '<article><a href="/actualites-sorties/agenda/metal-fest-2027" '
            'aria-label="Plus d&#39;information sur l&#39;évènement : '
            'Metal Fest des Rives 2027">En savoir plus</a></article>')
        found = candidate_links(html, ANGERS, "2026-11-06")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Metal Fest des Rives 2027")
        self.assertEqual(found[0]["signal"], "THEMATIC_NAME_ONLY")
        self.assertTrue(found[0]["candidate_url"].startswith("https://www.angers.fr/"))

    def test_municipal_accessibility_metadata_never_overrides_specific_visible_title(self):
        html = ('<a href="/actualites-sorties/agenda/visible-concert" '
                'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
                'Concert de jazz 2027</a>')
        self.assertEqual(candidate_links(html, ANGERS, "2026-11-06"), [])

    def test_municipal_event_names_stay_private_and_reject_untrusted_links(self):
        source = ANGERS
        html = (
            '<div hidden><a href="/actualites-sorties/agenda/hidden" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
            'En savoir plus</a></div>'
            '<script><a href="/actualites-sorties/agenda/script">'
            "Plus d'information sur l'évènement : Metal Fest 2027</a></script>"
            '<a href="https://evil.example/fest" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/old-fest" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2022">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/generic" '
            'aria-label="Plus d’information sur l’évènement : Festival des plantes 2027">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/ticket.pdf" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/suspect" '
            'aria-label="Plus d’information sur l’évènement sans titre">'
            'En savoir plus</a>'
        )
        self.assertEqual(candidate_links(html, source, "2026-11-06"), [])

    def test_accessible_municipal_lead_is_never_approved_by_scan(self):
        html = ('<a href="/actualites-sorties/agenda/metal-fest-2027" '
                'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
                'En savoir plus</a>')
        state = {}
        r = report("2026-11-06")
        found = scan_regional_indexes(
            r, state, [B], "2026-11-06", lambda _: html, limit=1)
        self.assertEqual(len(found), 1)
        self.assertIs(found[0]["publication_authorized"], False)
        self.assertEqual(r["regional_festival_publications"], 0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"], 0)

    def test_allowlist_never_accepts_dynamic_hosts_or_region_spoofs(self):
        self.assertEqual(load_indexes({"schema":SCHEMA,"indexes":[A]}),[A])
        for bad in (dict(A,url="https://127.0.0.1/agenda"),
                    dict(A,url="https://evil.fr/agenda"),
                    dict(A,region="Grand Est"),dict(A,url="http://sortir.limoges.fr/agenda")):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                load_indexes({"schema":SCHEMA,"indexes":[bad]})
        with self.assertRaises(ValueError):
            load_indexes({"schema":SCHEMA,"indexes":[A,A]})
    def test_national_config_has_thirteen_regions_and_only_curated_https(self):
        import json
        file = Path(__file__).with_name("regional_festival_indexes.json")
        source = json.loads(file.read_text(encoding="utf-8"))
        seeds = load_indexes(source)
        self.assertEqual(len(seeds), 18)
        self.assertEqual(len({s["region"] for s in seeds}), 13)
        self.assertEqual(len({s["url"] for s in seeds}), 18)
        self.assertEqual(set(APPROVED), {s["url"] for s in seeds})
        for seed in seeds:
            self.assertTrue(seed["url"].startswith("https://"))
            if "?" in seed["url"]:
                self.assertIn(seed["url"], (
                    "https://sortir.limoges.fr/agenda?keys=rock",
                    "https://sortir.limoges.fr/agenda?keys=festival"))
        source["indexes"].append(dict(seeds[0], id="unapproved-copy"))
        with self.assertRaises(ValueError):
            load_indexes(source)

    def test_region_metrics_distinguish_configured_attempted_scanned(self):
        r = report()
        state = {}
        scan_regional_indexes(r, state, [A,B], DAY,
                              lambda url: page() if url == LIMOGES else "",
                              limit=1)
        self.assertEqual(r["regional_festival_configured_sources_review_only"], 2)
        self.assertEqual(r["regional_festival_configured_regions_review_only"], 2)
        self.assertEqual(r["regional_festival_regions_attempted_review_only"], 1)
        self.assertEqual(r["regional_festival_scanned_this_pass_review_only"], 1)
        self.assertEqual(r["regional_festival_inaccessible_this_pass_review_only"], 0)
        r2 = report()
        scan_regional_indexes(r2, state, [A,B], DAY,
                              lambda _: (_ for _ in ()).throw(OSError("403")),
                              limit=1)
        self.assertEqual(r2["regional_festival_regions_attempted_review_only"], 2)
        self.assertEqual(r2["regional_festival_regions_this_pass_review_only"], 1)
        self.assertEqual(r2["regional_festival_scanned_this_pass_review_only"], 0)
        self.assertEqual(r2["regional_festival_inaccessible_this_pass_review_only"], 1)
        self.assertEqual(r2["regional_festival_publications"], 0)

    def test_visible_unmatched_vs_linkless_script_diagnostics_not_festival_proof(self):
        variants = (
            ("<html><script src='/app.js'></script><main>Chargement</main></html>",
             "NO_VISIBLE_LINKS", 1, 0, 1),
            ("<main><a href='/agenda/concert'>Concert de métal</a></main>",
             "VISIBLE_LINKS_NO_CANDIDATE", 0, 1, 0),
            ("<main><a href='/agenda/shred-fest-2027'>Shred Fest 2027</a></main>",
             "CANDIDATE_LINKS_REVIEW_ONLY", 0, 0, 0),
        )
        for html, diagnostic, linkless, unmatched, maybe_dynamic in variants:
            with self.subTest(diagnostic=diagnostic):
                r = report()
                state = {}
                scan_regional_indexes(r, state, [A], DAY,
                                      lambda _: html, limit=1)
                self.assertEqual(
                    r["regional_festival_indexes_review_only"][0]["page_diagnostic"],
                    diagnostic)
                self.assertEqual(
                    r["regional_festival_no_visible_links_review_only"], linkless)
                self.assertEqual(
                    r["regional_festival_visible_unmatched_review_only"], unmatched)
                self.assertEqual(
                    r["regional_festival_possible_dynamic_review_only"], maybe_dynamic)
                self.assertEqual(r["regional_festival_publications"], 0)

    def test_curated_search_pages_cannot_be_mutated_by_external_queries(self):
        config={"schema":SCHEMA, "indexes":[
            {"id":"na-rock-query", "region":"Nouvelle-Aquitaine",
             "url":"https://sortir.limoges.fr/agenda?keys=rock"}]}
        self.assertEqual(load_indexes(config),config["indexes"])
        for url in (
            "https://sortir.limoges.fr/agenda?keys=metal",
            "https://sortir.limoges.fr/agenda?keys=rock&page=999",
            "https://sortir.limoges.fr/agenda?keys=festival&next=http://127.0.0.1",
            "https://sortir.limoges.fr/agenda?keys=rock#foo",
            "https://sortir.limoges.fr/agenda?keys=festival&keys=rock",
        ):
            config["indexes"][0]["url"]=url
            with self.subTest(url=url), self.assertRaises(ValueError):
                load_indexes(config)
        # A pagination-only link on the same path is not a festival.
        source="https://sortir.limoges.fr/agenda?keys=festival"
        page='<a href="?keys=festival&page=1">Metal Fest 2027</a>'
        self.assertEqual(candidate_links(page,source,DAY),[])

    def test_curated_visible_result_counts_seed_only_delayed_private_pagination(self):
        rock = LIMOGES + "?keys=rock"
        first = rock + "&page=1"
        second = rock + "&page=2"
        html = "<main>Affichage des événements 1 à 9 sur 25 au total</main>"
        self.assertEqual(curated_count_pages(html, rock, rock), [first, second])
        seed = {"id": "na-rock-query", "region": "Nouvelle-Aquitaine",
                "url": rock}
        state, visits = {}, []
        def fetch(url):
            visits.append(url)
            return page() if url == first else html
        r = report()
        found = scan_regional_indexes(r, state, [seed], DAY, fetch, limit=1)
        self.assertEqual(found, [])
        self.assertEqual(visits, [rock])
        self.assertEqual(r["regional_festival_pagination_discovered_review_only"], 2)
        self.assertEqual(r["regional_festival_pagination_checked_review_only"], 0)
        self.assertEqual(set(state["regional_festival_page_queue_review_only"]),
                         {first, second})
        self.assertEqual(r["regional_festival_publications"], 0)
        visits.clear()
        following = "2026-11-06"
        r2 = report(following)
        found = scan_regional_indexes(r2, state, [seed], following, fetch, limit=2)
        self.assertIn(first, visits)
        self.assertEqual(len(visits), 2)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["candidate_url"], TARGET)
        self.assertEqual(found[0]["source_page"], first)
        self.assertEqual(found[0]["source_index"], rock)
        self.assertEqual(state["regional_festival_candidates_review_only"][TARGET]["source_page"], first)
        self.assertFalse(found[0]["publication_authorized"])
        self.assertEqual(r2["regional_festival_detail_pages_checked_review_only"], 0)
        self.assertEqual(r2["regional_festival_publications"], 0)

    def test_curated_page_counts_fail_closed_for_other_hosts_hidden_or_invalid(self):
        rock = LIMOGES + "?keys=rock"
        good = "<p>Affichage des événements 1 à 9 sur 25 au total</p>"
        self.assertEqual(curated_count_pages(good, LIMOGES, LIMOGES), [])
        self.assertEqual(curated_count_pages(good, ANGERS, ANGERS), [])
        self.assertEqual(curated_count_pages(good, rock + "&page=1", rock), [])
        self.assertEqual(curated_count_pages(good, LIMOGES + "?keys=metal",
                                             LIMOGES + "?keys=metal"), [])
        self.assertEqual(curated_count_pages("<script>" + good + "</script>",
                                             rock, rock), [])
        for bad in ("Affichage des événements 10 à 18 sur 25 au total",
                    "Affichage des événements 1 à 9 sur 9 au total",
                    "Affichage des événements 1 à 0 sur 25 au total",
                    "Affichage des événements 1 à 9 sur 9999 au total"):
            with self.subTest(bad=bad):
                self.assertEqual(curated_count_pages(bad, rock, rock), [])

    def test_independent_link_does_not_require_existing_catalogue_lead(self):
        self.assertEqual(candidate_links(page(),LIMOGES,DAY),
                         [{"candidate_url":TARGET,"title":"Shred Fest 2027",
                           "signal":"THEMATIC_NAME_ONLY","archive_slug":None}])
    def test_plain_rock_festivals_produce_only_private_candidates(self):
        for title in ("Festival Rock 2027", "Rock Festival 2027",
                      "La Sainte Rock Festival 2027", "Festival punk rock 2027"):
            with self.subTest(title=title):
                found = candidate_links(page(title), LIMOGES, DAY)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["signal"], "THEMATIC_NAME_ONLY")
        for title in ("Concert de rock 2027", "Rock expo 2027",
                      "Festival du cinéma 2027", "Rock Festival 2029"):
            with self.subTest(title=title):
                self.assertEqual(candidate_links(page(title), LIMOGES, DAY), [])
        r = report()
        found = scan_regional_indexes(r, {}, [A], DAY,
                                      lambda _: page("Rock Festival 2027"),
                                      limit=1)
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["publication_authorized"])
        self.assertFalse(found[0]["date_verified"])
        self.assertEqual(r["regional_festival_publications"], 0)

    def test_local_music_categories_reveal_private_candidates(self):
        cases = (
            ('<article><p>Genre : métal '
             '<a href="/agenda/festival-forges-2027">Festival des Forges 2027</a>'
             '</p></article>', "Festival des Forges 2027"),
            ('<li>Festival rock : '
             '<a href="/agenda/nuits-noires-2027">Les Nuits Noires 2027</a>'
             '</li>', "Les Nuits Noires 2027"),
            ('<p>Catégorie : punk '
             '<a href="/agenda/festival-des-lacs">Festival des Lacs</a>'
             '</p>', "Festival des Lacs"),
        )
        for html, title in cases:
            with self.subTest(title=title):
                found = candidate_links(html, LIMOGES, DAY)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["title"], title)
                self.assertEqual(found[0]["signal"], "MUSIC_CATEGORY_CONTEXT_ONLY")
        r = report()
        state = {}
        scan_regional_indexes(
            r, state, [A], DAY, lambda _: cases[0][0], limit=1)
        self.assertEqual(r["regional_festival_contextual_links_new_review_only"], 1)
        self.assertEqual(r["regional_festival_publications"], 0)
        row = next(iter(state["regional_festival_candidates_review_only"].values()))
        self.assertFalse(row["date_verified"])
        self.assertFalse(row["publication_authorized"])

    def test_context_is_not_global_hidden_or_unrelated(self):
        bad = (
            '<div>Genre : métal</div><div>'
            '<a href="/agenda/festival-des-forges">Festival des Forges</a></div>',
            '<div hidden>Genre : métal</div>'
            '<a href="/agenda/festival-des-forges">Festival des Forges</a>',
            '<p>Genre : métal <a href="/agenda/cinema">Festival du cinéma 2027</a></p>',
            '<p>Festival rock : <a href="/agenda/concert">Concert de punk 2027</a></p>',
            '<p>Festival rock : <a href="/agenda/details">En savoir plus</a></p>',
            '<p>Jazz : <a href="/agenda/festival-des-forges">Festival des Forges</a></p>',
        )
        for html in bad:
            with self.subTest(html=html):
                self.assertEqual(candidate_links(html, LIMOGES, DAY), [])

    def test_rotation_can_cover_four_distinct_regions_in_one_pass(self):
        indexes = [
            A, B,
            {"id": "occ-montpellier", "region": "Occitanie",
             "url": "https://agenda.montpellier.fr/"},
            {"id": "nor-tourisme", "region": "Normandie",
             "url": "https://www.normandie-tourisme.fr/agenda/"}
        ]
        state, visited = {}, []
        def fetch(url):
            visited.append(url)
            return "<p>Agenda consultable</p>"
        r = report()
        scan_regional_indexes(r, state, indexes, DAY, fetch, limit=4)
        self.assertEqual(len(visited), 4)
        self.assertEqual(r["regional_festival_regions_attempted_review_only"], 4)
        self.assertEqual(r["regional_festival_scanned_this_pass_review_only"], 4)
        self.assertEqual(r["regional_festival_publications"], 0)

    def test_rejects_generic_festivals_and_concerts(self):
        for name in ("Festival du cinéma", "Festival de la BD",
                     "Concert de metal", "Le festival des disques 2027",
                     "Festival metal 2025", "Metal Fest 2029"):
            with self.subTest(name=name):
                self.assertEqual(candidate_links(page(name),LIMOGES,DAY),[])
    def test_rejects_cross_host_http_ip_pdfs_years_and_hidden_links(self):
        bads = ("https://sortir.limoges.fr.evil.fr/agenda/shred-fest-2027",
                "https://127.0.0.1/agenda/shred-fest-2027",
                "http://sortir.limoges.fr/agenda/shred-fest-2027",
                "https://sortir.limoges.fr/affiche.pdf")
        for url in bads:
            with self.subTest(url=url):
                self.assertEqual(candidate_links(page(target=url),LIMOGES,DAY),[])
        for tag in ("<script>", "<noscript>", "<div hidden>",
                    '<div aria-hidden="true">', '<div style="display:none">'):
            closing="</"+tag.split()[0][1:].strip(">")+">"
            self.assertEqual(candidate_links(tag+page()+closing,LIMOGES,DAY),[])
    def test_rotation_across_regions_once_per_day(self):
        state={}
        self.assertEqual(select_indexes([A,B],state,DAY,limit=1),[A])
        state["regional_festival_index_last_checked"]={LIMOGES:DAY}
        self.assertEqual(select_indexes([A,B],state,DAY,limit=2),[B])
        self.assertEqual(select_indexes([A,B],state,"2026-11-06",limit=1),[B])
        state["regional_festival_index_last_checked"][LIMOGES]="2026-11-07"
        with self.assertRaises(ValueError):
            select_indexes([A,B],state,DAY,limit=2)
    def test_scan_private_one_new_not_published_next_call_deduplicated(self):
        state={}; visits=[]
        def fetch(url):
            visits.append(url);return page()
        r=report()
        found=scan_regional_indexes(r,state,[A],DAY,fetch,limit=1)
        self.assertEqual(len(found),1)
        self.assertEqual(visits,[LIMOGES])
        self.assertEqual(r["regional_festival_new_links_review_only"],1)
        self.assertEqual(r["regional_festival_publications"],0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"],0)
        self.assertFalse(found[0]["publication_authorized"])
        scan_regional_indexes(r,state,[A],DAY,fetch,limit=1)
        self.assertEqual(visits,[LIMOGES])
        self.assertEqual(r["regional_festival_new_links_review_only"],0)
        self.assertEqual(r["regional_festival_pending_links_review_only"],1)
        scan_regional_indexes(report("2026-11-06"),state,[A],"2026-11-06",fetch,limit=1)
        self.assertEqual(len(visits),2)
        self.assertEqual(state["regional_festival_candidates_review_only"][TARGET]["firstSeen"],DAY)
    def test_cross_pipeline_duplicate_is_not_a_new_regional_festival(self):
        state={"institutional_agenda_candidate_pages":{"older-edition":[{
            "candidate_url":TARGET,"source":"https://www.phalempin.fr/agenda",
            "lastSeen":DAY,"publication_authorized":False,
            "status":"UNVERIFIED_INDEX_LINK"}]}}
        r=report()
        hits=scan_regional_indexes(r,state,[A],DAY,lambda _:page(),limit=1)
        self.assertEqual(hits,[])
        self.assertEqual(r["regional_festival_existing_links_skipped_review_only"],1)
        self.assertEqual(r["regional_festival_pending_links_review_only"],0)
        self.assertEqual(r["regional_festival_publications"],0)

    def test_existing_catalogue_source_urls_are_skipped(self):
        r=report()
        r["source_reference_leads_review_only"]=[{"candidate_urls":[TARGET]}]
        found=scan_regional_indexes(r,{},[A],DAY,lambda _:page(),limit=1)
        self.assertEqual(found,[])
        self.assertEqual(r["regional_festival_existing_links_skipped_review_only"],1)

    def test_archive_consistency_fail_closed_no_extra_fetch_targets(self):
        archive={"schema":2,"knownFestivals":[
            {"slug":"motocultor-festival","name":"Motocultor Festival",
             "startDate":"2026-08-20","endDate":"2026-08-23","lastKnownYear":2026},
            {"slug":"unconfirmed-fest","name":"Unconfirmed Fest",
             "startDate":None,"endDate":None,"lastKnownYear":None}]}
        urls=[]
        def stable(url):
            urls.append(url)
            return archive
        hints,status,total=load_verified_archive_hints(DAY,stable)
        self.assertEqual(status,"CONSISTENT")
        self.assertEqual(total,2)
        self.assertEqual(len(hints),1)
        self.assertEqual(len(urls),2)
        self.assertTrue(all("festival-history.json" in u for u in urls))
        def changed(url):
            return dict(archive,updatedAt="divergent") if "github.io" in url else archive
        self.assertEqual(load_verified_archive_hints(DAY,changed)[1],"DIVERGENT")
        self.assertEqual(load_verified_archive_hints(
            DAY,lambda url: (_ for _ in ()).throw(OSError("403")))[1],
            "UNAVAILABLE_OR_INVALID")

    def test_archived_identity_future_year_is_private_hint_not_confirmed(self):
        hints={"motocultor festival":{"slug":"motocultor-festival",
                                      "last_known_year":2026}}
        url="https://sortir.limoges.fr/agenda/motocultor-festival-2027"
        page2027=page("Motocultor Festival 2027",url)
        found=candidate_links(page2027,LIMOGES,DAY,hints)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["signal"],ARCHIVE_SIGNAL)
        self.assertEqual(found[0]["archive_slug"],"motocultor-festival")
        for name in ("Motocultor Festival 2026", "Motocultor Festival 2025",
                     "Motocultor Festival Junior 2027",
                     "Motocultor Festival 2027 et 2028",
                     "Motocultor Festival"):
            with self.subTest(name=name):
                self.assertEqual(candidate_links(page(name,url),LIMOGES,DAY,hints),[])
        self.assertEqual(candidate_links(page2027,LIMOGES,DAY),[])
        state={}
        r=report()
        recorded=scan_regional_indexes(
            r,state,[A],DAY,lambda _:page2027,limit=1,
            historical_hints=hints,archive_status="CONSISTENT",archive_total=173)
        self.assertEqual(len(recorded),1)
        self.assertEqual(recorded[0]["historical_name_slug"],"motocultor-festival")
        self.assertFalse(recorded[0]["date_verified"])
        self.assertFalse(recorded[0]["publication_authorized"])
        self.assertEqual(r["regional_festival_archive_links_new_review_only"],1)
        self.assertEqual(r["regional_festival_publications"],0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"],0)

    def test_undated_and_future_archive_rows_never_seed_discovery(self):
        document={"schema":2,"knownFestivals":[
            {"slug":"festival-first","name":"Festival First",
             "startDate":None,"endDate":None,"lastKnownYear":None},
            {"slug":"festival-next","name":"Festival Next",
             "startDate":"2027-01-01","endDate":"2027-01-02",
             "lastKnownYear":2027}]}
        self.assertEqual(archive_hints(document,DAY),{})
        with self.assertRaises(ValueError):
            archive_hints(dict(document,schema=1),DAY)
        with self.assertRaises(ValueError):
            archive_hints(dict(document,knownFestivals=document["knownFestivals"]*2),DAY)

    def test_inaccessible_is_not_public_or_confirmed(self):
        def down(_):
            raise OSError("403")
        r=report()
        scan_regional_indexes(r,{},[A],DAY,down,limit=1)
        self.assertEqual(r["regional_festival_indexes_review_only"][0]["status"],"INACCESSIBLE")
        self.assertEqual(r["regional_festival_new_links_review_only"],0)
        self.assertEqual(r["regional_festival_publications"],0)
    def test_poisoned_private_state_pruned_and_never_fetched(self):
        state={"regional_festival_candidates_review_only":{
            "https://127.0.0.1/event":{"source_index":LIMOGES,"status":"UNVERIFIED_THEME_LINK",
              "lastSeen":DAY,"publication_authorized":False},
            TARGET:{"source_index":LIMOGES,"status":"VERIFIED",
                    "lastSeen":DAY,"publication_authorized":True}
        }}
        r=report()
        scan_regional_indexes(r,state,[A],DAY,lambda _: "<p>no events</p>",limit=1)
        self.assertEqual(state["regional_festival_candidates_review_only"],{})
        self.assertEqual(r["regional_festival_publications"],0)
if __name__=="__main__":
    unittest.main()
