"""Select a signed current catalogue against a trusted, verified predecessor.

Selection is offline except for the injected content retrieval. The signed
content path is verified before fetching any bytes. No signing or publication.
"""
import argparse
from pathlib import Path
from radio_daily_baseline_verify import verify_pointer, verify_baseline, strict_json, PUBLIC_KEY, KEY_ID
from radio_daily_v9_generator import BASELINE, check_catalog, digest, encode


def select(pointer, fetch_body, *, prior_pointer=None, prior_body=None,
           expected_sha=BASELINE, expected_sequence=8, public_key=PUBLIC_KEY, key_id=KEY_ID):
    anchor=dict(expected_sha=expected_sha,expected_sequence=expected_sequence,public_key=public_key,key_id=key_id)
    if (prior_pointer is None)!=(prior_body is None):
        raise ValueError("incomplete predecessor material")
    previous=verify_baseline(prior_pointer,prior_body,**anchor) if prior_pointer is not None else None
    if not 0<len(pointer)<=16384:
        raise ValueError("pointer size")
    candidate=strict_json(pointer)
    if not isinstance(candidate,dict):
        raise ValueError("invalid current pointer")
    seq=candidate.get("release_sequence")
    sha=candidate.get("content_sha256")
    if type(seq) is not int or seq<expected_sequence:
        raise ValueError("catalogue rollback refused")
    if seq>expected_sequence+1:
        raise ValueError("missing intermediate signed predecessor")
    if seq==expected_sequence and sha!=expected_sha:
        raise ValueError("same-sequence catalogue equivocation")
    if seq>expected_sequence and previous is None:
        raise ValueError("verified predecessor required for advancement")
    selected=dict(expected_sha=sha,expected_sequence=seq,public_key=public_key,key_id=key_id)
    p=verify_pointer(pointer,**selected)
    if previous is not None and seq==expected_sequence:
        body=prior_body
    else:
        body=fetch_body(p["content_path"],p["content_length"])
    if not isinstance(body,bytes):
        raise ValueError("invalid catalogue body")
    current=verify_baseline(pointer,body,**selected)
    if seq>expected_sequence:
        check_catalog(current,previous=previous)
        tombstones={t["go_station_id"]:t for t in current["tombstones"]}
        if any(tombstones.get(t["go_station_id"])!=t for t in previous["tombstones"]):
            raise ValueError("historical redirect changed")
    return body,{"schemaVersion":1,"publicationAllowed":False,"selectedSequence":seq,
                 "selectedSha256":digest(body),"previousSequence":expected_sequence,
                 "previousSha256":expected_sha,"advanced":seq>expected_sequence,
                 "migrationRequired":seq>expected_sequence,"signatureVerified":True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pointer",type=Path,required=True)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    # Existing workflow remains anchored to the real signed v8. No advancement
    # is authorized until the persisted predecessor and migration are wired.
    if a.pointer.stat().st_size>16384 or a.baseline.stat().st_size>10485760:
        raise ValueError("oversized selection material")
    body,report=select(a.pointer.read_bytes(),lambda path,length:a.baseline.read_bytes())
    if a.report.exists():
        raise ValueError("fresh selection report required")
    a.report.write_bytes(encode(report))
    print("RADIO_SIGNED_BASELINE_SELECTED",report)

if __name__=="__main__":
    main()
