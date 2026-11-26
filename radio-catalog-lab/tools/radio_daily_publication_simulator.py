"""Memory-only atomic publication simulator. No network, CLI, real key or remote writes."""
from threading import RLock
from radio_daily_baseline_verify import strict_json, verify_baseline
from radio_daily_lab_signing import validate_candidate
from radio_daily_logo_plan import PREVIEW_BASE, EXTENSIONS
from radio_catalog_logo_pilot_probe import decode_image, MAX_LOGO_BYTES
from radio_daily_v9_generator import digest


class MemoryStore:
    """Simulated immutable objects and one compare-and-swap pointer."""
    def __init__(self, pointer, body, *, legacy_logos=None):
        self._lock = RLock()
        self._current = pointer
        self._objects = {"releases/"+digest(body)+".json": body}
        self._legacy = dict(legacy_logos or {})

    def current(self):
        with self._lock:
            return self._current

    def get(self, path):
        with self._lock:
            return self._objects[path]

    def put_immutable(self, path, data):
        with self._lock:
            if path in self._objects and self._objects[path] != data:
                raise ValueError("immutable object conflict")
            self._objects.setdefault(path, data)

    def compare_and_swap(self, expected, replacement):
        with self._lock:
            if self._current != expected:
                raise ValueError("publication concurrency conflict")
            self._current = replacement

    def logo(self, url):
        if url.startswith(PREVIEW_BASE):
            return self.get("objects/sha256/"+url[len(PREVIEW_BASE):])
        # Exact URL mapped to fixture bytes, never a network fetch.
        return self._legacy[url]


def check_logo(logo, data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_LOGO_BYTES:
        raise ValueError("invalid logo bytes")
    if len(data) != logo["byte_size"] or digest(data) != logo["sha256"]:
        raise ValueError("logo digest or length mismatch")
    mime, width, height = decode_image(data)
    if (mime, width, height) != (logo["mime_type"],logo["width"],logo["height"]):
        raise ValueError("logo decode mismatch")


def inventory(doc):
    for station in doc["stations"]:
        logo=station.get("logo")
        if logo is None:
            continue
        url=logo["url"]
        if url.startswith(PREVIEW_BASE):
            path=logo["sha256"]+"."+EXTENSIONS[logo["mime_type"]]
            if url != PREVIEW_BASE+path:
                raise ValueError("logo URL/digest mismatch")
        else:
            path=None
        yield logo, path


def verify_visible(store, pointer, *, sha, sequence, signer):
    """Read the actual pointer, immutable body and every referenced image."""
    if store.current()!=pointer:
        raise ValueError("visible pointer changed")
    body=store.get("releases/"+sha+".json")
    doc=verify_baseline(pointer, body, expected_sha=sha, expected_sequence=sequence,
                        public_key=signer.public_key,key_id=signer.key_id)
    for logo,_ in inventory(doc):
        check_logo(logo,store.logo(logo["url"]))
    if store.current()!=pointer:
        raise ValueError("visible pointer changed during verification")
    return doc


def publish(store, signer, prior_pointer, prior_body, candidate, *, expected_sha,
            expected_sequence, expected_candidate_sha, day, objects=None, checkpoint=None):
    """Simulate exact ordered publication; retry reuses immutable resources.

    No candidate means no version change. Checkpoint is an injected laboratory
    interruption hook, never a network callback. An orphan immutable object
    is safe; it is deliberately not deleted by an interrupted publisher.
    """
    checkpoint=checkpoint or (lambda phase: None)
    objects=dict(objects or {})
    old=verify_baseline(prior_pointer,prior_body,expected_sha=expected_sha,
        expected_sequence=expected_sequence,public_key=signer.public_key,key_id=signer.key_id)
    if candidate is None:
        if expected_candidate_sha is not None or objects:
            raise ValueError("unexpected material for unchanged cycle")
        verify_visible(store,prior_pointer,sha=expected_sha,sequence=expected_sequence,signer=signer)
        return {"changed":False,"sequence":expected_sequence,"publicationAllowed":False}
    new=validate_candidate(prior_pointer,prior_body,candidate,expected_sha=expected_sha,
        expected_sequence=expected_sequence,expected_candidate_sha=expected_candidate_sha,
        public_key=signer.public_key,key_id=signer.key_id,day=day)
    current=store.current()
    if current!=prior_pointer:
        # Retry after an interruption following the pointer swap. Never
        # overwrite a different competing release of the same sequence.
        verify_visible(store,current,sha=expected_candidate_sha,sequence=expected_sequence+1,signer=signer)
        return {"changed":True,"sequence":expected_sequence+1,"resumed":True,"publicationAllowed":False}
    verify_visible(store,prior_pointer,sha=expected_sha,sequence=expected_sequence,signer=signer)
    checkpoint("reference_verified")
    needed={path for _,path in inventory(new) if path is not None}
    if set(objects)-needed:
        raise ValueError("unreferenced artwork object")
    for logo,path in inventory(new):
        data=objects[path] if path in objects else store.logo(logo["url"])
        check_logo(logo,data)
    checkpoint("objects_validated")
    for path,data in sorted(objects.items()):
        store.put_immutable("objects/sha256/"+path,data)
        if store.get("objects/sha256/"+path)!=data:
            raise ValueError("object readback mismatch")
        checkpoint("object_written")
    for logo,_ in inventory(new):
        check_logo(logo,store.logo(logo["url"]))
    checkpoint("objects_visible")
    path="releases/"+expected_candidate_sha+".json"
    store.put_immutable(path,candidate)
    checkpoint("catalogue_written")
    if store.get(path)!=candidate:
        raise ValueError("catalogue readback mismatch")
    checkpoint("catalogue_visible")
    pointer=signer.sign_candidate(prior_pointer,prior_body,candidate,expected_sha=expected_sha,
        expected_sequence=expected_sequence,expected_candidate_sha=expected_candidate_sha,day=day)
    checkpoint("before_pointer_swap")
    # Re-read candidate and all resources just before the atomic operation.
    if store.get(path)!=candidate:
        raise ValueError("catalogue changed before switch")
    for logo,_ in inventory(new):
        check_logo(logo,store.logo(logo["url"]))
    store.compare_and_swap(prior_pointer,pointer)
    checkpoint("after_pointer_swap")
    verify_visible(store,pointer,sha=expected_candidate_sha,sequence=expected_sequence+1,signer=signer)
    return {"changed":True,"sequence":expected_sequence+1,"resumed":False,"publicationAllowed":False}
