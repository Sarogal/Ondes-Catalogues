#!/usr/bin/env python3
"""Independent, fail-closed schedule recovery for the two other Ondes motors.

Only scheduled trusted-main GitHub Actions can dispatch the EXISTING protected
Festivals or P'tites Ondes intake workflow. Never signs, approves or publishes.
No private data, credentials from external input, or untrusted PR code.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from types import MappingProxyType

from concerts_schedule_catchup import iso, request

REPO = "Sarogal/Ondes-Catalogues"
API = "https://api.github.com/repos/" + REPO
FAILURE_GAP = dt.timedelta(minutes=90)

# Verified workflow_dispatch inputs, committed in the trusted main branch.
# A call to either target only restarts its normal evidence/approval pipeline.
TARGETS = MappingProxyType({
    "festivals": {
        "workflow": "grossesondes-festivals-private-intake-on-public-runners.yml",
        "success_gap": dt.timedelta(hours=14),
        "active_gap": dt.timedelta(hours=14),
        "inputs": {"phase": "catchup"},
    },
    "sorties": {
        "workflow": "ptitesondes-private-intake-on-public-runners.yml",
        "success_gap": dt.timedelta(hours=7),
        "active_gap": dt.timedelta(hours=7),
        # The existing runner allows recovery=catchup only for outings.\n        # 'write' is private intake persistence, NOT public publication.
        "inputs": {"cycle": "outings", "mode": "write", "recovery": "catchup"},
    },
})


def decide(rows, now, success_gap, active_gap):
    """Determine whether an intake workflow has truly gone stale.

    GitHub's created_at is a run start, not the theoretical schedule slot.
    Include manual/automated dispatch runs to avoid redundant recovery.
    Ignore PRs, foreign branches and unrelated workflows. Fail closed for
    malformed or future timestamps; never infer a successful publication.
    """
    if not isinstance(rows, list) or not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ValueError("Invalid run history or timezone")
    if not isinstance(success_gap, dt.timedelta) or success_gap <= dt.timedelta(0):
        raise ValueError("Invalid success gap")
    if not isinstance(active_gap, dt.timedelta) or active_gap <= dt.timedelta(0):
        raise ValueError("Invalid active gap")
    eligible = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed GitHub run")
        if row.get("event") not in ("schedule", "workflow_dispatch", "push"):
            continue
        if row.get("head_branch") != "main":
            continue
        stamp = iso(row.get("created_at"))
        if stamp > now + dt.timedelta(minutes=3):
            return False, "clock-skew"
        eligible.append((stamp, row))
    if not eligible:
        return True, "no-run-on-trusted-main"
    stamp, last = max(eligible, key=lambda pair: pair[0])
    age = now.astimezone(dt.timezone.utc) - stamp
    status = last.get("status")
    if status in ("requested", "queued", "in_progress", "pending", "waiting"):
        return age >= active_gap, "active-or-stalled-intake"
    if status != "completed":
        return False, "unknown-run-status"
    if last.get("conclusion") == "success":
        return age >= success_gap, "last-success"
    return age >= FAILURE_GAP, "last-failure"


def plan(run_history, now):
    """Diagnostic-only, with fixed predefined workflow names."""
    if not isinstance(run_history, dict) or set(run_history) != set(TARGETS):
        raise ValueError("Unexpected target history")
    decision = {}
    for key, spec in TARGETS.items():
        should, reason = decide(
            run_history[key], now, spec["success_gap"], spec["active_gap"])
        decision[key] = {"dispatch": should, "reason": reason}
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if (os.getenv("GITHUB_REPOSITORY") != REPO
            or os.getenv("GITHUB_EVENT_NAME") != "schedule"
            or os.getenv("GITHUB_REF") != "refs/heads/main"):
        raise ValueError("Only the trusted scheduled main workflow may dispatch")
    token = os.getenv("GH_TOKEN")
    if not token:
        raise ValueError("GitHub Actions token missing")
    history = {}
    for name, spec in TARGETS.items():
        url = API + "/actions/workflows/" + spec["workflow"] + "/runs?branch=main&per_page=60"
        rows = request(token, url)["workflow_runs"]
        history[name] = rows
    decisions = plan(history, dt.datetime.now(dt.timezone.utc))
    for key, spec in TARGETS.items():
        result = decisions[key]
        print(key + ": " + result["reason"] + "; catchup=" + str(result["dispatch"]))
        if result["dispatch"] and args.execute:
            url = API + "/actions/workflows/" + spec["workflow"] + "/dispatches"
            request(token, url, {"ref": "main", "inputs": spec["inputs"]})
            print(key + ": protected existing intake dispatched, never publication")
    if not args.execute:
        print("Dry-run only: no workflow dispatched")


if __name__ == "__main__":
    main()
