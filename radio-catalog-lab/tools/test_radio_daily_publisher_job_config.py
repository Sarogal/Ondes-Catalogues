import base64
import unittest
from unittest.mock import patch

from radio_daily_publisher_job_config import (validate_job, signing_job,
    readback_job, publisher_job, ROLES, REPO, REPO_ID, REF)
from radio_daily_baseline_verify import PUBLIC_KEY
from radio_daily_durable_lab_signer import DurableLabSigner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, BestAvailableEncryption

SHA = "a" * 40


def context(role):
    return dict(repository=REPO, repository_id=REPO_ID, ref=REF, sha=SHA,
                event="workflow_dispatch", environment=ROLES[role][0], role=role)


class PublisherJobConfigTests(unittest.TestCase):
    def setUp(self):
        key = Ed25519PrivateKey.generate()
        self.signer = DurableLabSigner._from_key(key)
        password = "synthetic-password-for-role-tests"
        self.secrets = {
            "collector": {},
            "signer": {
                "RADIO_LAB_ENCRYPTED_KEY": base64.b64encode(key.private_bytes(
                    Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(password.encode()))).decode(),
                "RADIO_LAB_PASSPHRASE": password,
            },
            "publisher": {"RADIO_LAB_WRITE_TOKEN": "fake_write_token"},
            "readback": {"RADIO_LAB_READ_TOKEN": "fake_read_token"},
        }

    def args(self, role):
        return dict(context=context(role), reviewed_sha=SHA, secrets=self.secrets[role])

    def test_exact_role_inputs_only(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertIsNone(validate_job(role, **self.args(role)))

    def test_cross_role_and_missing_credentials_refused(self):
        for role in ROLES:
            for other in ROLES:
                if other == role or not self.secrets[other]:
                    continue
                with self.subTest(role=role, other=other), self.assertRaisesRegex(ValueError,"cross-role"):
                    validate_job(role, **dict(self.args(role),
                        secrets=dict(self.secrets[role], **self.secrets[other])))
            if self.secrets[role]:
                with self.assertRaisesRegex(ValueError,"cross-role"):
                    validate_job(role, **dict(self.args(role), secrets={}))

    def test_untrusted_execution_refused(self):
        for patch_context in (dict(repository="Other/Repo"), dict(repository_id=1),
                              dict(ref="refs/heads/main"), dict(sha="b"*40),
                              dict(event="pull_request_target"), dict(event="schedule"),
                              dict(environment=None), dict(role="collector")):
            with self.subTest(patch_context=patch_context), self.assertRaisesRegex(ValueError,"unreviewed"):
                validate_job("signer", **dict(self.args("signer"),
                    context=dict(context("signer"), **patch_context)))

    def test_real_encrypted_signer_with_independent_pin(self):
        pin = dict(public_key=self.signer.public_key, key_id=self.signer.key_id)
        self.assertEqual(signing_job(**self.args("signer"), **pin).key_id, self.signer.key_id)
        with self.assertRaisesRegex(ValueError,"public pin"):
            signing_job(**self.args("signer"), public_key=PUBLIC_KEY, key_id=self.signer.key_id)

    def test_readback_has_only_read_credential(self):
        with patch("radio_daily_publisher_job_config.GitHubJSONReader") as reader, \
             patch("radio_daily_publisher_job_config.GitHubReadback") as readback:
            readback_job(**self.args("readback"))
            reader.assert_called_once_with(token="fake_read_token")
            readback.assert_called_once_with(reader.return_value)

    def test_publisher_explicit_authorization_and_adapter(self):
        args = dict(self.args("publisher"),read_head=lambda *a:None,read_tree=lambda *a:None)
        with patch("radio_daily_publisher_job_config.transmit_github") as transmit:
            with self.assertRaisesRegex(ValueError,"authorization"):
                publisher_job(None,None,None,**args)
            transmit.assert_not_called()
            publisher_job(None,None,None,**args,authorized=True)
            transmit.assert_called_once_with(None,None,None,read_head=args["read_head"],
                read_tree=args["read_tree"],write_token="fake_write_token",authorized=True)
