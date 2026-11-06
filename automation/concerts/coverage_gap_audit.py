#!/usr/bin/env python3
"""Private, read-only gap analysis for Grosses Ondes concert discovery."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import triage
from review_batches import region_of

ROOT = Path(__file__).resolve().parent
CATALOG = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json"
HELD = {"possible_duplicate", "festival_overlap_review", "cancellation_watch",
        "excluded_nonconcert", "undated_lead"}

def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+", value.encode("ascii", "ignore").decode()))

def date_iso(value):
    if not isinstance(value, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}",value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None

def public_url(value):
    if not isinstance(value,str):
        return None
    try:
        u=urlsplit(value)
        if u.scheme!="https" or not u.hostname or u.username or u.password or u.port:
            return None
        return urlunsplit(("https",u.hostname.lower(),u.path,"",""))
    except ValueError:
        return None

def individual_official(candidate):
    source = str(candidate.get("source") or "").lower()
    url = public_url(candidate.get("sourceUrl")) or ""
    path = urlsplit(url).path.rstrip("/")
    generic = path in ("", "/", "/agenda", "/nos-evenements", "/programmation")
    return (not generic and "multi_event.php" not in path and
            any(x in source for x in ("agenda_officiel", "official_detail",
                                       "fiche_officielle", "salle_officielle")))

def evaluate(catalogue, registry, sources, national, today):
    if not isinstance(catalogue,dict) or not all(isinstance(catalogue.get(x),list)
            for x in ("events","venues","artists")):
        raise ValueError("Catalogue public absent ou invalide")
    if registry.get("schema")!="grossesondes.concert.intake.v1" or not isinstance(registry.get("items"),dict):
        raise ValueError("Registre privé de pistes invalide")
    if sources.get("schema")!="grossesondes.concert.sourcelist.v1" or not isinstance(sources.get("venues"),list):
        raise ValueError("Sources de veille non conformes")
    if national.get("schema")!="grossesondes.concert.venues.v1" or not isinstance(national.get("venues"),list):
        raise ValueError("Registre national invalide")
    catalogue_venues={v["id"]:v for v in catalogue["venues"]}
    future=[e for e in catalogue["events"]
            if date_iso(e.get("date")) and date_iso(e.get("date"))>=today]
    regions=Counter(catalogue_venues.get(e.get("venueId"),{}).get("region","inconnue") for e in future)
    months=Counter(e["date"][:7] for e in future)
    index=triage.catalogue_index(catalogue)
    quarantined=Counter()
    leads=[]
    seen=set()
    for record in registry["items"].values():
        if not isinstance(record,dict) or record.get("status") in ("rejected","superseded"):
            quarantined["rejected_or_invalid"]+=1
            continue
        candidate=record.get("candidate")
        if not isinstance(candidate,dict):
            quarantined["invalid_candidate"]+=1
            continue
        day=date_iso(candidate.get("date"))
        if not day or day<today:
            quarantined["undated_or_past"]+=1
            continue
        classified=triage.triage(candidate,index=index)
        bucket=classified["reviewBucket"]
        if bucket in HELD or bucket not in ("genre_tag_review","genre_unknown"):
            quarantined[bucket]+=1
            continue
        name=candidate.get("name") or candidate.get("leadArtist") or ""
        key=(day.isoformat(),norm(candidate.get("city")),norm(candidate.get("venue")),
             norm(candidate.get("leadArtist") or name))
        if key in seen:
            quarantined["duplicate_lead"]+=1
            continue
        seen.add(key)
        has_genre=bucket=="genre_tag_review"
        official=individual_official(candidate)
        third_party=bool(candidate.get("thirdPartyOnly")) or "ticketmaster" in str(candidate.get("source","")).lower()
        score=(6 if has_genre else 0)+(3 if official else 0)-(2 if third_party else 0)
        if (day.year-today.year)*12+day.month-today.month>=4:
            score+=1
        leads.append({
            "date":day.isoformat(),"name":str(name),
            "venue":str(candidate.get("venue") or ""),"city":str(candidate.get("city") or ""),
            "department":str(candidate.get("department") or ""),
            "region":region_of(candidate.get("department")),
            "sourceUrl":public_url(candidate.get("sourceUrl")),
            "sourceKind":str(candidate.get("source") or ""),
            "tier":"genre_documented" if has_genre else "genre_to_verify",
            "individualOfficialLead":bool(official),"reviewScore":score,
            "publicationAllowed":False,"reviewRequired":True})
    # Keep documented genres ahead of unknowns, then select scarce regions
    # before prolific ones. Otherwise the first 100 leads can be consumed
    # by major cities and the regional batcher never sees the gaps.
    leads.sort(key=lambda x:(
        0 if x["tier"]=="genre_documented" else 1,
        regions.get(x["region"],0) if x["region"]!="Autres régions" else 10**9,
        -x["reviewScore"],x["date"],norm(x["city"]),norm(x["name"])))
    groups=defaultdict(lambda:{"total":0,"genreDocumented":0,"officialIndividual":0})
    for item in leads:
        group=groups[(item["venue"],item["city"],item["department"])]
        group["total"]+=1
        group["genreDocumented"]+=int(item["tier"]=="genre_documented")
        group["officialIndividual"]+=int(item["individualOfficialLead"])
    priorities=[{"venue":name,"city":city,"department":dept,
                 "region":region_of(dept),**counts}
                for (name,city,dept),counts in groups.items()]
    priorities.sort(key=lambda x:(
        regions.get(x["region"],0) if x["region"]!="Autres régions" else 10**9,
        -x["genreDocumented"],-x["officialIndividual"],
        -x["total"],norm(x["city"])))
    source_keys={(norm(v.get("name")),norm(v.get("city"))) for v in sources["venues"]}
    missing=[{"name":v.get("name"),"city":v.get("city"),"department":v.get("department")}
             for v in national["venues"] if v.get("sourceType") in
             ("existing","official","institutional") and
             (norm(v.get("name")),norm(v.get("city"))) not in source_keys]
    missing.sort(key=lambda x:(norm(x["city"]),norm(x["name"])))
    return {
        "schema":"grossesondes.concert.coverage-gaps.v1",
        "asOf":today.isoformat(),"publicationAllowed":False,
        "catalogue":{"upcoming":len(future),"venues":len(catalogue_venues),
                     "regions":dict(sorted(regions.items())),
                     "months":dict(sorted(months.items()))},
        "discovery":{"archived":len(registry["items"]),"sources":len(sources["venues"]),
                     "nationalVenues":len(national["venues"]),
                     "potentialMissing":len(leads),
                     "genreDocumented":sum(x["tier"]=="genre_documented" for x in leads),
                     "officialIndividualLeads":sum(x["individualOfficialLead"] for x in leads),
                     "excluded":dict(sorted(quarantined.items()))},
        "priorityVenues":priorities[:60],"priorityLeads":leads[:100],
        "venuesOutsideSourceRotation":missing,
        "warning":"PISTES NON APPROUVÉES : ne rien publier sans vérification officielle événement par événement."
    }

def report_md(data):
    c,d=data["catalogue"],data["discovery"]
    lines=[
        "# Grosses Ondes — priorités nationales Concerts",
        "","Diagnostic privé du "+data["asOf"]+" ; aucune publication.",
        "",
        f"- Concerts futurs publiés : **{c['upcoming']}**",
        f"- Salles publiées : **{c['venues']}** ; sources configurées : **{d['sources']}**",
        f"- Salles nationales prospectées : **{d['nationalVenues']}**",
        f"- Pistes archivées : **{d['archived']}**",
        f"- Pistes à examiner sans doublon apparent : **{d['potentialMissing']}**",
        f"- Genre explicitement nommé : **{d['genreDocumented']}**",
        f"- Fiches individuelles officielles potentielles : **{d['officialIndividualLeads']}**",
        "","## Salles à contrôler d'abord",""]
    for v in data["priorityVenues"][:20]:
        lines.append(f"- {v['venue']} ({v['city']}, {v['department']}, {v['region']}) : "
                     f"{v['total']} pistes ; {v['genreDocumented']} avec genre documenté")
    lines+=["","## Pistes prioritaires — ne pas publier",""]
    for v in data["priorityLeads"][:30]:
        lines.append(f"- {v['date']} | {v['name']} | {v['venue']} ({v['city']}) "
                     f"| {v['tier']} | {v['sourceUrl'] or 'lien absent'}")
    lines+=["","## Région par nombre de dates",""]
    for k,v in sorted(c["regions"].items(),key=lambda p:(p[1],p[0])):
        lines.append(f"- {k} : {v}")
    lines+=["","**Aucune piste n'est confirmée ni approuvée automatiquement.**",""]
    return "\n".join(lines)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--registry",type=Path,default=ROOT/"intake/registry.json")
    p.add_argument("--sources",type=Path,default=ROOT/"sources.json")
    p.add_argument("--venues",type=Path,default=ROOT/"venues-national.json")
    p.add_argument("--catalogue-file",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--date",type=dt.date.fromisoformat,default=dt.date.today())
    args=p.parse_args()
    if args.catalogue_file:
        catalogue=json.loads(args.catalogue_file.read_text(encoding="utf-8"))
    else:
        from discover import json_url
        catalogue=json_url(CATALOG)
    result=evaluate(catalogue,json.loads(args.registry.read_text(encoding="utf-8")),
                    json.loads(args.sources.read_text(encoding="utf-8")),
                    json.loads(args.venues.read_text(encoding="utf-8")),args.date)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"lacunes.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.output/"RAPPORT_LACUNES.md").write_text(report_md(result),encoding="utf-8")
    print("Pistes absentes à revérifier :",result["discovery"]["potentialMissing"],"; aucune publication.")

if __name__=="__main__":
    main()
