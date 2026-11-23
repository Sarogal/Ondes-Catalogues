"""Read the private P'tites Ondes intake without modifying its source branch.

GitHub Contents only embeds Base64 for files up to 1 MiB. A large national
research queue has no inlined body, so read its immutable Git Blob by SHA.
Verify both the immutable SHA-1 object identity and exact byte count before
handing any untrusted patch to the already strict Publisher.
"""
import base64
import binascii
from datetime import date
import hashlib
import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

BRANCH = "automation/ptitesondes-intake"
PATH = "automation-intake/ptitesondes"
ROOT = "https://api.github.com/repos/Sarogal/PtitesOndes/"
MAX_JSON_RESPONSE = 8_000_000
MAX_PRIVATE_PATCH = 5_000_000
BLOB_SHA = re.compile(r"[0-9a-f]{40}\Z")


def github(path, token, *, blob=False):
    """Read exclusively the pinned contents or Git-blob API path."""
    if not isinstance(path, str):
        raise ValueError("Chemin GitHub invalide")
    if blob:
        if BLOB_SHA.fullmatch(path) is None:
            raise ValueError("Empreinte Git Blob invalide")
        endpoint = "git/blobs/" + path
    else:
        if not path.startswith(PATH + ("/", "?")):
            raise ValueError("Chemin de veille privée invalide")
        endpoint = "contents/" + path
    req = Request(ROOT + endpoint, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "OndesCloudSync/1.0",
    })
    with urlopen(req, timeout=30) as response:
        data = response.read(MAX_JSON_RESPONSE + 1)
    if len(data) > MAX_JSON_RESPONSE:
        raise ValueError("Réponse Github trop volumineuse")
    return json.loads(data)


def latest(token, today):
    if not token:
        raise ValueError("Secret privé manquant")
    suffix = "?ref=" + quote(BRANCH, safe="")
    files = github(PATH + suffix, token)
    if not isinstance(files, list):
        raise ValueError("Dossier des veilles introuvable")
    matches = []
    for f in files:
        if not isinstance(f, dict):
            raise ValueError("Entrée GitHub invalide")
        name = f.get("name", "")
        m = re.fullmatch(r"patch-(\d{4}-\d{2}-\d{2})\.json", name)
        if f.get("type") != "file" or m is None:
            continue
        day = date.fromisoformat(m.group(1))
        path = f.get("path")
        sha = f.get("sha")
        size = f.get("size")
        if (path != PATH + "/" + name
                or type(size) is not int or not 0 < size <= MAX_PRIVATE_PATCH
                or not isinstance(sha, str) or BLOB_SHA.fullmatch(sha) is None):
            raise ValueError("Fichier privé GitHub non vérifiable")
        if day <= today:
            matches.append((day, path, sha, size))
    if not matches:
        raise ValueError("Aucune veille disponible")
    day, path, sha, size = max(matches)
    if (today - day).days > 3:
        raise ValueError("Veille trop ancienne")
    # GitHub Contents returns encoding=none and content="" for >1 MiB.
    # Reading the immutable blob also prevents a race if the private branch
    # advances between listing and content retrieval.
    response = github(sha, token, blob=True)
    if (not isinstance(response, dict) or response.get("encoding") != "base64"
            or response.get("sha") != sha or response.get("size") != size
            or not isinstance(response.get("content"), str)):
        raise ValueError("Réponse Git Blob incorrecte")
    try:
        raw = base64.b64decode(response["content"], validate=False)
    except (ValueError, binascii.Error):
        raise ValueError("Base64 Git Blob incorrect") from None
    if len(raw) != size or len(raw) > MAX_PRIVATE_PATCH:
        raise ValueError("Taille du Git Blob incorrecte")
    actual_sha = hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()
    if actual_sha != sha:
        raise ValueError("Intégrité du Git Blob incorrecte")
    patch = json.loads(raw)
    if not isinstance(patch, dict) or patch.get("generated_at") != day.isoformat():
        raise ValueError("Date différente du nom de fichier")
    return patch, path
