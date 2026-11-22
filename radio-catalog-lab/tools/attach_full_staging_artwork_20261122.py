#!/usr/bin/env python3
"""Attach existing SHA-reviewed TEST artwork to an unsigned central-staging copy.

No network, no signing, no public endpoint mutation, no replacement of an
existing logo. A preview SHA is evidence from earlier CI, not new live-byte
verification. Only exact historical UUID joins with name agreement qualify.
"""
from __future__ import annotations
import argparse
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

DIGEST = re.compile(r"^[a-f0-9]{64}$")


def attach(catalog: dict, preview: dict):
    if preview.get("scope") != "TEST_ONLY" or preview.get("production_publication_allowed") is not False:
        raise ValueError("only unsigned TEST-only reviewed manifest is accepted")
    records = preview.get("assets")
    if not isinstance(records, list) or not records:
        raise ValueError("no preview assets")
    out = copy.deepcopy(catalog)
    owners = {}
    for station in out["stations"]:
        for alias in station["legacy_aliases"]:
            if alias in owners:
                raise ValueError("legacy alias collision")
            owners[alias] = station
    applied, seen_aliases = [], set()
    for record in records:
        alias = record.get("legacy_media_id")
        st = owners.get(alias)
        if not st or alias in seen_aliases or st["display_name"].casefold() != str(record.get("station_name")).casefold():
            raise ValueError("unknown/ambiguous station or mismatched official channel identity")
        seen_aliases.add(alias)
        if st.get("logo") is not None:
            raise ValueError("refusing to replace previously SHA-verified logo")
        source = record.get("source")
        if not isinstance(source, dict) or source.get("review_scope") != "test_only" or not source.get("visual_identity_evidence"):
            raise ValueError("missing exact-station source/visual evidence")
        logo = record.get("logo")
        if not isinstance(logo, dict):
            raise ValueError("missing logo")
        sha = logo.get("sha256")
        if not isinstance(sha, str) or not DIGEST.fullmatch(sha) or logo.get("asset_id") != f"sha256:{sha}":
            raise ValueError("invalid SHA metadata")
        if logo.get("mime_type") not in ("image/png", "image/jpeg", "image/webp"):
            raise ValueError("unsupported logo format")
        if any(type(logo.get(k)) is not int or logo[k] < 1 for k in ("revision", "byte_size", "height", "width")):
            raise ValueError("missing verified image dimensions/byte count")
        if logo["byte_size"] > 8 * 1024 * 1024 or logo["width"] > 10000 or logo["height"] > 10000:
            raise ValueError("image too large")
        url = urlsplit(str(logo.get("url")))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("unsafe artwork URL")
        st["logo"] = copy.deepcopy(logo)
        applied.append({"go_station_id": st["go_station_id"], "legacy_media_id": alias,
                        "name": st["display_name"], "sha256": sha,
                        "source": source.get("official_station_page"),
                        "verification": "previous_test_sha_metadata_not_reprobed"})
    result = {
        "scope": "UNSIGNED_TEST_ARTWORK_ATTACHMENT_ONLY",
        "preview_source": "unsigned-v2-12-logos-20261121",
        "linked_logo_count": len(applied),
        "total_sha_descriptors_after_preview": sum(s.get("logo") is not None for s in out["stations"]),
        "radio_count_unchanged": len(out["stations"]) == len(catalog["stations"]),
        "ready_to_sign": False,
        "can_replace_test_current_json": False,
        "records": applied,
    }
    return out, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for p in (args.out, args.report):
        if p.exists():
            parser.error("refuse to overwrite any previous staging result")
    candidate, report = attach(
        json.loads(args.catalog.read_text(encoding="utf-8")),
        json.loads(args.preview.read_text(encoding="utf-8")),
    )
    args.out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"linked": report["linked_logo_count"],
                      "total_metadata": report["total_sha_descriptors_after_preview"],
                      "signed": False}))


if __name__ == "__main__":
    main()
