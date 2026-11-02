"""Record lookup and the signed Yes/No decision (FR1, FR6, FR7)."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

SIGNATURE_ALG = "PBKDF2-HMAC-SHA256"


def load_dataset(path: Path) -> dict[str, dict]:
    """Load the synthetic records, keyed by UID. Fails loudly on bad data."""
    with path.open(encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("synthetic") is not True:
        raise ValueError(f"{path} is not marked synthetic")
    records = {r["uid"]: r for r in doc["records"]}
    bad = [uid for uid in records if not uid.startswith("TEST-")]
    if bad:
        raise ValueError(f"{len(bad)} records without the TEST- prefix, e.g. {bad[0]}")
    return records


def _normalise_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def check_factor(record: dict | None, otp: str | None, demo: dict | None) -> str | None:
    """Return None if the factor matches, otherwise the reason it does not."""
    if record is None:
        return "uid_not_found"
    if otp is not None:
        return None if hmac.compare_digest(otp, record["otp"]) else "otp_mismatch"
    # Demographic match: every field the caller sent must match.
    if demo.get("name") is not None and _normalise_name(demo["name"]) != _normalise_name(record["name"]):
        return "demo_mismatch"
    if demo.get("dob") is not None and demo["dob"] != record["dob"]:
        return "demo_mismatch"
    if demo.get("gender") is not None and demo["gender"] != record["gender"]:
        return "demo_mismatch"
    return None


def _signing_payload(txn_id: str, timestamp: str, uid: str, auth: str, reason: str | None) -> bytes:
    return f"{txn_id}|{timestamp}|{uid}|{auth}|{reason or ''}".encode()


def sign(payload: bytes, key: bytes, work: int) -> str:
    """HMAC-SHA256 iterated `work` times. `work` is SIGN_WORK, the CPU knob for E0."""
    return hashlib.pbkdf2_hmac("sha256", payload, key, work).hex()


def authenticate(
    records: dict[str, dict],
    uid: str,
    otp: str | None,
    demo: dict | None,
    key: bytes,
    work: int,
) -> dict:
    """Decide Y or N and sign it, like UIDAI's signed response (report 2.1).

    The signature is computed for every decision, including unknown UIDs, so
    the CPU cost per request is the same whatever the outcome.
    """
    reason = check_factor(records.get(uid), otp, demo)
    auth = "N" if reason else "Y"
    txn_id = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return {
        "uid": uid,
        "auth": auth,
        "reason": reason,
        "txn_id": txn_id,
        "timestamp": timestamp,
        "signature": sign(_signing_payload(txn_id, timestamp, uid, auth, reason), key, work),
        "signature_alg": SIGNATURE_ALG,
        "sign_work": work,
    }


def verify(result: dict, key: bytes) -> bool:
    payload = _signing_payload(
        result["txn_id"], result["timestamp"], result["uid"], result["auth"], result["reason"]
    )
    return hmac.compare_digest(result["signature"], sign(payload, key, result["sign_work"]))
