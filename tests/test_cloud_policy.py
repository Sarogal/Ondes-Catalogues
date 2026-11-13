import unittest
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from merge_policy import merge,validate_patch,valid,safe_published_event
from run_cloud_sync import public_summary
from proof import norm,names,meters,LD,proof

TODAY=date(2026,10,29)
URL="https://ptitesondes.fr/config/sorties.json"
def event(i):
    return {"id":f"existant-{i}","title":f"Titre {i}","category":"concert","category_label":"Concert",
            "date_start":"2027-02-02","date_end":"2027-02-02","city":"Bordeaux","department":"Gironde (33)",
            "region":"Nouvelle-Aquitaine","venue":"Auditorium de Bordeaux","source_url":"https://www.opera-bordeaux.com/agenda",
            "source_label":"Opéra de Bordeaux","verified_at":"2026-10-29","geo_verified_at":"2026-10-29",
            "geo_precision":"venue","lat":44.842222,"lng":-0.579722}
def fixture():
    b={"version":3,"updated_at":"2026-10-22T21:00:00+02:00","events":[event(i) for i in range(100)]}
    x=dict(event(100),id="nouvelle-concert-2027-02-02",title="Nouveau concert")
    p={"schema":"ptitesondes.patch.v1","generated_at":"2026-10-29",
       "source":{"url":URL,"version":3,"updated_at":b["updated_at"],"events_count":100},
       "safe_to_publish":False,"additions":[x],"updates":[],"deferred":[],
       "checks":{"ids_unique":True,"official_sources_verified":True}}
    return b,p

class TestsCloud(unittest.TestCase):
    def test_public_sync_summary_never_reveals_private_ids_or_reasons(self):
        private_id = "openagenda-private-unpublished-2027-03-01"
        private_reason = "Lien organisateur secret avec preuve non publiable"
        report = {"initial":514,"final":514,"ajoutes":0,
                  "attente":[{"id":private_id,"raison":private_reason}]}
        summary = public_summary(report)
        self.assertIn("514", summary)
        self.assertIn("Propositions différées : 1", summary)
        self.assertNotIn(private_id, summary)
        self.assertNotIn(private_reason, summary)
        self.assertNotIn("openagenda-private", summary)

    def test_public_sync_summary_only_counts_approved(self):
        report = {"initial":514,"final":517,"ajoutes":3,"attente":[]}
        summary = public_summary(report)
        self.assertIn("Nouvelles fiches conformes : 3", summary)
        self.assertIn("Catalogue simulé : 517", summary)
        self.assertIn("déploiement est décidé séparément", summary)


    def test_add_with_proof(self):
        b,p=fixture()
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(len(out["events"]),101)
        self.assertEqual(r["ajoutes"],1)
        self.assertEqual(out["events"][:100],b["events"])
        self.assertEqual(r["suppression"],0)

    def test_no_proof_no_publication(self):
        b,p=fixture()
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(False,"non vérifié"))
        self.assertEqual(out,b)
        self.assertEqual(r["ajoutes"],0)
        self.assertEqual(len(r["attente"]),1)

    def test_already_published_is_idempotent(self):
        b,p=fixture()
        o=dict(b,events=b["events"]+[p["additions"][0]])
        out,r=merge(b,o,p,TODAY,checker=lambda e,ref:(False,"non vérifié"))
        self.assertEqual(len(out["events"]),101)
        self.assertEqual(r["ajoutes"],0)

    def test_unchecked_description_is_replaced(self):
        b,p=fixture()
        b["events"][0]["description"]="Description historique"
        p["additions"][0]["description"]="Promesse non vérifiée."
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(r["ajoutes"],1)
        self.assertNotIn("Promesse non vérifiée.",out["events"][-1]["description"])
        self.assertIn("source officielle",out["events"][-1]["description"])

    def test_sanitized_catalogue_is_idempotent(self):
        b,p=fixture()
        p["additions"][0]["description"]="Description non auditée"
        accepted=safe_published_event(p["additions"][0])
        published=dict(b,events=b["events"]+[accepted])
        out,r=merge(b,published,p,TODAY,checker=lambda e,ref:(False,"sans appel"))
        self.assertEqual(len(out["events"]),101)
        self.assertEqual(r["ajoutes"],0)

    def test_previously_published_event_can_gain_room_without_overwrite(self):
        b,p=fixture()
        original=dict(p["additions"][0],description="Texte de la veille")
        p["additions"]=[original]
        public_event=safe_published_event(original)
        public=dict(b,events=b["events"]+[public_event])
        proposed=dict(original,
                      venue="Auditorium de Bordeaux – salle Sauguet",
                      verified_at="2026-10-29",
                      description="Précision de salle publiée dans la veille")
        p["additions"]=[proposed]
        out,report=merge(b,public,p,TODAY,checker=lambda e,ref:(False,"non vérifié"))
        self.assertEqual(out,public)
        self.assertEqual(report["ajoutes"],0)
        self.assertEqual(len(report["attente"]),1)
        self.assertIn("non appliquée",report["attente"][0]["raison"])

    def test_refinement_plus_new_event_still_publishes_verified_new(self):
        b,p=fixture()
        original=dict(p["additions"][0],id="atelier-deja-publie",title="Atelier",description="Description ancienne")
        old=safe_published_event(original)
        public=dict(b,events=b["events"]+[old])
        patch_version=dict(original,venue="Auditorium de Bordeaux – salle Sauguet",
                           description="Nouveau détail non audité")
        new=dict(original,id="autre-evenement-nouveau",title="Autre événement")
        new.pop("description",None)
        p["additions"]=[patch_version,new]
        out,report=merge(b,public,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(report["ajoutes"],1)
        self.assertEqual(len(out["events"]),102)
        self.assertEqual(out["events"][100],old)
        self.assertEqual(out["events"][101]["id"],"autre-evenement-nouveau")

    def test_changed_date_on_published_event_still_blocks(self):
        b,p=fixture()
        original=dict(p["additions"][0],description="Vieille description")
        public=dict(b,events=b["events"]+[safe_published_event(original)])
        p["additions"]=[dict(original,date_start="2027-02-03")]
        with self.assertRaises(ValueError):merge(b,public,p,TODAY)

    def test_changed_coordinates_on_published_event_still_blocks(self):
        b,p=fixture()
        original=dict(p["additions"][0],description="Vieille description")
        public=dict(b,events=b["events"]+[safe_published_event(original)])
        p["additions"]=[dict(original,lat=1.5)]
        with self.assertRaises(ValueError):merge(b,public,p,TODAY)

    def test_unrelated_venue_replacement_still_blocks(self):
        b,p=fixture()
        original=dict(p["additions"][0],description="Vieille description")
        public=dict(b,events=b["events"]+[safe_published_event(original)])
        p["additions"]=[dict(original,venue="Nouvelle salle inventée")]
        with self.assertRaises(ValueError):merge(b,public,p,TODAY)

    def test_older_verified_date_still_blocks(self):
        b,p=fixture()
        original=dict(p["additions"][0],description="Vieille description")
        public=dict(b,events=b["events"]+[safe_published_event(original)])
        p["additions"]=[dict(original,venue="Auditorium de Bordeaux – salle Sauguet",
                             verified_at="2026-10-28")]
        with self.assertRaises(ValueError):merge(b,public,p,TODAY)

    def test_momo_school_only_history_correction_is_exact_and_manual(self):
        b, p = fixture()
        p["additions"] = []
        item = b["events"][0]
        item.update(
            id="bordeaux-momo-enfant-peche-2027-01-21",
            date_start="2027-01-21", date_end="2027-01-22",
            source_url="https://www.opera-bordeaux.com/famille-orchestre-momo-lenfant-peche-86301",
            time="21 janv. 19:00 ; 22 janv. 14:30 (scolaires) et 19:00")
        current = dict(b, events=[dict(b["events"][0], time="21 janv. 19:00 ; 22 janv. 19:00")] + b["events"][1:])
        result, summary = merge(b, current, p, TODAY, checker=lambda e, ref: (True, "proof"))
        self.assertEqual(result, current)
        self.assertEqual(summary["ajoutes"], 0)
        self.assertEqual(summary["correction"], 0)
        for forbidden in (
            dict(current["events"][0], time="21 janv. 19:00"),
            dict(current["events"][0], title="Autre spectacle"),
            dict(current["events"][0], lat=1.5),
            dict(current["events"][0], source_url="https://example.org/momo"),
        ):
            with self.subTest(forbidden=forbidden):
                forged = dict(b, events=[forbidden] + b["events"][1:])
                with self.assertRaisesRegex(ValueError, "historique"):
                    merge(b, forged, p, TODAY)

    def test_historical_deletion_blocked(self):
        b,p=fixture()
        o=dict(b,events=b["events"][1:])
        with self.assertRaises(ValueError):merge(b,o,p,TODAY)

    def test_historical_tampering_blocked(self):
        b,p=fixture()
        o=dict(b,events=[dict(b["events"][0],title="Faux")]+b["events"][1:])
        with self.assertRaises(ValueError):merge(b,o,p,TODAY)

    def test_collision_blocked(self):
        b,p=fixture()
        o=dict(b,events=b["events"]+[dict(p["additions"][0],title="Autre")])
        with self.assertRaises(ValueError):merge(b,o,p,TODAY)

    def test_approved_openagenda_alias_cannot_duplicate_official_venue_listing(self):
        b, p = fixture()
        existing = dict(p["additions"][0],
                        id="nantes-quand-le-chat-2027-01-13",
                        title="Quand le chat n’est pas là… ça part en LIVE !",
                        category="concert", category_label="Concert",
                        city="Nantes", department="Loire-Atlantique",
                        region="Pays de la Loire", venue="Théâtre de Jeanne",
                        date_start="2027-01-13", date_end="2027-01-13",
                        source_url=("https://www.theatre-jeanne.com/spectacle/"
                                    "quand-le-chat-nest-pas-laca-part-en-live/2027-01-13/"),
                        lat=47.20457, lng=-1.57551)
        candidate = dict(existing,
                         id="openagenda-25603859-2027-01-13",
                         title=('Jeune public - Concert - "Quand le chat '
                                'n\'est pas là...ça part en live !"'),
                         source_url=("https://openagenda.com/"
                                     "contributions-evenements-culturels-nantes-et-metropole-nantaise/"
                                     "events/jeune-public-concert-quand-le-chat-nest-pas-laca-part-en-live"))
        p["additions"] = [candidate]
        public = dict(b, events=b["events"] + [existing])
        with self.assertRaisesRegex(ValueError, "doublon sémantique"):
            merge(b, public, p, TODAY, checker=lambda ev, old: (True, "proof"))
        self.assertEqual(len(public["events"]), 101)

    def test_verified_alias_same_show_on_new_day_remains_distinct(self):
        b, p = fixture()
        existing = dict(p["additions"][0],
                        id="nantes-quand-le-chat-2027-01-13",
                        title="Quand le chat n’est pas là… ça part en LIVE !",
                        category="concert", category_label="Concert",
                        city="Nantes", department="Loire-Atlantique",
                        region="Pays de la Loire", venue="Théâtre de Jeanne",
                        date_start="2027-01-13", date_end="2027-01-13",
                        source_url=("https://www.theatre-jeanne.com/spectacle/"
                                    "quand-le-chat-nest-pas-laca-part-en-live/2027-01-13/"),
                        lat=47.20457, lng=-1.57551)
        candidate = dict(existing,
                         id="openagenda-25603859-2027-01-14",
                         title=('Jeune public - Concert - "Quand le chat '
                                'n\'est pas là...ça part en live !"'),
                         date_start="2027-01-14", date_end="2027-01-14",
                         source_url=("https://openagenda.com/"
                                     "contributions-evenements-culturels-nantes-et-metropole-nantaise/"
                                     "events/jeune-public-concert-quand-le-chat-nest-pas-laca-part-en-live"))
        p["additions"] = [candidate]
        public = dict(b, events=b["events"] + [existing])
        out, report = merge(b, public, p, TODAY,
                            checker=lambda ev, old: (True, "proof"))
        self.assertEqual(report["ajoutes"], 1)
        self.assertEqual(out["events"][-1]["date_start"], "2027-01-14")

    def test_duplicate_patch_blocked(self):
        b,p=fixture()
        p["additions"]*=2
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_unknown_category_pending(self):
        b,p=fixture()
        p["additions"][0]["category"]="fantaisie"
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(r["ajoutes"],0)

    def test_invalid_geo_pending(self):
        b,p=fixture()
        p["additions"][0]["lat"]=999
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(r["ajoutes"],0)

    def test_patch_update_rejected(self):
        b,p=fixture()
        p["updates"]=[{"id":"existant-1"}]
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_wrong_baseline_rejected(self):
        b,p=fixture()
        p["source"]["events_count"]=42
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_future_patch_rejected(self):
        b,p=fixture()
        p["generated_at"]="2026-10-30"
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_normalized_names(self):
        self.assertTrue(names("Auditorium de Bordeaux","Auditorium de Bordeaux"))
        self.assertFalse(names("Théâtre du Châtelet","Auditorium de Bordeaux"))

    def test_distance(self):
        self.assertLess(meters((44.842222,-0.579722),(44.842222,-0.579722)),1)
        self.assertGreater(meters((44.842222,-0.579722),(48.85777,2.34613)),100000)

    def test_ld_parser(self):
        p=LD()
        p.feed('<script type="application/ld+json">{"@type":"Event","name":"Concert"}</script>')
        self.assertEqual(len(p.blocks),1)


class TestsPrivateIntakeEventBridge(unittest.TestCase):
    def test_private_intake_success_triggers_independent_public_sync(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/ptitesondes-cloud-sync.yml").read_text(
                        encoding="utf-8")
        self.assertIn("  workflow_run:", workflow)
        self.assertIn(
            '- "P\'tites Ondes — moteurs privés sur runners publics (bascule pilote)"',
            workflow)
        self.assertIn("    types: [completed]", workflow)
        self.assertIn("    branches: [main]", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", workflow)
        self.assertIn('[ "$EVENT_NAME" = "workflow_run" ]', workflow)
        self.assertIn("    queue: max", workflow)
        self.assertIn("run: python scripts/run_cloud_sync.py", workflow)
        self.assertNotIn("PRIVATE_INTAKE_WRITE_TOKEN", workflow)

if __name__=="__main__":
    unittest.main()
