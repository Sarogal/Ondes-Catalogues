#!/usr/bin/env python3
"""Atabal-only first-party live test. Private outputs; NO approvals or publishing."""
from __future__ import annotations
import json,os
from pathlib import Path
import discover

ROOT=Path(__file__).resolve().parent

def main():
    sources=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
    rows=[x for x in sources["venues"] if x["id"]=="venue-source-026"]
    if len(rows)!=1 or rows[0].get("adapter")!="atabal_official_detail":
        raise ValueError("Missing exact Atabal source")
    catalogue=discover.json_url(discover.CATALOG)
    if not isinstance(catalogue.get("events"),list):
        raise ValueError("Current public catalog not readable")
    checks=[]
    items=discover.scan_venues({"venues":rows},
                              discover.make_known_keys(catalogue),
                              discover.today_fr(),checks)
    leads=[x for x in items if x.get("source")=="agenda_officiel_atabal_detail"]
    if any(x.get("publicationAllowed") is not False or
           x.get("reviewRequired") is not True for x in leads):
        raise ValueError("Unsafe lead published or not quarantined")
    stat=checks[0].get("adapterDiagnostic") or {}
    result={"source":"Atabal Biarritz",
            "accessible":not bool(checks[0].get("error")),
            "eventLinksFound":stat.get("eventLinksFound",0),
            "detailPagesRead":stat.get("detailPagesRead",0),
            "detailErrors":stat.get("detailErrors",0),
            "datedGenreLeads":stat.get("datedGenreLeads",0),
            "alreadyPossible":stat.get("alreadyLikelyPublished",0),
            "newUnapproved":sum(not v.get("possibleExistingConcert") for v in leads),
            "sourceErrorType":str(checks[0].get("error") or "").split(":",1)[0] or None,
            "publicationAllowed":False,
            "leads":[{"name":x["name"],"date":x["date"],
                      "genre":x["classification"],"time":x["localTime"],
                      "url":x["sourceUrl"],
                      "possibleDuplicate":bool(x["possibleExistingConcert"])}
                     for x in leads]}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY","/dev/null"),
              "a",encoding="utf-8") as report:
        report.write("### Atabal Biarritz — essai officiel sans publication\n\n")
        for k,v in result.items():
            if k!="leads":report.write(f"- {k}: {v}\n")
        report.write("\n")
        for row in result["leads"]:
            report.write(f"- {row['date']} : {row['name']} "
                         f"({row['genre']}) — "
                         f"{'doublon possible' if row['possibleDuplicate'] else 'à valider'}"
                         f" — {row['url']}\n")
    if not result["accessible"]:
        print("::warning title=Atabal indisponible::Source officielle inaccessible.")
    elif not result["datedGenreLeads"]:
        print("::warning title=Atabal : aucune fiche métal ou punk::Contrôler les sélecteurs.")
if __name__=="__main__":
    main()
