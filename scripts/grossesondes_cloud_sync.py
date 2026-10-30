"""Grosses Ondes: synchronisation cloud à sécurité stricte.

Compare la production Infomaniak à son empreinte initiale, revalide les
preuves officielles, fusionne le patch privé sans suppression ni régression.
Le mode preview ne modifie aucun fichier; le mode publish ne valide que le
catalogue issu de cette preuve et de cet instantané.
"""
import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from grossesondes_preview import (
    ROOT, CAL_URL, HIS_URL, load_patch, require, index
)
from grossesondes_stage import official_text, stage
from grossesondes_field_proof import (
    CERNUNNOS_HOME_URL,CERNUNNOS_GROUPS_URL,CERNUNNOS_INFO_URL,
    FANTASMAGORIK_TICKET_URL,FANTASMAGORIK_DATE_URL
)

from grossesondes_history_guard import validate_history_extension
from grossesondes_calendar_approval import approved_calendar, merge_staged_with_approved

MANIFEST=ROOT/"reference-manifest.json"
SOURCES=[
    ("festivals.json", CAL_URL, "festivals", 1),
    ("festival-history.json", HIS_URL, "knownFestivals", 2),
]

def load_production(reference_manifest, reader=None):
    if reader is None:
        def reader(url):
            req=Request(url,headers={"User-Agent":"GrossesOndesCloudSync/1.0",
                                     "Accept":"application/json"})
            with urlopen(req,timeout=30) as res:
                require(res.status==200 and res.geturl()==url,
                        "source de production redirigée ou inaccessible")
                return res.read(2_000_001)
    data={}
    for filename,url,key,version in SOURCES:
        expected=reference_manifest["sources"][filename]
        require(expected["url"]==url,"URL de référence divergente")
        raw=reader(url)
        require(isinstance(raw,bytes) and len(raw)<=2_000_000,
                "octets JSON non valides ou trop volumineux")
        require(sha256(raw).hexdigest()==expected["sha256"],
                "SOURCE INFOMANIAK MODIFIÉE : "+filename+" ; rebasage manuel nécessaire")
        obj=json.loads(raw.decode("utf-8-sig"))
        mapping=index(obj,key,version)
        require(len(mapping)==expected["count"],"volume de référence inattendu")
        data[filename]=obj
    return data

def safe_target(baseline, candidate, currently_published):
    """Le catalogue cloud courant doit être exactement la base ou une version
    précédemment validée de la nouvelle cible; jamais une variante imprévue.
    """
    original=index(baseline,"festivals",1)
    target=index(candidate,"festivals",1)
    live=index(currently_published,"festivals",1)
    require(len(original)<=len(target),"la fusion retirerait des fiches")
    require(set(original).issubset(set(target)),"édition de référence supprimée")
    require(set(original).issubset(set(live)),"édition publique supprimée")
    require(set(live).issubset(set(target)),"édition publique absente du patch cumulatif")
    require(list(original)==list(target)[:len(original)],
            "ordre ou identité des anciennes éditions altéré")
    for slug, old in original.items():
        new=target[slug]
        current=live[slug]
        keys=set(old)|set(new)|set(current)
        for k in keys:
            if old.get(k)==new.get(k):
                require(k in current and current[k]==old.get(k) if k in old else k not in current,
                        "champ non prévu modifié : "+slug+"."+k)
            else:
                # Une valeur publique déjà modifiée doit être soit la valeur de
                # référence, soit la valeur exacte admissible du patch.
                require(
                    (k in old and k in current and current[k]==old[k]) or
                    (k in new and k in current and current[k]==new[k]) or
                    (k not in current and k not in old),
                    "champ public modifié hors du périmètre autorisé : "+slug+"."+k
                )
    for slug in set(live)-set(original):
        require(live[slug]==target[slug],
                "ancienne édition ajoutée devenue incohérente : "+slug)
    # On n'accepte pas un glissement silencieux de métadonnées de schéma.
    require(baseline.get("schema")==currently_published.get("schema")==candidate.get("schema")==1,
            "version de schéma différente")
    return currently_published["festivals"]!=candidate["festivals"]

def build_candidate(snapshot, published, patch, official_sources, today):
    proven,report=stage(
        snapshot["festivals.json"],snapshot["festival-history.json"],
        patch,official_sources,today
    )
    # Une seule extension historique approuvée est admissible, sans toucher
    # à l'empreinte immuable des 170 archives sur Infomaniak.
    validate_history_extension(
        snapshot["festival-history.json"], published["festival-history.json"]
    )
    if published["festivals.json"] == snapshot["festivals.json"]:
        # Compatibilité avec les tests et le premier bootstrap, avant le lot 124.
        reference = snapshot["festivals.json"]
        target = proven
        report["trusted_calendar_base"] = "production_initiale_123"
    else:
        # Les 124 fiches déjà officiellement publiées sont une couche approuvée.
        # Le patch du jour est construit sur la photographie initiale 123, puis
        # ses SEULES différences prouvées sont appliquées à cette couche.
        reference = approved_calendar(snapshot["festivals.json"])
        target = merge_staged_with_approved(snapshot["festivals.json"], proven, reference)
        report["trusted_calendar_base"] = "publication_approuvee_124"
    changed=safe_target(reference,target,published["festivals.json"])
    report["candidate_total"] = len(target["festivals"])
    if not changed:
        target["generatedAt"]=published["festivals.json"]["generatedAt"]
    report["changed"]=changed
    report["publication"]="PREVIEW" if not changed else "EN ATTENTE AUTORISATION"
    return target,report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("preview","publish"),required=True)
    args=parser.parse_args()
    token=os.environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN","")
    require(bool(token),"jeton privé absent")
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    today=datetime.now(ZoneInfo("Europe/Paris")).date()
    snapshot=load_production(manifest)
    published={
      key:json.loads((ROOT/key).read_text(encoding="utf-8"))
      for key in ("festivals.json","festival-history.json")
    }
    patch,path=load_patch(token,today)
    sources={}
    for key,url in [
       ("muscadeath","https://muscadeath.fr/"),
       ("autfest","https://www.billetweb.fr/autfest-anniversaire"),
       ("vouziers","https://www.sudardennes.fr/fete-manifestation/festival-metal-vouziers/"),
       ("cernunnos_home",CERNUNNOS_HOME_URL),
       ("cernunnos_groups",CERNUNNOS_GROUPS_URL),
       ("cernunnos_info",CERNUNNOS_INFO_URL),
       ("fantasmagorik_ticket",FANTASMAGORIK_TICKET_URL),
       ("fantasmagorik_date",FANTASMAGORIK_DATE_URL)
    ]:
        try:sources[key]=official_text(url)
        except Exception:
            sources[key]=""
            print(key+": source inaccessible : changement exclu")
    # Sources enregistrées dans la photographie de production, jamais tirées
    # des URLs proposées par une veille privée. Le pilote limite le trafic.
    original={e["slug"]:e for e in snapshot["festivals.json"]["festivals"]}
    known={"cernunnos-pagan-fest","fantasmagorik-fest-2026",
           "autfest-2027","festival-metal-vouziers-2026","winter-rising-fest-2026"}
    checked=set()
    for update in patch.get("updates",[])[:15]:
        slug=update.get("slug")
        item=original.get(slug,{})
        url=item.get("officialSite")
        if slug in known or not isinstance(url,str) or url in checked:
            continue
        checked.add(url)
        try:sources["registered:"+slug]=official_text(url,registered=True)
        except Exception:
            sources["registered:"+slug]=""
            print("Site officiel enregistré inaccessible pour "+slug+" : modifications différées.")
    out,report=build_candidate(snapshot,published,patch,sources,today.isoformat())
    report["patch"]=path
    report["mode"]=args.mode
    report["non_deployed_updates"]=len(report["held"])
    Path("/tmp/grossesondes_cloud").mkdir(exist_ok=True)
    Path("/tmp/grossesondes_cloud/candidate.json").write_text(
        json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    Path("/tmp/grossesondes_cloud/report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.mode=="publish" and report["changed"]:
        require(os.environ.get("GROSSES_ONDES_CLOUD_SYNC")=="enabled",
                "variable GROSSES_ONDES_CLOUD_SYNC différente de enabled")
        ROOT.joinpath("festivals.json").write_text(
            json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("Fichier public préparé dans le workspace Actions pour commit.")
    elif args.mode=="preview":
        print("PREVIEW : aucune donnée publique modifiée.")
    else:
        print("Aucune différence de contenu à publier.")

if __name__=="__main__":
    main()
