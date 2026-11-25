#!/usr/bin/env python3
"""Deterministic decision preview, never an admission or publishing authority.

The policy is independent of station/host allowlists. Missing or conflicting
evidence creates a work item, not a permanent rejection. A logo is optional.
Only current discovery and evidence bound to the same stream and page can
produce a staging-review proposal. No raw stream or homepage URL is emitted.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

from radio_daily_qualification_dossiers import index, safe_digest, MAX_BYTES
from radio_daily_editorial_preview import homepage_url, normalize, ANALYZER_VERSION
from radio_stream_recheck_ledger import parse_day, SHA256_RE

POLICY_VERSION = 1
MAX_EDITORIAL_AGE = 7
MAX_TECHNICAL_AGE = 7
STRONG_VERDICTS = ("continuous_icy_frame_indication", "advancing_hls_audio_frame_indication")


def fresh(value, day, max_age):
    try:
        age = (dt.date.fromisoformat(day) - dt.date.fromisoformat(parse_day(value))).days
        return 0 <= age <= max_age
    except (TypeError, ValueError):
        return False


def qualified_days(evidence, day):
    dates = evidence.get("positiveObservationDates", [])
    if not isinstance(dates, list) or len(dates)>30:
        raise ValueError("invalid continuity dates")
    dates = [parse_day(x) for x in dates]
    if dates != sorted(set(dates)) or any(x>day for x in dates):
        raise ValueError("invalid continuity history")
    return [x for x in dates if fresh(x,day,MAX_TECHNICAL_AGE)]


def decide(discovery, dossiers, baseline_sha):
    day = parse_day(discovery.get("scanDate"))
    if (not isinstance(baseline_sha,str) or not SHA256_RE.fullmatch(baseline_sha)
            or discovery.get("schemaVersion")!=1 or discovery.get("publicationAllowed") is not False
            or dossiers.get("schemaVersion")!=1 or dossiers.get("scanDate")!=day
            or dossiers.get("catalogBaselineSha256")!=baseline_sha
            or dossiers.get("publicationAllowed") is not False or dossiers.get("approvedCount")!=0):
        raise ValueError("invalid decision input")
    current, rows = index(discovery,"candidates"), index(dossiers,"records")
    if not set(current)<=set(rows):
        raise ValueError("discovery missing from dossier registry")
    stream_groups = {}
    for uid, row in rows.items():
        if row.get("approved") is not False or row.get("publicationAllowed") is not False:
            raise ValueError("unexpected admission")
        obs=row.get("lastSourceObservation") or {}
        fingerprint=obs.get("streamSha256")
        if fingerprint and obs.get("classification") in ("unmapped_candidate","already_mapped","known_legacy_not_yet_mapped","possible_variant_or_duplicate"):
            stream_groups.setdefault(fingerprint,[]).append(uid)
    output=[]
    for uid,row in sorted(rows.items()):
        obs=row.get("lastSourceObservation") or {}
        source=current.get(uid)
        sha=obs.get("streamSha256")
        cls=obs.get("classification")
        reasons=[]
        homepage=row.get("homepageEvidence") or {}
        audio=row.get("streamEvidence") or {}
        cont=row.get("continuityEvidence") or {}
        hls=row.get("hlsEvidence") or {}
        logo=row.get("logoEvidence") or {}
        current_source=bool(source and row.get("observedInScan") is True and obs.get("date")==day
                            and sha and safe_digest(source.get("streamUrl"))==sha)
        duplicate=bool(row.get("duplicateRisk") or obs.get("possibleGoStationIds")
                       or len(stream_groups.get(sha,[]))>1)
        page=homepage_url(source.get("homepage")) if source else None
        page_bound=bool(current_source and page and homepage.get("homepageSha256")==safe_digest(page)
                         and homepage.get("identityNameSha256")==safe_digest(normalize(source.get("name")))
                         and homepage.get("streamSha256")==sha
                         and homepage.get("analyzerVersion")==ANALYZER_VERSION
                         and homepage.get("retrieval")=="html_observed"
                         and fresh(homepage.get("observedDate"),day,MAX_EDITORIAL_AGE))
        editorial_match=bool(page_bound and homepage.get("identityNameMatch") is True
                             and homepage.get("signal")=="identity_and_target_indication"
                             and homepage.get("primaryTargetTerms") and not homepage.get("primaryElectronicTerms"))
        linked=bool(page_bound and homepage.get("declaredStreamLinked") is True)
        # An isolated target keyword can describe just one show. Require
        # additional station-level programme evidence before staging review.
        structured=bool(editorial_match and homepage.get("structuredProgrammeEvidence") is True)
        mixed=(row.get("editorialSignal") in ("mixed_genre_review","electronic_context_review")
               or homepage.get("signal") in ("mixed_programme_indication","electronic_indication"))
        strong=[]
        for evidence in (cont,hls):
            if (sha and evidence.get("streamSha256")==sha
                    and evidence.get("verdict") in STRONG_VERDICTS
                    and fresh(evidence.get("observedDate"),day,MAX_TECHNICAL_AGE)):
                strong.append(evidence)
        latest_negative=(audio.get("streamSha256")==sha and audio.get("lastVerdict") not in ("audio_sample_ok","playlist_pending")
                         and fresh(audio.get("lastObservedDate"),day,MAX_TECHNICAL_AGE)
                         and all(audio["lastObservedDate"]>=x["observedDate"] for x in strong))
        # A fresh negative continuity check must not be bypassed via stale HLS.
        negative_dates=[x["observedDate"] for x in (cont,hls)
                        if sha and x.get("streamSha256")==sha and x.get("verdict") not in STRONG_VERDICTS
                        and fresh(x.get("observedDate"),day,MAX_TECHNICAL_AGE)]
        strong=[x for x in strong if not any(d>=x["observedDate"] for d in negative_dates)]
        days=sorted({d for x in strong for d in qualified_days(x,day)})
        continuous=bool(strong and not latest_negative)
        repeat=continuous and len(days)>=2 and day in days
        logo_hint=bool(logo.get("retrieval")=="decoded_unapproved" and logo.get("sourceSha256")
                       and logo.get("sourceSha256")==obs.get("reportedFaviconSha256"))
        if cls=="already_mapped":
            decision="already_known"
        elif cls in ("known_legacy_not_yet_mapped","possible_variant_or_duplicate") or duplicate:
            decision="identity_review"
            reasons.append("resolve_duplicate_or_legacy_identity")
        else:
            if not current_source or cls!="unmapped_candidate":
                reasons.append("refresh_current_reconciliation")
            if not editorial_match:
                reasons.append("obtain_station_bound_editorial_evidence")
            if not linked:
                reasons.append("bind_broadcaster_to_stream")
            if not structured:
                reasons.append("confirm_station_level_programme_scope")
            if mixed:
                reasons.append("resolve_mixed_or_electronic_format")
            if not continuous:
                reasons.append("obtain_current_continuity_evidence")
            elif not repeat:
                reasons.append("repeat_continuity_on_distinct_days")
            if latest_negative or negative_dates:
                reasons.append("resolve_recent_negative_technical_observation")
            if not reasons:
                decision="ready_for_staging_review"
            elif not current_source:
                decision="source_recheck"
            elif editorial_match and linked and continuous:
                decision="advanced_candidate"
            elif not editorial_match or not linked or not structured or mixed:
                decision="editorial_review"
            else:
                decision="technical_review"
        output.append({"stationuuid":uid,"name":row.get("name"),"decision":decision,
                       "streamSha256":sha,"editorialMatch":editorial_match,
                       "broadcasterStreamLink":linked,"structuredProgrammeEvidence":structured,
                       "continuityIndication":continuous,"positiveContinuityDays":days,
                       "logoDecodedHint":logo_hint,"blockingReasons":reasons,
                       "approved":False,"publicationAllowed":False})
    counts=dict(sorted(Counter(x["decision"] for x in output).items()))
    return {"schemaVersion":1,"policyVersion":POLICY_VERSION,"scanDate":day,
            "catalogBaselineSha256":baseline_sha,"publicationAllowed":False,"approvedCount":0,
            "stagingReviewCount":counts.get("ready_for_staging_review",0),"counts":counts,
            "blockingReasonCounts":dict(sorted(Counter(y for x in output for y in x["blockingReasons"]).items())),
            "records":output}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("discovery","dossiers","output"):
        p.add_argument("--"+key,type=Path,required=True)
    p.add_argument("--baseline-sha256",required=True)
    a=p.parse_args()
    def load(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversized decision input")
        return json.loads(path.read_text())
    report=decide(load(a.discovery),load(a.dossiers),a.baseline_sha256)
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversized decision output")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_DECISION_PREVIEW_ONLY",{k:v for k,v in report.items() if k!="records"})

if __name__=="__main__":
    main()
