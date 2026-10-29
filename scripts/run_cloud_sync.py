"""Entrée GitHub Actions. Ne déploie rien : le workflow décide après validation."""
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from merge_policy import merge,ORIGIN
from private_intake import latest

CATALOGUE=Path("docs/ptitesondes/sorties.json")
REPORT=Path("/tmp/ptitesondes-sync-report.json")

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
    print("Aucune suppression ni correction automatique.")

if __name__=="__main__":
    main()
