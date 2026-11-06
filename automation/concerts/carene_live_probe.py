#!/usr/bin/env python3
"""Live one-venue La Carène probe: no autoapprove, no public writes."""
import json,os
from pathlib import Path
import discover

ROOT=Path(__file__).resolve().parent
ID="venue-source-010"

def main():
    sources=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
    selected=[s for s in sources.get("venues",[]) if s.get("id")==ID]
    if len(selected)!=1 or selected[0].get("adapter")!="carene_spip_official_detail":
        raise ValueError("La Carène official adapter missing/ambiguous")
    current=discover.json_url(discover.CATALOG)
    if not isinstance(current.get("events"),list):
        raise ValueError("Unable to load actual public reference")
    reports=[]
    events=discover.scan_venues({"venues":selected},
                               discover.make_known_keys(current),
                               discover.today_fr(),reports)
    details=reports[0].get("adapterDiagnostic") or {}
    valid=[e for e in events if e.get("source")=="agenda_officiel_carene_detail"]
    if any(x.get("reviewRequired") is not True or
           x.get("publicationAllowed") is not False for x in valid):
        raise ValueError("Unsafe candidate authorization")
    results={
        "venue":"La Carène","sourceAccessible":not bool(reports[0].get("error")),
        "agendaPagesRead":details.get("agendaPagesRead",0),
        "agendaErrors":details.get("agendaErrors",0),
        "datedLinks":details.get("datedLinks",0),
        "festivalAndCanceledFiltered":details.get("festivalAndCanceledFiltered",0),
        "detailPagesRead":details.get("detailPagesRead",0),
        "detailErrors":details.get("detailErrors",0),
        "datedGenreLeads":details.get("datedGenreLeads",0),
        "alreadyLikelyPublished":details.get("alreadyLikelyPublished",0),
        "newUnapproved":sum(not e.get("possibleExistingConcert") for e in valid),
        "errorType":str(reports[0].get("error") or "").split(":",1)[0] or None,
        "publicationAllowed":False,
        "leads":[{"name":e["name"],"date":e["date"],"url":e["sourceUrl"],
                  "genre":e.get("classification"),
                  "possibleDuplicate":bool(e.get("possibleExistingConcert"))}
                 for e in valid],
    }
    print(json.dumps(results,ensure_ascii=False,indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY","/dev/null"),
              "a",encoding="utf-8") as report:
        report.write("### La Carène — premier contrôle du collecteur réel\n\n")
        for key,value in results.items():
            if key!="leads":report.write(f"- {key}: {value}\n")
        report.write("\n")
        for row in results["leads"]:
            report.write(f"- {row['date']} : {row['name']} — "
                         f"{'déjà possible' if row['possibleDuplicate'] else 'nouveau à revoir'} "
                         f"({row['url']})\n")
    if not results["sourceAccessible"]:
        print("::warning title=Source La Carène inaccessible::Aucune publication.")
    elif not results["datedGenreLeads"]:
        print("::warning title=La Carène : aucun résultat::Examiner la structure HTML et les critères stricts.")
if __name__=="__main__":main()
