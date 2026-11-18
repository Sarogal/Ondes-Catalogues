#!/usr/bin/env python3
"""Anonymous inventory of the configured OA agendas; never auto-trust a source.

This script is MANUAL/READ ONLY. Execute only in a trusted context able to
read the existing public OpenAgenda READ key and private sources.json.
The API's own url, title and official bit are leads, NOT an institution's
independent consent, not an organizer attestation and not an event license.
"""
from collections import Counter
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from ptitesondes_openagenda_v2_direct_evidence import read_direct_agenda_v2

SCHEMA = "ptitesondes.oa2.agenda_census.v1"
MAX_CONFIG_BYTES = 60000
MAX_AGENDAS = 100
VALID_UID = re.compile(r"[1-9][0-9]{0,11}\Z")


def _safe_reference(url):
    if not isinstance(url, str) or len(url) > 1200:
        return False
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username
                or u.password or u.port not in (None, 443)
                or u.query or u.fragment):
            return False
        host = u.hostname.lower()
        if (host == "openagenda.com" or host.endswith(".openagenda.com")
                or host == "opendatasoft.com" or host.endswith(".opendatasoft.com")):
            return False
        return True
    except ValueError:
        return False


def check_source_config(config):
    if not isinstance(config, dict) or config.get("schema") != "ptitesondes.sources.v1":
        raise ValueError("invalid_sources_config")
    ids = config.get("openagenda_agendas")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_AGENDAS
            or any(type(uid) is not int
                   or VALID_UID.fullmatch(str(uid)) is None for uid in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("invalid_unique_agenda_uids")
    return tuple(ids)


def inventory(config, public_key, reader=read_direct_agenda_v2):
    """Aggregate metadata only, exposing no title, slug, identifier or URL."""
    ids = check_source_config(config)
    counters = Counter()
    for uid in ids:
        try:
            meta = reader(uid, public_key)
            if (not isinstance(meta, dict) or
                    type(meta.get("uid")) is not int
                    or meta["uid"] != uid
                    or not isinstance(meta.get("slug"), str)
                    or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", meta["slug"])):
                counters["api_identity_mismatch"] += 1
                continue
            counters["api_identity_concordant"] += 1
            if meta.get("official") == 1 and type(meta.get("official")) is int:
                counters["api_official_indicator_only"] += 1
            if _safe_reference(meta.get("url")):
                counters["api_self_declared_external_reference"] += 1
            if meta.get("private") in (True, 1):
                counters["api_private_or_restricted"] += 1
        except Exception:
            # Do not accidentally log the key/URL from a network exception.
            counters["api_unavailable_or_unverified"] += 1
    return {
        "schema": SCHEMA,
        "mode": "manual_oa2_identity_inventory_not_owner_attestation",
        "configured_agendas": len(ids),
        "counts": dict(sorted(counters.items())),
        "independently_confirmed_owners": 0,
        "organizer_sessions_attested": 0,
        "licences_reviewed": 0,
        "publisher_connected": False,
        "approval_granted": False,
        "public_writes": 0,
        "contains_identifiers_or_private_candidate_data": False,
    }


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--sources", type=Path, required=True)
    args = cli.parse_args()
    try:
        size = args.sources.stat().st_size
        if not 0 < size <= MAX_CONFIG_BYTES:
            raise ValueError("invalid_sources_config")
        config = json.loads(args.sources.read_text(encoding="utf-8"))
        check_source_config(config)
    except (OSError, ValueError, UnicodeDecodeError):
        raise SystemExit("invalid_sources_config") from None
    key = os.environ.get("OPENAGENDA_READ_KEY", "")
    if (not key.startswith("oa_pk_") or len(key) < 15 or
            any(c in key for c in ("\r", "\n", " ", "\t"))):
        raise SystemExit("public_read_key_unavailable")
    print(json.dumps(inventory(config, key), sort_keys=True))


if __name__ == "__main__":
    main()
