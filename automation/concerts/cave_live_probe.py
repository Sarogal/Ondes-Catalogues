#!/usr/bin/env python3
"""One venue only: official Cave aux Poètes extraction diagnostics. NO publish."""
import json,os
from pathlib import Path
import discover

ROOT=Path(__file__).resolve().parent

def main():
    settings=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
    venues=[v for v in settings["venues"] if v["id"]=="venue-source-017"]
    if len(venues)!=1 or venues[0].get("adapter")!="cave_poetes_first_party_detail":
        raise ValueError("Cave official adapter config missing or repeated")
    catalogue=discover.json_url(discover.CATALOG)
    if catalogue.get("schemaVersion")!=1:
        raise ValueError("Public concert source unavailable")
    logs=[]
    leads=discover.scan_venues({"venues":venues},discover.make_known_keys(catalogue),
                              discover.today_fr(),logs)
    stats=logs[0].get("adapterDiagnostic") or {}
    rows=[{"name":r["name"],"date":r["date"],"url":r["sourceUrl"],
           "alreadyPossible":bool(r.get("possibleExistingConcert")),
           "classification":r.get("classification",[])}
          for r in leads if r.get("source")=="agenda_officiel_cave_poetes_detail"]
    if any(r["publicationAllowed"] is not False or r["reviewRequired"] is not True
           for r in leads):
        raise ValueError("Candidate permitted to publish without independent review")
    payload={
        "source":"La Cave aux Poètes",
        "accessible":not bool(logs[0].get("error")),
        "cardsFound":stats.get("eventLinksFound",0),
        "detailPagesRead":stats.get("detailPagesRead",0),
        "datedGenreLeads":stats.get("datedGenreLeads",0),
        "alreadyPossible":stats.get("possibleExisting",0),
        "newUnapproved":sum(not x["alreadyPossible"] for x in rows),
        "sourceErrorType":logs[0].get("error","").split(":",1)[0] or None,
        "publicationAllowed":False,
        "leads":rows
    }
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY","/dev/null"),"a",
              encoding="utf-8") as out:
        out.write("### La Cave aux Poètes — collecte officielle sans publication\n\n")
        for k in ("accessible","cardsFound","detailPagesRead","datedGenreLeads",
                  "alreadyPossible","newUnapproved","sourceErrorType"):
            out.write(f"- {k}: {payload[k]}\n")
        for item in rows:
            out.write(f"- {item['date']} — {item['name']} — "
                      f"{'doublon possible' if item['alreadyPossible'] else 'à revérifier'} — "
                      f"{item['url']}\n")
    if not payload["accessible"]:
        print("::warning title=Source inaccessible::Aucune publication.")
    if not payload["detailPagesRead"]:
        print("::warning title=Aucune page événement lue::Vérifier robots et HTML.")
if __name__=="__main__":
    main()
