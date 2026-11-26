import base64
import copy
import json
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from radio_daily_baseline_verify import FIELDS
from radio_daily_v9_generator import encode,digest
from radio_daily_state_migration import migrate
from radio_daily_maintenance_preview import build as maintenance
from radio_daily_logo_maintenance import build as logo
from radio_daily_missing_logo import build as missing
from radio_daily_status_preview import build as status
from radio_daily_repair_preview import build as repair
from radio_daily_repair_confirmation import build as confirm
from radio_daily_repair_plan import plan
from test_radio_daily_logo_plan import reports,DATA,DAY,SID
from test_radio_daily_repair_plan import fixture

def sign(doc):
    body=encode(doc)
    sha=digest(body)
    key=Ed25519PrivateKey.generate()
    pub=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
    kid="migration-test"
    p={"schema_version":1,"catalog_id":"grosses-ondes-radio","release_sequence":doc["release_sequence"],
       "published_at":DAY+"T00:00:00Z","content_sha256":sha,"content_length":len(body),"content_path":"releases/"+sha+".json"}
    message=("GO-RADIO-CATALOG-POINTER-V1\n"+"".join(str(p[k])+"\n" for k in FIELDS)+kid+"\n").encode()
    p["signature"]={"algorithm":"Ed25519","key_id":kid,"signature_base64":base64.b64encode(key.sign(message)).decode()}
    return encode(p),body,dict(expected_sha=sha,expected_sequence=doc["release_sequence"],public_key=pub,key_id=kid)

def setup(update=False):
    raw,sha,l,n=reports(update)
    def probe(u):
        return {"streamSha256":digest(u.encode()),"verdict":"audio_sample_ok","frameChain":"mp3"}
    m=maintenance(raw,DAY,expected=sha,limit=20,probe=probe)
    d={"schemaVersion":1,"scanDate":DAY,"publicationAllowed":False,"candidates":[]}
    r=repair(raw,m,d,expected=sha)
    c=confirm(raw,r,expected=sha)
    st=status(raw,m,plan(raw,m,r,c,expected=sha),expected=sha)
    old=json.loads(raw)
    new=copy.deepcopy(old)
    new["release_sequence"]=9
    return old,new,dict(maintenance=m,logo=l,missing=n,status=st,repair=r,confirmation=c)

def run(old,new,evidence):
    p,a,x=sign(old)
    q,b,y=sign(new)
    return migrate(p,a,q,b,old_anchor=x,new_anchor=y,day=DAY,**evidence)

class MigrationTests(unittest.TestCase):
    def test_preserve_unchanged_stream_and_missing_logo(self):
        old,new,e=setup()
        result=run(old,new,e)
        self.assertEqual(result["maintenance"]["streams"],e["maintenance"]["streams"])
        self.assertEqual(result["missingLogo"]["records"],e["missing"]["records"])
        self.assertEqual(result["migration"]["streamHistoriesRetained"],1)
        self.assertEqual(result["maintenance"]["catalogBaselineSha256"],digest(encode(new)))
        self.assertFalse(result["migration"]["publicationAllowed"])

    def test_changed_url_discards_only_affected_history(self):
        old,new,e=setup()
        new["stations"][0]["streams"][0]["url"]="https://radio.example.org/new-stream"
        result=run(old,new,e)
        self.assertEqual(result["maintenance"]["streams"][0]["observations"],[])
        self.assertEqual(result["migration"]["missingLogoRowsRetained"],1)

    def test_changed_logo_resets_source_history(self):
        old,new,e=setup(True)
        result=run(old,new,e)
        self.assertEqual(result["migration"]["logoSourceHistoriesRetained"],1)
        new["stations"][0]["logo"]["revision"]+=1
        result=run(old,new,e)
        self.assertEqual(result["migration"]["logoSourceHistoriesRetained"],0)

    def test_identity_change_resets_resource_history(self):
        old,new,e=setup()
        new["stations"][0]["display_name"]="Different Radio"
        result=run(old,new,e)
        self.assertEqual(result["migration"]["streamHistoriesRetained"],0)
        self.assertEqual(result["migration"]["missingLogoRowsRetained"],0)

    def test_refuse_skipped_sequence(self):
        old,new,e=setup()
        new["release_sequence"]=10
        with self.assertRaisesRegex(ValueError,"immediate signed successor"):
            run(old,new,e)

    def test_refuse_mixed_baseline_evidence(self):
        old,new,e=setup()
        e["logo"]["catalogBaselineSha256"]="a"*64
        with self.assertRaisesRegex(ValueError,"incompatible migration evidence"):
            run(old,new,e)

if __name__=="__main__":
    unittest.main()
