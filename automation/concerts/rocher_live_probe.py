#!/usr/bin/env python3
"""Run one bounded official Rocher de Palmer discovery probe (read-only)."""
from __future__ import annotations

import json
from pathlib import Path
import discover

HERE=Path(__file__).resolve().parent


def main():
    sources=json.loads((HERE/"sources.json").read_text(encoding="utf-8"))
    selected=[v for v in sources.get("venues",[])
              if v.get("id")=="regional-33-rocher-de-palmer"]
    if len(selected)!=1 or selected[0].get("adapter")!="rocher_palmer_official_detail":
        raise ValueError("Official Rocher collector not enabled exactly once")
    catalogue=discover.json_url(discover.CATALOG)
    if not isinstance(catalogue.get("events"),list):
        raise ValueError("Current cloud catalogue missing")
    checks=[]
    selected[0]=dict(selected[0],maxDetailPagesPerRun=6,maxAgendaPagesPerRun=2)
    candidates=discover.scan_venues({"venues":selected},
                                    discover.make_known_keys(catalogue),
                                    discover.today_fr(),checks)
    line=checks[0]
    stats=line.get("adapterDiagnostic") or {}
    out={
        "venue":"Le Rocher de Palmer",
        "officialAgenda":selected[0]["url"],
        "sourceAccessible":not bool(line.get("error")),
        "agendaPagesRead":stats.get("agendaPagesRead",0),
        "detailPagesRead":stats.get("detailPagesRead",0),
        "datedGenreLeads":stats.get("datedGenreLeads",0),
        "possibleExistingConcerts":sum(bool(c.get("possibleExistingConcert")) for c in candidates),
        "newUnapprovedLeads":sum(not c.get("possibleExistingConcert") for c in candidates),
        "sourceErrorType":(line["error"].split(":",1)[0] if line.get("error") else None),
        "publicationAllowed":False,
        "notes":"Diagnostic technique, sans approbation ni écriture au catalogue."
    }
    if any(c.get("publicationAllowed") is not False or c.get("reviewRequired") is not True
           for c in candidates):
        raise ValueError("Non-quarantined candidate returned by probe")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    summary=Path(__import__("os").environ.get("GITHUB_STEP_SUMMARY", "/dev/null"))
    with summary.open("a",encoding="utf-8") as f:
        f.write("### Rocher de Palmer — premier essai réel\n\n")
        for key in ("sourceAccessible","agendaPagesRead","detailPagesRead",
                    "datedGenreLeads","possibleExistingConcerts","newUnapprovedLeads",
                    "sourceErrorType","publicationAllowed"):
            f.write(f"- {key}: {out[key]}\n")
    if not out["sourceAccessible"]:
        print("::warning title=Rocher de Palmer inaccessible::Aucune piste publiée ; consulter le statut de source.")
    elif not out["detailPagesRead"]:
        print("::warning title=Rocher de Palmer sans fiche::Vérifier robots.txt, HTML et rotation des pages.")
    elif not out["datedGenreLeads"]:
        print("::warning title=Rocher de Palmer : aucun lead qualifié::Adapter ou échantillonnage à revoir.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
