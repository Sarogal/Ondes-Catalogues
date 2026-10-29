"""Independent, field-level proof policies for Grosses Ondes.

No generative text is accepted as evidence. A web source is fetched independently
by the runner from a fixed organizer / ticket partner URL; source text is compared
against the actual values proposed in the private patch. Only proven fields
are applied. Geolocation, dates and cancellations require separate validators.
"""
import re
import unicodedata


def normalize(value):
    s=str(value).casefold()
    for a,b in {"ø":"o","æ":"ae","œ":"oe","ß":"ss","ł":"l","ð":"d","þ":"th"}.items():
        s=s.replace(a,b)
    s=unicodedata.normalize("NFKD",s)
    s="".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())


def words_present(document, required):
    doc=normalize(document)
    return all(re.search(r"(?<![a-z0-9])"+re.escape(normalize(w))+r"(?![a-z0-9])",doc)
               for w in required)


CERNUNNOS_GROUPS_URL="https://www.cernunnospaganfest.fr/groupes/"
CERNUNNOS_INFO_URL="https://www.cernunnospaganfest.fr/infos-pratiques/"
FANTASMAGORIK_TICKET_URL="https://www.helloasso.com/associations/tout-en-scene/evenements/fantasmagorik-fest"
FANTASMAGORIK_DATE_URL="https://www.deltafm.fr/fantasmagorik-fest"


def cernunnos_update(original, update, official, today):
    """Return (revised, fields, pending) or None. Can validate a strict subset
    of a patch's proposed lineup without accepting unproven group names.
    """
    changes={x["field"]:x for x in update.get("changes",[])}
    fields={"lineup","bands","price","notes","verificationStatus",
            "sourceConfidence","auditSources","lastVerified"}
    if set(changes)!=fields or len(update["changes"])!=len(fields):
        return None
    groups=official.get("cernunnos_groups","")
    info=official.get("cernunnos_info","")
    if not (words_present(groups,["cernunnos2027","lineup"]) and
            words_present(info,["12","13","14","fevrier","2027","ferme du buisson","noisiel"])):
        return None
    proposed=changes["lineup"]["after"]
    before=original.get("lineup",[])
    if not (isinstance(proposed,list) and all(isinstance(x,str) for x in proposed)
            and len(set(map(normalize,proposed)))==len(proposed)
            and proposed[:len(before)]==before and len(proposed)>len(before)):
        return None
    # Zero artist names can disappear from the baseline without an explicit
    # cancellation proof. Some new names may appear in press only: leave pending.
    if not all(words_present(groups,[name]) for name in before):
        return None
    present=[name for name in proposed if words_present(groups,[name])]
    if len(present)<len(before)+1 or present[:len(before)]!=before:
        return None
    if not (
       words_present(info,["preventes","vendredi","45","samedi","dimanche","60",
                            "pass 3 jours","130"]) and
       words_present(info,["sur place","65","pass 2 jours","100"])
    ):
        return None
    # Prices explicitly visible, but the site also has a contradictory
    # generic "not yet open" notice. Do NOT claim booking availability.
    expected="Préventes 2027 : vendredi 45 € ; samedi 60 € ; dimanche 60 € ; pass 3 jours 130 €. Sur place (site officiel) : samedi ou dimanche 65 € ; pass 2 jours 100 € (catégorie à clarifier)."
    if changes["price"]["after"]!=expected:
        return None
    result=dict(original)
    result["lineup"]=present
    result["bands"]=len(present)
    result["price"]=(
       "Tarifs affichés sur le site officiel pour 2027 : vendredi 45 €, "
       "samedi ou dimanche 60 €, pass 3 jours 130 € en prévente ; "
       "sur place, journée samedi/dimanche 65 €, pass 2 jours 100 €. "
       "État d'ouverture de la billetterie non établi."
    )
    result["notes"]=(
       "Édition 2027 du 12 au 14 février à la Ferme du Buisson, Noisiel. "
       f"{len(present)} artistes nommément affichés sur la page officielle des groupes. "
       "Répartition par journée non publiée. Les tarifs indiqués sont ceux de "
       "la page officielle d'informations pratiques, sans confirmation "
       "de disponibilité immédiate des billets."
    )
    result["verificationStatus"]=(
       f"{len(present)} artistes vérifiés sur le site officiel ; "
       "autres annonces et répartition par jour en attente."
    )
    result["sourceConfidence"]="Site officiel : noms des groupes et grille tarifaire ; aucune déduction de programmation par jour."
    result["auditSources"]=list(dict.fromkeys(
       original.get("auditSources",[])+[CERNUNNOS_GROUPS_URL,CERNUNNOS_INFO_URL]
    ))
    result["lastVerified"]=changes["lastVerified"]["after"]
    pending=[name for name in proposed if name not in present]
    return result,list(fields),pending


def fantasmagorik_update(original,update,official,today):
    changes={x["field"]:x for x in update.get("changes",[])}
    expected={"status","lastVerified","verificationStatus"}
    if set(changes)!=expected or len(update["changes"])!=3:
        return None
    if changes["status"]["after"]!="Confirmé" or original.get("status")!="Annoncé":
        return None
    ticket=official.get("fantasmagorik_ticket","")
    dated=official.get("fantasmagorik_date","")
    if not words_present(ticket,["fantasmagorik fest","tout en scene",
                                 "la poudriere","330","leffrinckoucke","10"]):
        return None
    if not words_present(dated,["fantasmagorik fest","31 octobre 2026",
                                "la poudriere","leffrinckoucke"]):
        return None
    result=dict(original)
    result["status"]="Confirmé"
    result["lastVerified"]=changes["lastVerified"]["after"]
    result["verificationStatus"]=(
        "Édition du 31 octobre 2026, lieu et billetterie corroborés "
        "par l'organisateur et l'agenda local ; programmation partielle."
    )
    return result,list(expected),[]
