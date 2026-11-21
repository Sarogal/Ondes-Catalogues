"""Entrée GitHub Actions. Ne déploie rien : le workflow décide après validation."""
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from merge_policy import merge,ORIGIN
from private_intake import latest
from ptitesondes_open_world_patch_bridge import merge_verified_open_world

CATALOGUE=Path("docs/ptitesondes/sorties.json")
REPORT=Path("/tmp/ptitesondes-sync-report.json")

def public_summary(report):
    """Résumé agrégé uniquement : aucune piste privée ni motif détaillé dans Actions."""
    counts=report.get("open_world_counts",{})
    extra=(
        f"- Dossiers nationaux présentés : {counts['research_dossiers']}\\n"
        f"- Dossiers recontrôlés pour fusion : {counts['reviewed_for_merge']}\\n"
        f"- Dossiers maintenus en vérification : {counts['held_for_independent_review']}\\n"
        if counts else "")
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
            "held_for_independent_review":bridge["held"]}
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
