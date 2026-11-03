"""Unit tests for tests/locustfile.py (PLAN step 9).

These exercise the dataset parsing and payload shaping without starting a Locust
runner. Importing the locustfile loads the real synthetic dataset, which also
checks it stays parseable.
"""

from __future__ import annotations

import importlib
import json

import pytest

locustfile = pytest.importorskip("locustfile")  # skip if locust isn't installed


def test_dataset_loads_credentials():
    creds = locustfile._credentials
    assert creds, "the synthetic dataset should yield at least one record"
    first = creds[0]
    assert first["uid"].startswith("TEST-")      # FR6 fake-ID format
    assert "otp" in first and "demo" in first


def test_load_credentials_rejects_empty(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"records": []}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        locustfile._load_credentials(empty)


def test_load_credentials_parses_demo_fields(tmp_path):
    ds = tmp_path / "ds.json"
    ds.write_text(json.dumps({"records": [
        {"uid": "TEST-0000-0000-0001", "otp": "000001",
         "name": "Canary", "dob": "2000-01-01", "gender": "T"},
    ]}), encoding="utf-8")
    creds = locustfile._load_credentials(ds)
    assert creds[0]["demo"] == {"name": "Canary", "dob": "2000-01-01", "gender": "T"}


def test_user_class_is_paced_and_fast():
    # FastHttpUser gives the throughput these experiments need (5.3.4, ref 68).
    from locust import FastHttpUser
    assert issubclass(locustfile.AuthUser, FastHttpUser)
    # constant_throughput wait_time is set from LOCUST_RPS_PER_USER.
    assert callable(locustfile.AuthUser.wait_time)


def test_clean_endpoint_recovers_msys_mangling():
    # Git-Bash rewrites /api/v1/... into a Windows path; recover the real path.
    clean = locustfile._clean_endpoint
    assert clean("/api/v1/authenticate") == "/api/v1/authenticate"
    assert clean("C:/Program Files/Git/api/v1/authenticate") == "/api/v1/authenticate"
    assert clean("C:\\Program Files\\Git\\api\\v1\\authenticate") == "/api/v1/authenticate"
    assert clean("health") == "/health"     # bare path still made absolute


def test_env_knobs_respected(monkeypatch):
    monkeypatch.setenv("LOCUST_RPS_PER_USER", "7")
    monkeypatch.setenv("LOCUST_ENDPOINT", "/custom")
    monkeypatch.setenv("LOCUST_FACTOR", "demo")
    reloaded = importlib.reload(locustfile)
    try:
        assert reloaded.RPS_PER_USER == 7.0
        assert reloaded.ENDPOINT == "/custom"
        assert reloaded.FACTOR == "demo"
    finally:
        # Restore the module to its default state for other tests.
        monkeypatch.undo()
        importlib.reload(reloaded)
