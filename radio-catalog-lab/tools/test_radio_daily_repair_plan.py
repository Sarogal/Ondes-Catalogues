import copy
import hashlib
import json
import unittest
from radio_daily_repair_plan import plan,simulate
from radio_daily_maintenance_preview import build as maintenance,digest
from radio_daily_repair_preview import build as repair
from radio_daily_repair_confirmation import build as confirm
from radio_daily_v9_generator import encode

DAY1="2026-11-25"
DAY="2026-11-26"
SID="go-station-000001"
UID="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OLD="https://radio.example.org/old"
NEW="https://radio.example.org/new"
PAGE="https://radio.example.org/metal"

def fixture(new=NEW,quarantine=False,strong=True,approved=False):
    station={"go_station_id":SID,"display_name":"Iron Radio","country_code":"FR","genres":["Metal"],
             "homepage":PAGE,"radio_browser_uuids":[{"uuid":UID,"state":"current"}],"legacy_aliases":[UID],
             "status":{"state":"quarantined" if quarantine else "active","reason_code":"legacy","changed_at":"2026-11-23T00:00:00Z"},
             "streams":[{"stream_id":"one","url":OLD,"priority":0,"protocol":"https","state":"verified",
                         "previous_urls":["https://radio.example.org/former"]}],
             "logo":{"asset_id":"sha256:"+"f"*64,"sha256":"f"*64,"revision":1,
                     "url":"https://radio.example.org/logo.png","byte_size":123,"width":32,"height":32,"mime_type":"image/png"},
             "editorial":{"admission_state":"legacy_preserved","reviewed_at":None,"evidence_refs":[]}}
    if approved:
        station["logo"]=None
        station["editorial"].update(admission_state="approved",reviewed_at=DAY+"T00:00:00Z")
    doc={"schema_version":1,"catalog_id":"grosses-ondes-radio","release_sequence":8,
         "generated_at":"2026-11-23T00:00:00Z","stations":[station],"tombstones":[]}
    raw=encode(doc)
    sha=hashlib.sha256(raw).hexdigest()
    def failure(u):return {"streamSha256":digest(u),"verdict":"needs_review","reason":"http_not_successful"}
    def search(n):return [{"stationuuid":UID,"name":"Iron Radio","countrycode":"FR","homepage":PAGE,
                            "url_resolved":new,"lastcheckok":1}]
    def fetch(u):
        return PAGE,('<script type="application/ld+json">'+json.dumps({"@type":"RadioStation","name":"Iron Radio","streamUrl":new})+'</script>').encode()
    def audio(u):return {"streamSha256":digest(u),"verdict":"audio_sample_ok","frameChain":"mp3"}
    def continuity(u):return {"verdict":"continuous_icy_frame_indication" if strong else "finite_response_review"}
    m=r=c=None
    for day in (DAY1,DAY):
        m=maintenance(raw,day,expected=sha,prior=m,limit=1,probe=failure)
        d={"schemaVersion":1,"scanDate":day,"publicationAllowed":False,"candidates":[]}
        r=repair(raw,m,d,expected=sha,prior=r,limit=1,search=search)
        c=confirm(raw,r,expected=sha,prior=c,limit=1,search=search,fetch=fetch,probe=audio,continuity_probe=continuity)
    return raw,sha,m,r,c

class RepairPlanTests(unittest.TestCase):
    def test_append_only_preserves_all_existing_station_fields(self):
        raw,sha,m,r,c=fixture()
        p=plan(raw,m,r,c,expected=sha)
        self.assertEqual(p["proposalCount"],1)
        self.assertFalse(p["candidateCatalogueWritten"])
        self.assertFalse(p["publicationAllowed"])
        result=simulate(raw,m,r,c,p,{(SID,digest(NEW)):NEW},expected=sha)
        old=json.loads(raw)
        self.assertEqual(result["release_sequence"],9)
        self.assertEqual(result["stations"][0]["streams"][-1]["state"],"candidate_verified")
        self.assertEqual(result["stations"][0]["streams"][-1]["priority"],1)
        result["stations"][0]["streams"].pop()
        self.assertEqual(result["stations"],old["stations"])
        self.assertEqual(result["tombstones"],old["tombstones"])

    def test_quarantine_remains_quarantine(self):
        raw,sha,m,r,c=fixture(quarantine=True)
        p=plan(raw,m,r,c,expected=sha)
        result=simulate(raw,m,r,c,p,{(SID,digest(NEW)):NEW},expected=sha)
        self.assertEqual(result["stations"][0]["status"]["state"],"quarantined")

    def test_audio_sample_only_no_proposal(self):
        raw,sha,m,r,c=fixture(strong=False)
        p=plan(raw,m,r,c,expected=sha)
        self.assertEqual(p["proposalCount"],0)
        self.assertIsNone(simulate(raw,m,r,c,p,{},expected=sha))

    def test_forged_confirmation_or_plan_rejected(self):
        raw,sha,m,r,c=fixture(strong=False)
        forged=copy.deepcopy(c)
        forged["records"][0]["reviewStatus"]="repeated_continuity_review"
        with self.assertRaises(ValueError):
            plan(raw,m,r,forged,expected=sha)
        p=plan(raw,m,r,c,expected=sha)
        p["approvedCount"]=1
        with self.assertRaises(ValueError):
            simulate(raw,m,r,c,p,{},expected=sha)

    def test_wrong_digest_or_token_held(self):
        raw,sha,m,r,c=fixture()
        p=plan(raw,m,r,c,expected=sha)
        with self.assertRaises(ValueError):
            simulate(raw,m,r,c,p,{(SID,digest(NEW)):OLD},expected=sha)
        token=NEW+"?token=secret"
        raw,sha,m,r,c=fixture(new=token)
        p=plan(raw,m,r,c,expected=sha)
        self.assertNotIn("secret",json.dumps(p))
        with self.assertRaises(ValueError):
            simulate(raw,m,r,c,p,{(SID,digest(token)):token},expected=sha)

    def test_maintenance_derived_status_cannot_be_forged(self):
        raw,sha,m,r,c=fixture()
        m["records"][0]["reviewStatus"]="quarantine_review"
        with self.assertRaises(ValueError):
            plan(raw,m,r,c,expected=sha)

if __name__=="__main__":
    unittest.main()
