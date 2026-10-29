"""Validation conservative des nouvelles programmations officielles."""
import re
from grossesondes_field_proof import normalize, words_present

ALLOWED_FIELDS={"lineup","bands","notes","verificationStatus","sourceConfidence","auditSources","lastVerified"}

def validate_roster(original,patch,source_text):
    fields={c.get("field"):c for c in patch.get("changes",[])}
    if len(fields)!=len(patch.get("changes",[])) or not {"lineup","lastVerified"}<=set(fields)<=ALLOWED_FIELDS:
        return None
    old=original.get("lineup")
    new=fields["lineup"].get("after")
    if not (isinstance(old,list) and isinstance(new,list) and len(old)>0 and
            len(new)>len(old) and new[:len(old)]==old and
            all(isinstance(n,str) and len(normalize(n))>=3 for n in new) and
            len(set(map(normalize,new)))==len(new)):
        return None
    if "bands" in fields and not (original.get("bands")==len(old) and fields["bands"]["after"]==len(new)):
        return None
    year=str(original.get("startDate") or "")[:4]
    doc=normalize(source_text)
    name=re.sub(r"\\b20\\d{2}\\b","",normalize(original.get("name",""))).strip()
    if not (year.isdigit() and len(year)==4 and len(name)>=6 and words_present(doc,[name])):
        return None
    m=re.search(r"(?:programmation|lineup|line up|affiche)\\s+"+re.escape(year)+r"\\b",doc)
    if not m:
        return None
    section=doc[m.end():m.end()+1800]
    approved_new=[name for name in new[len(old):] if words_present(section,[name])]
    if not approved_new:
        return None
    result=dict(original)
    result["lineup"]=old+approved_new
    if "bands" in fields:
        result["bands"]=len(result["lineup"])
    if "notes" in fields:
        result["notes"]=(
            f"Édition {year} : {len(result['lineup'])} groupes recensés, "
            f"dont {len(approved_new)} nouvellement corroboré(s) sur le site organisateur. "
            "Aucune annonce non vérifiée n'a été intégrée."
        )
    if "verificationStatus" in fields:
        result["verificationStatus"]=f"{len(approved_new)} nouveau(x) artiste(s) attesté(s) par la programmation officielle."
    if "sourceConfidence" in fields:
        result["sourceConfidence"]="Programme publié par le site organisateur enregistré."
    if "auditSources" in fields:
        result["auditSources"]=list(dict.fromkeys(original.get("auditSources",[])+[original["officialSite"]]))
    result["lastVerified"]=fields["lastVerified"]["after"]
    return result,list(fields),[n for n in new[len(old):] if n not in approved_new]
