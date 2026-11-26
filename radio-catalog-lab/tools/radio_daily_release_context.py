"""Prepare a verified release context and compatible evidence in one operation.

The production/test pointer is never written. The CLI currently uses the
pinned v8 bootstrap; successor handling is available to the offline harness
with an explicit verified previous snapshot and complete maintenance state.
"""
import argparse
from pathlib import Path
from radio_daily_baseline_selection import select
from radio_daily_state_migration import migrate
from radio_daily_baseline_verify import KEY_ID, PUBLIC_KEY, strict_json
from radio_daily_v9_generator import BASELINE, encode, load_bytes
from radio_stream_recheck_ledger import parse_day

STATE_FILES={
    "maintenance":"maintenance-preview.json",
    "logo":"logo-maintenance-preview.json",
    "missing":"missing-logo-preview.json",
    "status":"status-transition-preview.json",
    "repair":"repair-preview.json",
    "confirmation":"repair-confirmation-preview.json",
}
MIGRATED_FILES={
    "maintenance":"maintenance-preview.json",
    "logoMaintenance":"logo-maintenance-preview.json",
    "missingLogo":"missing-logo-preview.json",
    "status":"status-transition-preview.json",
    "repair":"repair-preview.json",
    "confirmation":"repair-confirmation-preview.json",
    "repairPlan":"repair-plan-preview.json",
}
# These reports must be freshly reconciled, not blindly rebound.
REQUALIFY=("qualification-dossiers.json","decision-preview.json","qualification-v3-preview.json")


def prepare(pointer,fetch_body,*,day,state=None,prior_pointer=None,prior_body=None,
            expected_sha=BASELINE,expected_sequence=8,public_key=PUBLIC_KEY,key_id=KEY_ID):
    day=parse_day(day)
    anchor=dict(expected_sha=expected_sha,expected_sequence=expected_sequence,public_key=public_key,key_id=key_id)
    raw,selected=select(pointer,fetch_body,prior_pointer=prior_pointer,prior_body=prior_body,**anchor)
    if state is None:
        state={}
    if set(state)-set(STATE_FILES):
        raise ValueError("unexpected maintenance state input")
    for name,report in state.items():
        if (not isinstance(report,dict) or report.get("schemaVersion")!=1
                or report.get("publicationAllowed") is not False
                or report.get("catalogBaselineSha256")!=expected_sha
                or parse_day(report.get("scanDate"))>day):
            raise ValueError("incompatible release context evidence: "+name)
    migration=None
    migrated={}
    if selected["advanced"]:
        if set(state)!=set(STATE_FILES):
            raise ValueError("complete predecessor evidence required for migration")
        next_anchor=dict(anchor,expected_sha=selected["selectedSha256"],
                         expected_sequence=selected["selectedSequence"])
        result=migrate(prior_pointer,prior_body,pointer,raw,old_anchor=anchor,new_anchor=next_anchor,
                       day=day,**state)
        migration=result["migration"]
        migrated={filename:result[key] for key,filename in MIGRATED_FILES.items()}
    context={"schemaVersion":1,"publicationAllowed":False,"scanDate":day,
             "selectedSequence":selected["selectedSequence"],"selectedSha256":selected["selectedSha256"],
             "previousSequence":expected_sequence,"previousSha256":expected_sha,
             "signatureVerified":True,"advanced":selected["advanced"],
             "stateMode":"migrated" if selected["advanced"] else "unchanged",
             "stateReportsChecked":len(state),"migratedFiles":sorted(migrated),
             "qualificationReportsToRebuild":list(REQUALIFY) if selected["advanced"] else [],
             "migration":migration}
    return raw,selected,migrated,context


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("pointer","baseline","previous-dir","report","selection-report"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--day",required=True)
    a=p.parse_args()
    if a.pointer.stat().st_size>16384 or a.baseline.stat().st_size>10485760:
        raise ValueError("oversize signed material")
    if a.report.exists() or a.selection_report.exists():
        raise ValueError("fresh context reports required")
    state={key:strict_json(load_bytes(a.previous_dir/filename)) for key,filename in STATE_FILES.items()
           if (a.previous_dir/filename).is_file()}
    raw,selected,migrated,context=prepare(a.pointer.read_bytes(),lambda path,length:a.baseline.read_bytes(),
                                          day=a.day,state=state)
    if migrated:
        raise ValueError("pinned workflow may not advance")
    a.selection_report.write_bytes(encode(selected))
    a.report.write_bytes(encode(context))
    print("RADIO_SIGNED_RELEASE_CONTEXT",context)

if __name__=="__main__":
    main()
