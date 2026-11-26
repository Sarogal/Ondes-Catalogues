"""Entrée GitHub Actions. Ne déploie rien : le workflow décide après validation."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from merge_policy import merge,ORIGIN
from private_intake import latest
from ptitesondes_historical_gps_cloud import LEDGER_PATH, prepare_cloud_repairs
from ptitesondes_historical_gps_ledger import reconcile
from ptitesondes_open_world_patch_bridge import (
    merge_verified_open_world, PUBLIC_REHEARSAL_REASONS,
)
from ptitesondes_oa_first_party_admission import PUBLIC_OA_DIRECT_REASONS

# All statuses are internal, fixed codes. Unknown values collapse into one
# aggregate and can never disclose source URLs, venue names or private IDs.
PUBLIC_INTAKE_REASONS = frozenset({
    "venue_research_identity_missing",
    "independent_municipal_domain_unverified",
    "independent_municipal_source_delegation_missing",
    "independent_municipal_source_delegation_unconfirmed",
    "live_oa_gps_invalid_or_partial",
    "fresh_independent_venue_proof_missing",
    "source_provider_unavailable_or_invalid",
    "duplicate_private_open_world_id",
    "openagenda_public_read_key_unavailable",
    "live_publisher_evidence_not_confirmed",
}) | PUBLIC_OA_DIRECT_REASONS | frozenset(
    "rehearsal_" + code for code in PUBLIC_REHEARSAL_REASONS)


def redacted_blocker_counts(value):
    if not isinstance(value, dict):
        return {}
    summarized = {}
    other = 0
    for reason, count in value.items():
        if type(count) is not int or count < 0:
            continue
        if reason in PUBLIC_INTAKE_REASONS:
            summarized[reason] = summarized.get(reason, 0) + count
        else:
            other += count
    if other:
        summarized["other_private_reason"] = other
    return dict(sorted(summarized.items()))

CATALOGUE=Path("docs/ptitesondes/sorties.json")
REPORT=Path("/tmp/ptitesondes-sync-report.json")

def public_summary(report):
    """Résumé agrégé uniquement : aucune piste privée ni motif détaillé dans Actions."""
    counts=report.get("open_world_counts",{})
    extra=(
        f"- Dossiers nationaux présentés : {counts['research_dossiers']}\n"
        f"- Dossiers recontrôlés pour fusion : {counts['reviewed_for_merge']}\n"
        f"- Dossiers maintenus en vérification : {counts['held_for_independent_review']}\n"
        f"- Séances expirées ignorées en sécurité : {counts.get('expired_dossiers_skipped', 0)}\n"
        f"- Occurrences déjà publiées ignorées avant relecture : {counts.get('already_published_dossiers_skipped', 0)}\n"
        if counts else "")
    blockers = redacted_blocker_counts(counts.get("reason_counts", {}))
    if blockers:
        extra += "\nMotifs de retenue (agrégés, sans identité privée) :\n"
        extra += "".join(
            f"- {reason} : {count}\n"
            for reason, count in blockers.items())
    gps = report.get("gps_research_counts", {})
    if isinstance(gps, dict):
        for name in ("checkpoint_missing", "candidate_groups", "examined_groups",
                     "source_reads", "proposed_count", "fresh_proof_missing_or_changed",
                     "event_identity_unconfirmed"):
            count = gps.get(name)
            if type(count) is int and 0 <= count <= 100000:
                extra += f"- GPS {name} : {count}\n"
    if counts and counts.get("research_dossiers") == 0:
        extra += "- Aucun dossier national transmis au Publisher pour ce passage.\n"
    return (
        "### P'tites Ondes — contrôle de publication\n\n"
        f"- Catalogue avant : {report['initial']}\n"
        f"- Catalogue simulé : {report['final']}\n"
        f"- Nouvelles fiches conformes : {report['ajoutes']}\n"
        f"- Corrections GPS historiques vérifiées : {report.get('correction', 0)}\n"
        f"- Recherche GPS différée : {report.get('gps_research_deferred', False)}\n"
        f"- Propositions différées : {len(report['attente'])}\n"
        +extra
        +"- Le déploiement est décidé séparément par le workflow.\n"
    )


def main():
    secret=os.getenv("PRIVATE_INTAKE_READ_TOKEN","")
    if not secret:
        raise RuntimeError("PRIVATE_INTAKE_READ_TOKEN absent : publication bloquée")
    as_of_utc=datetime.now(timezone.utc)
    today=as_of_utc.astimezone(ZoneInfo("Europe/Paris")).date()
    req=Request(ORIGIN,headers={"User-Agent":"OndesCatalogues/1.0","Accept":"application/json"})
    with urlopen(req,timeout=30) as response:
        data=response.read(9_000_001)
    if len(data)>9_000_000:raise ValueError("Production trop volumineuse")
    reference=json.loads(data.decode("utf-8-sig"))
    current=json.loads(CATALOGUE.read_text(encoding="utf-8"))
    ledger=json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    effective_reference=reconcile(reference,current,ledger)
    patch,path=latest(secret,today)
    if "open_world_research" in patch:
        # A private research dossier never grants verification. The bridge
        # re-reads OpenAgenda, DILA, municipal events and independent GPS.
        candidate,report,bridge=merge_verified_open_world(
            effective_reference,current,patch,today,
            os.getenv("OPENAGENDA_READ_KEY",""),
            as_of_utc=as_of_utc)
        report["open_world_counts"]={
            "research_dossiers":bridge["dossiers"],
            "reviewed_for_merge":bridge["admitted_to_merge"],
            "held_for_independent_review":bridge["held"],
            "expired_dossiers_skipped":bridge.get("expired_dossiers_skipped", 0),
            "already_published_dossiers_skipped":bridge.get("already_published_dossiers_skipped", 0),
            "reason_counts":redacted_blocker_counts(
                bridge.get("held_reason_counts", {}))}
    else:
        candidate,report=merge(effective_reference,current,patch,today)
    # A fresh historical correction is separate from private patch updates.
    # Failure of optional geographic research must not lose valid additions.
    gps_counts={}
    try:
        corrected,new_ledger,count=prepare_cloud_repairs(
            reference,candidate,ledger,today,secret,diagnostics=gps_counts)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError, RecursionError, OverflowError):
        corrected,new_ledger,count=candidate,ledger,0
        report["gps_research_deferred"]=True
    else:
        report["gps_research_deferred"]=False
    report["gps_research_counts"]=gps_counts
    report["correction"]=count
    if count:
        candidate=corrected
        candidate["updated_at"]=as_of_utc.astimezone(ZoneInfo("Europe/Paris")).isoformat(timespec="seconds")
        LEDGER_PATH.write_text(json.dumps(new_ledger,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report["patch"]=path
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    changed=bool(report["ajoutes"] or report["correction"])
    if changed:
        CATALOGUE.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    output=os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output,"a",encoding="utf-8") as file:
            file.write("changed="+str(changed).lower()+"\n")
    print("Catalogue :",report["initial"],"->",report["final"],
          " | admis :",report["ajoutes"]," | en attente :",len(report["attente"]))
    # Safe diagnostic counters are needed even when GitHub's rich job
    # summary cannot be read by external monitoring. The helper exposes
    # only fixed, preapproved reason codes and counts, never a private
    # event ID, organizer name, URL, title or venue.
    print(public_summary(report).rstrip())
    # Ne jamais exposer les IDs et motifs privés dans les journaux publics.
    summary_path=os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path,"a",encoding="utf-8") as summary:
            summary.write(public_summary(report))
    print("Aucune suppression; corrections GPS historiques vérifiées :", report["correction"])

if __name__=="__main__":
    main()
