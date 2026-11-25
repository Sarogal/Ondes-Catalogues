import copy
import json
import unittest

from radio_daily_v9_generator import build, digest, encode
from radio_daily_decision_preview import decide
from test_radio_daily_decision_preview import inputs, A, B, DAY

def fixture():
    station = {"go_station_id":"go-station-000001", "display_name":"Existing",
               "country_code":"FR", "genres":["Metal"], "homepage":"https://existing.example.org",
               "radio_browser_uuids":[{"uuid":B,"state":"current"}], "legacy_aliases":[B],
               "status":{"state":"active","reason_code":"legacy","changed_at":"2026-11-23T00:00:00Z"},
               "streams":[{"stream_id":"one","url":"https://existing.example.org/live","priority":0,
                           "protocol":"https","state":"verified","previous_urls":[]}],
               "logo":{"asset_id":"sha256:"+"f"*64,"sha256":"f"*64,"revision":1,
                       "url":"https://existing.example.org/logo.png","byte_size":123,
                       "width":32,"height":32,"mime_type":"image/png"},
               "editorial":{"admission_state":"legacy_preserved","reviewed_at":None,"evidence_refs":[]}}
    quarantine=copy.deepcopy(station)
    quarantine.update(go_station_id="go-station-000002",display_name="Quarantine",
                      legacy_aliases=[],radio_browser_uuids=[],streams=[],logo=None)
    quarantine["status"]["state"]="quarantined"
    doc={"schema_version":1,"catalog_id":"grosses-ondes-radio","release_sequence":8,
         "generated_at":"2026-11-23T00:00:00Z","stations":[station,quarantine],
         "tombstones":[{"go_station_id":"go-station-000003","legacy_aliases":[],
                        "retired_at":"2026-11-23T00:00:00Z","reason_code":"merged_into_station",
                        "redirect_to":"go-station-000001"}]}
    raw=encode(doc)
    discovery,dossiers=inputs()
    discovery["candidates"][0].update(status="candidate_requires_qualification",countrycode="GB")
    dossiers["catalogBaselineSha256"]=digest(raw)
    return raw,discovery,dossiers

def run(raw,discovery,dossiers):
    sha=digest(raw)
    return build(raw,discovery,dossiers,decide(discovery,dossiers,sha),expected_sha=sha)

class V9Tests(unittest.TestCase):
    def test_additive_deterministic_and_no_logo(self):
        raw,d,e=fixture()
        payload,report=run(raw,d,e)
        old,new=json.loads(raw),json.loads(payload)
        self.assertEqual(new["stations"][:-1],old["stations"])
        self.assertEqual(new["tombstones"],old["tombstones"])
        self.assertEqual(new["release_sequence"],9)
        self.assertEqual(new["stations"][-1]["legacy_aliases"],[A])
        self.assertIsNone(new["stations"][-1]["logo"])
        self.assertEqual(new["stations"][-1]["streams"][0]["state"],"candidate_verified")
        self.assertEqual(report["candidateSha256"],digest(payload))
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(run(raw,d,e),(payload,report))

    def test_no_change_no_version(self):
        raw,d,e=fixture()
        e["records"][0]["continuityEvidence"]["positiveObservationDates"]=[DAY]
        payload,report=run(raw,d,e)
        self.assertIsNone(payload)
        self.assertIsNone(report["candidateSequence"])
        self.assertFalse(report["changed"])

    def test_forged_decision_rejected(self):
        raw,d,e=fixture()
        decision=decide(d,e,digest(raw))
        decision["records"][0]["approved"]=True
        with self.assertRaisesRegex(ValueError,"decision report"):
            build(raw,d,e,decision,expected_sha=digest(raw))

    def test_tampered_baseline_rejected(self):
        raw,d,e=fixture()
        with self.assertRaisesRegex(ValueError,"digest mismatch"):
            build(raw+b" ",d,e,decide(d,e,digest(raw)),expected_sha=digest(raw))

    def test_existing_name_and_country_not_duplicated(self):
        raw,d,e=fixture()
        existing=json.loads(raw)
        existing["stations"][0]["display_name"]="Iron Radio"
        existing["stations"][0]["country_code"]="GB"
        raw=encode(existing)
        e["catalogBaselineSha256"]=digest(raw)
        payload,report=run(raw,d,e)
        self.assertIsNone(payload)
        self.assertEqual(report["deferred"][0]["reason"],"identity_or_url_recheck")

    def test_wrong_sequence_refused(self):
        raw,d,e=fixture()
        doc=json.loads(raw)
        doc["release_sequence"]=9
        raw=encode(doc)
        with self.assertRaisesRegex(ValueError,"exact v8"):
            build(raw,d,e,{},expected_sha=digest(raw))

if __name__=="__main__":
    unittest.main()
