"""Offline Ed25519 signing rehearsal. No CLI, network, key import or publisher."""
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from radio_catalog_guard import validate_catalog
from radio_daily_baseline_verify import FIELDS, verify_baseline, validate_shape, strict_json
from radio_daily_v9_generator import digest, encode
from radio_stream_recheck_ledger import parse_day


def validate_candidate(prior_pointer, prior_body, candidate, *, expected_sha,
                       expected_sequence, expected_candidate_sha, public_key, key_id, day,
                       logo_evidence=None):
    """Revalidate exact bytes independently of the staging generator's assertions."""
    day = parse_day(day)
    old = verify_baseline(prior_pointer, prior_body, expected_sha=expected_sha,
                          expected_sequence=expected_sequence, public_key=public_key, key_id=key_id)
    if not isinstance(candidate, bytes) or not 0 < len(candidate) <= 10485760:
        raise ValueError("candidate size")
    if digest(candidate) != expected_candidate_sha:
        raise ValueError("candidate digest mismatch")
    new = strict_json(candidate)
    validate_shape(new)
    if new["release_sequence"] != expected_sequence + 1:
        raise ValueError("candidate is not the immediate successor")
    if new["generated_at"] != day + "T00:00:00Z":
        raise ValueError("candidate generation day mismatch")
    if new["stations"] == old["stations"] and new["tombstones"] == old["tombstones"]:
        raise ValueError("no catalogue change")
    tombstones = {t["go_station_id"]: t for t in new["tombstones"]}
    if any(tombstones.get(t["go_station_id"]) != t for t in old["tombstones"]):
        raise ValueError("historical redirect changed")
    # A legacy row can change only through a dedicated evidence gate.
    # This gate permits an exact logo-only successor; not a caller-supplied
    # list of authorized rows or a generic waiver. All other fields survive.
    reference = old
    if logo_evidence is not None:
        from radio_daily_logo_release_validation import expected_logo_release
        if not isinstance(logo_evidence, dict) or set(logo_evidence) != {
                "logo_maintenance", "missing_logo", "artwork", "objects"}:
            raise ValueError("invalid logo evidence contract")
        rebuilt = expected_logo_release(prior_body, expected_sha=expected_sha,
            expected_sequence=expected_sequence, day=day, **logo_evidence)
        if candidate != rebuilt:
            raise ValueError("unauthorized catalogue delta")
        reference = strict_json(rebuilt)
        reference["release_sequence"] = old["release_sequence"]
        reference["generated_at"] = old["generated_at"]
    issues = validate_catalog(new, mode="publish", previous=reference, authenticated_legacy=True)
    if issues:
        raise ValueError("publication guard refused: " + "; ".join(issues[:8]))
    if any(stream["state"] == "candidate_verified"
           for station in new["stations"] for stream in station["streams"]):
        raise ValueError("unresolved candidate_verified stream")
    return new


class EphemeralLabSigner:
    """Own an in-memory random key; never accept external/private key material."""
    def __init__(self):
        self._key = Ed25519PrivateKey.generate()
        raw = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.public_key = base64.b64encode(raw).decode("ascii")
        self.key_id = "radio-lab-" + digest(raw)[:24]

    def sign_candidate(self, prior_pointer, prior_body, candidate, *, expected_sha,
                       expected_sequence, expected_candidate_sha, day, logo_evidence=None):
        new = validate_candidate(prior_pointer, prior_body, candidate,
                                 expected_sha=expected_sha, expected_sequence=expected_sequence,
                                 expected_candidate_sha=expected_candidate_sha,
                                 public_key=self.public_key, key_id=self.key_id, day=day,
                                 logo_evidence=logo_evidence)
        pointer = dict(schema_version=1, catalog_id="grosses-ondes-radio",
                       release_sequence=new["release_sequence"], published_at=day+"T00:00:00Z",
                       content_sha256=expected_candidate_sha, content_length=len(candidate),
                       content_path="releases/"+expected_candidate_sha+".json")
        message = ("GO-RADIO-CATALOG-POINTER-V1\n" +
                   "".join(str(pointer[k])+"\n" for k in FIELDS)+self.key_id+"\n").encode()
        pointer["signature"] = dict(algorithm="Ed25519", key_id=self.key_id,
                                    signature_base64=base64.b64encode(self._key.sign(message)).decode("ascii"))
        result = encode(pointer)
        # Independent verifier uses the existing Android-compatible contract.
        verify_baseline(result, candidate, expected_sha=expected_candidate_sha,
                        expected_sequence=new["release_sequence"],
                        public_key=self.public_key, key_id=self.key_id)
        return result
