"""Read-only GitHub Git Data API adapter for the isolated lab branch.

No credential lookup or default network client. The injected read_json
receives only fixed-repository GET paths and a response byte limit.
It must distinguish a genuine 404 from all other HTTP/network errors.
No branch creation, signing, write or publication is implemented.
"""
import base64
import hashlib
import re

from radio_daily_git_lab_transport import OID, REF, ZERO
from radio_daily_github_transfer_contract import DESTINATION
from radio_daily_git_lab_reader import HISTORY, RELEASE, ARTWORK

API = "https://api.github.com/repos/Sarogal/Ondes-Catalogues"
MAX_TREE = 4 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_ENTRIES = 12000


def git_oid(kind, data):
    return hashlib.sha1((kind+" "+str(len(data))+"\0").encode()+data).hexdigest()


def object_limit(path):
    if path == "pointer.json" or HISTORY.fullmatch(path):
        return 16384
    if RELEASE.fullmatch(path):
        return 10485760
    if ARTWORK.fullmatch(path):
        return 2097152
    return 0


class GitHubReadback:
    def __init__(self, read_json):
        if not callable(read_json):
            raise ValueError("explicit bounded JSON reader required")
        self.read_json = read_json

    def _read(self, path, limit, *, missing=False):
        status, obj = self.read_json(API+path, limit)
        if type(status) is not int:
            raise ValueError("invalid GitHub HTTP status")
        if missing and status == 404:
            return None
        if status != 200 or not isinstance(obj, dict):
            raise ValueError("GitHub read unavailable")
        return obj

    def read_head(self, destination, ref):
        if destination != DESTINATION or ref != REF:
            raise ValueError("unauthorized GitHub read destination")
        data = self._read("/git/ref/"+REF.removeprefix("refs/"), 16384, missing=True)
        if data is None:
            return ZERO
        obj = data.get("object")
        if (data.get("ref") != REF or not isinstance(obj,dict)
                or obj.get("type") != "commit" or not isinstance(obj.get("sha"),str)
                or not OID.fullmatch(obj["sha"]) or obj["sha"] == ZERO):
            raise ValueError("invalid remote ref")
        return obj["sha"]

    def read_tree(self, destination, commit):
        if (destination != DESTINATION or not isinstance(commit,str)
                or not OID.fullmatch(commit) or commit == ZERO):
            raise ValueError("unauthorized GitHub commit read")
        meta = self._read("/git/commits/"+commit, 65536)
        root = meta.get("tree")
        if (meta.get("sha") != commit or not isinstance(root,dict)
                or not isinstance(root.get("sha"),str) or not OID.fullmatch(root["sha"])):
            raise ValueError("invalid remote commit")
        # Traverse nonrecursive trees: no query-string redirects or truncated
        # recursive responses, and independently recompute every tree hash.
        result = {}
        seen = set()
        cached = {}
        total = 0
        count = 0
        def walk(oid, prefix, depth):
            nonlocal total, count
            if depth > 3 or oid in seen:
                raise ValueError("invalid Git tree nesting")
            seen.add(oid)
            doc = self._read("/git/trees/"+oid, MAX_TREE)
            entries = doc.get("tree")
            if doc.get("sha") != oid or doc.get("truncated") is not False or not isinstance(entries,list):
                raise ValueError("incomplete remote Git tree")
            rows = []
            names = set()
            for item in entries:
                count += 1
                if count > MAX_ENTRIES or not isinstance(item,dict):
                    raise ValueError("remote Git tree budget")
                name, mode, kind, child = (item.get(k) for k in ("path","mode","type","sha"))
                if (not isinstance(name,str) or not re.fullmatch(r"[a-zA-Z0-9._-]+",name)
                        or name in (".","..") or name in names
                        or not isinstance(child,str) or not OID.fullmatch(child)):
                    raise ValueError("invalid remote tree entry")
                names.add(name)
                path = prefix+name
                if mode == "040000" and kind == "tree":
                    if path not in ("history","releases","objects","objects/sha256"):
                        raise ValueError("unexpected remote Git directory")
                    rows.append((name+"/",b"40000 "+name.encode()+b"\0"+bytes.fromhex(child)))
                    walk(child,path+"/",depth+1)
                    continue
                limit = object_limit(path)
                size = item.get("size")
                if (mode != "100644" or kind != "blob" or type(size) is not int
                        or not 0 < size <= limit or total+size > MAX_TOTAL or path in result):
                    raise ValueError("unexpected remote Git blob")
                rows.append((name,b"100644 "+name.encode()+b"\0"+bytes.fromhex(child)))
                if child not in cached:
                    blob = self._read("/git/blobs/"+child, 2*size+16384)
                    if (blob.get("sha") != child or blob.get("encoding") != "base64"
                            or blob.get("size") != size or not isinstance(blob.get("content"),str)):
                        raise ValueError("invalid remote blob metadata")
                    data = base64.b64decode("".join(blob["content"].splitlines()),validate=True)
                    if len(data) != size or git_oid("blob",data) != child:
                        raise ValueError("remote blob hash mismatch")
                    cached[child] = data
                data = cached[child]
                if len(data) != size:
                    raise ValueError("remote blob size mismatch")
                result[path] = data
                total += size
            if git_oid("tree",b"".join(row for _,row in sorted(rows))) != oid:
                raise ValueError("remote tree hash mismatch")
            seen.remove(oid)
        walk(root["sha"],"",0)
        return result
