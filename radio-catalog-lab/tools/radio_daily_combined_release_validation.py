"""Compose independently validated operation candidates against one signed baseline.

No generator report or caller-provided validation function is trusted.
Conflicting station edits and newly introduced endpoint collisions are held.
The strict signer and real-catalogue isolation remain unchanged.
"""
import copy
from radio_daily_baseline_verify import strict_json, verify_baseline
from radio_daily_lab_signing import validate_candidate
from radio_daily_logo_release_validation import validate_logo_release
from radio_daily_status_release_validation import validate_status_release
from radio_daily_merge_release_validation import validate_merge_release
from radio_daily_repair_release_validation import validate_repair_release
from radio_daily_admission_release_validation import validate_admission_release
from radio_daily_publication_simulator import publish
from radio_daily_v9_generator import digest, encode

GATES = {
    "logo": validate_logo_release,
    "status": validate_status_release,
    "merge": validate_merge_release,
    "repair": validate_repair_release,
    "admission": validate_admission_release,
}


def compose(prior_pointer, prior_body, *, anchor, day, operations, objects):
    old = verify_baseline(prior_pointer, prior_body, **anchor)
    if not isinstance(operations,dict) or set(operations)-set(GATES):
        raise ValueError("unknown combined operation")
    if not operations:
        if objects:
            raise ValueError("unexpected combined artwork")
        return None
    original = {s["go_station_id"]: s for s in old["stations"]}
    reserved = set(original) | {t["go_station_id"] for t in old["tombstones"]}
    original_urls = {u for s in old["stations"] for v in s["streams"]
                     for u in [v["url"], *v.get("previous_urls",[])]}
    introduced_urls = set()
    touched = set()
    replacements = {}
    additions = {}
    removals = set()
    tombs = []
    required = {}
    for kind in sorted(operations):
        item = operations[kind]
        if not isinstance(item,dict) or set(item) != {"candidate","evidence"}:
            raise ValueError("invalid combined operation material")
        body = item["candidate"]
        evidence = item["evidence"]
        if not isinstance(evidence,dict) or set(evidence)&{"anchor","day"}:
            raise ValueError("invalid combined evidence binding")
        if GATES[kind](prior_pointer,prior_body,body,anchor=anchor,day=day,**evidence) != digest(body):
            raise ValueError("operation digest mismatch")
        if kind == "logo":
            required.update(evidence["objects"])
        doc = strict_json(body)
        rows = {r["go_station_id"]:r for r in doc["stations"]}
        local = {sid for sid in original if rows.get(sid) != original[sid]}
        new_tombs = doc["tombstones"][len(old["tombstones"]):]
        local.update(t["redirect_to"] for t in new_tombs if "redirect_to" in t)
        new_ids = set(rows)-set(original)
        if (local | new_ids)&touched or new_ids&reserved:
            raise ValueError("combined station conflict")
        touched.update(local | new_ids)
        for sid in set(original)-set(rows):
            removals.add(sid)
        for sid in local & set(rows):
            if rows[sid] != original[sid]:
                replacements[sid] = rows[sid]
        for sid in new_ids:
            additions[sid] = rows[sid]
        for sid in (local & set(rows)) | new_ids:
            before = {v["url"] for v in original.get(sid,{}).get("streams",[])}
            for stream in rows[sid]["streams"]:
                url = stream["url"]
                if url not in before:
                    if url in original_urls or url in introduced_urls:
                        raise ValueError("combined endpoint collision")
                    introduced_urls.add(url)
        tombs.extend(new_tombs)
    if objects != required:
        raise ValueError("combined artwork inventory mismatch")
    expected = copy.deepcopy(old)
    expected["stations"] = [replacements.get(r["go_station_id"],r)
        for r in expected["stations"] if r["go_station_id"] not in removals]
    expected["stations"].extend(additions[sid] for sid in sorted(additions))
    expected["tombstones"].extend(tombs)
    expected.update(release_sequence=anchor["expected_sequence"]+1,
                    generated_at=day+"T00:00:00Z")
    body = encode(expected)
    validate_candidate(prior_pointer,prior_body,body,
        expected_candidate_sha=digest(body),day=day,**anchor)
    return body


def validate_combined(prior_pointer,prior_body,candidate,**kwargs):
    if candidate != compose(prior_pointer,prior_body,**kwargs):
        raise ValueError("unauthorized combined catalogue delta")
    return digest(candidate) if candidate is not None else None


def publish_combined(store,signer,prior_pointer,prior_body,candidate,*,
                     expected_sha,expected_sequence,expected_candidate_sha,
                     day,operations,objects,checkpoint=None):
    anchor=dict(expected_sha=expected_sha,expected_sequence=expected_sequence,
                public_key=signer.public_key,key_id=signer.key_id)
    verified=validate_combined(prior_pointer,prior_body,candidate,
        anchor=anchor,day=day,operations=operations,objects=objects)
    if verified != expected_candidate_sha:
        raise ValueError("combined validated digest mismatch")
    return publish(store,signer,prior_pointer,prior_body,candidate,
        expected_sha=expected_sha,expected_sequence=expected_sequence,
        expected_candidate_sha=verified,day=day,objects=objects,checkpoint=checkpoint)
