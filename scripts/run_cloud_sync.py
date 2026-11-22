"""Entrée GitHub Actions. Ne déploie rien : le workflow décide après validation."""
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from merge_policy import merge,ORIGIN
from private_intake import latest
from ptitesondes_open_world_patch_bridge import (
    merge_verified_open_world, PUBLIC_REHEARSAL_REASONS,
)

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
}) | frozenset("rehearsal_" + code for code in PUBLIC_REHEARSAL_REASONS)


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
        if counts else "")
    blockers = redacted_blocker_counts(counts.get("reason_counts", {}))
    if blockers:
        extra += "\nMotifs de retenue (agrégés, sans identité privée) :\n"
        extra += "".join(
            f"- {reason} : {count}\n"
            for reason, count in blockers.items())
    if counts and counts.get("research_dossiers") == 0:
        extra += "- Aucun dossier national transmis au Publisher pour ce passage.\n"
    return (
        "### P'tites Ondes — contrôle de publication\n\n"
        f"- Catalogue avant : {report['initial']}\n"
        f"- Catalogue simulé : {report['final']}\n"
        f"- Nouvelles fiches conformes : {report['ajoutes']}\n"
        f"- Propositions différées : {len(report['attente'])}\n"
        +extra
        +"- Le déploiement est décidé séparément par le workflow.\n"
    )


def main():
    secret=os.getenv("PRIVATE_INTAKE_READ_TOKEN","")
    if not secret:
        raise RuntimeError("PRIVATE_INTAKE_READ_TOKEN absent : publication bloquée")
    today=datetime.now(ZoneInfo("Europe/Paris")).date()
    req=Request(ORIGIN,headers={"User-Agent":"OndesCatalogues/1.0","Accept":"application/json"})
    with urlopen(req,timeout=30) as response:
        data=response.read(9_000_001)
    if len(data)>9_000_000:raise ValueError("Production trop volumineuse")
    reference=json.loads(data.decode("utf-8-sig"))
    current=json.loads(CATALOGUE.read_text(encoding="utf-8"))
    patch,path=latest(secret,today)
    if "open_world_research" in patch:
        # A private research dossier never grants verification. The bridge
        # re-reads OpenAgenda, DILA, municipal events and independent GPS.
        candidate,report,bridge=merge_verified_open_world(
            reference,current,patch,today,
            os.getenv("OPENAGENDA_READ_KEY",""))
        report["open_world_counts"]={
            "research_dossiers":bridge["dossiers"],
            "reviewed_for_merge":bridge["admitted_to_merge"],
            "held_for_independent_review":bridge["held"],
            "reason_counts":redacted_blocker_counts(
                bridge.get("held_reason_counts", {}))}
    else:
        candidate,report=merge(reference,current,patch,today)
    report["patch"]=path
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    changed=bool(report["ajoutes"])
    if changed:
        CATALOGUE.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    output=os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output,"a",encoding="utf-8") as file:
            file.write("changed="+str(changed).lower()+"\n")
    print("Catalogue :",report["initial"],"->",report["final"],
          " | admis :",report["ajoutes"]," | en attente :",len(report["attente"]))
    # Ne jamais exposer les IDs et motifs privés dans les journaux publics.
    summary_path=os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path,"a",encoding="utf-8") as summary:
            summary.write(public_summary(report))
    print("Aucune suppression ni correction automatique.")

if __name__=="__main__":
    main()
