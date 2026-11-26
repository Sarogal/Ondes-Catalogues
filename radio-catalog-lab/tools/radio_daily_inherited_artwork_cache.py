"""Incrementally stage exact signed-baseline artwork, never publish a catalogue."""
import argparse
import datetime as dt
import http.client
import re
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

from radio_daily_baseline_verify import verify_baseline, PUBLIC_KEY, KEY_ID
from radio_daily_publication_simulator import check_logo, inventory
from radio_daily_logo_plan import EXTENSIONS
from radio_catalog_logo_pilot_probe import fetch_strict_https, MAX_LOGO_BYTES
from radio_daily_v9_generator import digest, encode
from radio_stream_recheck_ledger import parse_day

MAX_OBJECTS = 12
MAX_LOCAL_OBJECTS = 100
MAX_LOCAL_BYTES = 32 * 1024 * 1024
MAX_SECONDS = 90
WORKERS = 4
FIRST_PARTY = "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"


def filename(logo):
    sha = logo["sha256"]
    if not re.fullmatch("[a-f0-9]{64}", sha):
        raise ValueError("invalid artwork digest")
    return sha + "." + EXTENSIONS[logo["mime_type"]]


def cached(logo, directories):
    for directory in directories:
        directory = Path(directory)
        if directory.is_symlink():
            raise ValueError("unsafe artwork cache directory")
        path = directory / filename(logo)
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_size != logo["byte_size"] or info.st_size > MAX_LOGO_BYTES:
            raise ValueError("invalid cached artwork file")
        data = path.read_bytes()
        check_logo(logo, data)
        return data
    return None


def populate(pointer, raw, *, anchor, day, previous, output, limit=MAX_OBJECTS,
             fetch=fetch_strict_https, clock=time.monotonic, local_sources=()):
    doc = verify_baseline(pointer, raw, **anchor)
    day = parse_day(day)
    if type(limit) is not int or not 0 <= limit <= MAX_OBJECTS:
        raise ValueError("artwork cache budget")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    entries = {}
    for logo, path in inventory(doc):
        if path is None:
            entries.setdefault(filename(logo), {})[logo["url"]] = logo
    missing = []
    hits = 0
    local_count = local_bytes = local_rejected = 0
    for name, sources in sorted(entries.items()):
        representative = next(iter(sources.values()))
        if cached(representative, (previous,)) is not None:
            hits += 1
        else:
            data = None
            if (local_count < MAX_LOCAL_OBJECTS
                    and local_bytes + representative["byte_size"] <= MAX_LOCAL_BYTES
                    and any(u.startswith(FIRST_PARTY) for u in sources)):
                for directory in local_sources:
                    try:
                        data = cached(representative, (directory,))
                    except (ValueError, OSError, RuntimeError):
                        local_rejected += 1
                        continue
                    if data is not None:
                        break
            if data is None:
                missing.append((name, sources))
            else:
                with (output/name).open("xb") as target:
                    target.write(data)
                local_count += 1
                local_bytes += len(data)
    # Prioritize already content-addressed repository objects, then rotate
    # each lane daily so a failing URL cannot permanently starve later ones.
    rotation = dt.date.fromisoformat(day).toordinal() * MAX_OBJECTS
    def rotate(items):
        if not items:
            return items
        offset = rotation % len(items)
        return items[offset:] + items[:offset]
    first = [x for x in missing if any(u.startswith(FIRST_PARTY) for u in x[1])]
    other = [x for x in missing if x not in first]
    queue = (rotate(first)[:limit//2] + rotate(other)[:limit-limit//2])
    selected = {x[0] for x in queue}
    queue += [x for x in rotate(first)+rotate(other) if x[0] not in selected][:limit-len(queue)]
    deadline = clock() + MAX_SECONDS
    def load(item):
        name, sources = item
        urls = sorted(sources, key=lambda u:(not u.startswith(FIRST_PARTY),u))
        url = urls[rotation % len(urls)] if not urls[0].startswith(FIRST_PARTY) else urls[0]
        logo = sources[url]
        try:
            data, mime = fetch(url, urlsplit(url).hostname)
            if mime != logo["mime_type"]:
                raise ValueError("artwork MIME mismatch")
            check_logo(logo,data)
            return name,data
        except (ValueError,OSError,RuntimeError,http.client.HTTPException):
            return name,None
    attempted = recovered = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i in range(0,len(queue),WORKERS):
            if clock() >= deadline:
                break
            batch = queue[i:i+WORKERS]
            for name,data in pool.map(load,batch):
                attempted += 1
                if data is not None:
                    with (output/name).open("xb") as target:
                        target.write(data)
                    recovered += 1
    return dict(schemaVersion=1,publicationAllowed=False,scanDate=day,
        catalogBaselineSha256=anchor["expected_sha"],objectCount=len(entries),
        cachedCount=hits,recoveredCount=recovered+local_count,attemptedCount=attempted,
        localImportedCount=local_count,localImportedBytes=local_bytes,
        localRejectedCount=local_rejected,networkRecoveredCount=recovered,
        availableCount=hits+recovered+local_count,remainingCount=len(entries)-hits-recovered-local_count)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("pointer","baseline","previous","output","report"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--baseline-sha256",required=True)
    p.add_argument("--baseline-sequence",type=int,required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--local-source",type=Path,action="append",default=[])
    args=p.parse_args()
    report=populate(args.pointer.read_bytes(),args.baseline.read_bytes(),
        anchor=dict(expected_sha=args.baseline_sha256,expected_sequence=args.baseline_sequence,
                    public_key=PUBLIC_KEY,key_id=KEY_ID),day=args.day,previous=args.previous,
        output=args.output,local_sources=args.local_source)
    with args.report.open("xb") as target:
        target.write(encode(report))
    print("INHERITED_ARTWORK_CACHE",report)


if __name__=="__main__":
    main()
