#!/usr/bin/env python3
"""Fail-closed secondary source guard before the privileged Festivals publisher.

Triggered ONLY by GitHub workflow_run for the already existing protected
Festivals intake. This guard does not approve events or read/write catalogues.
The publisher independently re-downloads immutable first-party proof.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

REPO = "Sarogal/Ondes-Catalogues"
SOURCE_NAME = "Grosses Ondes — moteur Festivals public, état privé protégé"
SOURCE_EVENTS = frozenset({"schedule", "workflow_dispatch"})
SHA = re.compile(r"[0-9a-f]{40}\Z")


def trusted(payload):
    if not isinstance(payload, dict):
        return False
    origin = payload.get("repository")
    run = payload.get("workflow_run")
    if not isinstance(origin, dict) or not isinstance(run, dict):
        return False
    head_repo = run.get("head_repository")
    return (
        origin.get("full_name") == REPO
        and isinstance(head_repo, dict)
        and head_repo.get("full_name") == REPO
        and run.get("name") == SOURCE_NAME
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("event") in SOURCE_EVENTS
        and run.get("head_branch") == "main"
        and isinstance(run.get("head_sha"), str)
        and SHA.fullmatch(run["head_sha"]) is not None
        and type(run.get("id")) is int and run["id"] > 0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-event", action="store_true", required=True)
    args = parser.parse_args()
    if (os.getenv("GITHUB_REPOSITORY") != REPO
            or os.getenv("GITHUB_REF") != "refs/heads/main"
            or os.getenv("GITHUB_EVENT_NAME") != "workflow_run"):
        raise SystemExit("Festival intake source rejected")
    path = os.getenv("GITHUB_EVENT_PATH")
    if not path:
        raise SystemExit("Festival intake event unavailable")
    try:
        source = Path(path)
        if not source.is_file() or not 0 < source.stat().st_size <= 150_000:
            raise ValueError("Bad event file")
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise SystemExit("Festival intake event invalid") from None
    if not trusted(payload):
        raise SystemExit("Festival intake origin not trusted")
    print("PASS: trusted protected intake success; publisher still proves candidates independently")


if __name__ == "__main__":
    main()
