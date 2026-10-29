import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from grossesondes_cloud_sync import safe_target, build_candidate, load_production
from test_grosses_stage import fixtures

class CloudSyncTests(unittest.TestCase):
    def test_initial_change_allowed(self):
        c,h,p=fixtures()
        candidate=dict(c,festivals=[dict(e) for e in c["festivals"]])
        candidate["festivals"][1]["lineup"]+=["Vanaheim"]
        self.assertTrue(safe_target(c,candidate,c))
    def test_second_run_no_content_change(self):
        c,h,p=fixtures()
        candidate=dict(c,festivals=[dict(e) for e in c["festivals"]])
        candidate["festivals"][1]["lineup"]+=["Vanaheim"]
        self.assertFalse(safe_target(c,candidate,candidate))
    def test_public_tampering_fails(self):
        c,h,p=fixtures()
        live=dict(c,festivals=[dict(e) for e in c["festivals"]])
        live["festivals"][0]["name"]="Nouveau nom non autorisé"
        with self.assertRaises(ValueError):safe_target(c,c,live)
    def test_delete_fails(self):
        c,h,p=fixtures()
        new=dict(c,festivals=c["festivals"][1:])
        with self.assertRaises(ValueError):safe_target(c,new,c)
    def test_unknown_addition_fails(self):
        c,h,p=fixtures()
        live=dict(c,festivals=c["festivals"]+[{"slug":"unknown-2027","name":"inconnu"}])
        with self.assertRaises(ValueError):safe_target(c,c,live)
    def test_reorder_fails(self):
        c,h,p=fixtures()
        new=dict(c,festivals=list(reversed(c["festivals"])))
        with self.assertRaises(ValueError):safe_target(c,new,c)
    def test_mirror_history_change_fails(self):
        c,h,p=fixtures()
        different=dict(h,knownFestivals=h["knownFestivals"][:-1])
        with self.assertRaises(ValueError):
            build_candidate({"festivals.json":c,"festival-history.json":h},
                            {"festivals.json":c,"festival-history.json":different},
                            p,{},"2026-10-29")
    def test_original_snapshot_hash_matches(self):
        c,h,p=fixtures()
        raws={
            "festivals.json":json.dumps(c).encode("utf-8"),
            "festival-history.json":json.dumps(h).encode("utf-8")
        }
        urls={"festivals.json":"https://grosses-ondes.fr/data/festivals.json",
              "festival-history.json":"https://grosses-ondes.fr/data/festival-history.json"}
        manifest={"sources":{k:{"url":url,
                                   "sha256":hashlib.sha256(raws[k]).hexdigest(),
                                   "count":len(c["festivals"] if k=="festivals.json" else h["knownFestivals"])}
                             for k,url in urls.items()}}
        lookup={url:raws[k] for k,url in urls.items()}
        result=load_production(manifest,lambda url:lookup[url])
        self.assertEqual(len(result["festivals.json"]["festivals"]),100)
        lookup[urls["festivals.json"]]+=b" "
        with self.assertRaises(ValueError):
            load_production(manifest,lambda url:lookup[url])
    def test_candidate_conserves_170_archives(self):
        c,h,p=fixtures()
        sources={"muscadeath":"muscadeath rendez vous en 2027",
                 "autfest":"autfest 2027 lievin ultra vomit septicflesh tagada jones vanaheim hope as a weapon"}
        out,report=build_candidate(
            {"festivals.json":c,"festival-history.json":h},
            {"festivals.json":c,"festival-history.json":h},
            p,sources,"2026-10-29"
        )
        self.assertTrue(report["changed"])
        self.assertEqual(report["candidate_total"],101)
        self.assertTrue(report["unchanged_history"])
        self.assertEqual(report["unmodified_festivals"],99)
        self.assertEqual(len(out["festivals"]),101)
    def test_no_proof_gives_no_candidate_change(self):
        c,h,p=fixtures()
        out,report=build_candidate(
            {"festivals.json":c,"festival-history.json":h},
            {"festivals.json":c,"festival-history.json":h},
            p,{},"2026-10-29"
        )
        self.assertFalse(report["changed"])
        self.assertEqual(out["generatedAt"],"2026-10-25")
    def test_no_perpetual_last_verified_increment(self):
        c,h,p=fixtures()
        sources={"autfest":"autfest 2027 lievin ultra vomit septicflesh tagada jones vanaheim hope as a weapon"}
        out,report=build_candidate(
            {"festivals.json":c,"festival-history.json":h},
            {"festivals.json":c,"festival-history.json":h},
            p,sources,"2026-11-10"
        )
        autfest=next(e for e in out["festivals"] if e["slug"]=="autfest-2027")
        self.assertEqual(autfest["lastVerified"],"2026-10-29")

if __name__=="__main__":
    unittest.main()
