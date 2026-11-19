"""Grosses Ondes: synchronisation cloud à sécurité stricte.

Compare la production Infomaniak à son empreinte initiale, revalide les
preuves officielles, fusionne le patch privé sans suppression ni régression.
Le mode preview ne modifie aucun fichier; le mode publish ne valide que le
catalogue issu de cette preuve et de cet instantané.
"""
import argparse
from datetime import datetime
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from time import sleep
from zoneinfo import ZoneInfo

from grossesondes_preview import (
    ROOT, CAL_URL, HIS_URL, load_patch, require, index
)
from grossesondes_stage import official_text, stage, PROOF_MODE
from grossesondes_structured_edition import (
    PROOF_MODE as EDITION_PROOF_MODE, ARCHIVED_PROOF_MODE,
    HTML_PROOF_MODE, ARCHIVED_HTML_PROOF_MODE,
    ARCHIVED_BROWSER_PROOF_MODE,
)
from grossesondes_archived_html_intake import (
    PINNED_ARCHIVED_HTML_SOURCES, pinned_first_party, organizer_homepage,
    official_date, private_date_rejection_reason,
)
from grossesondes_structured_tickets import PROOF_MODE as TICKET_PROOF_MODE
from grossesondes_field_proof import (
    CERNUNNOS_HOME_URL,CERNUNNOS_GROUPS_URL,CERNUNNOS_INFO_URL,
    FANTASMAGORIK_TICKET_URL,FANTASMAGORIK_DATE_URL,
    IN_YOUR_FACE_TICKET_URL, verified_2026_11_01_ticket_snapshot
)

from grossesondes_history_guard import validate_history_extension
from grossesondes_noel_2026 import (
    PROOF_MODE as NOEL_PROOF_MODE, PROOF_SOURCES as NOEL_PROOF_SOURCES,
    SLUG as NOEL_SLUG,
)
from grossesondes_calendar_approval import approved_calendar, merge_staged_with_approved
from grossesondes_cernunnos_running_order import (
    RUNNING_ORDER_URL, GROUPS_URL, FIELDS as CERNUNNOS_LIVE_FIELDS,
    revalidate as revalidate_cernunnos_running_order,
)

MANIFEST=ROOT/"reference-manifest.json"
PUBLISHED_HEAD=Path("reviews/grossesondes-published-head.json")
GENESIS_BLOB_SHA="7fca36caba870d327ec5aadb504c46c251956c6d"


def git_blob_sha(data):
    return sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_published_head(published):
    """Anchor each public generation to the last successfully committed artifact.

    This prevents accidental drift from passing as approved, while allowing
    legitimately verified daily changes to survive tomorrow's sync even
    if the original source is temporarily unavailable.
    """
    record=json.loads(PUBLISHED_HEAD.read_text(encoding="utf-8"))
    require(record.get("schema")=="grossesondes.published-head.v1"
            and record.get("genesisBlobSha")==GENESIS_BLOB_SHA,
            "registre de publication manquant ou origine altérée")
    data=ROOT.joinpath("festivals.json").read_bytes()
    require(record.get("currentBlobSha")==git_blob_sha(data),
            "calendrier Git modifié hors synchroniseur")
    # The JSON object supplied to the validator must be the EXACT pinned
    # on-disk publication, not a modified in-memory object with unchanged
    # schema/count/date metadata.
    require(published==json.loads(data.decode("utf-8-sig")),
            "calendrier fourni divergent de sa version Git signée")
    require(record.get("calendarCount")==len(published.get("festivals",[]))
            and record.get("generatedAt")==published.get("generatedAt"),
            "métadonnées du calendrier divergent du registre")
    return record


def record_published_head(candidate, previous):
    data=ROOT.joinpath("festivals.json").read_bytes()
    record=dict(previous)
    record["currentBlobSha"]=git_blob_sha(data)
    record["calendarCount"]=len(candidate["festivals"])
    record["generatedAt"]=candidate["generatedAt"]
    PUBLISHED_HEAD.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",
                              encoding="utf-8")

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

def build_candidate(snapshot, published, patch, official_sources, today, trusted_published=False):
    proven,report=stage(
        snapshot["festivals.json"],snapshot["festival-history.json"],
        patch,official_sources,today,
        published_calendar=published["festivals.json"],
        published_history=published["festival-history.json"],
    )
    # Une seule extension historique approuvée est admissible, sans toucher
    # à l'empreinte immuable des 170 archives sur Infomaniak.
    validate_history_extension(
        snapshot["festival-history.json"], published["festival-history.json"]
    )
    if trusted_published:
        # The signed Git blob of the last published calendar was checked by
        # verify_published_head(). Preserve already validated later changes.
        # New changes can still enter ONLY through independently proven stage().
        reference = published["festivals.json"]
        target = merge_staged_with_approved(snapshot["festivals.json"], proven, reference)
        report["trusted_calendar_base"] = "publication_precedente_signee"
    elif published["festivals.json"] == snapshot["festivals.json"]:
        reference = snapshot["festivals.json"]
        target = proven
        report["trusted_calendar_base"] = "production_initiale_123"
    else:
        reference = approved_calendar(snapshot["festivals.json"])
        target = merge_staged_with_approved(snapshot["festivals.json"], proven, reference)
        report["trusted_calendar_base"] = "publication_approuvee_124"
    # Only two pinned current-edition organizer pages can add the verified
    # Cernunnos 2027 daily running order. The private cumulative patch is
    # never trusted as proof of any new band or appearance date.
    for position, row in enumerate(target["festivals"]):
        if row.get("slug") != "cernunnos-pagan-fest":
            continue
        updated = revalidate_cernunnos_running_order(
            row, official_sources.get("cernunnos_running_order", ""),
            official_sources.get("cernunnos_groups", ""), today
        )
        if updated is not None:
            target["festivals"][position] = updated
            # This is a real, independently rechecked content change.
            # Do not leave generatedAt at the previous publication date.
            target["generatedAt"] = today
            report["accepted_updates"].append({
                "slug": "cernunnos-pagan-fest",
                "fields": list(CERNUNNOS_LIVE_FIELDS),
            })
            report["source_proofs"].extend([GROUPS_URL, RUNNING_ORDER_URL])
        break
    changed=safe_target(reference,target,published["festivals.json"])
    report["candidate_total"] = len(target["festivals"])
    if not changed:
        target["generatedAt"]=published["festivals.json"]["generatedAt"]
    report["changed"]=changed
    report["publication"]="PREVIEW" if not changed else "EN ATTENTE AUTORISATION"
    return target,report

def collect_registered_update_sources(patch, original, fetcher=official_text):
    """Re-fetch original officialSite, never the private patch's evidence URLs.

    Legacy festival-specific validations keep their existing dedicated sources.
    Typed JSON-LD proposals require an independent HTML fetch even for those
    festivals. Cache per (URL, representation) so editions sharing a site each
    receive the same re-fetched proof, without making redundant requests.
    """
    known_legacy={"cernunnos-pagan-fest","fantasmagorik-fest-2026",
                  "autfest-2027","festival-metal-vouziers-2026",
                  "winter-rising-fest-2026"}
    sources={}
    fetched={}
    for update in patch.get("updates",[])[:15]:
        slug=update.get("slug")
        item=original.get(slug,{})
        url=item.get("officialSite")
        if not isinstance(url,str):
            continue
        mode=update.get("proofMode")
        if mode == PROOF_MODE:
            key,raw="registered-schema:"+slug,True
        elif mode == TICKET_PROOF_MODE:
            key,raw="registered-ticket:"+slug,True
        elif mode is None and slug not in known_legacy:
            key,raw="registered:"+slug,False
        else:
            # Unsupported proof modes may not trigger arbitrary network reads.
            continue
        cache_key=(url,raw)
        if cache_key not in fetched:
            try:
                fetched[cache_key]=fetcher(url,registered=True,raw=raw)
            except Exception:
                fetched[cache_key]=""
                print("Site officiel enregistré inaccessible pour "+slug+
                      " : modifications différées.")
        sources[key]=fetched[cache_key]
    return sources


def collect_registered_edition_sources(patch, original, fetcher=official_text,
                                       archived=None, published_slugs=None,
                                       browser_fetcher=None):
    """Fetch only registered first-party parents (published or archived).

    Both parent registries come from the immutable Infomaniak snapshots;
    never fetch a URL supplied by the private proposal. The archive path
    needs its separate proof mode and cannot silently borrow old metadata.
    """
    sources={}
    cached={}
    browser_checks = 0
    # Ten fresh first-party fetches per run protect latency and remote sites.
    # Crucially, skip editions ALREADY on the signed published calendar before
    # applying this batch limit. Otherwise the first ten private additions
    # are checked forever and later editions starve.
    if published_slugs is None:
        published_slugs = set()
    if (not isinstance(published_slugs, (set, frozenset))
            or any(not isinstance(x, str) for x in published_slugs)):
        raise ValueError("Invalid signed published edition identities")
    ready = []
    for addition in patch.get("additions", []):
        if not isinstance(addition, dict):
            continue
        if (addition.get("slug") not in published_slugs
                and addition.get("proofMode") in (
                    EDITION_PROOF_MODE, ARCHIVED_PROOF_MODE,
                    HTML_PROOF_MODE, ARCHIVED_HTML_PROOF_MODE,
                    ARCHIVED_BROWSER_PROOF_MODE)):
            ready.append(addition)
        if len(ready) == 10:
            break
    for proposed in ready:
        mode=proposed.get("proofMode")
        if mode not in (EDITION_PROOF_MODE, ARCHIVED_PROOF_MODE,
                        HTML_PROOF_MODE, ARCHIVED_HTML_PROOF_MODE,
                        ARCHIVED_BROWSER_PROOF_MODE):
            continue
        slug=proposed.get("slug")
        registered = (archived if mode in (
            ARCHIVED_PROOF_MODE, ARCHIVED_HTML_PROOF_MODE,
            ARCHIVED_BROWSER_PROOF_MODE) else original)
        if not isinstance(registered, dict):
            continue
        parent=registered.get(proposed.get("originSlug"),{})
        if not isinstance(parent, dict):
            continue
        url=parent.get("officialSite")
        if not isinstance(url,str):
            continue
        proof_url=url
        if mode == ARCHIVED_HTML_PROOF_MODE:
            pinned = PINNED_ARCHIVED_HTML_SOURCES.get(proposed.get("originSlug"))
            if (isinstance(pinned,dict)
                    and pinned["officialSite"] == url
                    and proposed.get("startDate","")[:4] == str(pinned["year"])
                    and proposed.get("endDate","")[:4] == str(pinned["year"])
                    and pinned_first_party(url, pinned["proofUrl"])):
                # A pre-reviewed fixed first-party page; NEVER from the patch.
                proof_url=pinned["proofUrl"]
        browser_mode = mode == ARCHIVED_BROWSER_PROOF_MODE
        # Browser mode is never inferred from raw HTML and cannot be
        # satisfied by a URL, HTML, or marker carried in the private patch.
        if browser_mode:
            if browser_checks >= 2 or not organizer_homepage(url):
                continue
            browser_checks += 1
        cache_key = (proof_url, "rendered" if browser_mode else "raw")
        if cache_key not in cached:
            if browser_mode:
                try:
                    # The browser re-fetches the IMMUTABLE archived origin in
                    # a fresh public runner, with same-host request isolation.
                    if browser_fetcher is None:
                        from grossesondes_official_browser_probe import rendered_html
                        browser_renderer = rendered_html
                    else:
                        browser_renderer = browser_fetcher
                    raw = fetcher(url, registered=True, raw=True)
                    rendered = browser_renderer(url)
                    year = int(str(proposed.get("startDate", ""))[:4])
                    actual = official_date(rendered, parent, year)
                    raw_dates = official_date(raw, parent, year)
                    conflicting_raw = (
                        private_date_rejection_reason(raw, parent, year)
                        == "official_html_conflicting_future_ranges")
                    if (actual is None or conflicting_raw
                            or (raw_dates is not None and raw_dates != actual)):
                        raise ValueError("Conflicting browser and raw official dates")
                    cached[cache_key] = rendered
                except Exception:
                    cached[cache_key] = ""
                    print("Contre-preuve navigateur indisponible pour "+str(slug))
            else:
                try:
                    cached[cache_key] = fetcher(
                        proof_url, registered=True, raw=True)
                except Exception:
                    cached[cache_key] = ""
                    print("Preuve officielle de nouvelle édition indisponible pour "+str(slug))
        sources["registered-edition:"+str(slug)] = cached[cache_key]
        if browser_mode and cached[cache_key]:
            sources["registered-edition-browser-verified:"+str(slug)] = True
        if proof_url != url:
            sources["registered-edition-proof-url:"+str(slug)]=proof_url
    return sources


def collect_noel_independent_sources(patch, fetcher=official_text, sleeper=sleep):
    """Fetch only pinned organizer/municipal URLs; retry transient server errors.

    Retry never changes a proof result. HTTP 403 and non-HTTP failures remain
    unknown. All data stays untrusted until noel_2026_update revalidates it.
    """
    needs_proof = any(
        isinstance(up, dict) and up.get("slug") == NOEL_SLUG
        and up.get("proofMode") == NOEL_PROOF_MODE
        for up in patch.get("updates", [])
    )
    if not needs_proof:
        return {}
    result = {}
    for key, url in NOEL_PROOF_SOURCES.items():
        body = ""
        for attempt in range(2):
            try:
                body = fetcher(url)
                break
            except HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and attempt == 0:
                    sleeper(1)
                    continue
                print(key + ": source inaccessible, code HTTP " +
                      str(exc.code) + " ; preuve différée.")
            except Exception as exc:
                print(key + ": preuve inaccessible (" +
                      type(exc).__name__ + "), modification différée.")
            break
        result[key] = body
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("preview","publish"))
    parser.add_argument("--browser-needed-only", action="store_true")
    args=parser.parse_args()
    token=os.environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN","")
    require(bool(token),"jeton privé absent")
    if args.browser_needed_only:
        # Output only a boolean; never expose private dossier fields, dates,
        # organizer URLs, or authentication details to GitHub Action logs.
        patch, _ = load_patch(
            token, datetime.now(ZoneInfo("Europe/Paris")).date(),
            allow_stale_for_reproof=True)
        required = any(
            isinstance(row, dict)
            and row.get("proofMode") == ARCHIVED_BROWSER_PROOF_MODE
            for row in patch.get("additions", []))
        print("browser_required=" + ("true" if required else "false"))
        return
    require(args.mode is not None, "mode de synchronisation absent")
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8"))
    today=datetime.now(ZoneInfo("Europe/Paris")).date()
    snapshot=load_production(manifest)
    published={
      key:json.loads((ROOT/key).read_text(encoding="utf-8"))
      for key in ("festivals.json","festival-history.json")
    }
    head=verify_published_head(published["festivals.json"])
    # Un patch ancien reste une proposition : chaque champ est reverifie
    # dans stage() avec des sources officielles telechargees aujourd'hui.
    patch,path=load_patch(token,today,allow_stale_for_reproof=True)
    sources={}
    for key,url in [
       ("muscadeath","https://muscadeath.fr/"),
       ("autfest","https://www.billetweb.fr/autfest-anniversaire"),
       ("vouziers","https://www.sudardennes.fr/fete-manifestation/festival-metal-vouziers/"),
       ("cernunnos_home",CERNUNNOS_HOME_URL),
       ("cernunnos_groups",CERNUNNOS_GROUPS_URL),
       ("cernunnos_running_order",RUNNING_ORDER_URL),
       ("cernunnos_info",CERNUNNOS_INFO_URL),
       ("fantasmagorik_ticket",FANTASMAGORIK_TICKET_URL),
       ("fantasmagorik_date",FANTASMAGORIK_DATE_URL),
       ("in_your_face_ticket",IN_YOUR_FACE_TICKET_URL)
    ]:
        try:sources[key]=official_text(
            url, raw=(key=="cernunnos_running_order"))
        except Exception as exc:
            if key=="in_your_face_ticket":
                # This is a PINNED observation dated 2026-11-01 only;
                # it cannot prove any later availability.
                sources[key]=verified_2026_11_01_ticket_snapshot()
                print("in_your_face_ticket: page inaccessible; preuve officielle historique du 01/11 utilisée")
            else:
                sources[key]=""
                print(key+": source inaccessible : changement exclu ("+type(exc).__name__+")")
    # Fixed proofs never use any URL supplied by the private patch.
    sources.update(collect_noel_independent_sources(patch))
    # Only re-fetch registered officialSite URLs from the immutable production.
    original={e["slug"]:e for e in snapshot["festivals.json"]["festivals"]}
    sources.update(collect_registered_update_sources(patch,original))
    registered_archives={
        e["slug"]:e for e in snapshot["festival-history.json"]["knownFestivals"]
    }
    signed_published_slugs = {
        row["slug"] for row in published["festivals.json"]["festivals"]
        if isinstance(row, dict) and isinstance(row.get("slug"), str)
    }
    sources.update(collect_registered_edition_sources(
        patch, original, archived=registered_archives,
        published_slugs=signed_published_slugs))
    out,report=build_candidate(snapshot,published,patch,sources,today.isoformat(),trusted_published=True)
    report["patch"]=path
    report["patch_age_days"]=(today-datetime.strptime(patch["generated_at"],"%Y-%m-%d").date()).days
    report["stale_patch_reproved_live"]=report["patch_age_days"]>7
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
        record_published_head(out,head)
        print("Calendrier et registre de publication préparés pour commit atomique.")
    elif args.mode=="preview":
        print("PREVIEW : aucune donnée publique modifiée.")
    else:
        print("Aucune différence de contenu à publier.")

if __name__=="__main__":
    main()
