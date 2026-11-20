#!/usr/bin/env python3
"""Append-only preview of repeat audio evidence on separate UTC dates.

This is *NOT* a playable-stream certification, a publisher, or a deletion engine.
An observed MP3/Ogg/FLAC header can be a recording rather than live radio.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import uuid
from pathlib import Path

VALID_VERDICTS = frozenset({
    "audio_sample_ok", "audio_mime_only", "playlist_pending",
    "not_confirmed_audio", "needs_review", "blocked_unsafe", "container_pending",
})
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def parse_day(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("Invalid observation day")
    day = dt.date.fromisoformat(raw).isoformat()
    if day != raw:
        raise ValueError("Non-canonical observation day")
    return day


def valid_uuid(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("Invalid station UUID")
    value = str(uuid.UUID(raw))
    if value != raw:
        raise ValueError("Non-canonical station UUID")
    return value


def sustained_transport_evidence(item: dict) -> bool:
    """Only an explicit bounded transport record earns the *non-certifying* flag."""
    evidence = item.get("continuityEvidence")
    if evidence is None:
        return False  # legacy 512-byte probes never become sustained by inference
    if (not isinstance(evidence, dict) or
        evidence.get("publicationAllowed") is not False or
        evidence.get("state") not in {"transport_sustained", "not_confirmed"}):
        raise ValueError("Invalid extended stream evidence")
    if evidence["state"] != "transport_sustained":
        return False
    values = (evidence.get("elapsedMs"), evidence.get("observedBytes"),
              evidence.get("readChunks"))
    if (item.get("verdict") != "audio_sample_ok" or
        any(not isinstance(x, int) or isinstance(x, bool) for x in values) or
        values[0] < 6000 or values[1] < 4096 or values[2] < 2 or
        values[1] > 512 * 1024 or values[2] > 1024):
        raise ValueError("Inconsistent sustained transport claim")
    return True


def frame_chain_evidence(item: dict) -> bool:
    """Conservative, format-limited frame evidence; never an admission stamp."""
    evidence = item.get("continuityEvidence")
    if evidence is None:
        return False
    if not isinstance(evidence, dict):
        raise ValueError("Invalid continuity evidence")
    frames = evidence.get("frameEvidence")
    if frames is None:
        return False
    if (not isinstance(frames, dict) or
        frames.get("state") not in {"frame_chain", "not_confirmed"} or
        frames.get("publicationAllowed") is not False):
        raise ValueError("Invalid frame evidence")
    if frames["state"] != "frame_chain":
        return False
    count = frames.get("frameCount")
    sample = frames.get("sampleBytes")
    codec = frames.get("codec")
    if (codec not in {"mpeg_audio", "aac_adts"} or
        not isinstance(count, int) or isinstance(count, bool) or count < 3 or
        count > 100 or not isinstance(sample, int) or isinstance(sample, bool) or
        sample < 24 or sample > 65536 or
        not isinstance(evidence.get("observedBytes"), int) or
        evidence["observedBytes"] < sample or
        item.get("verdict") != "audio_sample_ok"):
        raise ValueError("Inconsistent frame chain evidence")
    return evidence.get("state") == "transport_sustained"


def decoded_pcm_evidence(item: dict) -> bool:
    """A bounded successful decode is evidence, never a live-radio certificate."""
    evidence = item.get("continuityEvidence")
    if evidence is None:
        return False
    if not isinstance(evidence, dict):
        raise ValueError("Invalid continuity evidence for decoder")
    decoded = evidence.get("decodeEvidence")
    if decoded is None:
        return False
    if (not isinstance(decoded, dict) or decoded.get("publicationAllowed") is not False or
        decoded.get("state") not in {"decoded_pcm", "not_decoded",
            "decoder_unavailable", "decoder_not_supported", "decoder_failed_or_timed_out"}):
        raise ValueError("Invalid decoder observation")
    if decoded["state"] != "decoded_pcm":
        return False
    pcm = decoded.get("pcmBytes")
    source = decoded.get("inputBytes")
    if (item.get("verdict") != "audio_sample_ok" or
        not isinstance(pcm, int) or isinstance(pcm, bool) or
        not isinstance(source, int) or isinstance(source, bool) or
        pcm < 1024 or pcm > 65536 or source < 512 or source > 65536 or
        evidence.get("observedBytes", 0) < source or
        not sustained_transport_evidence(item)):
        raise ValueError("Inconsistent PCM decoding observation")
    return True


def next_evidence_report(
    probe: dict, previous: dict | None = None, *,
    retain_stream_variants: bool = False,
) -> dict:
    """Opt-in per-(UUID, stream SHA) retention; legacy behavior remains default.

    This is only technical evidence retention, not a live-radio certificate.
    Existing one-stream reports can migrate forward without losing observations.
    """
    if (not isinstance(probe, dict) or probe.get("schemaVersion") != 1 or
        probe.get("publicationAllowed") is not False or
        not isinstance(probe.get("checks"), list)):
        raise ValueError("Untrusted technical probe report")
    day = parse_day(probe.get("observationDate"))
    checks = probe["checks"]
    if len(checks) > 5:
        raise ValueError("Probe count exceeds isolated budget")
    records: dict[str | tuple[str, str], dict] = {}
    if previous is not None:
        if (not isinstance(previous, dict) or previous.get("schemaVersion") != 1 or
            previous.get("publicationAllowed") is not False or
            not isinstance(previous.get("records"), list)):
            raise ValueError("Invalid previous evidence report")
        if previous.get("streamHistoryMode") == "per_stream" and not retain_stream_variants:
            raise ValueError("Refusing to downgrade multi-stream evidence history")
        if previous.get("streamHistoryMode") not in (None, "per_stream"):
            raise ValueError("Unknown historical evidence mode")
        if len(previous["records"]) > 25000:
            raise ValueError("Excessive technical stream history")
        for row in previous["records"]:
            if not isinstance(row, dict):
                raise ValueError("Invalid previous record")
            uid = valid_uuid(row.get("stationuuid"))
            sha = row.get("streamSha256")
            if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
                raise ValueError("Invalid previous stream fingerprint")
            dates = row.get("audioEvidenceDates")
            if not isinstance(dates, list) or len(dates) > 30:
                raise ValueError("Bad previous observation count")
            dates = [parse_day(value) for value in dates]
            if dates != sorted(set(dates)) or any(value > day for value in dates):
                raise ValueError("Invalid previous evidence days")
            sustained_dates = row.get("sustainedTransportDates", [])
            if not isinstance(sustained_dates, list) or len(sustained_dates) > 30:
                raise ValueError("Bad sustained transport observation count")
            sustained_dates = [parse_day(value) for value in sustained_dates]
            if (sustained_dates != sorted(set(sustained_dates)) or
                not set(sustained_dates).issubset(dates)):
                raise ValueError("Invalid sustained transport evidence days")
            frame_dates = row.get("frameChainDates", [])
            if not isinstance(frame_dates, list) or len(frame_dates) > 30:
                raise ValueError("Invalid frame chain observation dates")
            frame_dates = [parse_day(value) for value in frame_dates]
            if (frame_dates != sorted(set(frame_dates)) or
                not set(frame_dates).issubset(sustained_dates)):
                raise ValueError("Inconsistent frame chain days")
            decode_dates = row.get("decodedPcmDates", [])
            if not isinstance(decode_dates, list) or len(decode_dates) > 30:
                raise ValueError("Bad decoded PCM observation dates")
            decode_dates = [parse_day(value) for value in decode_dates]
            if (decode_dates != sorted(set(decode_dates)) or
                not set(decode_dates).issubset(sustained_dates)):
                raise ValueError("Inconsistent decoded PCM days")
            last_decode_state = row.get("lastDecodeState", "not_run")
            if last_decode_state not in {"not_run", "decoded_pcm", "not_decoded",
                    "decoder_unavailable", "decoder_not_supported",
                    "decoder_failed_or_timed_out"}:
                raise ValueError("Invalid prior decoder state")
            last_frame_state = row.get("lastFrameState", "not_run")
            if last_frame_state not in {"not_run", "not_confirmed", "frame_chain"}:
                raise ValueError("Invalid frame observation state")
            continuity_state = row.get("lastContinuityState", "not_run")
            if continuity_state not in {"not_run", "not_confirmed", "transport_sustained"}:
                raise ValueError("Invalid previous continuity state")
            last = parse_day(row.get("lastObservedDate"))
            key = (uid, sha) if retain_stream_variants else uid
            if last > day or key in records:
                raise ValueError("Future or repeated evidence record")
            records[key] = {
                "stationuuid": uid,
                "streamSha256": sha,
                "audioEvidenceDates": dates,
                "sustainedTransportDates": sustained_dates,
                "frameChainDates": frame_dates,
                "decodedPcmDates": decode_dates,
                "lastObservedDate": last,
                "lastVerdict": str(row.get("lastVerdict") or ""),
                "lastContinuityState": continuity_state,
                "lastFrameState": last_frame_state,
                "lastDecodeState": last_decode_state,
            }
    seen = set()
    for item in checks:
        if not isinstance(item, dict) or item.get("publicationAllowed") is not False:
            raise ValueError("Unsafe or invalid probe result")
        uid = valid_uuid(item.get("stationuuid"))
        if uid in seen:
            raise ValueError("Duplicate probe UUID")
        seen.add(uid)
        verdict = item.get("verdict")
        sha = item.get("streamSha256")
        if verdict not in VALID_VERDICTS or not isinstance(sha, str) or (
            not SHA256_RE.fullmatch(sha)
        ):
            raise ValueError("Unknown verdict or stream fingerprint")
        sustained = sustained_transport_evidence(item)
        frames = frame_chain_evidence(item)
        decoded = decoded_pcm_evidence(item)
        key = (uid, sha) if retain_stream_variants else uid
        old = records.get(key)
        if old is None or old["streamSha256"] != sha:
            old = {
                "stationuuid": uid, "streamSha256": sha,
                "audioEvidenceDates": [], "sustainedTransportDates": [],
                "frameChainDates": [], "decodedPcmDates": [],
                "lastObservedDate": day, "lastVerdict": verdict,
                "lastContinuityState": "not_run",
                "lastFrameState": "not_run", "lastDecodeState": "not_run",
            }
            if len(records) >= 25000:
                raise ValueError("Technical stream history capacity exceeded")
            records[key] = old
        old["lastVerdict"] = verdict
        old["lastObservedDate"] = day
        old["lastContinuityState"] = (
            "transport_sustained" if sustained else
            "not_confirmed" if item.get("continuityEvidence") is not None else "not_run")
        frame_observation = item.get("continuityEvidence") or {}
        old["lastFrameState"] = (
            "frame_chain" if frames else
            "not_confirmed" if frame_observation.get("frameEvidence") is not None else "not_run")
        decode_observation = frame_observation.get("decodeEvidence") or {}
        old["lastDecodeState"] = (
            "decoded_pcm" if decoded else
            decode_observation.get("state", "not_run"))
        if verdict == "audio_sample_ok" and day not in old["audioEvidenceDates"]:
            old["audioEvidenceDates"] = sorted(
                (old["audioEvidenceDates"] + [day])[-30:])
        if sustained and day not in old["sustainedTransportDates"]:
            old["sustainedTransportDates"] = sorted(
                (old["sustainedTransportDates"] + [day])[-30:])
        if frames and day not in old["frameChainDates"]:
            old["frameChainDates"] = sorted((old["frameChainDates"] + [day])[-30:])
        if decoded and day not in old["decodedPcmDates"]:
            old["decodedPcmDates"] = sorted((old["decodedPcmDates"] + [day])[-30:])
        # Retire only expired evidence samples, never a radio or its identifiers.
        old["sustainedTransportDates"] = [
            d for d in old["sustainedTransportDates"] if d in old["audioEvidenceDates"]
        ]
        old["frameChainDates"] = [
            d for d in old["frameChainDates"] if d in old["sustainedTransportDates"]
        ]
        old["decodedPcmDates"] = [
            d for d in old["decodedPcmDates"] if d in old["sustainedTransportDates"]
        ]
    output_rows = []
    for uid, row in sorted(records.items()):
        # Repeat evidence is a prompt for extended live-radio checks, not
        # a stamp that a station plays music continuously or can be published.
        output_rows.append({
            **row,
            "repeatAudioSample": (
                len(row["audioEvidenceDates"]) >= 2
                and row["lastObservedDate"] == day
                and row["lastVerdict"] == "audio_sample_ok"
            ),
            "repeatSustainedTransport": (
                len(row["sustainedTransportDates"]) >= 2
                and row["lastObservedDate"] == day
                and row["lastContinuityState"] == "transport_sustained"
            ),
            "repeatFrameChain": (
                len(row["frameChainDates"]) >= 2
                and row["lastObservedDate"] == day
                and row["lastFrameState"] == "frame_chain"
            ),
            "repeatDecodedPcm": (
                len(row["decodedPcmDates"]) >= 2
                and row["lastObservedDate"] == day
                and row["lastDecodeState"] == "decoded_pcm"
            ),
            "technicalQualified": False,
            "publicationAllowed": False,
        })
    return {
        "schemaVersion": 1, "observationDate": day,
        "streamHistoryMode": "per_stream" if retain_stream_variants else "legacy_uuid",
        "publicationAllowed": False, "technicallyQualifiedCount": 0,
        "repeatAudioCandidateCount": sum(
            x["repeatAudioSample"] for x in output_rows),
        "repeatSustainedTransportCount": sum(
            x["repeatSustainedTransport"] for x in output_rows),
        "repeatFrameChainCount": sum(x["repeatFrameChain"] for x in output_rows),
        "repeatDecodedPcmCount": sum(x["repeatDecodedPcm"] for x in output_rows),
        "notObservedTodayCount": sum(
            x["lastObservedDate"] != day for x in output_rows),
        "records": output_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument(
        "--retain-stream-variants", action="store_true",
        help="Opt-in: preserve separate evidence for each UUID + SHA-256 stream",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    previous = (json.loads(args.previous.read_text(encoding="utf-8"))
                if args.previous else None)
    report = next_evidence_report(
        probe, previous, retain_stream_variants=args.retain_stream_variants,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("RADIO_STREAM_EVIDENCE_PREVIEW_ONLY "
          f"repeat_sample_candidates={report['repeatAudioCandidateCount']} "
          f"repeat_sustained={report['repeatSustainedTransportCount']} "
          f"repeat_frames={report['repeatFrameChainCount']} "
          f"repeat_decoded={report['repeatDecodedPcmCount']} "
          f"retained_unseen={report['notObservedTodayCount']} "
          "qualified=0 published=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
