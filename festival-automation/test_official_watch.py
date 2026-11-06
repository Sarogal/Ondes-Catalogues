import copy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from official_watch import (
    GIT, ORIGIN, PAGES, analyze, choose_sources, fingerprint, indexed,
    latest_patch, merge_deferred, permitted_url, run, source_inventory, source_leads,
    choose_pending_rechecks, verify_references,
)


def catalogue(count=100):
    return {"schema": 1, "generatedAt": "2026-11-03", "festivals": [
        {"slug": f"festival-{n}", "name": f"Festival {n}",
         "officialSite": f"https://fest{n}.example.org/programme",
         "startDate": "2027-01-09" if n % 2 else None}
        for n in range(count)
    ]}


def patch(day="2026-11-03"):
    return {"schema": "grossesondes.patch.v1", "generated_at": day,
            "safe_to_publish": False,
            "source": {"festivals": {"count": 123}, "history": {"count": 170}},
            "additions": [{"slug": "known-2027"}],
            "updates": [{"slug": "festival-2", "changes": [{"field": "price", "before": None, "after": "20 EUR"}], "evidence": ["https://example.org"]}],
            "history_additions": [], "history_updates": [], "deferred": []}


class OfficialWatchTests(unittest.TestCase):
    def test_rejects_private_urls_and_plain_http(self):
        for url in ("http://festival.fr/", "https://127.0.0.1/", "https://localhost/", "https://metal.local/", "https://a.test/", "https://user:pass@metal.fr/", "https://metal.fr:8080/"):
            self.assertFalse(permitted_url(url), url)
        self.assertTrue(permitted_url("https://metal.fr/2027"))

    def test_fingerprint_ignores_script_but_detects_programme(self):
        a = "<html><script>random 123</script><p>" + "Festival de Metal " * 10 + "</p></html>"
        b = a.replace("random 123", "random 456")
        c = b.replace("Festival de Metal", "Festival de Punk")
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertNotEqual(fingerprint(b), fingerprint(c))

    def test_no_trust_in_divergent_published_catalogues(self):
        doc = catalogue()
        other = copy.deepcopy(doc)
        other["festivals"][3]["name"] = "change"
        with self.assertRaisesRegex(ValueError, "DIVERGENCE"):
            verify_references(doc, other, doc)
        with self.assertRaisesRegex(ValueError, "absente"):
            verify_references(doc, doc, {**doc, "festivals": doc["festivals"] + [{"slug": "unpublished"}]})
        self.assertEqual(verify_references(doc, doc, doc)["published"], 100)

    def test_drift_diagnostics_are_public_and_fail_closed(self):
        doc = catalogue()
        stale = dict(doc, generatedAt="2026-10-30")
        with self.assertRaisesRegex(ValueError, "Pages generatedAt=2026-10-30"):
            verify_references(stale, doc, doc)
        changed = copy.deepcopy(doc)
        changed["festivals"][2]["officialSite"] = None
        with self.assertRaisesRegex(ValueError, "champs d'édition divergents=1"):
            verify_references(changed, doc, doc)

    def test_reject_duplicate_slugs(self):
        doc = catalogue()
        doc["festivals"][1]["slug"] = doc["festivals"][0]["slug"]
        with self.assertRaisesRegex(ValueError, "dupliqués"):
            indexed(doc)

    def test_rotation_deterministic_and_bounded(self):
        doc = catalogue()
        one = choose_sources(doc, date(2026, 11, 4), limit=12)
        self.assertEqual(one, choose_sources(doc, date(2026, 11, 4), limit=12))
        self.assertEqual(len(one), 12)
        self.assertNotEqual(one, choose_sources(doc, date(2026, 11, 5), limit=12))

    def test_all_sources_rotate_without_starvation(self):
        doc = catalogue(100)
        checked = []
        for day in range(7):
            for phase in ("primary", "catchup"):
                selected = choose_sources(doc, date(2026, 11, 4 + day), phase, 12)
                self.assertEqual(len(set(u for _s, u in selected)), 12)
                checked.extend(url for _slug, url in selected)
        self.assertEqual(len(set(checked)), 100)

    def test_next_day_priority_preserves_national_rotation(self):
        doc=catalogue(100)
        today=date(2026, 11, 5)
        ordinary=choose_sources(doc,today,"primary",12)
        previous=choose_sources(doc,date(2026,11,4),"primary",12)
        not_selected=[url for _slug,url in previous
                      if url not in {u for _s,u in ordinary}]
        self.assertTrue(not_selected)
        target=not_selected[0]
        state={"future_edition_observations": {
            "next-year-2028": {"source":target,
                               "firstSeen":"2026-11-04",
                               "lastSeen":"2026-11-04"}}}
        chosen=choose_pending_rechecks(doc,today,"primary",12,state)
        self.assertEqual(len(chosen),12)
        self.assertEqual(len({u for _slug,u in chosen}),12)
        self.assertIn(target,{u for _slug,u in chosen})
        self.assertGreaterEqual(len({u for _slug,u in chosen} &
                                    {u for _slug,u in ordinary}),11)
        self.assertEqual(choose_pending_rechecks(doc,today,"primary",12,{}),
                         ordinary)
        self.assertEqual(choose_pending_rechecks(
            doc,date(2026,11,6),"primary",12,state),
            choose_sources(doc,date(2026,11,6),"primary",12))

    def test_priority_never_fetches_url_absent_from_official_inventory(self):
        doc=catalogue(100)
        target="https://not-in-catalogue.example.org/"
        state={"future_edition_observations":{"fake":{
            "source":target,"firstSeen":"2026-11-04",
            "lastSeen":"2026-11-04"}}}
        result=choose_pending_rechecks(doc,date(2026,11,5),"primary",12,state)
        self.assertEqual(result,choose_sources(doc,date(2026,11,5),"primary",12))
        with self.assertRaises(ValueError):
            choose_pending_rechecks(doc,date(2026,11,5),"primary",12,
                                    {"future_edition_observations":[]})

    def test_next_day_priority_promotes_stable_future_edition_in_live_watch(self):
        doc=catalogue(100)
        first=choose_sources(doc,date(2026,11,4),"primary",12)
        ordinary_next={u for _slug,u in choose_sources(
            doc,date(2026,11,5),"primary",12)}
        slug,url=next((slug,url) for slug,url in first if url not in ordinary_next)
        row=next(r for r in doc["festivals"] if r["slug"]==slug)
        row.update(name="Follow Up Metal Fest 2027",startDate="2027-05-13",
                   endDate="2027-05-14",lineup=[],bands=0,
                   lastVerified="2026-11-01")
        html_text=("<main>"+"Official metal festival announced. "*10+"</main>"
                   +'<script type="application/ld+json">'
                   +json.dumps({"@type":"MusicEvent","name":"Follow Up Metal Fest 2028",
                                "startDate":"2028-05-12",
                                "endDate":"2028-05-13"})
                   +"</script>")
        def page(which):
            if which==url:
                return html_text
            return "<main>"+"Ordinary official festival website. "*10+"</main>"
        p=patch()
        p["source"]["festivals"]={
            "url":ORIGIN,"generatedAt":doc["generatedAt"],"count":100}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/"patch-2026-11-03.json").write_text(
                json.dumps(p),encoding="utf-8")
            day_one=run(folder,"2026-11-04",limit=12,
                        download_json=lambda u:doc,download_page=page)
            day_two=run(folder,"2026-11-05",limit=12,
                        download_json=lambda u:doc,download_page=page)
            self.assertEqual(day_one["candidateEditionCount"],0)
            self.assertEqual(day_two["candidateEditionCount"],1)
            self.assertEqual(day_two["candidate_editions"][0]["slug"],
                             slug+"-2028")
            result=json.loads((folder/"patch-2026-11-05.json").read_text())
            self.assertIs(result["safe_to_publish"],False)
            self.assertIs(result["additions"][-1]["showOnMap"],False)

    def test_urgent_sources_rechecked_and_routine_still_covered(self):
        doc = catalogue(100)
        for row in doc["festivals"][:5]:
            row["startDate"] = "2026-11-20"
        a = choose_sources(doc, date(2026, 11, 4), "primary", 24)
        b = choose_sources(doc, date(2026, 11, 4), "catchup", 24)
        urgent = {doc["festivals"][n]["officialSite"] for n in range(5)}
        self.assertTrue(urgent.issubset({u for _, u in a}))
        self.assertTrue(urgent.issubset({u for _, u in b}))
        self.assertTrue({u for _, u in a} - urgent)
        self.assertTrue({u for _, u in b} - urgent)

    def test_shared_sites_deduplicated_missing_sites_reported(self):
        doc = catalogue(100)
        first = doc["festivals"][0]["officialSite"]
        doc["festivals"][1]["officialSite"] = first
        doc["festivals"][2]["officialSite"] = None
        doc["festivals"][3]["officialSite"] = "http://invalid.example.org"
        inventory, missing = source_inventory(doc, date(2026, 11, 4))
        self.assertEqual(len(inventory), 97)
        self.assertEqual(len(inventory[first]["slugs"]), 2)
        self.assertEqual(len(missing), 2)
        selected = choose_sources(doc, date(2026, 11, 4), "primary", 24)
        self.assertEqual(len({url for _, url in selected}), len(selected))

    def test_unverified_existing_references_become_review_leads_only(self):
        doc = catalogue()
        row = doc["festivals"][0]
        row["officialSite"] = None
        row["source"] = "https://www.mairie-test.fr/evenement/festival"
        row["auditSources"] = [
            "https://www.mairie-test.fr/evenement/festival",
            "https://www.helloasso.com/associations/test/evenements/festival",
            "http://unsafe-source.example.org", "https://127.0.0.1/",
        ]
        second = doc["festivals"][1]
        second["officialSite"] = ""
        second["source"] = None
        second["auditSources"] = "invalid not a list"
        leads = source_leads(doc, date(2026, 11, 4))
        self.assertEqual(len(leads), 2)
        self.assertEqual(leads[0]["official_status"], "NOT_VERIFIED")
        self.assertEqual(leads[0]["start_date"], row["startDate"])
        self.assertIs(leads[0]["allowed_to_publish"], False)
        self.assertEqual(len(leads[0]["candidate_urls"]), 2)
        self.assertEqual(leads[1]["candidate_urls"], [])
        inventory, missing = source_inventory(doc, date(2026, 11, 4))
        self.assertEqual(len(inventory), 98)
        self.assertEqual(len(missing), 2)

    def test_invalid_phase_or_limit_fails_closed(self):
        doc = catalogue()
        with self.assertRaises(ValueError):
            choose_sources(doc, date(2026, 11, 4), "unknown", 24)
        with self.assertRaises(ValueError):
            choose_sources(doc, date(2026, 11, 4), "primary", 0)

    def test_first_observation_not_a_proof(self):
        state = {"schema": "grossesondes.source-watch.v1", "sources": {}}
        outcome, finding = analyze(state, "metal-2027", "https://metal.fr", "aaa", "2026-11-04")
        self.assertEqual((outcome, finding), ("baseline", None))
        outcome, finding = analyze(state, "metal-2027", "https://metal.fr", "aaa", "2026-11-04")
        self.assertEqual((outcome, finding), ("unchanged", None))
        outcome, finding = analyze(state, "metal-2027", "https://metal.fr", "bbb", "2026-11-05")
        self.assertEqual(outcome, "changed")
        self.assertEqual(finding["sources"], ["https://metal.fr"])

    def test_append_only_deferred_and_preserve_changes(self):
        p = patch()
        finding = {"slug": "metal-2027", "fingerprint_sha256": "xyz", "sources": ["https://metal.fr"]}
        original = copy.deepcopy(p)
        self.assertEqual(merge_deferred(p, [finding, finding], "2026-11-04"), 1)
        self.assertEqual(p["additions"], original["additions"])
        self.assertEqual(p["updates"], original["updates"])
        self.assertEqual(p["safe_to_publish"], False)
        self.assertEqual(merge_deferred(p, [finding], "2026-11-05"), 0)
        self.assertEqual(p["generated_at"], "2026-11-04")
        p["safe_to_publish"] = True
        with self.assertRaises(ValueError):
            merge_deferred(p, [], "2026-11-06")

    def test_run_baseline_no_patch_generated_then_detects_change(self):
        doc = catalogue()
        html = "<html>" + " Festival metal avec programmation et billetterie officielles." * 5 + "</html>"
        data = {PAGES: doc, GIT: doc, ORIGIN: doc}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "patch-2026-11-03.json").write_text(json.dumps(patch()), encoding="utf-8")
            first = run(folder, "2026-11-04", limit=3, download_json=lambda u: data[u], download_page=lambda u: html)
            self.assertEqual(len(first["baselines"]), 3)
            self.assertEqual(first["coverage"]["official_sources"], 100)
            self.assertEqual(first["coverage"]["editions_without_official_https"], 0)
            self.assertEqual(first["coverage"]["missing_with_reference_leads"], 0)
            self.assertEqual(first["deferredAdded"], 0)
            self.assertFalse((folder / "patch-2026-11-04.json").exists())
            state = json.loads((folder / "source-watch-state.json").read_text())
            self.assertEqual(len(state["sources"]), 3)
            second = run(folder, "2026-11-04", limit=3, download_json=lambda u: data[u], download_page=lambda u: html.replace("metal", "punk"))
            self.assertEqual(second["deferredAdded"], 3)
            addition = json.loads((folder / "patch-2026-11-04.json").read_text())
            self.assertEqual(len(addition["deferred"]), 3)
            self.assertEqual(addition["updates"], patch()["updates"])
            again = run(folder, "2026-11-04", limit=3, download_json=lambda u: data[u], download_page=lambda u: html.replace("metal", "punk"))
            self.assertEqual(again["deferredAdded"], 0)
            self.assertEqual(len(latest_patch(folder, "2026-11-04")["deferred"]), 3)

    def test_structured_hint_is_deferred_on_baseline_not_published(self):
        doc = catalogue()
        slug, url = choose_sources(doc, date(2026, 11, 4), limit=1)[0]
        item = next(r for r in doc["festivals"] if r["slug"] == slug)
        item["startDate"] = "2027-01-09"
        item["endDate"] = "2027-01-09"
        name = item["name"] + " 2027"
        html_text = (
            "<p>" + "Metal festival programme officiel. " * 8 + "</p>"
            + '<script type="application/ld+json">'
            + json.dumps({"@type": "MusicEvent", "name": name,
                          "startDate": "2027-01-11", "endDate": "2027-01-11",
                          "performer": [{"name": "Groupe officiel"}]})
            + "</script>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "patch-2026-11-03.json").write_text(json.dumps(patch()), encoding="utf-8")
            first = run(folder, "2026-11-04", limit=1,
                        download_json=lambda url: doc, download_page=lambda url: html_text)
            self.assertEqual(first["deferredAdded"], 1)
            self.assertEqual(first["publishedChanges"], 0)
            proposal = json.loads((folder / "patch-2026-11-04.json").read_text())
            self.assertEqual(proposal["additions"], patch()["additions"])
            self.assertEqual(proposal["updates"], patch()["updates"])
            self.assertEqual(proposal["deferred"][0]["evidence_kind"], "schema.org")
            self.assertIs(proposal["deferred"][0]["safe_to_publish"], False)
            self.assertEqual(proposal["deferred"][0]["structured_evidence"][0]["hints"]["startDate"], "2027-01-11")
            second = run(folder, "2026-11-04", limit=1,
                         download_json=lambda url: doc, download_page=lambda url: html_text)
            self.assertEqual(second["deferredAdded"], 0)

    def test_two_day_stable_official_roster_creates_private_update_only(self):
        doc = catalogue()
        row = doc["festivals"][0]
        row.update({"name": "Festival Metal 2027",
                    "startDate": "2027-01-09", "endDate": "2027-01-09",
                    "lineup": ["Ancien Artiste"], "bands": 1,
                    "lastVerified": "2026-10-01"})
        for other in doc["festivals"][1:]:
            other["officialSite"] = None
        official = ('<p>' + "Festival Metal 2027 programme officiel. " * 8 + '</p>'
                    + '<script type="application/ld+json">'
                    + json.dumps({"@type": "MusicEvent", "name": "Festival Metal 2027",
                                  "startDate": "2027-01-09",
                                  "endDate": "2027-01-09",
                                  "performer": [{"name": "Nouvel Artiste"}]})
                    + "</script>")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            current = patch()
            current["source"]["festivals"] = {
                "url": ORIGIN, "generatedAt": doc["generatedAt"],
                "count": len(doc["festivals"]),
            }
            (folder / "patch-2026-11-03.json").write_text(json.dumps(current), encoding="utf-8")
            first = run(folder, "2026-11-04", limit=1,
                        download_json=lambda u: doc, download_page=lambda u: official)
            self.assertEqual(first["candidateUpdateCount"], 0)
            self.assertEqual(first["deferredAdded"], 1)
            second = run(folder, "2026-11-05", limit=1,
                         download_json=lambda u: doc, download_page=lambda u: official)
            self.assertEqual(second["candidateUpdateCount"], 1)
            result = json.loads((folder / "patch-2026-11-05.json").read_text())
            self.assertEqual(len(result["updates"]), len(current["updates"]) + 1)
            self.assertEqual(result["updates"][-1]["proofMode"], "structured-roster.v1")
            self.assertEqual(result["updates"][-1]["changes"][0]["after"],
                             ["Ancien Artiste", "Nouvel Artiste"])
            self.assertIs(result["safe_to_publish"], False)
            self.assertEqual(result["deferred"], json.loads(
                (folder / "patch-2026-11-04.json").read_text())["deferred"])
            third = run(folder, "2026-11-05", limit=1,
                        download_json=lambda u: doc, download_page=lambda u: official)
            self.assertEqual(third["candidateUpdateCount"], 0)

    def test_source_unavailable_not_deleted_or_claimed(self):
        doc = catalogue()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "patch-2026-11-03.json").write_text(json.dumps(patch()), encoding="utf-8")
            report = run(folder, "2026-11-04", limit=2,
                         download_json=lambda u: doc,
                         download_page=lambda u: (_ for _ in ()).throw(OSError("offline")))
            self.assertEqual(len(report["unavailable"]), 2)
            self.assertEqual(report["publishedChanges"], 0)
            self.assertFalse((folder / "patch-2026-11-04.json").exists())


if __name__ == "__main__":
    unittest.main()
