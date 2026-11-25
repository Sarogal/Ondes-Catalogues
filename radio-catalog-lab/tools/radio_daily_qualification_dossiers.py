#!/usr/bin/env python3
"""Join durable discovery, reconciliation, audio and artwork evidence by UUID.

Review-only: no verified editorial source, live certification or approval is
inferred from Radio Browser hints, transport evidence or a decoded image.
Raw URLs are not persisted in this public register (they may contain tokens).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from radio_stream_recheck_ledger import parse_day, valid_uuid, SHA256_RE

MAX_BYTES = 12 * 1024 * 1024
MAX_ROWS = 20000
CLASSES = {"already_mapped", "known_legacy_not_yet_mapped",
           "possible_variant_or_duplicate", "unmapped_candidate"}


def index(report, field):
    rows = report.get(field)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("Invalid dossier source rows")
    result = {}
    for row in rows:
        uid = valid_uuid(row.get("stationuuid"))
        if uid in result:
            raise ValueError("Duplicate UUID in dossier source")
        result[uid] = row
    return result


def safe_digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if isinstance(raw, str) and raw else None


def reported_host(raw):
    try:
        url = urlsplit(raw)
        if (url.scheme not in ("http", "https") or url.username or url.password
                or not url.hostname or len(url.hostname) > 253):
            return None
        return url.hostname if re.fullmatch(r"[a-z0-9.-]+", url.hostname) else None
    except (ValueError, TypeError, AttributeError):
        return None


def build_dossiers(discovery, reconciliation, ledger, stream, logo, baseline_sha, previous=None):
    if not isinstance(baseline_sha, str) or not SHA256_RE.fullmatch(baseline_sha):
        raise ValueError("Missing pinned catalogue digest")
    day = parse_day(discovery.get("scanDate"))
    for report, date_key, count_key in (
        (discovery, "scanDate", None), (ledger, "scanDate", "automaticallyApprovedCount"),
        (stream, "observationDate", "technicallyQualifiedCount"),
        (logo, "scanDate", "approvedLogoCount"),
    ):
        if (report.get("schemaVersion") != 1 or report.get("publicationAllowed") is not False
                or report.get(date_key) != day or (count_key and report.get(count_key) != 0)):
            raise ValueError("Untrusted or mismatched dossier input")
    if (reconciliation.get("schemaVersion") != 1 or reconciliation.get("scanDate") != day
            or reconciliation.get("automaticAdmissionAllowed") is not False
            or reconciliation.get("catalogChanged") is not False):
        raise ValueError("Untrusted reconciliation")
    candidates = index(discovery, "candidates")
    reconciled = index(reconciliation, "candidates")
    history = index(ledger, "records")
    audio = index(stream, "records")
    artwork = index(logo, "records")
    if set(candidates) != set(reconciled) or not set(candidates) <= set(history):
        raise ValueError("Discovery/reconciliation/ledger mismatch")
    if any(x.get("technicalQualified") is not False or x.get("publicationAllowed") is not False
           for x in audio.values()):
        raise ValueError("Unexpected technical approval")
    if any(x.get("logoApproved") is not False or x.get("publicationAllowed") is not False
           for x in artwork.values()):
        raise ValueError("Unexpected logo approval")
    prior = {}
    if previous is not None:
        if (previous.get("schemaVersion") != 1 or previous.get("publicationAllowed") is not False
                or previous.get("approvedCount") != 0 or parse_day(previous.get("scanDate")) > day):
            raise ValueError("Untrusted prior dossier")
        if previous.get("catalogBaselineSha256") == baseline_sha:
            prior = index(previous, "records")
    tomorrow = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    records = []
    for uid, h in sorted(history.items()):
        old = prior.get(uid, {})
        if old and (old.get("approved") is not False or old.get("publicationAllowed") is not False):
            raise ValueError("Unexpected prior approval")
        observation = None
        if uid in candidates:
            row, rec = candidates[uid], reconciled[uid]
            cls = rec.get("classification")
            if cls not in CLASSES:
                raise ValueError("Unknown reconciliation class")
            observation = {
                "date": day, "countryCode": str(row.get("countrycode") or "")[:2],
                "reportedTags": str(row.get("tags") or "")[:1000],
                "reportedHomepageHost": reported_host(row.get("homepage")),
                "streamSha256": safe_digest(row.get("streamUrl")),
                "reportedFaviconSha256": safe_digest(row.get("favicon")),
                "classification": cls,
                "existingGoStationId": rec.get("existingGoStationId"),
                "possibleGoStationIds": rec.get("possibleGoStationIds", []),
            }
        elif old.get("lastSourceObservation"):
            snapshot = old["lastSourceObservation"]
            if (parse_day(snapshot.get("date")) > day or snapshot.get("classification") not in CLASSES):
                raise ValueError("Invalid prior source observation")
            observation = {k: snapshot.get(k) for k in (
                "date", "countryCode", "reportedTags", "reportedHomepageHost", "streamSha256",
                "reportedFaviconSha256", "classification", "existingGoStationId", "possibleGoStationIds")}
        cls = observation["classification"] if observation else None
        a = audio.get(uid)
        l = artwork.get(uid)
        fingerprint = observation.get("streamSha256") if observation else None
        matching_audio = bool(fingerprint and a and a.get("streamSha256") == fingerprint)
        positive = matching_audio and a.get("lastVerdict") == "audio_sample_ok"
        reasons = []
        if cls == "already_mapped":
            status = "already_known"
        elif cls in ("known_legacy_not_yet_mapped", "possible_variant_or_duplicate") or h.get("duplicateRisk"):
            status = "identity_review"
            reasons.append("resolve_legacy_or_duplicate_identity")
        else:
            status = "awaiting_evidence"
            if cls is None:
                reasons.append("reconcile_against_pinned_catalogue")
            reasons.append("independent_editorial_programme_evidence_required")
            if h.get("editorialSignal") in ("mixed_genre_review", "electronic_context_review"):
                reasons.append("resolve_genre_context")
            if not matching_audio:
                reasons.append("probe_current_stream_fingerprint")
            elif not positive:
                reasons.append("recheck_stream_after_non_positive_sample")
            elif len(a.get("liveFrameEvidenceDates", [])) < 2:
                reasons.append("repeat_live_frame_evidence_on_distinct_days")
            else:
                reasons.append("verify_continuous_live_playback")
        if uid not in candidates and status != "already_known":
            reasons.append("source_not_in_current_scan")
        next_review = None if status == "already_known" else (
            tomorrow if matching_audio and a.get("lastObservedDate") == day else day)
        records.append({
            "stationuuid": uid, "name": h.get("name"),
            "firstSeen": h.get("firstSeen"), "lastSeen": h.get("lastSeen"), "seenDays": h.get("seenDays"),
            "observedInScan": uid in candidates, "lastSourceObservation": observation,
            "editorialSignal": h.get("editorialSignal"), "editorialVerified": False,
            "officialHomepageVerified": False, "duplicateRisk": h.get("duplicateRisk") is True,
            "streamEvidence": {k: a.get(k) for k in (
                "streamSha256", "audioEvidenceDates", "liveFrameEvidenceDates", "lastObservedDate",
                "lastVerdict")} if a else None,
            "streamEvidenceMatchesCurrentSource": matching_audio,
            "logoEvidence": {k: l.get(k) for k in (
                "sourceClass", "sourceSha256", "retrieval", "imageSha256", "mime",
                "width", "height", "byteLength", "observedDate")} if l else None,
            "logoIdentityVerified": False, "status": status, "reviewReasons": reasons,
            "nextReviewDate": next_review, "approved": False, "publicationAllowed": False,
        })
    counts = {s: sum(x["status"] == s for x in records)
              for s in ("already_known", "identity_review", "awaiting_evidence")}
    return {"schemaVersion": 1, "scanDate": day, "catalogBaselineSha256": baseline_sha,
            "publicationAllowed": False, "approvedCount": 0, "counts": counts, "records": records}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("discovery", "reconciliation", "ledger", "stream", "logo", "output"):
        p.add_argument("--" + name, required=True, type=Path)
    p.add_argument("--previous", type=Path)
    p.add_argument("--baseline-sha256", required=True)
    a = p.parse_args()
    def load(path):
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("Dossier input too large")
        return json.loads(path.read_text(encoding="utf-8"))
    report = build_dossiers(*(load(getattr(a, k)) for k in
                              ("discovery", "reconciliation", "ledger", "stream", "logo")),
                            a.baseline_sha256, load(a.previous) if a.previous else None)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Dossier register capacity exceeded")
    a.output.write_text(encoded, encoding="utf-8")
    print("RADIO_QUALIFICATION_DOSSIERS_ONLY", report["counts"], "approved=0 published=false")


if __name__ == "__main__":
    main()
