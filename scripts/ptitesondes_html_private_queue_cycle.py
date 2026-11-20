#!/usr/bin/env python3
"""Opt-in runner-side HTML -> PRIVATE Git checkout queue stage. No publication.

Zero network writes, no Github API/secret processing, and no patch.v1.
The only potential file write is an atomically replaced, validated private
queue file in a verified PtitesOndes checkout at automation/ptitesondes-intake.
The runner owns the separate authenticated Git push AFTER staging; this script
never commits or pushes. All stdout is fixed aggregate counters.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
from zoneinfo import ZoneInfo

from ptitesondes_html_index_detail_live_smoke import _independent_context
from ptitesondes_html_index_detail_funnel import READ_ONLY_ADAPTERS
from ptitesondes_institutional_source_policy import (
    MANIFEST_PATH, MAX_REGISTRY_BYTES, MAX_SOURCES as POLICY_MAX_SOURCES,
    _manifest_valid,
)
from ptitesondes_nonmusical_private_queue_handoff import (
    MAX_QUEUE, prepare_private_html_review_handoff,
    reconcile_private_html_review_queue,
)

SCHEMA = "ptitesondes.html_private_runner_stage.v1"
STORAGE_RELATIVE = Path("automation-intake/ptitesondes/html-review-candidates.json")
PRIVATE_REPO = "Sarogal/PtitesOndes"
PRIVATE_BRANCH = "automation/ptitesondes-intake"
MAX_FILE_BYTES = 2_000_000
MAX_SOURCE_BATCH = 4


def _validated_manifest():
    if MANIFEST_PATH.stat().st_size > MAX_REGISTRY_BYTES:
        raise ValueError("institutional_registry_too_large")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not _manifest_valid(manifest):
        raise ValueError("institutional_registry_invalid")
    return manifest


def _registered_adapters(manifest):
    """Only from curated, committed institutional registry and adapters.

    New sources cannot authorize their own hosts/child paths, nor can a
    collector select an arbitrary URL to fetch.
    """
    out = []
    if (type(manifest) is not dict
            or type(manifest.get("entries")) is not list
            or len(manifest["entries"]) > POLICY_MAX_SOURCES):
        raise ValueError("institutional_registry_invalid")
    for entry in manifest["entries"]:
        if type(entry) is not dict:
            raise ValueError("institutional_registry_invalid")
        for adapter_id, adapter in sorted(READ_ONLY_ADAPTERS.items()):
            if (entry.get("approved_host") == adapter["host"]
                    and entry.get("child_prefix") == adapter["child_path"]):
                pin = {"approved_host": entry["approved_host"],
                       "exact_index_url": entry["index_url"]}
                if (pin["approved_host"] != entry["approved_host"]
                        or not pin["exact_index_url"].startswith(
                            "https://" + entry["approved_host"] + "/")):
                    raise ValueError("institutional_index_host_mismatch")
                out.append((adapter_id, pin, adapter["timezone"]))
                break
    # Unrecognized institutional sites are counted, not silently "approved".
    return out


def _git_value(root, *args):
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True,
            text=True, timeout=6, check=True,
        )
        return proc.stdout.strip()
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        # Never forward git stderr, which may contain a credential/URL.
        raise ValueError("private_git_checkout_unverified") from None


def _private_target(root):
    root = Path(root)
    # Reject symlink escapes and unexpected repository / branch. No
    # collector-controlled path is ever used to choose the output file.
    if (not root.is_dir() or root.is_symlink()
            or not (root / ".git").exists()
            or any((root / child).is_symlink() for child in (
                "automation-intake", "automation-intake/ptitesondes",
                str(STORAGE_RELATIVE)))):
        raise ValueError("private_git_checkout_unverified")
    if _git_value(root, "rev-parse", "--show-toplevel") != str(root.resolve()):
        raise ValueError("private_git_checkout_unverified")
    if _git_value(root, "branch", "--show-current") != PRIVATE_BRANCH:
        raise ValueError("private_git_branch_wrong")
    remote = _git_value(root, "remote", "get-url", "origin")
    if remote not in (
            "https://github.com/" + PRIVATE_REPO,
            "https://github.com/" + PRIVATE_REPO + ".git",
            "git@github.com:" + PRIVATE_REPO + ".git"):
        raise ValueError("private_git_remote_wrong")
    return root / STORAGE_RELATIVE


def _load_queue(path):
    if not path.exists():
        return []
    if not path.is_file() or path.is_symlink():
        raise ValueError("private_review_file_invalid")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("private_review_file_too_large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("private_review_file_invalid") from None
    if type(data) is not list or len(data) > MAX_QUEUE:
        raise ValueError("private_review_file_invalid")
    # Reuse the queue contract to reject duplicate IDs, forged approvals,
    # unexpected keys and untrusted prior data, without logging any row.
    reconcile_private_html_review_queue(data, [], datetime.now(
        ZoneInfo("Europe/Paris")).date())
    return data


def _stage_queue(path, queue):
    # No filename from caller or candidate enters this function.
    if (type(queue) is not list or len(queue) > MAX_QUEUE
            or path.is_symlink()):
        raise ValueError("private_html_output_invalid")
    reconcile_private_html_review_queue(queue, [], datetime.now(
        ZoneInfo("Europe/Paris")).date())
    data = (json.dumps(queue, ensure_ascii=False, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("private_html_output_too_large")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".html-review-stage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def execute_cycle(existing, now, *, batch=0, max_sources=2,
                  manifest=None, context=None,
                  runner=prepare_private_html_review_handoff):
    """All mutable state lives in private memory until caller opts to stage."""
    if (type(now) is not datetime or now.tzinfo is None
            or now.utcoffset() is None
            or type(batch) is not int or batch < 0
            or type(max_sources) is not int
            or not 1 <= max_sources <= MAX_SOURCE_BATCH):
        raise ValueError("invalid_html_cycle_options")
    manifest = _validated_manifest() if manifest is None else manifest
    targets = _registered_adapters(manifest)
    # Bounded work per invocation, but rotate over ALL registered adapters:
    # a fixed range of eight batches would permanently starve source 17+.
    total_batches = max(1, (len(targets) + max_sources - 1) // max_sources)
    selected_batch = batch % total_batches
    selected = targets[selected_batch * max_sources:(selected_batch + 1) * max_sources]
    if context is None:
        context = _independent_context()
    # Existing is validated even when there are no eligible adapters.
    current = reconcile_private_html_review_queue(
        existing, [], now.astimezone(ZoneInfo("Europe/Paris")).date())["queue"]
    counts = {
        "schema": SCHEMA, "registered_sources": len(manifest["entries"]),
        "recognized_adapters": len(targets),
        "unrecognized_adapters": len(manifest["entries"]) - len(targets),
        "sources_selected": len(selected), "sources_sampled": 0,
        "source_batches_total": total_batches, "source_batch_selected": selected_batch,
        "sources_unavailable": 0, "sessions_observed_for_private_review": 0,
        "new_private_reviews": 0, "rechecked_private_reviews": 0,
        "total_private_reviews": 0, "public_writes": 0,
        "private_patch_additions": 0, "publisher_connected": False,
        "publication_ready": False, "approval_granted": False,
    }
    for adapter_id, pin, timezone in selected:
        source_day = now.astimezone(ZoneInfo(timezone))
        # No exception strings or source URLs in report, even on error.
        try:
            result = runner(
                current, pin, adapter_id, source_day.date(),
                max_details=30, as_of=source_day,
                independent_context=context,
            )
            if (type(result) is not dict
                    or type(result.get("queue")) is not list
                    or type(result.get("report")) is not dict
                    or type(result.get("public_funnel_report")) is not dict):
                raise ValueError("private_html_runner_contract_invalid")
            summary = result["report"]
            source = result["public_funnel_report"]
            if (summary.get("publication_ready") is not False
                    or summary.get("public_writes") != 0
                    or summary.get("publisher_connected") is not False
                    or source.get("publication_ready") is not False
                    or source.get("public_writes") != 0
                    or any(type(summary.get(key)) is not int
                           or not 0 <= summary[key] <= MAX_QUEUE
                           for key in ("new_private_reviews",
                                       "rechecked_private_reviews"))):
                raise ValueError("private_html_unsafe_handoff")
            # An index fetch that returned zero detail pages is not a
            # successful sample, however green the runner process may be.
            pages_read = source.get("child_pages_read")
            if type(pages_read) is not int or pages_read < 1:
                raise ValueError("private_html_source_not_sampled")
            current = reconcile_private_html_review_queue(
                result["queue"], [], source_day.date())["queue"]
            counts["sources_sampled"] += 1
            counts["sessions_observed_for_private_review"] += (
                summary.get("new_private_reviews", 0)
                + summary.get("rechecked_private_reviews", 0))
            counts["new_private_reviews"] += summary.get(
                "new_private_reviews", 0)
            counts["rechecked_private_reviews"] += summary.get(
                "rechecked_private_reviews", 0)
        except (ValueError, KeyError, TypeError, OSError,
                TimeoutError, UnicodeError):
            counts["sources_unavailable"] += 1
            # Retain current data even when one source fails.
    counts["total_private_reviews"] = len(current)
    return {"queue": current, "report": counts}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("preview", "stage"), default="preview")
    p.add_argument("--state-checkout", type=Path, required=True)
    p.add_argument("--batch", type=int, default=0)
    p.add_argument("--max-sources", type=int, default=2)
    args = p.parse_args()
    # Do not allow preview to write even to a temporary output.
    try:
        target = _private_target(args.state_checkout)
        existing = _load_queue(target)
        report = execute_cycle(existing, datetime.now(ZoneInfo("Europe/Paris")),
                               batch=args.batch, max_sources=args.max_sources)
        if args.mode == "stage":
            _stage_queue(target, report["queue"])
        # The only stdout is a fixed, source-free aggregation.
        print(json.dumps(dict(report["report"], mode=args.mode),
                         ensure_ascii=False, sort_keys=True))
    except (ValueError, TypeError, OSError, UnicodeError):
        raise SystemExit("PRIVATE_HTML_QUEUE_STAGE_FAILED_CLOSED") from None


if __name__ == "__main__":
    main()
