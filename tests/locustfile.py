"""Load test for the mock service (PLAN step 9, ARCHITECTURE.md 5.3.3-5.3.4, 8.3).

Drives the Tier 2 ALB from a laptop with Locust to measure latency against load
and against instance count. Three experiments use the same file (8.4):

* E0  calibration: ramp the rate on a single instance (ASG min=desired=max=1,
      scaling off) until errors or the server-side p95 doubles. Fixes SIGN_WORK
      and R_max.
* E5a fixed-capacity sweep: hold 0.9 x R_max at N=1 then N=2 instances (scaling
      off), to chart response time against instance count.
* E5b autoscaling step: one load step 0.8 -> 1.6 x R_max, held 10 min each way,
      so the target-tracking policy moves desired 1 -> 2 and back.

Design choices (ARCHITECTURE.md 5.3.4, 8.3):

* ``FastHttpUser`` with keep-alive on. One process can drive thousands of
  requests/s, well past the 100-400/s these experiments need [68].
* ``constant_throughput`` wait time, so each user is paced at a fixed rate
  rather than hammering closed-loop. The achieved rate is ``users x
  LOCUST_RPS_PER_USER``; keep it within 5% of the target or the run is invalid.
* We hit ``POST /api/v1/authenticate``, the CPU-bearing endpoint (it runs the
  PBKDF2 signing work set by SIGN_WORK, FR7). ``/`` and ``/health`` are almost
  free and would not saturate an instance, so they cannot find R_max.
* UIDs are synthetic ``TEST-`` records read from ``service/data/residents.json``
  with their matching OTPs (FR6), so every request is a real "Yes" lookup.
* The ALB publishes ``TargetResponseTime`` and ``RequestCountPerTarget`` every
  60 s; that is the server-side ground truth. Locust latency includes laptop
  and Internet jitter, so always pull the ALB metrics too (tests/fetch_metrics,
  5.3.3 step 5). Here we additionally tally responses per AZ / instance from the
  identity headers, so the "which instances served" question is answered from
  the client side as well.

Run it through ``tests/step9_load.ps1`` (or ``step9_load.sh``), which lays the
Locust CSV/HTML down in ``results/<experiment>/<run_id>/`` and writes meta.json,
matching the prober's layout (CONTRIBUTING.md). Standalone:

    locust -f tests/locustfile.py --headless \\
        --host http://<alb-dns> --users 10 --spawn-rate 10 --run-time 5m \\
        --csv results/e5a/e5a-r01-n1/locust --html results/e5a/e5a-r01-n1/locust.html

Environment knobs (all optional):

    LOCUST_RPS_PER_USER   requests/s each user is paced at (default 10.0). The
                          total target rate is this times --users.
    LOCUST_DATASET        path to the residents JSON (default service/data).
    LOCUST_ENDPOINT       request path (default /api/v1/authenticate).
    LOCUST_FACTOR         otp | demo, the auth factor to send (default otp).
"""

from __future__ import annotations

import itertools
import json
import os
import random
import threading
from collections import Counter
from pathlib import Path

from locust import FastHttpUser, constant_throughput, events, task

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = REPO_ROOT / "service" / "data" / "residents.json"

RPS_PER_USER = float(os.environ.get("LOCUST_RPS_PER_USER", "10"))
FACTOR = os.environ.get("LOCUST_FACTOR", "otp").lower()


def _clean_endpoint(raw: str) -> str:
    """Return a leading-slash request path, repairing MSYS path mangling.

    On Git-Bash / MSYS a value like ``/api/v1/authenticate`` passed to a native
    program is rewritten into a Windows path such as
    ``C:/Program Files/Git/api/v1/authenticate``. If that reaches us, recover the
    real path from the known API tail rather than hammer the ALB with a 404/又.
    """
    ep = (raw or "").strip()
    if ep.startswith("/"):
        return ep
    low = ep.replace("\\", "/").lower()
    marker = "/api/v1/"
    i = low.find(marker)
    if i >= 0:
        recovered = ep.replace("\\", "/")[i:]
        print(f"warning: LOCUST_ENDPOINT looked mangled ({raw!r}); using {recovered!r}")
        return recovered
    # Last resort: make it a path so requests are at least well-formed.
    return "/" + ep.lstrip("/")


ENDPOINT = _clean_endpoint(os.environ.get("LOCUST_ENDPOINT", "/api/v1/authenticate"))

# Count responses per AZ and per instance, so we can see the 1 -> 2 instance
# split from the client side (E5a / E5b). Guarded by a lock: FastHttpUser runs
# many greenlets, but they are cooperatively scheduled, so contention is light.
_by_az: Counter[str] = Counter()
_by_instance: Counter[str] = Counter()
_tally_lock = threading.Lock()


def _load_credentials(path: Path) -> list[dict]:
    """Return [{uid, otp, demo}] for every synthetic record with an OTP."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    creds = []
    for rec in data.get("records", []):
        uid = rec.get("uid")
        if not uid:
            continue
        creds.append(
            {
                "uid": uid,
                "otp": rec.get("otp"),
                "demo": {
                    k: rec[k] for k in ("name", "dob", "gender") if rec.get(k) is not None
                },
            }
        )
    if not creds:
        raise RuntimeError(f"no usable records in {path}")
    return creds


_dataset_path = Path(os.environ.get("LOCUST_DATASET", DEFAULT_DATASET))
_credentials = _load_credentials(_dataset_path)


class AuthUser(FastHttpUser):
    """One simulated client, paced at a fixed rate (open-loop-ish)."""

    # constant_throughput(X): Locust waits so this user completes X tasks/s,
    # regardless of response time. Total rate = users x X (ARCHITECTURE.md 5.3.4).
    wait_time = constant_throughput(RPS_PER_USER)

    # FastHttpUser defaults: keep-alive on, HTTP/1.1. Give a generous per-request
    # timeout so a slow (not failed) response is recorded, not dropped.
    network_timeout = 30.0
    connection_timeout = 10.0

    def on_start(self):
        # Each user walks the record list from a random offset, so load is spread
        # across the dataset rather than hammering one record's cache line.
        start = random.randrange(len(_credentials))
        self._creds = itertools.cycle(_credentials[start:] + _credentials[:start])

    def _payload(self, cred: dict) -> dict:
        if FACTOR == "demo" and cred["demo"]:
            return {"uid": cred["uid"], "demo": cred["demo"]}
        return {"uid": cred["uid"], "otp": cred["otp"]}

    @task
    def authenticate(self):
        cred = next(self._creds)
        # catch_response lets us fail a 200 that is not actually a "Yes", and tally
        # which instance answered from the identity headers (FR2).
        with self.client.post(
            ENDPOINT,
            json=self._payload(cred),
            name=ENDPOINT,
            catch_response=True,
        ) as resp:
            az = resp.headers.get("X-AZ", "") if resp.headers else ""
            inst = resp.headers.get("X-Instance-Id", "") if resp.headers else ""
            with _tally_lock:
                _by_az[az or "(none)"] += 1
                _by_instance[inst or "(none)"] += 1
            if resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")
                return
            try:
                decision = resp.json().get("auth")
            except (ValueError, AttributeError):
                resp.failure("non-JSON body")
                return
            if decision != "Y":
                resp.failure(f"auth={decision!r}")


@events.quitting.add_listener
def _dump_tally(environment, **_kwargs):
    """At the end, print and (if asked) save the per-AZ / per-instance counts.

    step9_load.ps1 points LOCUST_TALLY_OUT at results/<run>/served_by.json so the
    split between instances is captured next to the Locust CSVs (E5a / E5b).
    """
    with _tally_lock:
        tally = {
            "requests_by_az": dict(_by_az),
            "requests_by_instance": dict(_by_instance),
            "distinct_instances": len([k for k in _by_instance if k != "(none)"]),
            "rps_per_user": RPS_PER_USER,
            "endpoint": ENDPOINT,
            "factor": FACTOR,
        }
    print("served by AZ      :", tally["requests_by_az"])
    print("served by instance:", tally["requests_by_instance"])
    out = os.environ.get("LOCUST_TALLY_OUT")
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(tally, f, indent=2)
            f.write("\n")
        print(f"wrote {p}")
