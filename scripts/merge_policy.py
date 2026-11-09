"""Fusion publique fail-closed: seul un événement avec preuve indépendante est ajouté."""
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json, math, re
from urllib.parse import urlparse
from proof_text import verify_event as proof
from official_organizer_proof import canonical_event_title
from proof import norm

REQUIRED={"id","title","category","category_label","date_start","date_end","city","department","region","venue","source_url","source_label","verified_at","geo_verified_at","geo_precision","lat","lng"}
ORIGIN="https://ptitesondes.fr/config/sorties.json"

# Explicit one-field historical correction, independently verified against:
# https://www.opera-bordeaux.com/famille-orchestre-momo-lenfant-peche-86301
# 22 January 2027 at 14:30 is for schools only. Family sessions remain at 19:00.
# This is NOT a patch update route: the publisher never edits existing records.
MOMO_HISTORY_ID = "bordeaux-momo-enfant-peche-2027-01-21"
MOMO_HISTORY_URL = "https://www.opera-bordeaux.com/famille-orchestre-momo-lenfant-peche-86301"
MOMO_HISTORY_OLD = "21 janv. 19:00 ; 22 janv. 14:30 (scolaires) et 19:00"
MOMO_HISTORY_NEW = "21 janv. 19:00 ; 22 janv. 19:00"


def historical_event_unchanged(previous, published):
    """Allow only the exact, reviewed schooling typo, never general edits."""
    if previous == published:
        return True
    if not isinstance(previous, dict) or not isinstance(published, dict):
        return False
    if (previous.get("id") != MOMO_HISTORY_ID
            or previous.get("source_url") != MOMO_HISTORY_URL
            or previous.get("date_start") != "2027-01-21"
            or previous.get("date_end") != "2027-01-22"
            or previous.get("time") != MOMO_HISTORY_OLD):
        return False
    return published == dict(previous, time=MOMO_HISTORY_NEW)


def guard(ok, message):
    if not ok: raise ValueError("ARRÊT DE SÉCURITÉ: "+message)

def byid(doc):
    guard(isinstance(doc,dict) and doc.get("version")==3 and isinstance(doc.get("updated_at"),str),"catalogue version 3 attendu")
    events=doc.get("events")
    guard(isinstance(events,list) and 100<=len(events)<=100000,"nombre de fiches anormal")
    guard(all(isinstance(e,dict) and isinstance(e.get("id"),str) and e["id"] for e in events),"identifiants invalides")
    ix={e["id"]:e for e in events}
    guard(len(ix)==len(events),"doublons d'identifiants")
    return ix

def validate_patch(p,ref,day,today):
    guard(isinstance(p,dict) and p.get("schema")=="ptitesondes.patch.v1" and p.get("safe_to_publish") is False,"format patch inattendu")
    guard(p.get("generated_at")==str(day) and 0<=(today-day).days<=3,"patch périmé ou date incohérente")
    s=p.get("source")
    guard(isinstance(s,dict) and (s.get("url"),s.get("version"),s.get("updated_at"),s.get("events_count"))==(ORIGIN,3,ref["updated_at"],len(ref["events"])),"source du patch différente de la référence")
    guard(all(isinstance(p.get(k),list) for k in ("additions","updates","deferred")),"listes manquantes")
    guard(len(p["additions"])<=100 and len(p["updates"])<=100,"trop de modifications")
    guard(not p["updates"],"les corrections de fiches existantes demandent une autre procédure")
    guard(p.get("checks",{}).get("ids_unique") is True,"contrôle d'identifiants manquant")

def valid(ev,categories,fields,today):
    if not isinstance(ev,dict) or REQUIRED-set(ev) or set(ev)-fields: return False,"champs inconnus ou absents"
    if not isinstance(ev.get("id"),str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",ev["id"]): return False,"ID non conforme"
    if not all(isinstance(ev.get(k),str) and ev[k].strip() for k in ("title","city","department","region","venue","source_label","category_label")):return False,"champ vide"
    if ev.get("category") not in categories:return False,"catégorie inconnue"
    try:
        start,end=date.fromisoformat(ev["date_start"]),date.fromisoformat(ev["date_end"])
        verified=date.fromisoformat(ev["verified_at"])
        geo_verified=date.fromisoformat(ev["geo_verified_at"])
        if start>end or end<today or (end-start).days>31:return False,"période invalide"
        if any(abs((today-d).days)>14 for d in (verified,geo_verified)):return False,"contrôle trop ancien"
        lat,lng=ev["lat"],ev["lng"]
        if isinstance(lat,bool) or isinstance(lng,bool) or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (lat,lng)):return False,"GPS invalide"
        if not -90<=lat<=90 or not -180<=lng<=180 or ev.get("geo_precision")!="venue":return False,"lieu non géolocalisé précisément"
        u=urlparse(ev["source_url"])
        if u.scheme!="https" or not u.hostname or u.username or u.password:return False,"URL source incorrecte"
    except (ValueError,TypeError,KeyError,OverflowError):return False,"champ incorrect"
    return True,"structure conforme"

def safe_published_event(event):
    """Ne pas recopier un texte descriptif non audité, même si les champs sont prouvés."""
    public=dict(event)
    if "description" in public:
        public["description"]=(
            "Date, horaires et lieu contrôlés auprès de l'organisateur. "
            "Consultez la source officielle pour le programme détaillé "
            "et les conditions de participation."
        )
    return public

def compatible_published_refinement(old, proposed, today):
    """Compatibilité d'un ajout CUMULATIF déjà publié.

    Le patch privé peut préciser le lieu ou renouveler sa date de contrôle
    après publication. Aucun de ces changements n'est APPLIQUÉ ici.
    Tout autre champ divergent reste une collision bloquante.
    """
    if not isinstance(old,dict) or not isinstance(proposed,dict):
        return False
    if set(old)!=set(proposed):
        return False
    allowed={"description","venue","verified_at"}
    if any(old[k]!=proposed[k] for k in old if k not in allowed):
        return False
    sanitized=safe_published_event(proposed)
    if old.get("description") not in (
        proposed.get("description"),sanitized.get("description")
    ):
        return False
    if old.get("venue")!=proposed.get("venue"):
        old_venue=norm(old.get("venue",""))
        new_venue=norm(proposed.get("venue",""))
        # Enrichissement strict de l'ancien lieu avec une salle identifiée.
        if not (old_venue and new_venue.startswith(old_venue+" salle ")):
            return False
    try:
        before=date.fromisoformat(old["verified_at"])
        after=date.fromisoformat(proposed["verified_at"])
        if not before<=after<=today:
            return False
    except (ValueError,TypeError,KeyError):
        return False
    return True

def merge(ref,public,patch,today,checker=proof):
    originals=byid(ref)
    published=byid(public)
    validate_patch(patch,ref,date.fromisoformat(patch["generated_at"]),today)
    for key,e in originals.items():
        guard(key in published and historical_event_unchanged(e, published[key]),
              "fiche historique supprimée ou modifiée : "+key)
    fields=set().union(*(set(e) for e in ref["events"]))
    categories={e["category"] for e in ref["events"]}
    signatures={(canonical_event_title(e),norm(e.get("city")),norm(e.get("venue")),e.get("date_start")) for e in public["events"]}
    seen=set();accepted=[];waiting=[]
    for ev in patch["additions"]:
        guard(isinstance(ev,dict) and isinstance(ev.get("id"),str),"ajout malformé")
        eid=ev["id"]
        guard(eid not in seen,"doublon dans patch : "+eid)
        seen.add(eid)
        if eid in published:
            if published[eid] in (ev,safe_published_event(ev)):
                continue
            guard(compatible_published_refinement(published[eid],ev,today),
                  "collision avec une fiche déjà publiée : "+eid)
            waiting.append({
                "id":eid,
                "raison":"fiche déjà publiée : précision de salle ou nouvelle date de "
                         "vérification détectée, non appliquée automatiquement"
            })
            continue
        signature=(canonical_event_title(ev),norm(ev.get("city")),norm(ev.get("venue")),ev.get("date_start"))
        guard(signature not in signatures,"doublon sémantique : "+eid)
        ok,reason=valid(ev,categories,fields,today)
        if ok:
            ok,reason=checker(ev,ref["events"])
        if ok:
            accepted.append(safe_published_event(ev));signatures.add(signature)
        else:
            waiting.append({"id":eid,"raison":reason})
    result=dict(public)
    result["events"]=list(public["events"])+accepted
    if accepted: result["updated_at"]=datetime.now(ZoneInfo("Europe/Paris")).isoformat(timespec="seconds")
    return result,{"initial":len(published),"final":len(result["events"]),"ajoutes":len(accepted),"attente":waiting,"suppression":0,"correction":0}
