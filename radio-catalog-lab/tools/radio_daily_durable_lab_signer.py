"""Encrypted local Ed25519 key for synthetic laboratory rehearsals only.

No CLI, environment lookup, production key import or remote storage. The
caller owns the private directory and passphrase; the independently retained
public key and key ID are required on reopen.
"""
import base64
import hmac
import os
import stat
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption, Encoding, PrivateFormat, PublicFormat,
    load_pem_private_key,
)

from radio_daily_baseline_verify import PUBLIC_KEY
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_v9_generator import digest


def _passphrase(value):
    if not isinstance(value, bytes) or not 24 <= len(value) <= 1024:
        raise ValueError("laboratory passphrase must contain 24-1024 bytes")
    return value


def _private_path(path):
    if os.name != "posix":
        raise ValueError("private POSIX directory required")
    path = Path(path).absolute()
    parent = path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
            or parent.st_mode & 0o077 or path.parent.resolve() != path.parent):
        raise ValueError("private POSIX directory required")
    return path


class DurableLabSigner(EphemeralLabSigner):
    """Reuse the strict candidate gate with a persistent laboratory identity."""

    def __init__(self):
        raise TypeError("use create or reopen")

    @classmethod
    def _from_key(cls, key):
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Ed25519 laboratory key required")
        raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        public = base64.b64encode(raw).decode("ascii")
        if public == PUBLIC_KEY:
            raise ValueError("TEST key forbidden")
        obj = cls.__new__(cls)
        obj._key = key
        obj.public_key = public
        obj.key_id = "radio-lab-" + digest(raw)[:24]
        return obj

    @classmethod
    def create(cls, path, passphrase):
        """Generate once; atomically install encrypted PKCS8 without overwrite."""
        path = _private_path(path)
        password = _passphrase(passphrase)
        signer = cls._from_key(Ed25519PrivateKey.generate())
        encrypted = signer._key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(password))
        fd, name = tempfile.mkstemp(prefix=".radio-lab-key-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            # A hard link installs the completed file without replacing a key
            # created by another process, including a symlink at the target.
            os.link(name, path, follow_symlinks=False)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(name)
        return signer

    @classmethod
    def reopen(cls, path, passphrase, *, expected_public_key, expected_key_id):
        path = _private_path(path)
        password = _passphrase(passphrase)
        if not isinstance(expected_public_key, str) or not isinstance(expected_key_id, str):
            raise ValueError("independent laboratory key pin required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            meta = os.fstat(handle.fileno())
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                    or meta.st_mode & 0o077 or not 0 < meta.st_size <= 8192):
                raise ValueError("unsafe laboratory key file")
            encrypted = handle.read(8193)
        if len(encrypted) > 8192 or not encrypted.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----"):
            raise ValueError("encrypted laboratory key required")
        try:
            key = load_pem_private_key(encrypted, password=password)
        except (TypeError, ValueError):
            raise ValueError("cannot decrypt laboratory key") from None
        signer = cls._from_key(key)
        if (not hmac.compare_digest(signer.public_key, expected_public_key)
                or not hmac.compare_digest(signer.key_id, expected_key_id)):
            raise ValueError("laboratory key pin mismatch")
        return signer
