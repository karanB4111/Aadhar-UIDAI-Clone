import json

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import CANARY_OTP, CANARY_UID
from app.main import app, settings

IDENTITY = ("instance_id", "az", "region", "app_version")
IDENTITY_HEADERS = ("x-instance-id", "x-az", "x-region", "x-app-version")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def record(client):
    # Any generated (non-canary) record.
    return next(r for uid, r in app.state.records.items() if uid != CANARY_UID)


def assert_identity(resp, body=True):
    for h in IDENTITY_HEADERS:
        assert resp.headers[h]
    if body:
        data = resp.json()
        for field in IDENTITY:
            assert data[field] == getattr(settings, field)


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["synthetic_data_only"] is True
    assert_identity(resp)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert_identity(resp)


def test_health_deep(client):
    resp = client.get("/health/deep")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert_identity(resp)


def test_health_deep_fails_without_canary(client):
    # Starlette's State does not undo cleanly with monkeypatch, so swap by hand.
    original = app.state.records
    app.state.records = {uid: r for uid, r in original.items() if uid != CANARY_UID}
    try:
        resp = client.get("/health/deep")
    finally:
        app.state.records = original
    assert resp.status_code == 503
    assert resp.json()["error"] == "canary_failed"


def test_otp_yes_and_signature_verifies(client):
    resp = client.post("/api/v1/authenticate", json={"uid": CANARY_UID, "otp": CANARY_OTP})
    assert resp.status_code == 200
    data = resp.json()
    assert data["auth"] == "Y" and data["reason"] is None
    assert data["sign_work"] == settings.sign_work
    assert auth.verify(data, settings.signing_key)
    assert_identity(resp)


def test_tampered_response_fails_verification(client):
    data = client.post("/api/v1/authenticate", json={"uid": CANARY_UID, "otp": CANARY_OTP}).json()
    data["auth"] = "N"
    assert not auth.verify(data, settings.signing_key)


def test_otp_mismatch(client, record):
    wrong = f"{(int(record['otp']) + 1) % 1_000_000:06d}"
    data = client.post("/api/v1/authenticate", json={"uid": record["uid"], "otp": wrong}).json()
    assert data["auth"] == "N" and data["reason"] == "otp_mismatch"


def test_unknown_uid_is_signed_no(client):
    data = client.post("/api/v1/authenticate", json={"uid": "TEST-9999-9999-9999", "otp": "123456"}).json()
    assert data["auth"] == "N" and data["reason"] == "uid_not_found"
    assert auth.verify(data, settings.signing_key)


def test_demo_match_ignores_case_and_spacing(client, record):
    demo = {"name": "  " + record["name"].upper().replace(" ", "   "), "dob": record["dob"], "gender": record["gender"]}
    data = client.post("/api/v1/authenticate", json={"uid": record["uid"], "demo": demo}).json()
    assert data["auth"] == "Y"


def test_demo_partial_match(client, record):
    data = client.post("/api/v1/authenticate", json={"uid": record["uid"], "demo": {"dob": record["dob"]}}).json()
    assert data["auth"] == "Y"


def test_demo_mismatch(client, record):
    data = client.post("/api/v1/authenticate", json={"uid": record["uid"], "demo": {"dob": "1900-01-01"}}).json()
    assert data["auth"] == "N" and data["reason"] == "demo_mismatch"


@pytest.mark.parametrize("body", [
    {"uid": "1234-5678-9012", "otp": "123456"},           # real-looking number
    {"uid": "123456789012", "otp": "123456"},
    {"uid": CANARY_UID},                                    # no factor
    {"uid": CANARY_UID, "otp": CANARY_OTP, "demo": {"gender": "T"}},  # two factors
    {"uid": CANARY_UID, "demo": {}},                        # empty demo
    {"uid": CANARY_UID, "otp": "12ab56"},
])
def test_rejects_bad_requests(client, body):
    resp = client.post("/api/v1/authenticate", json=body)
    assert resp.status_code == 422
    assert_identity(resp, body=False)


def test_transaction_ids_are_unique(client):
    ids = {
        client.post("/api/v1/authenticate", json={"uid": CANARY_UID, "otp": CANARY_OTP}).json()["txn_id"]
        for _ in range(20)
    }
    assert len(ids) == 20


def test_load_dataset_rejects_real_looking_ids(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"synthetic": True, "records": [{"uid": "1234-5678-9012"}]}))
    with pytest.raises(ValueError, match="TEST- prefix"):
        auth.load_dataset(path)


def test_load_dataset_requires_synthetic_flag(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"records": []}))
    with pytest.raises(ValueError, match="synthetic"):
        auth.load_dataset(path)
