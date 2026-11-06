"""Independent PUBLIC preflight: private proposals cannot authorize publication."""
import argparse
import base64
from datetime import date, datetime
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo
from ptitesondes_places import validate, assert_append_only, norm
from private_intake import github, BRANCH, PATH

PRIVATE = "lieux-release-review.json"
PLACE_ID = "nantes-ludotheque-bellevue"
OFFICIAL = "https://parents.loire-atlantique.fr/44/centre-socioculturel-de-bellevue-meta-accoord/parents_10602"
OSM = "https://api.openstreetmap.org/api/0.6/node/2810810943"
OSM_PAGE = "https://www.openstreetmap.org/node/2810810943"
PAGES = "https://sarogal.github.io/Ondes-Catalogues/ptitesondes/lieux.json"
FACTS = {
    "id": PLACE_ID, "name": "Ludothèque Bellevue",
    "kind": "lieu-permanent", "category": "ludotheque",
    "category_label": "Ludothèque", "city": "Nantes",
    "department": "Loire-Atlantique", "region": "Pays de la Loire",
    "postal_code": "44100", "address": "20 rue Firmin Colas, 44100 Nantes",
    "geo_precision": "lieu", "age_min": None, "age_max": None,
    "admission": "Adhésion Accoord (8,80 €) nécessaire pour participer aux activités ; certaines gratuites, d’autres payantes.",
    "activities": ["ludothèque", "contes et comptines", "atelier d’éveil artistique parents/enfants"],
    "reservation_note": "Vérifier les horaires, l’adhésion et les modalités de participation sur le site officiel.",
    "official_url": OFFICIAL, "geo_source_url": OSM_PAGE,
    "is_publicly_accessible": True,
}
ANCHORS = (
    "Ludothèque Bellevue-Meta", "20 rue Firmin Colas", "44100 Nantes",
    "ludo.meta@accoord.fr", "une ludothèque", "Contes et comptines",
    "Atelier d’éveil artistique parents/enfants",
    "L’adhésion à l’Accoord (8,80€) est nécessaire pour participer aux activités",
    "certaines étant gratuites et d'autres payantes",
)
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"): self.hidden += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden: self.hidden -= 1
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

def pinned_get(url, host, limit):
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname != host or p.port not in (None,443)
                or p.username or p.password or p.query or p.fragment):
            raise ValueError("source not pinned")
    except (TypeError, ValueError):
        raise ValueError("source not pinned")
    req = Request(url, headers={"User-Agent": "PtitesOndes-IndependentPlaceGate/1.0"})
    with build_opener(NoRedirect()).open(req, timeout=18) as r:
        if r.status != 200 or r.geturl() != url:
            raise ValueError("source redirect or status mismatch")
        data = r.read(limit+1)
    if len(data) > limit: raise ValueError("source too large")
    return data.decode("utf-8-sig")

def meters(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    da, db = b-a, math.radians(lon2-lon1)
    h = math.sin(da/2)**2 + math.cos(a)*math.cos(b)*math.sin(db/2)**2
    return 12742000*math.asin(min(1, math.sqrt(h)))

def official_proof(html):
    if not isinstance(html,str) or not 200 < len(html) <= 450000:
        raise ValueError("official source unavailable")
    parser = Visible()
    parser.feed(html.replace("\u00ad",""))
    text = norm(" ".join(parser.parts))
    if not all(norm(phrase) in text for phrase in ANCHORS):
        raise ValueError("official identity, conditions or activities changed")

def mapped_proof(xml, p):
    if not isinstance(xml,str) or len(xml)>40000:
        raise ValueError("map unavailable")
    root=ET.fromstring(xml)
    if root.tag!="osm": raise ValueError("invalid map document")
    nodes=[x for x in root.findall("node") if x.get("id")=="2810810943"]
    if len(nodes)!=1: raise ValueError("OSM node missing")
    n=nodes[0]
    tags={t.get("k"):t.get("v") for t in n.findall("tag")}
    expected={"name":"La ludothèque de la Meta","amenity":"toy_library",
              "addr:city":"Nantes","addr:street":"Rue Firmin Colas",
              "addr:housenumber":"20","addr:postcode":"44100"}
    if any(norm(tags.get(k))!=norm(v) for k,v in expected.items()):
        raise ValueError("OSM identity or civic address mismatch")
    lat,lon=float(n.get("lat")),float(n.get("lon"))
    if (not math.isfinite(lat) or not math.isfinite(lon)
            or meters(lat,lon,47.2035757,-1.6073739)>3
            or meters(lat,lon,p["lat"],p["lng"])>5):
        raise ValueError("OSM coordinates mismatch")
    return lat,lon

def verify_private(private,today):
    if (not isinstance(private,dict)
            or private.get("schema")!="ptitesondes.place_release_review.v1"
            or private.get("safe_to_publish") is not False
            or private.get("mode")!="private_proposal_only"
            or not isinstance(private.get("records"),list)
            or not isinstance(private.get("proposals"),list)
            or len(private["records"])>100 or len(private["proposals"])>30):
        raise ValueError("private review invalid or pre-authorized")
    statuses=[x for x in private["records"] if isinstance(x,dict)
              and x.get("city")=="Nantes" and x.get("venue")=="Ludothèque Bellevue"]
    if len(statuses)!=1 or statuses[0].get("status")!="requires_independent_public_preflight":
        raise ValueError("private candidate status not eligible")
    hits=[x for x in private["proposals"] if isinstance(x,dict)
          and x.get("id")==PLACE_ID]
    if len(hits)!=1: raise ValueError("private proposal absent or ambiguous")
    p=hits[0]
    if set(p)!=set(FACTS)|{"lat","lng","reviewed_at"}:
        raise ValueError("private proposal fields mismatch")
    for field,val in FACTS.items():
        if type(p[field]) is not type(val) or p[field]!=val:
            raise ValueError("private proposed field changed: "+field)
    try: stamp=date.fromisoformat(p["reviewed_at"])
    except (TypeError,ValueError): raise ValueError("private review date invalid")
    if not 0 <= (today-stamp).days <= 14:
        raise ValueError("private proposal expired")
    if (type(p["lat"]) is not float or type(p["lng"]) is not float
            or not math.isfinite(p["lat"]) or not math.isfinite(p["lng"])):
        raise ValueError("private coordinates invalid")
    return p

def examine(private,current,official_html,osm_xml,today):
    """Pure verification, no writes. All existing records remain immutable."""
    validate(current)
    p=verify_private(private,today)
    if any(x["id"]==PLACE_ID for x in current["places"]):
        return "already_public", current
    for x in current["places"]:
        if norm(x["city"])!=norm(p["city"]): continue
        if (norm(x["address"])==norm(p["address"])
                or meters(x["lat"],x["lng"],p["lat"],p["lng"])<=80
                or norm(x["name"]) in {norm(p["name"]),
                   norm("Ludothèque Bellevue-Méta"),norm("La ludothèque de la Meta")}):
            raise ValueError("existing permanent place duplicate/alias")
    official_proof(official_html)
    lat,lon=mapped_proof(osm_xml,p)
    added=dict(p,lat=lat,lng=lon)
    next_catalogue={"version":1,"updated_at":today.isoformat(),
                    "places":current["places"]+[added]}
    assert_append_only(current,next_catalogue)
    return "independently_verified",next_catalogue

def private_json(token):
    if not token: raise ValueError("PRIVATE_INTAKE_READ_TOKEN absent")
    data=github(quote(PATH+"/"+PRIVATE,safe="/")+"?ref="+quote(BRANCH,safe=""),token)
    if data.get("encoding")!="base64": raise ValueError("private encoding invalid")
    raw=base64.b64decode(data["content"])
    if len(raw)>100000: raise ValueError("private proposal too large")
    return json.loads(raw)

def live_review(token,current,today):
    private=private_json(token)
    html=pinned_get(OFFICIAL,"parents.loire-atlantique.fr",450000)
    xml=pinned_get(OSM,"api.openstreetmap.org",40000)
    status,proposal=examine(private,current,html,xml,today)
    live=json.loads(pinned_get(PAGES,"sarogal.github.io",1000000))
    validate(live)
    if live!=current: raise ValueError("GitHub Pages baseline differs from main")
    return status,proposal

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("preview","apply"),default="preview")
    p.add_argument("--file",type=Path,default=Path("docs/ptitesondes/lieux.json"))
    args=p.parse_args()
    current=json.loads(args.file.read_text(encoding="utf-8"))
    today=datetime.now(ZoneInfo("Europe/Paris")).date()
    status="deferred"
    try:
        status,new=live_review(os.getenv("PRIVATE_INTAKE_READ_TOKEN",""),current,today)
    except (ValueError,TypeError,KeyError,OSError,ET.ParseError,UnicodeError) as e:
        print("Lieu différé:",str(e)[:150])
    changed=(status=="independently_verified" and args.mode=="apply")
    if changed:
        args.file.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as out:
            out.write("changed="+str(changed).lower()+"\n")
    print("Prévalidation publique indépendante:",status,
          "| publication:", "préparée" if changed else "aucune")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as out:
            out.write("### Lieux P'tites Ondes\nStatut : "+status+
                      "\nMode : "+args.mode+"\n")
if __name__=="__main__": main()
