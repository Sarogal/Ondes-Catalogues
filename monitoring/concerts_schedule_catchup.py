#!/usr/bin/env python3
"""Second, fail-closed wakeup for missing Concerts intake cron runs.

Triggered only by a *scheduled successful* main-branch Concerts publisher.
Never reads the private registry, never signs or publishes, never executes
untrusted pull_request code, and never triggers after publisher workflow_run.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

REPO = "Sarogal/Ondes-Catalogues"
SOURCE = "Grosses Ondes — concerts, synchronisation cloud sécurisée"
TARGET = "grossesondes-concerts-private-intake-on-public-runners.yml"
SUCCESS_GAP = dt.timedelta(hours=7)
FAILURE_GAP = dt.timedelta(minutes=90)
ACTIVE_GAP = dt.timedelta(hours=7)


def iso(s):
    if not isinstance(s, str):
        raise ValueError("GitHub run timestamp missing")
    value = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("GitHub run timestamp without timezone")
    return value.astimezone(dt.timezone.utc)


def trusted(payload):
    if not isinstance(payload, dict):
        return False
    run, repo = payload.get("workflow_run"), payload.get("repository")
    if not isinstance(run, dict) or not isinstance(repo, dict):
        return False
    head_repo = run.get("head_repository")
    return (repo.get("full_name") == REPO and
            isinstance(head_repo, dict) and
            head_repo.get("full_name") == REPO and
            run.get("name") == SOURCE and
            run.get("event") == "schedule" and
            run.get("status") == "completed" and
            run.get("conclusion") == "success" and
            run.get("head_branch") == "main")


def should_wake(rows, now):
    """Returns (should_dispatch, reason); protects recent runs and failed API."""
    if not isinstance(rows, list) or now.tzinfo is None:
        raise ValueError("Untrusted run list")
    eligible = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed GitHub run")
        if (row.get("head_branch") == "main" and
                row.get("event") in ("schedule", "workflow_dispatch", "push")):
            stamp = iso(row.get("created_at"))
            if stamp > now + dt.timedelta(minutes=3):
                return False, "clock-skew"
            eligible.append((stamp, row))
    if not eligible:
        return True, "no-recent-intake"
    stamp, latest = max(eligible, key=lambda pair: pair[0])
    age = now - stamp
    status = latest.get("status")
    if status in ("requested", "queued", "in_progress", "pending", "waiting"):
        return age >= ACTIVE_GAP, "recent-or-stalled-intake"
    if status != "completed":
        return False, "unknown-run-status"
    if latest.get("conclusion") == "success":
        return age >= SUCCESS_GAP, "last-success"
    return age >= FAILURE_GAP, "last-failure"


def request(token, url, body=None):
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "GO-concerts-schedule-catchup"}
    data = None if body is None else json.dumps(body).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers,
                  method="POST" if data is not None else "GET")
    with urlopen(req, timeout=20) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("GitHub response too large")
        if data is not None:
            if response.status != 204:
                raise ValueError("Expected GitHub workflow-dispatch HTTP 204")
            return None
        if response.status != 200:
            raise ValueError("Unexpected GitHub runs response")
        obj = json.loads(raw)
        if not isinstance(obj, dict) or not isinstance(obj.get("workflow_runs"), list):
            raise ValueError("Invalid GitHub runs structure")
        return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if (os.getenv("GITHUB_REPOSITORY") != REPO or
            os.getenv("GITHUB_EVENT_NAME") != "workflow_run"):
        raise ValueError("Untrusted GitHub execution context")
    path = os.getenv("GITHUB_EVENT_PATH")
    if not path:
        raise ValueError("GitHub event file missing")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not trusted(payload):
        print("Scheduled source validation refused; no action.")
        return
    token = os.getenv("GH_TOKEN")
    if not token:
        raise ValueError("GitHub actions token unavailable")
    url = ("https://api.github.com/repos/" + REPO + "/actions/workflows/" +
           TARGET + "/runs?branch=main&per_page=60")
    history = request(token, url)
    wake, reason = should_wake(history["workflow_runs"],
                               dt.datetime.now(dt.timezone.utc))
    print("Concerts schedule catch-up: " + reason + "; needed=" + str(wake))
    if wake and args.execute:
        dispatch = ("https://api.github.com/repos/" + REPO +
                    "/actions/workflows/" + TARGET + "/dispatches")
        request(token, dispatch, {"ref": "main", "inputs": {"phase": "catchup"}})
        print("Existing protected intake dispatched. No approvals or publication here.")
    elif wake:
        print("Dry run only; no dispatch.")


if __name__ == "__main__":
    main()
