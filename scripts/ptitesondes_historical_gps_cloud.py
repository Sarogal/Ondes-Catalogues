"""Prepare a GPS-only repair during the existing serialized cloud sync.

Private inputs are hints only. No persisted candidate or private patch is
trusted to authorize a historical edit. Git must commit ledger and catalogue
together before the existing Pages deployment.
"""
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import quote

from private_intake import github, BRANCH, PATH, BLOB_SHA
from ptitesondes_acceslibre_geo_hints import load_hints, hinted_researcher
from ptitesondes_catalogue_geo_correction_preview import digest
from ptitesondes_historical_gps_apply_guard import prepare_corrections
from ptitesondes_historical_gps_ledger import reconcile, record_validated_repairs

LEDGER_PATH = Path("reviews/ptitesondes-historical-gps-ledger.json")
INPUTS = frozenset(("catalogue-geo-rotation.json",
                    "catalogue-geo-correction-progress.json",
                    "acceslibre-geo-hints.json"))
MAX_PRIVATE_BYTES = 2_000_000


def read_private_json(name, token, *, reader=github):
    if name not in INPUTS:
        raise ValueError("unknown_gps_input")
    path = PATH + "/" + name
    try:
        meta = reader(path + "?ref=" + quote(BRANCH, safe=""), token)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if (not isinstance(meta, dict) or meta.get("type") != "file"
            or meta.get("path") != path
            or type(meta.get("size")) is not int
            or not 0 < meta["size"] <= MAX_PRIVATE_BYTES
            or not isinstance(meta.get("sha"), str)
            or BLOB_SHA.fullmatch(meta["sha"]) is None):
        raise ValueError("invalid_private_gps_metadata")
    blob = reader(meta["sha"], token, blob=True)
    if (not isinstance(blob, dict) or blob.get("encoding") != "base64"
            or blob.get("sha") != meta["sha"] or blob.get("size") != meta["size"]
            or not isinstance(blob.get("content"), str)):
        raise ValueError("invalid_private_gps_blob")
    raw = base64.b64decode(blob["content"])
    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if len(raw) != meta["size"] or sha != meta["sha"]:
        raise ValueError("private_gps_blob_integrity")
    return json.loads(raw)


def prepare_cloud_repairs(reference, current, ledger, today, token, *, reader=read_private_json,
                          researcher_factory=hinted_researcher, diagnostics=None, **research_readers):
    """Return current unchanged when no private queue or no verified proposal."""
    effective = reconcile(reference, current, ledger)
    checkpoint = reader("catalogue-geo-rotation.json", token)
    if checkpoint is None:
        if diagnostics is not None:
            diagnostics["checkpoint_missing"] = 1
        return current, ledger, 0
    progress = reader("catalogue-geo-correction-progress.json", token)
    hints = reader("acceslibre-geo-hints.json", token)
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "hints.json"
        if hints is not None:
            path.write_text(json.dumps(hints, ensure_ascii=False), encoding="utf-8")
        researcher = researcher_factory(load_hints(path, today))
    corrected, audit, count = prepare_corrections(
        effective, current, today, checkpoint, progress=progress,
        researcher=researcher, **research_readers)
    if diagnostics is not None:
        for name in ("candidate_groups", "examined_groups", "source_reads", "proposed_count"):
            diagnostics[name] = audit[name]
        for name in ("fresh_proof_missing_or_changed", "event_identity_unconfirmed"):
            diagnostics[name] = audit["reasons"][name]
    if not count:
        return current, ledger, 0
    updated = record_validated_repairs(reference, current, corrected, ledger, audit, today)
    return corrected, updated, count
