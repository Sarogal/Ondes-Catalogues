"""Protected signing-job contract for encrypted experimental Ed25519 material.

No environment lookup, file writes, token access, key generation or activation.
The caller must provide the independent public pin and explicit encrypted
material. Production/TEST trust anchors are not supported by this lab helper.
"""
import base64
import hmac

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from radio_daily_durable_lab_signer import DurableLabSigner, _passphrase


def load_signer(encrypted_b64, passphrase, *, expected_public_key, expected_key_id):
    if (not isinstance(encrypted_b64,str) or not 1 <= len(encrypted_b64) <= 11000
            or not isinstance(expected_public_key,str) or not isinstance(expected_key_id,str)):
        raise ValueError("explicit encrypted key and public pin required")
    password = _passphrase(passphrase)
    try:
        encrypted = base64.b64decode(encrypted_b64,validate=True)
        if not 0 < len(encrypted) <= 8192 or not encrypted.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----"):
            raise ValueError("encrypted laboratory key required")
        key = load_pem_private_key(encrypted,password=password)
    except (TypeError,ValueError):
        raise ValueError("invalid encrypted laboratory key material") from None
    signer = DurableLabSigner._from_key(key)
    if (not hmac.compare_digest(signer.public_key,expected_public_key)
            or not hmac.compare_digest(signer.key_id,expected_key_id)):
        raise ValueError("laboratory key pin mismatch")
    return signer
