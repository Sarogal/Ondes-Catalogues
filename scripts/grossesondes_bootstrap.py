"""Cliché initial de Grosses Ondes : lecture seule sur Infomaniak, Git écrit par Actions.
Garde-fous basés sur l'audit public du 29/10/2026. Jamais d'écrasement.
"""
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path("docs/grossesondes")
SOURCES={
    "festivals.json":{
        "url":"https://grosses-ondes.fr/data/festivals.json",
        "schema":1,"date_field":"generatedAt","reference_date":"2026-10-25",
        "array":"festivals","expected_count":123,
    },
    "festival-history.json":{
        "url":"https://grosses-ondes.fr/data/festival-history.json",
        "schema":2,"date_field":"updatedAt","reference_date":"2026-10-22",
        "array":"knownFestivals","expected_count":170,
    },
}

def ensure(ok,message):
    if not ok:raise ValueError("Import initial bloqué : "+message)

def check(name,doc):
    rule=SOURCES[name]
    ensure(isinstance(doc,dict) and doc.get("schema")==rule["schema"],
           name+": schéma non attendu")
    ensure(doc.get(rule["date_field"])==rule["reference_date"],
           name+": la production a changé de version")
    rows=doc.get(rule["array"])
    ensure(isinstance(rows,list) and len(rows)==rule["expected_count"],
           name+": la production a changé de taille")
    slugs=[r.get("slug") for r in rows if isinstance(r,dict)]
    ensure(len(slugs)==len(rows) and all(isinstance(s,str) and s for s in slugs),
           name+": identifiant manquant")
    ensure(len(set(slugs))==len(rows),name+": identifiant répété")
    for r in rows:
        start,end=r.get("startDate"),r.get("endDate")
        if start and end:
            ensure(date.fromisoformat(start)<=date.fromisoformat(end),
                   name+": dates inversées pour "+r["slug"])
    return len(rows)

def read_source(url):
    request=Request(url,headers={"Accept":"application/json",
                                 "User-Agent":"GrossesOndesCloudSnapshot/1.0"})
    with urlopen(request,timeout=35) as response:
        ensure(response.status==200,"source inaccessible")
        ensure(response.geturl()==url,"redirection non attendue")
        raw=response.read(2_000_001)
    ensure(len(raw)<=2_000_000,"réponse trop lourde")
    return raw

def main():
    for name in SOURCES:
        ensure(not (ROOT/name).exists(),
               name+": une référence publique existe déjà ; import refusé")
    ROOT.mkdir(parents=True,exist_ok=True)
    inventory={"schema":"grossesondes.reference.v1",
               "description":"Copie historique exacte de la production du 29 octobre 2026.",
               "sources":{}}
    # Tous les fichiers sont validés avant la première écriture.
    copied={}
    for name,rule in SOURCES.items():
        raw=read_source(rule["url"])
        doc=json.loads(raw.decode("utf-8-sig"))
        number=check(name,doc)
        copied[name]=raw
        inventory["sources"][name]={
            "url":rule["url"],"count":number,
            "source_date":rule["reference_date"],"sha256":hashlib.sha256(raw).hexdigest()
        }
    for name,raw in copied.items():
        (ROOT/name).write_bytes(raw)
    (ROOT/"reference-manifest.json").write_text(
        json.dumps(inventory,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Référence Grosses Ondes créée : 123 calendaires et 170 archives.")
    print("Aucun fichier Infomaniak modifié. P'tites Ondes intact.")

if __name__=="__main__":
    main()
