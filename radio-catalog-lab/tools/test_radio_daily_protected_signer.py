import base64
import unittest
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,BestAvailableEncryption,NoEncryption
from radio_daily_durable_lab_signer import DurableLabSigner
from radio_daily_protected_signer import load_signer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class ProtectedSignerTests(unittest.TestCase):
    def setUp(self):
        self.key=Ed25519PrivateKey.generate()
        self.signer=DurableLabSigner._from_key(self.key)
        self.password=b"synthetic-password-for-lab-only"
        self.material=base64.b64encode(self.key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,
                         BestAvailableEncryption(self.password))).decode()
        self.pin=dict(expected_public_key=self.signer.public_key,expected_key_id=self.signer.key_id)

    def test_exact_pin_recovers_same_signer(self):
        loaded=load_signer(self.material,self.password,**self.pin)
        self.assertEqual(loaded.key_id,self.signer.key_id)
        self.assertEqual(loaded._key.sign(b"test"),self.signer._key.sign(b"test"))

    def test_wrong_passphrase_or_pin_refused(self):
        with self.assertRaisesRegex(ValueError,"invalid encrypted"):
            load_signer(self.material,b"another-synthetic-password",**self.pin)
        with self.assertRaisesRegex(ValueError,"pin mismatch"):
            load_signer(self.material,self.password,**dict(self.pin,expected_key_id="radio-lab-invalid"))

    def test_unencrypted_or_malformed_material_refused(self):
        raw=base64.b64encode(self.key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption())).decode()
        for material in (raw,"not base64!", "a"*11001):
            with self.assertRaises(ValueError):
                load_signer(material,self.password,**self.pin)
