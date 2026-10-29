"""Lecture de la veille privée par GitHub API (accès lecture seule)."""
import base64
from datetime import date
import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

BRANCH="automation/ptitesondes-intake"
PATH="automation-intake/ptitesondes"
ROOT="https://api.github.com/repos/Sarogal/PtitesOndes/contents/"

def github(path, token):
    req=Request(ROOT+path,headers={
        "Accept":"application/vnd.github+json",
        "Authorization":"Bearer "+token,
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"OndesCloudSync/1.0",
    })
    with urlopen(req,timeout=30) as result:
        data=result.read(1_500_001)
    if len(data)>1_500_000:raise ValueError("Réponse Github trop volumineuse")
    return json.loads(data)

def latest(token,today):
    if not token:raise ValueError("Secret privé manquant")
    suffix="?ref="+quote(BRANCH,safe="")
    files=github(PATH+suffix,token)
    if not isinstance(files,list):raise ValueError("Dossier des veilles introuvable")
    matches=[]
    for f in files:
        m=re.fullmatch(r"patch-(\d{4}-\d{2}-\d{2})\.json",f.get("name",""))
        if f.get("type")=="file" and m:
            day=date.fromisoformat(m.group(1))
            if day<=today:matches.append((day,f["path"]))
    if not matches:raise ValueError("Aucune veille disponible")
    day,path=max(matches)
    if (today-day).days>3:raise ValueError("Veille trop ancienne")
    response=github(quote(path,safe="/")+suffix,token)
    if response.get("encoding")!="base64":raise ValueError("Encodage Github incorrect")
    blob=base64.b64decode(response["content"])
    if len(blob)>1_000_000:raise ValueError("Veille trop volumineuse")
    patch=json.loads(blob)
    if patch.get("generated_at")!=day.isoformat():raise ValueError("Date différente du nom de fichier")
    return patch,path
