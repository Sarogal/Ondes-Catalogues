import json
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from radio_daily_baseline_verify import FIELDS
from radio_daily_v9_generator import encode,digest
import unittest
from cryptography.exceptions import InvalidSignature
from radio_daily_baseline_verify import verify_pointer, verify_baseline, validate_shape, BASELINE
from test_radio_daily_v9_generator import fixture

# Public, already-published TEST v8 signature. No signing seed in CI.
POINTER = {"catalog_id":"grosses-ondes-radio","content_length":574383,
           "content_path":f"releases/{BASELINE}.json","content_sha256":BASELINE,
           "published_at":"2026-11-23T21:57:25Z","release_sequence":8,"schema_version":1,
           "signature":{"algorithm":"Ed25519","key_id":"go-apk-test-20261122-v2",
           "signature_base64":"pSdiBuk1MzXwJ266fH/ullYHhYgIKOcoQm0ZlvIrpQVzGSaFk6X+tzii97eODeWIhOCm1mplsdvyE2QIl22GCQ=="}}

def raw(p=POINTER):
    return json.dumps(p).encode()

def signed_fixture(sequence):
    # Ephemeral test key only; never use the actual TEST signing identity.
    doc=json.loads(fixture()[0])
    doc["release_sequence"]=sequence
    body=encode(doc)
    sha=digest(body)
    key=Ed25519PrivateKey.generate()
    pub=base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
    p=dict(POINTER,release_sequence=sequence,content_sha256=sha,
           content_path=f"releases/{sha}.json",content_length=len(body))
    kid="ephemeral-unit-test"
    message=("GO-RADIO-CATALOG-POINTER-V1\n"+"".join(str(p[k])+"\n" for k in FIELDS)+kid+"\n").encode()
    p["signature"]={"algorithm":"Ed25519","key_id":kid,"signature_base64":base64.b64encode(key.sign(message)).decode()}
    return raw(p),body,dict(expected_sha=sha,expected_sequence=sequence,public_key=pub,key_id=kid)

class BaselineTests(unittest.TestCase):
    def test_later_signed_predecessor_requires_explicit_anchor(self):
        pointer,body,anchor=signed_fixture(10)
        self.assertEqual(verify_baseline(pointer,body,**anchor)["release_sequence"],10)
        with self.assertRaises(ValueError):
            verify_baseline(pointer,body)

    def test_wrong_sequence_and_digest_refused(self):
        pointer,body,anchor=signed_fixture(9)
        with self.assertRaises(ValueError):
            verify_baseline(pointer,body,**dict(anchor,expected_sequence=10))
        with self.assertRaises(ValueError):
            verify_baseline(pointer,body,**dict(anchor,expected_sha="a"*64))
        with self.assertRaises(ValueError):
            verify_baseline(pointer,body+b" ",**anchor)

    def test_public_signature(self):
        self.assertEqual(verify_pointer(raw()),POINTER)

    def test_modified_signed_timestamp(self):
        with self.assertRaises(InvalidSignature):
            verify_pointer(raw(dict(POINTER,published_at="2026-11-24T00:00:00Z")))

    def test_modified_catalog(self):
        with self.assertRaisesRegex(ValueError,"catalog bytes"):
            verify_baseline(raw(),b"{}")

    def test_duplicate_pointer_key(self):
        with self.assertRaisesRegex(ValueError,"duplicate"):
            verify_pointer(raw()[:-1]+b', "release_sequence":8}')

    def test_redirect_contract(self):
        doc=json.loads(fixture()[0])
        validate_shape(doc)
        doc["tombstones"][0]["redirect_to"]="go-station-000002"
        with self.assertRaisesRegex(ValueError,"active station"):
            validate_shape(doc)

    def test_alias_shadow(self):
        doc=json.loads(fixture()[0])
        doc["stations"][0]["legacy_aliases"].append("go-station-000002")
        with self.assertRaisesRegex(ValueError,"shadows"):
            validate_shape(doc)

if __name__=="__main__":
    unittest.main()
