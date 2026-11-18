"""Offline, no-key and no-network tests for the 16-agenda identity census."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_agenda_census import (
    inventory, check_source_config, _safe_reference,
)


class AgendaCensusContract(unittest.TestCase):
    def test_sixteen_configured_agendas_are_not_sixteen_owners(self):
        config = {
            "schema": "ptitesondes.sources.v1",
            "openagenda_agendas": list(range(1, 17)),
        }
        def reader(uid, key):
            self.assertEqual(key, "oa_pk_" + "x" * 30)
            if uid == 15:
                return {"uid": 13, "slug": "wrong-agenda"}
            if uid == 16:
                raise RuntimeError("secret and URL must not leak")
            return {
                "uid": uid, "slug": f"commune-{uid}",
                "official": 1, "url": "https://ville-exemple.fr/agenda",
            }
        report = inventory(config, "oa_pk_" + "x" * 30, reader)
        self.assertEqual(report["configured_agendas"], 16)
        self.assertEqual(report["counts"]["api_identity_concordant"], 14)
        self.assertEqual(report["counts"]["api_identity_mismatch"], 1)
        self.assertEqual(report["counts"]["api_unavailable_or_unverified"], 1)
        self.assertEqual(report["counts"]["api_official_indicator_only"], 14)
        self.assertEqual(report["independently_confirmed_owners"], 0)
        self.assertEqual(report["organizer_sessions_attested"], 0)
        self.assertFalse(report["approval_granted"])
        self.assertEqual(report["public_writes"], 0)
        data = json.dumps(report)
        for string in ("ville-exemple.fr", "commune-", "secret", "oa_pk_"):
            self.assertNotIn(string, data)

    def test_invalid_configs_fail_closed(self):
        good = {"schema": "ptitesondes.sources.v1",
                "openagenda_agendas": [1, 2]}
        for config in (
            None, {},
            {"schema": "unknown", "openagenda_agendas": [1]},
            dict(good, openagenda_agendas=[]),
            dict(good, openagenda_agendas=[1, 1]),
            dict(good, openagenda_agendas=["1", 2]),
            dict(good, openagenda_agendas=[True, 2]),
            dict(good, openagenda_agendas=list(range(1, 103))),
        ):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    check_source_config(config)

    def test_self_claimed_official_url_is_never_an_attestation(self):
        for url in (
            "http://mairie.test/agenda",
            "https://openagenda.com/ville",
            "https://api.openagenda.com/ville",
            "https://public.opendatasoft.com/agenda",
            "https://ville.test.evil/openagenda#fragment",
            "https://user:pass@ville.test/page",
        ):
            with self.subTest(url=url):
                self.assertFalse(_safe_reference(url))
        self.assertTrue(_safe_reference("https://ville-exemple.fr/agenda"))

    def test_private_or_restricted_agenda_is_only_a_diagnostic(self):
        config = {"schema": "ptitesondes.sources.v1",
                  "openagenda_agendas": [919191]}
        result = inventory(config, "oa_pk_" + "x" * 30,
                           reader=lambda uid, key: {
                               "uid": uid, "slug": "ville-test",
                               "private": True, "official": 1,
                           })
        self.assertEqual(result["counts"]["api_private_or_restricted"], 1)
        self.assertEqual(result["independently_confirmed_owners"], 0)
        self.assertFalse(result["publisher_connected"])


if __name__ == "__main__":
    unittest.main()
