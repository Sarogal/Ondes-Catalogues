#!/usr/bin/env python3
"""Timed, bounded triple-sampling evidence for discovered audio streams.

No media is saved. This is not full audio decoder / human audition and does
NOT promote a station to verified or grant permission to publish. Works for
newly discovered station IDs/hosts without a provider/station whitelist.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from probe_open_radio_candidates import validate_input, probe_stream


def summarize(samples: list[dict]) -> dict:
    okay = [s for s in samples if s.get("transport_audio_prefix") is True]
    digests = [s.get("prefix_sha256") for s in okay]
    varying = (
        len(samples) >= 3 and len(okay) == len(samples) and
        all(isinstance(x, str) and len(x) == 64 for x in digests) and
        len(set(digests)) == len(digests)
    )
    return {
        "distinct_audio_prefixes": len(set(x for x in digests if isinstance(x, str))),
        "sample_count": len(samples),
        "all_samples_have_audio_headers": len(okay) == len(samples),
        "time_separated_audio_evidence": varying,
        "publication_allowed": False,
        "editorial_review_required": True,
        "playback_decoding_confirmed": False,
    }


def evaluate(manifest: dict, *, network: bool, gap_seconds: int = 5) -> dict:
    if not 0 <= gap_seconds <= 20:
        raise ValueError("Unsafe continuity sampling gap")
    rows = validate_input(manifest)
    result = {
        "evidence_kind": "time_separated_audio_headers_not_full_playback",
        "publication_allowed": False,
        "radios": [],
    }
    for row in rows:
        # One preferred MP3 stream per radio; other variants have the bounded
        # individual-prefix verification from probe_open_radio_candidates.
        preferred = next(
            (x for x in row["streams"] if x["codec"] == "MP3"),
            row["streams"][0],
        )
        samples = []
        for index in range(3):
            if index > 0 and network:
                time.sleep(gap_seconds)
            samples.append(
                probe_stream(preferred["url"], preferred["codec"])
                if network else {
                    "transport_audio_prefix": False,
                    "reason": "offline_only",
                }
            )
        result["radios"].append({
            "candidate_id": row["candidate_id"],
            "name": row["name"],
            "preferred_stream_url": preferred["url"],
            "sample_gap_s": gap_seconds if network else 0,
            "samples": samples,
            "summary": summarize(samples),
            "status": "candidate",
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-probe", action="store_true")
    parser.add_argument("--gap-seconds", type=int, default=5)
    args = parser.parse_args()
    doc = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = evaluate(doc, network=args.live_probe,
                      gap_seconds=args.gap_seconds)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "GO_RADIO_TIME_SEPARATED_CANDIDATES_ONLY",
        "tested": len(result["radios"]),
        "all_three_audio_windows_passed": sum(
            x["summary"]["time_separated_audio_evidence"]
            for x in result["radios"]
        ),
        "publication_allowed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
