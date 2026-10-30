"""Grosses Ondes : premier lot candidat strictement vérifié, jamais publié.

Constitue un JSON de prévisualisation à partir du miroir et du patch privé.
Le certificat par source externe est requis pour les changements acceptés.
Les autres modifications sont exclues du lot, pas oubliées de la collecte.
"""
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import json
import re
import unicodedata

from grossesondes_preview import (
    ROOT,CAL_URL,HIS_URL,fetch_json,load_patch,audit,require
)
from grossesondes_generic_roster import validate_roster
from grossesondes_field_proof import (
    cernunnos_update, fantasmagorik_update,
    CERNUNNOS_HOME_URL, CERNUNNOS_GROUPS_URL, CERNUNNOS_INFO_URL,
    FANTASMAGORIK_TICKET_URL, FANTASMAGORIK_DATE_URL
)

OUT=Path("/tmp/grossesondes_stage")
ALLOWED={
    "https://muscadeath.fr/",
    "https://www.billetweb.fr/autfest-anniversaire",
    "https://www.sudardennes.fr/fete-manifestation/festival-metal-vouziers/",
    CERNUNNOS_HOME_URL, CERNUNNOS_GROUPS_URL, CERNUNNOS_INFO_URL,
    FANTASMAGORIK_TICKET_URL, FANTASMAGORIK_DATE_URL,
}

class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg"):self.hidden=max(0,self.hidden-1)
    def handle_data(self,text):
        if not self.hidden:self.parts.append(text)

def norm(t):
    s=unicodedata.normalize("NFKD",str(t).casefold())
    s="".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())

def official_text(url, registered=False):
    p=urlparse(url)
    host=(p.hostname or "").lower()
    safe_registered=(registered and p.scheme=="https" and p.port is None and
        p.username is None and p.password is None and p.query=="" and p.fragment=="" and
        "." in host and not host.endswith((".local",".internal",".localhost")) and
        all(part.isascii() and part.replace("-","").isalnum() for part in host.split(".")) and
        not any(part.isdigit() for part in host.split(".")))
    require(url in ALLOWED or safe_registered,"URL non approuvée")
    p=urlparse(url)
    require(p.scheme=="https" and p.hostname and not p.username and not p.password,
            "URL non sûre")
    req=Request(url,headers={"User-Agent":"GrossesOndesAudit/1.0",
                            "Accept":"text/html"})
    with urlopen(req,timeout=25) as r:
        require(r.status==200,"source officielle inaccessible")
        require(urlparse(r.geturl()).hostname==p.hostname,"redirection vers un autre domaine")
        raw=r.read(1_400_001)
    require(len(raw)<=1_400_000,"source trop volumineuse")
    parser=TextOnly()
    parser.feed(raw.decode("utf-8",errors="replace"))
    return norm(" ".join(parser.parts))

def can_add_muscadeath(entry,source):
    if entry.get("slug")!="muscadeath-2027":return False
    absent=("startDate","endDate","city","department","region","venue","lat","lon","price")
    if any(entry.get(k) is not None for k in absent):return False
    if (entry.get("status"),entry.get("showOnMap"),entry.get("source"))!=(
        "Dates à venir",False,"https://muscadeath.fr/"):return False
    return "muscadeath" in source and "rendez vous en 2027" in source

def eligible_autfest(changes,body):
    needed=["ultra vomit","septicflesh","tagada jones","vanaheim",
            "hope as a weapon","2027","lievin"]
    if not all(s in body for s in needed):return False
    fields={c.get("field"):c for c in changes}
    if not all(k in fields for k in ("lineup","notes","verificationStatus","lastVerified")):
        return False
    # Refuse une modification d'autres champs pendant ce lot.
    if set(fields)-{"lineup","notes","verificationStatus","lastVerified"}:return False
    return fields["lineup"]["after"]==[
        "Ultra Vomit","Septicflesh","Tagada Jones","Vanaheim","Hope as a weapon"
    ]

def eligible_vouziers(changes,body):
    fields={c.get("field"):c for c in changes}
    required={"notes","sourceConfidence","verificationStatus","auditSources","lastVerified"}
    if set(fields)!=required:return False
    return all(t in body for t in ("festival metal vouziers","31 octobre 2026",
                  "prevente","50","sur place","55"))

def apply_changes(entry,changes,slug,today):
    updated=dict(entry)
    for ch in changes:
        name=ch["field"]
        require(name not in ("slug","name") and name in entry,
                "champ interdit à modifier : "+slug+"."+name)
        require(entry[name]==ch["before"],
                "ancienne valeur discordante : "+slug+"."+name)
    for ch in changes:
        updated[ch["field"]]=ch["after"]
    if slug=="autfest-2027":
        # Le patch contient un vieux paragraphe contradictoire « trois à annoncer » :
        # ne pas publier ce texte libre sans neutralisation.
        updated["notes"]=(
            "Édition anniversaire caritative le 2 octobre 2027 à l'Arena Stade "
            "Couvert de Liévin. Cinq groupes nommés sur la billetterie officielle "
            "(Ultra Vomit, Septicflesh, Tagada Jones, Vanaheim, Hope as a weapon) ; "
            "sixième groupe encore à annoncer. Aucun tarif chiffré vérifié."
        )
    # Conserver la date de vérification de la source dans le patch ;
    # ne pas la renouveler artificiellement à chaque exécution quotidienne.
    updated["lastVerified"]=next((c["after"] for c in changes if c["field"]=="lastVerified"),entry.get("lastVerified",today))
    return updated

def stage(calendar,history,patch,sources,today,production_calendar=None,production_history=None):
    # Lors d'une prévisualisation autonome, les JSON publics historiques
    # restent la référence du patch même après extension du miroir Pages.
    audit(calendar,history,patch,
          production_calendar if production_calendar is not None else calendar,
          production_history if production_history is not None else history)
    existing={e["slug"]:e for e in calendar["festivals"]}
    produced=dict(calendar)
    rows=list(calendar["festivals"])
    report={"original":len(rows),"history":len(history["knownFestivals"]),
            "accepted_additions":[],"accepted_updates":[],
            "held":[],"source_proofs":[],"automatic_publication":False}
    for e in patch["additions"]:
        slug=e["slug"]
        if slug=="muscadeath-2027" and can_add_muscadeath(e,sources.get("muscadeath","")):
            require(slug not in existing and all(x.get("slug")!=slug for x in history["knownFestivals"]),
                    "édition déjà connue")
            rows.append(e)
            report["accepted_additions"].append(slug)
            report["source_proofs"].append("https://muscadeath.fr/")
        else:
            report["held"].append({"slug":slug,"reason":"preuve indépendante insuffisante"})
    for up in patch["updates"]:
        slug=up["slug"]
        current=existing[slug]
        partial=None
        if slug=="cernunnos-pagan-fest":
            partial=cernunnos_update(current,up,sources,today)
        elif slug=="fantasmagorik-fest-2026":
            partial=fantasmagorik_update(current,up,sources,today)
        if partial is None and sources.get("registered:"+slug):
            partial=validate_roster(current,up,sources["registered:"+slug])
        if partial is not None:
            revised,fields,uncorroborated=partial
            rows[rows.index(current)]=revised
            report["accepted_updates"].append({"slug":slug,"fields":fields})
            report["source_proofs"].extend(
                [CERNUNNOS_HOME_URL,CERNUNNOS_GROUPS_URL,CERNUNNOS_INFO_URL]
                if slug=="cernunnos-pagan-fest"
                else ([FANTASMAGORIK_TICKET_URL,FANTASMAGORIK_DATE_URL]
                      if slug=="fantasmagorik-fest-2026"
                      else [current["officialSite"]])
            )
            if uncorroborated:
                report["held"].append({
                    "slug":slug,"reason":"Noms non présents sur le site officiel",
                    "pending_names":uncorroborated
                })
            continue
        passed=(
            slug=="autfest-2027" and eligible_autfest(up["changes"],sources.get("autfest",""))
            or slug=="festival-metal-vouziers-2026" and eligible_vouziers(up["changes"],sources.get("vouziers",""))
        )
        if not passed:
            report["held"].append({"slug":slug,"reason":"changement non entièrement prouvé"})
            continue
        revised=apply_changes(current,up["changes"],slug,today)
        rows[rows.index(current)]=revised
        report["accepted_updates"].append({"slug":slug,"fields":[x["field"] for x in up["changes"]]})
        report["source_proofs"].append(
            "https://www.billetweb.fr/autfest-anniversaire" if slug=="autfest-2027"
            else "https://www.sudardennes.fr/fete-manifestation/festival-metal-vouziers/"
        )
    produced["festivals"]=rows
    if report["accepted_additions"] or report["accepted_updates"]:
        produced["generatedAt"]=today
    report["candidate_total"]=len(rows)
    report["unchanged_history"]=True
    report["unmodified_festivals"]=sum(
        1 for e in calendar["festivals"] if next(
            (x for x in rows if x["slug"]==e["slug"]),None
        )==e)
    return produced,report

def main():
    today=datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    token=__import__("os").environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN","")
    patch,path=load_patch(token,__import__("datetime").date.fromisoformat(today))
    cal=json.loads((ROOT/"festivals.json").read_text(encoding="utf-8"))
    history=json.loads((ROOT/"festival-history.json").read_text(encoding="utf-8"))
    # Comparer avant tout avec Infomaniak : en cas de divergence bloquer
    # (ne pas réécrire depuis l'ancienne référence).
    production_calendar,production_history=fetch_json(CAL_URL),fetch_json(HIS_URL)
    audit(cal,history,patch,production_calendar,production_history)
    evidence={}
    for key,url in (
        ("muscadeath","https://muscadeath.fr/"),
        ("autfest","https://www.billetweb.fr/autfest-anniversaire"),
        ("vouziers","https://www.sudardennes.fr/fete-manifestation/festival-metal-vouziers/"),
        ("cernunnos_home",CERNUNNOS_HOME_URL),
        ("cernunnos_groups",CERNUNNOS_GROUPS_URL),
        ("cernunnos_info",CERNUNNOS_INFO_URL),
        ("fantasmagorik_ticket",FANTASMAGORIK_TICKET_URL),
        ("fantasmagorik_date",FANTASMAGORIK_DATE_URL),
    ):
        try:evidence[key]=official_text(url)
        except Exception as error:
            evidence[key]=""
            print(key+": preuve non disponible ; changement maintenu en attente")
    out,report=stage(cal,history,patch,evidence,today,
                     production_calendar=production_calendar,
                     production_history=production_history)
    report["patch"]=path
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"festivals-candidat.json").write_text(
        json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"rapport.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
