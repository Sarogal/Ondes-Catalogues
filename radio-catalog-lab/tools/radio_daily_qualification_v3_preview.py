#!/usr/bin/env python3
"""Shadow V3: combine V2 station/transport gates with observed programme hints.

Never changes V2, the generator, or an admission decision. Missing music data
is unknown, not negative evidence. No estimate of airtime or popularity.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from radio_daily_decision_preview import POLICY_VERSION as BASE_POLICY, fresh
from radio_daily_programme_preview import BUCKETS, FRESH_DAYS
from radio_daily_qualification_dossiers import index, MAX_BYTES
from radio_stream_recheck_ledger import parse_day, SHA256_RE

VERSION=3
BASE_STATES={"already_known","identity_review","source_recheck","editorial_review",
             "advanced_candidate","technical_review","ready_for_staging_review"}
CONFLICTS={"identity_conflict","genre_conflict","cross_source_identity_unlinked","collaboration_identity_held"}
CORROBORATED={"linked_sources","recording_linked_sources","recording_wikidata"}
SOURCE_TYPES=CONFLICTS|CORROBORATED|{"no_usable_source","collaboration_held","collaboration_partial",
              "collaboration_credit_genres","musicbrainz_only","wikidata_only",
              "recording_musicbrainz","recording_genre_hint","recording_only"}

def count_map(value, allowed, maximum):
    if (not isinstance(value,dict) or set(value)-set(allowed)
            or any(type(v) is not int or not 0<=v<=maximum for v in value.values())):
        raise ValueError("invalid programme counts")
    return {k:value.get(k,0) for k in allowed}

def dates(value,day):
    if not isinstance(value,list) or len(value)>90:
        raise ValueError("invalid programme dates")
    parsed=[parse_day(x) for x in value]
    if parsed!=sorted(set(parsed)) or any(x>day for x in parsed):
        raise ValueError("invalid programme dates")
    return [x for x in parsed if fresh(x,day,FRESH_DAYS-1)]

def observed_evidence(p,day):
    if p.get("verifiedArtistCount")!=0:
        raise ValueError("unexpected verified artist")
    for field in ("distinctArtistHints","distinctArtistTitleHints"):
        if type(p.get(field)) is not int or not 0<=p[field]<=90:
            raise ValueError("invalid observation counts")
    a=count_map(p.get("artistHintCounts"),BUCKETS,90)
    pairs=count_map(p.get("artistTitleHintCounts"),BUCKETS,90)
    members=count_map(p.get("collaborationMemberHintCounts",{}),BUCKETS,1800)
    sources=count_map(p.get("sourceHintCounts"),SOURCE_TYPES,90)
    if (sum(a.values())!=p["distinctArtistHints"] or sum(pairs.values())!=p["distinctArtistTitleHints"]
            or sum(sources.values())!=p["distinctArtistTitleHints"]
            or p["distinctArtistHints"]>p["distinctArtistTitleHints"]):
        raise ValueError("inconsistent programme counts")
    days=dates(p.get("observationDates"),day)
    historical=dates(p.get("reportedBroadcastDates"),day)
    return {"artistHints":a,"pairHints":pairs,"collaborationMemberHints":members,
            "sourceHints":{k:v for k,v in sorted(sources.items()) if v},
            "independentObservationDays":days,"reportedBroadcastDays":historical,
            "distinctArtistHints":p["distinctArtistHints"],"distinctArtistTitleHints":p["distinctArtistTitleHints"]}

def evaluate(decisions, programme, baseline):
    day=parse_day(decisions.get("scanDate"))
    if not isinstance(baseline,str) or not SHA256_RE.fullmatch(baseline):
        raise ValueError("invalid baseline")
    for report in (decisions,programme):
        if (report.get("schemaVersion")!=1 or report.get("scanDate")!=day
                or report.get("publicationAllowed") is not False or report.get("approvedCount")!=0):
            raise ValueError("invalid shadow input")
    if (decisions.get("policyVersion")!=BASE_POLICY or decisions.get("catalogBaselineSha256")!=baseline
            or programme.get("verifiedArtistCount")!=0 or programme.get("freshnessDays")!=FRESH_DAYS):
        raise ValueError("incompatible shadow input")
    base=index(decisions,"records")
    music=index(programme,"records")
    for row in list(base.values())+list(music.values()):
        if row.get("approved") is not False or row.get("publicationAllowed") is not False:
            raise ValueError("unexpected approval")
    evidence={uid:observed_evidence(p,day) for uid,p in music.items()}
    output=[]
    for uid,b in sorted(base.items()):
        state=b.get("decision")
        reasons=b.get("blockingReasons")
        if state not in BASE_STATES or not isinstance(reasons,list) or any(not isinstance(x,str) for x in reasons):
            raise ValueError("invalid V2 decision")
        sha=b.get("streamSha256")
        if sha is not None and (not isinstance(sha,str) or not SHA256_RE.fullmatch(sha)):
            raise ValueError("invalid stream digest")
        p=music.get(uid,{})
        bound=bool(sha and p.get("matchesDecisionStream") is True and p.get("streamSha256")==sha)
        e=evidence.get(uid) if bound else None
        status="no_bound_programme_evidence"
        corroborated=0
        if e:
            s=e["sourceHints"]
            corroborated=sum(s.get(k,0) for k in CORROBORATED)
            pairs=e["pairHints"]
            if any(s.get(k,0) for k in CONFLICTS):
                status="source_conflict"
            elif pairs["mixed_hint"] or (pairs["target_hint"] and pairs["other_hint"]):
                status="mixed_observed_hints"
            elif pairs["target_hint"]:
                status="target_observed_hints"
            elif pairs["other_hint"]:
                status="other_genre_observed_hints"
            elif e["distinctArtistTitleHints"]:
                status="unclassified_observations"
            else:
                status="no_observed_music"
        next_actions=[]
        # Preserve all V2 blocks, including duplicate and technical concerns.
        # A mixed observation triggers contextual review, not exclusion.
        if state in ("already_known","identity_review","source_recheck"):
            shadow=state
        elif status=="source_conflict":
            shadow="programme_conflict_review"
            next_actions.append("resolve_music_source_conflict")
        elif state=="ready_for_staging_review":
            if reasons or not all(b.get(k) is True for k in ("editorialMatch","broadcasterStreamLink","programmeScopeEvidence","continuityIndication")):
                raise ValueError("inconsistent V2 staging decision")
            days=dates(b.get("positiveContinuityDays"),day)
            if len(days)<2 or day not in days:
                raise ValueError("inconsistent V2 continuity")
            if status=="target_observed_hints":
                shadow="declared_and_observed_target_review"
            elif status in ("mixed_observed_hints","other_genre_observed_hints"):
                shadow="programme_context_review"
                next_actions.append("compare_observed_and_declared_programme")
            else:
                shadow="declared_format_review"
                next_actions.append("collect_more_programme_observations")
        elif status in ("target_observed_hints","mixed_observed_hints"):
            shadow="observed_music_candidate"
            next_actions.append("resolve_remaining_station_and_technical_gates")
        elif status=="other_genre_observed_hints":
            shadow="programme_context_review"
            next_actions.append("compare_observed_and_declared_programme")
        else:
            shadow=state
            next_actions.append("collect_more_programme_observations")
        output.append({"stationuuid":uid,"streamSha256":sha,
                       "v2Decision":state,"shadowDecision":shadow,
                       "v2BlockingReasons":list(reasons),"nextActions":next_actions,
                       "programmeEvidenceStatus":status,"programmeBound":bound,
                       "programmeEvidence":e,"crossSourcePairHintCount":corroborated,
                       "stationEditorialHint":b.get("editorialMatch") is True,
                       "broadcasterStreamLink":b.get("broadcasterStreamLink") is True,
                       "programmeScopeHint":b.get("programmeScopeEvidence") is True,
                       "continuityHint":b.get("continuityIndication") is True,
                       "logoDecodedHint":b.get("logoDecodedHint") is True,
                       "verifiedArtistCount":0,"approved":False,"publicationAllowed":False})
    return {"schemaVersion":1,"policyVersion":VERSION,"basePolicyVersion":BASE_POLICY,
            "scanDate":day,"catalogBaselineSha256":baseline,"publicationAllowed":False,
            "approvedCount":0,"verifiedArtistCount":0,"stationCount":len(output),
            "unmatchedProgrammeCount":len(set(music)-set(base)),
            "counts":dict(sorted(Counter(x["shadowDecision"] for x in output).items())),
            "programmeEvidenceCounts":dict(sorted(Counter(x["programmeEvidenceStatus"] for x in output).items())),
            "records":output}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("decisions","programme","output"):
        p.add_argument("--"+name,required=True,type=Path)
    p.add_argument("--baseline-sha256",required=True)
    a=p.parse_args()
    def load(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize V3 input")
        return json.loads(path.read_text("utf-8"))
    result=evaluate(load(a.decisions),load(a.programme),a.baseline_sha256)
    payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize V3 output")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_QUALIFICATION_V3_SHADOW_ONLY",{k:v for k,v in result.items() if k!="records"})

if __name__=="__main__":
    main()
