"""Prévisualisation Grosses Ondes : aucune publication ni écriture Git.

Compare la veille privée cumulative aux deux JSON de production et aux miroirs
publics. Détecte collisions, changements de base, effacements et ambiguïtés.
Il s'agit d'un audit, PAS encore d'une validation pour publication automatique.
"""
from datetime import datetime, date
from pathlib import Path
import base64
import json
import os
import re
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from grossesondes_history_guard import validate_history_extension

ROOT=Path("docs/grossesondes")
CAL_URL="https://grosses-ondes.fr/data/festivals.json"
HIS_URL="https://grosses-ondes.fr/data/festival-history.json"
PRIVATE="https://api.github.com/repos/Sarogal/GrossesOndes/contents/"
BRANCH="automation/grossesondes-intake"
FOLDER="automation-intake/grossesondes"

def require(ok,reason):
    if not ok:raise ValueError("Audit bloqué : "+reason)

def fetch_json(url, token=""):
    headers={"Accept":"application/vnd.github+json",
             "User-Agent":"GrossesOndesCloudAudit/1.0"}
    if token:
        headers["Authorization"]="Bearer "+token
        headers["X-GitHub-Api-Version"]="2022-11-28"
    with urlopen(Request(url,headers=headers),timeout=30) as response:
        raw=response.read(2_000_001)
    require(len(raw)<=2_000_000,"réponse distante trop volumineuse")
    return json.loads(raw)

def index(doc,key,expected_schema):
    require(isinstance(doc,dict) and doc.get("schema")==expected_schema,"schéma incorrect")
    rows=doc.get(key)
    require(isinstance(rows,list) and 90<=len(rows)<=3000,"volume incohérent")
    require(all(isinstance(r,dict) and isinstance(r.get("slug"),str) and r["slug"] for r in rows),
            "entrée sans slug")
    result={r["slug"]:r for r in rows}
    require(len(result)==len(rows),"doublon de slug")
    for e in rows:
        if e.get("startDate") and e.get("endDate"):
            require(date.fromisoformat(e["startDate"])<=date.fromisoformat(e["endDate"]),
                    "période inversée : "+e["slug"])
    return result

def load_patch(token,today):
    require(bool(token),"secret GROSSES_ONDES_INTAKE_READ_TOKEN absent")
    suffix="?ref="+quote(BRANCH,safe="")
    contents=fetch_json(PRIVATE+FOLDER+suffix,token)
    require(isinstance(contents,list),"dossier de collecte introuvable")
    items=[]
    for file in contents:
        m=re.fullmatch(r"patch-(\d{4}-\d{2}-\d{2})\.json",file.get("name",""))
        if m and file.get("type")=="file":
            day=date.fromisoformat(m.group(1))
            if day<=today:items.append((day,file["path"]))
    require(items,"aucun patch quotidien encore disponible")
    day,path=max(items)
    require((today-day).days<=7,"lot de plus de 7 jours")
    entry=fetch_json(PRIVATE+quote(path,safe="/")+suffix,token)
    require(entry.get("encoding")=="base64","encodage patch non reconnu")
    raw=base64.b64decode(entry["content"])
    require(len(raw)<1_000_000,"patch trop volumineux")
    patch=json.loads(raw)
    require(patch.get("generated_at")==day.isoformat(),"date patch non concordante")
    return patch,path

def audit(calendar,history,patch,production_calendar,production_history):
    cal=index(calendar,"festivals",1)
    hist=index(history,"knownFestivals",2)
    prod=index(production_calendar,"festivals",1)
    prodhist=index(production_history,"knownFestivals",2)
    # La production Infomaniak est le cliché immuable. Un miroir qui ajoute
    # des fiches de calendrier ne doit pas supprimer ou altérer sa base.
    require(all(prod.get(k)==v for k,v in cal.items()) or
            all(cal.get(k)==v for k,v in prod.items()),
            "le miroir diffère des fiches de la production ou elle a changé")
    # L'extension historique est strictement limitée aux fiches approuvées.
    validate_history_extension(production_history, history)
    require(isinstance(patch,dict) and patch.get("schema")=="grossesondes.patch.v1"
            and patch.get("safe_to_publish") is False,"format ou sécurité du patch incorrect")
    ref=patch.get("source") or {}
    f,h=ref.get("festivals") or {},ref.get("history") or {}
    require((f.get("url"),f.get("generatedAt"),f.get("count"))==
            (CAL_URL,production_calendar["generatedAt"],len(prod)),
            "base du calendrier différente du patch")
    require((h.get("url"),h.get("updatedAt"),h.get("count"))==
            (HIS_URL,production_history["updatedAt"],len(prodhist)),
            "base des archives différente du patch")
    for name in ("additions","updates","history_additions","history_updates","deferred"):
        require(isinstance(patch.get(name),list),"liste absente : "+name)
    require(len(patch["additions"])<=100 and len(patch["updates"])<=200,"volume de changements excessif")
    require(not patch["history_additions"] and not patch["history_updates"],
            "archives modifiées : audit historique séparé obligatoire")
    observed=set();pending=[];ready_add=[];ready_update=[]
    for e in patch["additions"]:
        require(isinstance(e,dict) and isinstance(e.get("slug"),str),"ajout malformé")
        s=e["slug"]
        require(s not in observed,"slug répété dans les ajouts : "+s);observed.add(s)
        if s in cal or s in hist:
            pending.append({"slug":s,"reason":"slug déjà connu, vérifier édition et identité"})
            continue
        require(e.get("status") in ("Confirmé","Annoncé","Dates à venir"),
                "statut d'ajout inconnu")
        if e.get("startDate") and e.get("endDate"):
            require(date.fromisoformat(e["startDate"])<=date.fromisoformat(e["endDate"]),
                    "dates ajout inversées")
        if e.get("showOnMap") is True:
            require(e.get("status")!="Dates à venir" and e.get("startDate") and e.get("endDate"),
                    "marqueur sans dates confirmées")
            require(isinstance(e.get("lat"),(int,float)) and isinstance(e.get("lon"),(int,float)),
                    "marqueur sans coordonnées")
        ready_add.append(s)
    touched=set()
    for upd in patch["updates"]:
        require(isinstance(upd,dict) and isinstance(upd.get("slug"),str)
                and isinstance(upd.get("changes"),list),"mise à jour malformée")
        slug=upd["slug"]
        require(slug in cal,"édition inconnue : "+slug)
        require(isinstance(upd.get("evidence"),list) and upd["evidence"],
                "source manquante : "+slug)
        for ch in upd["changes"]:
            require(isinstance(ch,dict) and isinstance(ch.get("field"),str)
                    and "before" in ch and "after" in ch,"diff invalide : "+slug)
            key=(slug,ch["field"])
            require(key not in touched,"champ corrigé plusieurs fois : "+slug)
            touched.add(key)
            require(ch["field"] not in ("slug","name"),
                    "changement d'identité interdit : "+slug)
            known_fields=set().union(*(row.keys() for row in cal.values()))
            require(ch["field"] in known_fields,
                    "champ étranger au schema public : "+ch["field"])
            # Les objets publics omettent certains champs facultatifs.
            # Une absence n'est équivalente à « null » que si la veille l'indique
            # explicitement et que le champ existe ailleurs dans le catalogue.
            require(ch["field"] in cal[slug] or ch["before"] is None,
                    "champ absent mais valeur précédente non nulle : "+slug+"."+ch["field"])
            require(cal[slug].get(ch["field"])==ch["before"],
                    "ancien champ discordant : "+slug+"."+ch["field"])
            ready_update.append(key)
    return {
        "current_calendar":len(cal),"current_history":len(hist),
        "additions_to_review":len(ready_add),"fields_to_review":len(ready_update),
        "patch_deferred":len(patch["deferred"]),"collisions":pending,
        "publication":"INTERDITE - PREVISUALISATION UNIQUEMENT",
        "history_unchanged":True,"deleted":0,
    }

def main():
    today=datetime.now(ZoneInfo("Europe/Paris")).date()
    token=os.getenv("GROSSES_ONDES_INTAKE_READ_TOKEN","")
    p,path=load_patch(token,today)
    c=json.loads((ROOT/"festivals.json").read_text(encoding="utf-8"))
    h=json.loads((ROOT/"festival-history.json").read_text(encoding="utf-8"))
    report=audit(c,h,p,fetch_json(CAL_URL),fetch_json(HIS_URL))
    report["private_patch"]=path
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
