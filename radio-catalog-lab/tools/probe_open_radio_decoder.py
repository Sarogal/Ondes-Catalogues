#!/usr/bin/env python3
"""Bounded FFmpeg live decoder check, read-only. No audio is stored or published.

Tests one official preferred HTTPS MP3 per discovered radio. Does not grant
automatic editorial approval. Publication is always forbidden here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from probe_open_radio_candidates import public_https, validate_input


def parse_ffmpeg_time(output: str) -> float:
    best = 0.0
    for line in output.splitlines():
        if not line.startswith("out_time="):
            continue
        try:
            hh, mm, ss = line[9:].split(":")
            best = max(best, 3600*int(hh) + 60*int(mm) + float(ss))
        except (ValueError, TypeError):
            pass
    return best


def decode_prefix(url: str, *, duration_s: int = 6) -> dict:
    result = {
        "url": url,
        "decoded_seconds": 0.0,
        "audio_decoder_passed": False,
        "publication_allowed": False,
        "state": "candidate",
    }
    if not public_https(url):
        result["reason"] = "unsafe_url"
        return result
    executable = shutil.which("ffmpeg")
    if not executable:
        result["reason"] = "ffmpeg_missing"
        return result
    argv = [
        executable, "-hide_banner", "-nostdin",
        "-loglevel", "error", "-stats_period", "1",
        "-protocol_whitelist", "https,tls,tcp",
        "-i", url, "-t", str(duration_s), "-vn", "-sn", "-dn",
        "-f", "null", "-", "-progress", "pipe:1",
    ]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=max(20, duration_s + 20), check=False,
            text=True, errors="replace",
        )
        output_seconds = parse_ffmpeg_time(proc.stdout)
        result["decoded_seconds"] = output_seconds
        result["audio_decoder_passed"] = (
            proc.returncode == 0 and output_seconds >= duration_s - 1
        )
        result["reason"] = (
            "decoded_audio_samples_no_file_written"
            if result["audio_decoder_passed"]
            else "decoder_incomplete_or_nonzero_exit"
        )
    except (OSError, subprocess.TimeoutExpired):
        result["reason"] = "decode_process_unavailable_or_timeout"
    result["duration_ms"] = round((time.monotonic()-start) * 1000)
    return result


def evaluate(manifest: dict, *, network: bool) -> dict:
    rows = validate_input(manifest)
    result = {
        "evidence_kind": "bounded_real_audio_decode_not_editorial_approval",
        "publication_allowed": False,
        "radios": [],
    }
    for radio in rows:
        preferred = next((s for s in radio["streams"] if s["codec"] == "MP3"),
                         radio["streams"][0])
        evidence = decode_prefix(preferred["url"]) if network else {
            "audio_decoder_passed": False,
            "reason": "offline_preflight_only",
            "publication_allowed": False,
        }
        result["radios"].append({
            "candidate_id": radio["candidate_id"],
            "name": radio["name"],
            "decoded": evidence,
            "editorial_review_required": True,
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-probe", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = evaluate(data, network=args.live_probe)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({
        "status": "GO_RADIO_DECODER_EVIDENCE_ONLY",
        "decoded": sum(bool(r["decoded"]["audio_decoder_passed"])
                       for r in report["radios"]),
        "candidates": len(report["radios"]),
        "publication_allowed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
