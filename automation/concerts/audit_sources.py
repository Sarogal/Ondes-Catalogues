#!/usr/bin/env python3
"""Audit du registre national des salles, lecture seule, aucun déploiement."""
import argparse
import collections
import concurrent.futures
import datetime as dt
import html.parser
import json
import re
import urllib.error
import urllib.parse
from pathlib import Path
import discover as d

ROOT=Path(__file__).resolve().parent

class Signals(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ics=[];self.rss=[];self.events=0;self.javascript=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs); href=a.get("href",""); typ=a.get("type","").lower()
        if tag=="link" and href:
            if "rss" in typ or "atom" in typ: self.rss.append(href)
            if "calendar" in typ or href.lower().split("?")[0].endswith(".ics"): self.ics.append(href)
        if tag=="a" and href:
            if ".ics" in href.lower() or "ical" in href.lower(): self.ics.append(href)
            if re.search(r"/(concert|evenements?|events?|agenda|programmation)/",href,re.I):self.events+=1
        if tag=="script" and a.get("src",""): self.javascript=True

def load_registry(document):
    if document.get("schema")!="grossesondes.concert.venues.v1":raise ValueError("Schema inconnu")
    v=document.get("venues",[])
    ids=[x.get("id") for x in v]
    if not 115 <= len(v) <= 300 or not all(isinstance(x,str) and x for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError("Registre national de salles vide, dupliqué ou hors limites")
    counts=collections.Counter(x.get("sourceType") for x in v)
    if counts!=document.get("counts"):
        raise ValueError("Répartition des provenances incohérente avec le registre")
    if any(x.get("sourceType") not in ("existing","official","institutional","directory") for x in v):
        raise ValueError("Provenance invalide")
    return v

def inspect(venue,known):
    key=(d.norm(venue["name"]),venue["department"])
    entry=known.get(key)
    row={k:venue.get(k) for k in ("id","name","city","department","priority","sourceType","sourceUrl","verifiedAgendaUrl")}
    row.update({"inDailyRegistry":bool(entry),"dailyCandidateUrl":entry.get("url") if entry else None,
                "monitoringProven":False,"publicationAllowed":False})
    typ=venue["sourceType"]
    if typ=="existing" and not venue.get("verifiedAgendaUrl"):
        row["status"]="missing_official_agenda";return row
    if typ=="directory" and not venue.get("verifiedAgendaUrl"):
        row["status"]="third_party_lead_only";return row
    url=venue.get("verifiedAgendaUrl") or venue.get("sourceUrl") or ""
    if urllib.parse.urlsplit(url).scheme!="https":row["status"]="invalid_url";return row
    try:
        if not d.robots_allow(url,{}):row["status"]="robots_unavailable_or_forbidden";return row
        content,final=d.download(url,timeout=10,cap=850_000)
        if not d.same_host(final,url):row["status"]="cross_domain_redirect";return row
        p=Signals();p.feed(content)
        structured=len(list(d.read_ld(content)))
        row["signals"]={"jsonLdEvents":structured,"icsLinks":len(p.ics),
                        "rssLinks":len(p.rss),"eventLinks":p.events,"hasScripts":p.javascript}
        row["suggestedMethod"]=("jsonld" if structured else "ics_candidate" if p.ics
                                else "rss_candidate" if p.rss else "event_page_adapter"
                                if p.events else "custom_adapter_needed")
        row["status"]="official_page_read"
    except urllib.error.HTTPError as e:
        row["status"]="http_error";row["httpCode"]=e.code
    except Exception as e:
        row["status"]="access_error";row["errorType"]=type(e).__name__
    return row

def analyze(venues,sources,workers=5):
    known={(d.norm(x["name"]),x["department"]):x for x in sources["venues"]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results=list(pool.map(lambda v:inspect(v,known),venues))
    return results

def save(out,results):
    out.mkdir(parents=True,exist_ok=True)
    stat=dict(collections.Counter(x["status"] for x in results))
    methods=dict(collections.Counter(x.get("suggestedMethod") for x in results if x.get("suggestedMethod")))
    report={"schema":"grossesondes.concert.sources-audit.v1",
            "generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(),
            "count":len(results),"statusCounts":stat,"methodSuggestions":methods,
            "publishesNothing":True,"venues":results,
            "warning":"HTTP 200 ou lien ICS/RSS ne signifie pas qu'un concert est confirmé ou surveillé"}
    (out/"salles_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[f"# Audit des {len(results)} salles Grosses Ondes","",
           "**Diagnostic uniquement : aucun catalogue modifié, aucun concert publié.**","",
           "## Statuts",""]
    lines += ["- "+k+" : "+str(v) for k,v in sorted(stat.items())]
    lines += ["","## Méthodes suggérées, à valider sur données réelles",""]
    lines += ["- "+k+" : "+str(v) for k,v in sorted(methods.items())]
    lines += ["","## Salles à travailler",""]
    lines += ["- "+v["name"]+" ("+v["department"]+") : "+v["status"] for v in results if v["status"]!="official_page_read"]
    lines += ["","Les sources d'annuaires et les pages sans calendrier ne sont jamais considérées comme des collecteurs opérationnels."]
    (out/"RAPPORT_AUDIT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);args=p.parse_args()
    venues=load_registry(json.loads((ROOT/"venues-national.json").read_text(encoding="utf-8")))
    sources=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
    report=save(Path(args.output),analyze(venues,sources))
    print("Audit :",report["count"],"salles.",report["statusCounts"]," Aucun déploiement.")

if __name__=="__main__":main()
