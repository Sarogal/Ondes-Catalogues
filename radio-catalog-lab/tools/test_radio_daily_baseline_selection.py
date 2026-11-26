import base64
import copy
import json
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from cryptography.exceptions import InvalidSignature
from radio_daily_baseline_verify import FIELDS
from radio_daily_baseline_selection import select
from radio_daily_v9_generator import encode,digest
from test_radio_daily_repair_plan import fixture,DAY

def signed(doc,key,kid="selection-test"):
    body=encode(doc)
    sha=digest(body)
    p={"schema_version":1,"catalog_id":"grosses-ondes-radio","release_sequence":doc["release_sequence"],
       "published_at":DAY+"T00:00:00Z","content_sha256":sha,"content_length":len(body),"content_path":"releases/"+sha+".json"}
    message=("GO-RADIO-CATALOG-POINTER-V1\n"+"".join(str(p[k])+"\n" for k in FIELDS)+kid+"\n").encode()
    p["signature"]={"algorithm":"Ed25519","key_id":kid,"signature_base64":base64.b64encode(key.sign(message)).decode()}
    return encode(p),body

def setup():
    raw,*_=fixture()
    old=json.loads(raw)
    new=copy.deepcopy(old)
    new["release_sequence"]=9
    key=Ed25519PrivateKey.generate()
    p,a=signed(old,key)
    q,b=signed(new,key)
    anchor=dict(expected_sha=digest(a),expected_sequence=8,
        public_key=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode(),
        key_id="selection-test")
    return old,new,key,p,a,q,b,anchor

class SelectionTests(unittest.TestCase):
    def test_bootstrap_anchored_current(self):
        old,new,key,p,a,q,b,anchor=setup()
        result,r=select(p,lambda path,length:a,**anchor)
        self.assertEqual(result,a)
        self.assertFalse(r["advanced"])

    def test_successor_with_verified_previous(self):
        old,new,key,p,a,q,b,anchor=setup()
        calls=[]
        def fetch(path,length):
            calls.append((path,length))
            return b
        result,r=select(q,fetch,prior_pointer=p,prior_body=a,**anchor)
        self.assertEqual(result,b)
        self.assertEqual(calls,[("releases/"+digest(b)+".json",len(b))])
        self.assertTrue(r["migrationRequired"])
        self.assertEqual(r["selectedSequence"],9)

    def test_same_version_reuses_verified_bytes(self):
        old,new,key,p,a,q,b,anchor=setup()
        result,r=select(p,lambda *x:self.fail("unexpected fetch"),prior_pointer=p,prior_body=a,**anchor)
        self.assertEqual(result,a)

    def test_future_without_verified_previous_refused(self):
        old,new,key,p,a,q,b,anchor=setup()
        with self.assertRaisesRegex(ValueError,"verified predecessor"):
            select(q,lambda *x:self.fail("unexpected fetch"),**anchor)

    def test_rollback_and_gap_refused(self):
        old,new,key,p,a,q,b,anchor=setup()
        for seq,reason in ((7,"rollback"),(10,"intermediate")):
            new["release_sequence"]=seq
            pointer,_=signed(new,key)
            with self.assertRaisesRegex(ValueError,reason):
                select(pointer,lambda *x:self.fail("unexpected fetch"),prior_pointer=p,prior_body=a,**anchor)

    def test_equivocation_refused(self):
        old,new,key,p,a,q,b,anchor=setup()
        old["stations"][0]["display_name"]="Changed"
        pointer,_=signed(old,key)
        with self.assertRaisesRegex(ValueError,"equivocation"):
            select(pointer,lambda *x:self.fail("unexpected fetch"),**anchor)

    def test_wrong_key_refused_before_fetch(self):
        old,new,key,p,a,q,b,anchor=setup()
        pointer,_=signed(new,Ed25519PrivateKey.generate())
        with self.assertRaises(InvalidSignature):
            select(pointer,lambda *x:self.fail("unexpected fetch"),prior_pointer=p,prior_body=a,**anchor)

    def test_tampered_body_refused(self):
        old,new,key,p,a,q,b,anchor=setup()
        with self.assertRaisesRegex(ValueError,"catalog bytes"):
            select(q,lambda *x:b+b" ",prior_pointer=p,prior_body=a,**anchor)

if __name__=="__main__":
    unittest.main()
