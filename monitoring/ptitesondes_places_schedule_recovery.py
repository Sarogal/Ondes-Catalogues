"""Recover missing permanent-place intake without interpreting outings as places.

Only dispatch the approved private-write pipeline, not the publisher. Observe
public Actions metadata, never private files or logs. Any active trusted
intake suppresses a dispatch; the collector retains its existing queue lock.
A completion-triggered recheck avoids confusing a preview or a partially
successful legacy collector with persisted generic research.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = "Sarogal/Ondes-Catalogues"
API = "https://api.github.com/repos/" + REPO
TARGET = "ptitesondes-private-intake-on-public-runners.yml"
INPUTS = {"cycle": "places", "mode": "write", "recovery": "none"}
PLACE_STEP = "Rechercher et qualifier les lieux permanents pour enfants"
WRITE_STEP = "Demander la synchronisation publique après écriture privée validée"
RESEARCH_STEP = "Attester la persistance de la recherche générique des lieux"
ACTIVE = {"requested", "queued", "in_progress", "pending", "waiting"}
MAX_HISTORY = 30
SUCCESS_GAP = timedelta(hours=4)
FAILURE_GAP = timedelta(minutes=90)
RESEARCH_PATHS = (
    "scripts/ptitesondes_open_world_permanent_place_research.py",
    "scripts/ptitesondes_open_world_permanent_place_ban.py",
    "scripts/ptitesondes_open_world_permanent_place_evidence.py",
    "scripts/ptitesondes_open_world_permanent_place_draft.py",
    "scripts/ptitesondes_cultural_directory_discovery.py",
)


def trusted(repo, ref, event, pause):
    return (repo == REPO and ref == "refs/heads/main"
            and event in ("schedule", "push", "workflow_run") and pause != "paused")


def request(token, url, body=None):
    req = Request(url, method="POST" if body is not None else "GET",
                  data=json.dumps(body).encode() if body is not None else None,
                  headers={"Authorization": "Bearer " + token,
                           "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json",
                           "X-GitHub-Api-Version": "2022-11-28",
                           "User-Agent": "PtitesOndesPlaceRecovery/1.0"})
    with urlopen(req, timeout=15) as response:
        if body is not None:
            if response.status != 204:
                raise ValueError("unexpected_dispatch_status")
            return None
        if response.status != 200:
            raise ValueError("unexpected_read_status")
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("oversized_actions_metadata")
        return json.loads(raw)


def timestamp(row):
    val = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    if val.tzinfo is None:
        raise ValueError("timezone_missing")
    return val.astimezone(timezone.utc)


def place_job_result(doc):
    if (not isinstance(doc, dict) or not isinstance(doc.get("jobs"), list)
            or type(doc.get("total_count")) is not int
            or doc["total_count"] != len(doc["jobs"])):
        raise ValueError("incomplete_jobs")
    jobs = [j for j in doc["jobs"] if j.get("name") == "run-private"]
    if len(jobs) != 1:
        raise ValueError("missing_or_ambiguous_private_job")
    job = jobs[0]
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise ValueError("missing_job_steps")
    if job.get("conclusion") == "skipped":
        return "not_places"
    # A successful preview or an outings-only run is not a persisted cycle.
    p = [s for s in steps if s.get("name") == PLACE_STEP]
    w = [s for s in steps if s.get("name") == WRITE_STEP]
    r = [s for s in steps if s.get("name") == RESEARCH_STEP]
    if len(p) > 1 or len(w) > 1 or len(r) > 1:
        raise ValueError("duplicate_job_step")
    if p and p[0].get("conclusion") == "skipped":
        return "not_places"
    if (job.get("conclusion") == "success" and p and w
            and p[0].get("conclusion") == w[0].get("conclusion") == "success"):
        if not r:
            # Legacy runs never proved the generic state actually persisted.
            return "places_research_unconfirmed"
        if r[0].get("conclusion") == "success":
            return "places_write_success"
        # A warning in generic research must not count as a successful write.
        return "places_failure"
    if p and p[0].get("conclusion") == "failure":
        return "places_failure"
    if p and p[0].get("conclusion") == "success" and w and w[0].get("conclusion") == "skipped":
        return "preview_or_no_write"
    # Unknown/failed runs may have failed before determining a cycle.
    return "unknown_or_failed"


def revision_floor(read_commits):
    """Latest main commit affecting research, not unrelated catalogue writes."""
    times = []
    for path in RESEARCH_PATHS:
        data = read_commits(path)
        if not isinstance(data, list) or len(data) != 1:
            raise ValueError("incomplete_research_revision")
        times.append(timestamp({"created_at": data[0]["commit"]["committer"]["date"]}))
    return max(times)


def contains_revisions(head, revisions, compare):
    """Verify ancestry, not the author/committer date of a pre-merge commit."""
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("invalid_intake_head")
    for revision in set(revisions):
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("invalid_research_revision")
        if revision == head:
            continue
        doc = compare(revision, head)
        if not isinstance(doc, dict) or doc.get("status") not in ("identical", "ahead", "behind", "diverged"):
            raise ValueError("invalid_revision_comparison")
        if doc["status"] not in ("identical", "ahead"):
            return False
    return True


def decide(rows, now, read_jobs, research_since=None, contains_current=None):
    if (not isinstance(rows, list) or len(rows) > MAX_HISTORY
            or not isinstance(now, datetime) or now.tzinfo is None):
        raise ValueError("invalid_run_history")
    if research_since is not None and (not isinstance(research_since, datetime)
            or research_since.tzinfo is None or research_since > now + timedelta(minutes=3)):
        raise ValueError("invalid_research_revision_time")
    eligible = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_run")
        if (row.get("head_branch") != "main"
                or row.get("event") not in ("schedule", "workflow_dispatch", "push")):
            continue
        when = timestamp(row)
        if when > now + timedelta(minutes=3):
            return False, "clock_skew"
        if row.get("status") in ACTIVE:
            return False, "trusted_intake_active"
        if row.get("status") != "completed":
            return False, "unknown_run_status"
        eligible.append((when, row))
    # Only inspect fresh runs; a stale history cannot mask a missing cycle.
    for when, row in sorted(eligible, key=lambda pair: pair[0], reverse=True):
        age = now - when
        if age >= SUCCESS_GAP:
            break
        rid = row.get("id")
        if type(rid) is not int or rid <= 0:
            raise ValueError("invalid_run_id")
        result = place_job_result(read_jobs(rid))
        if result == "places_write_success":
            # A previously persisted cycle is not evidence that newly
            # merged research code has run. Still suppress active jobs and
            # keep the existing failure grace; only one new cycle is due.
            if ((research_since is None or when >= research_since)
                    and (contains_current is None or contains_current(row))):
                return False, "recent_places_write"
        if result in ("places_failure", "unknown_or_failed") and age < FAILURE_GAP:
            return False, "failure_retry_grace"
    if len(rows) == MAX_HISTORY and eligible and min(w for w, _ in eligible) > now - SUCCESS_GAP:
        return False, "history_window_incomplete"
    return True, "places_cycle_due"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    if not trusted(os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_REF"),
                   os.getenv("GITHUB_EVENT_NAME"), os.getenv("PTITESONDES_PUBLIC_INTAKE")):
        raise ValueError("untrusted_or_paused_recovery")
    token = os.getenv("GH_TOKEN")
    if not token:
        raise ValueError("missing_actions_token")
    data = request(token, API + "/actions/workflows/" + TARGET
                   + "/runs?branch=main&per_page=30")
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise ValueError("invalid_run_list")
    def jobs(rid):
        return request(token, API + "/actions/runs/" + str(rid) + "/jobs?per_page=30")
    def commits(path):
        return request(token, API + "/commits?" + urlencode(
            {"sha": "main", "path": path, "per_page": 1}))
    revisions_by_path = {path: commits(path) for path in RESEARCH_PATHS}
    since = revision_floor(revisions_by_path.__getitem__)
    revisions = [value[0]["sha"] for value in revisions_by_path.values()]
    def current(row):
        return contains_revisions(row.get("head_sha"), revisions, lambda base, head:
            request(token, API + "/compare/" + base + "..." + head + "?per_page=1"))
    due, reason = decide(data["workflow_runs"], datetime.now(timezone.utc), jobs,
                         research_since=since, contains_current=current)
    print("places:", reason, "dispatch=", due)
    if due and args.execute:
        request(token, API + "/actions/workflows/" + TARGET + "/dispatches",
                {"ref": "main", "inputs": INPUTS})
        print("Existing protected places intake dispatched; no direct publication")


if __name__ == "__main__":
    main()
