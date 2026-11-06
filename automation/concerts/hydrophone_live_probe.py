#!/usr/bin/env python3
"""Hydrophone collector live read-only smoke; exact public reference comparison.

After PR #95, inspect the full official homepage / À venir instead of the truncated agenda.
"""
import json,os
from pathlib import Path
import discover

ROOT=Path(__file__).resolve().parent
def main():
    sources=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
    selected=[x for x in sources["venues"] if x.get("id")=="venue-source-011"]
    if len(selected)!=1 or selected[0].get("adapter")!="hydrophone_spip_review":
        raise ValueError("Hydrophone not enabled in P1 venue watch")
    ref=discover.json_url(discover.CATALOG)
    if not isinstance(ref.get("events"),list):raise ValueError("Public reference missing")
    reports=[]
    rows=discover.scan_venues({"venues":selected},
                              discover.make_known_keys(ref),
                              discover.today_fr(),reports)
    info=reports[0].get("adapterDiagnostic") or {}
    observed=[x for x in rows if
              x.get("source")=="hydrophone_first_party_agenda_detail_ticket_year"]
    if any(x.get("publicationAllowed") is not False or
           x.get("reviewRequired") is not True or
           not x.get("yearEvidence") for x in observed):
        raise ValueError("Unsafe output or unproved year")
    result={"source":"Hydrophone","sourceError":reports[0].get("error"),
       "agendaCards":info.get("agendaCards",0),
       "festivalAndNonconcertFiltered":info.get("festivalAndNonconcertFiltered",0),
       "yearUnverifiedCards":info.get("yearUnverifiedCards",0),
       "detailPagesRead":info.get("detailPagesRead",0),
       "detailErrors":info.get("detailErrors",0),
       "datedGenreLeads":info.get("datedGenreLeads",0),
       "existing":info.get("alreadyLikelyPublished",0),
       "publicationAllowed":False,
       "leads":[{"title":x["name"],"date":x["date"],"start":x["localTime"],
                 "officialUrl":x["sourceUrl"],"proof":x["yearEvidence"],
                 "existing":x.get("possibleExistingConcert")} for x in observed]}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY","/dev/null"),
              "a",encoding="utf-8") as s:
        s.write("### Hydrophone — test du collecteur, sans publication\n\n")
        for key,val in result.items():
            if key!="leads":s.write(f"- {key}: {val}\n")
        for x in result["leads"]:
            s.write(f"- {x['date']} : {x['title']}, {x['start']} — "
                    f"{'déjà présent' if x['existing'] else 'à approuver'}\n")
    if result["sourceError"] or result["detailErrors"]:
        print("::warning title=Collecte Hydrophone incomplète::Contrôler logs et structure DOM.")
    if not result["datedGenreLeads"]:
        print("::warning title=Hydrophone aucun lead daté::Ne pas publier.")
if __name__=="__main__":main()
