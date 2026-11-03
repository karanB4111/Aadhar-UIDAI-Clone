# results/e0/

PLAN step 9 (Kanu; reviewer Jeel) — **calibration** of one t3.micro to find
R_max, the highest request rate one instance sustains with zero errors and a
stable server-side p95 (ARCHITECTURE.md 8.4 E0, method 3.4 / 5.3.3). R_max then
sets `SIGN_WORK` and the E5a/E5b load and scaling-target values.

Load: `POST /api/v1/authenticate` (the CPU-bearing endpoint), synthetic `TEST-`
records, driven from a laptop with Locust `FastHttpUser` at a fixed per-user
rate. ASG pinned to **1 instance** (min=desired=max=1), scaling processes
suspended (set by Jeel before the run).

## Runs

| Run id        | Image tag | Shape | requests | failures | notes |
|---------------|-----------|-------|----------|----------|-------|
| e0-r01-ramp   | 6cc656f   | 40 users × 10 rps, spawn 0.5/s, 10 min (0 → 400 rps ramp) | 211,681 | 0 | client-bound; see below |

Client: home laptop, Wi-Fi. Run 2026-11-04 (UTC). `SIGN_WORK` = 1000 (service
default, not yet tuned). Raw files: `e0-r01-ramp/locust_stats.csv`,
`locust_stats_history.csv`, `locust.html`, `served_by.json`, `meta.json`.
Chart: `charts/latency_vs_load.png`.

## Finding: no saturation at `SIGN_WORK=1000` — R_max not reached

Over the whole ramp the server-side behaviour was flat, not a knee:

- **p95 held at ~110 ms** from ~20 rps all the way to ~390 rps — it did **not**
  rise with load.
- **Zero failures** in 211,681 requests; every request was served by the single
  pinned instance `i-0bf16bd4884d0c1a5` (ap-south-1a).
- The run plateaued at ~390 rps (median at 40 users), 11.7% under the 400 rps
  target. With a flat p95 and no errors, that ceiling is the **laptop / Wi-Fi
  client limit, not the instance** — the server never saturated.

So this run does not yield an R_max knee: at the default `SIGN_WORK` a single
t3.micro is faster than a laptop can load it. This is the exact situation
ARCHITECTURE.md 3.4 / 5.1.2 anticipates — auth is too cheap to saturate the
instance within a laptop-drivable rate.

## Action before E5a / E5b

Tune `SIGN_WORK` **up** so R_max lands in the **100–200 rps** band (ARCHITECTURE.md
3.4), then rerun a short E0 to pin the knee:

1. Raise `SIGN_WORK` in `infra/envs/tier2/terraform.tfvars` (passed to the
   container via user data, `modules/app_asg`). As a starting point, ~390 rps at
   1000 iterations and a target R_max ≈ 150 rps suggests roughly
   `SIGN_WORK ≈ 1000 × (390 / 150) ≈ 2600`; signing cost is close to linear in
   the iteration count, but confirm with a rerun rather than trusting the ratio.
   A new image is **not** needed — `SIGN_WORK` is an env var, so only a
   `terraform apply` with the new value.
2. Rerun `e0-r02-ramp` ramping 10 → ~200 rps; the knee is where p95 starts to
   climb and/or the first failures appear. That rate is R_max.
3. Set the E5 values from R_max: E5a load = 0.9 × R_max (N=1, N=2); E5b step
   0.8 → 1.6 × R_max; scaling target = 30 × R_max requests/minute (5.3.4).

Server-side cross-check (`TargetResponseTime`, `CPUUtilization`,
`CPUSurplusCreditBalance`) via `tests/fetch_metrics.py` is run by Jeel from his
profile; it is not required to read the knee but confirms the laptop-vs-server
split and that unlimited credits prevented throttling (5.1.2).
