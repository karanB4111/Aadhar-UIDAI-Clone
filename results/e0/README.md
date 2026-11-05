# results/e0/

PLAN step 9 (Kanu; reviewer Jeel) — **calibration** of one t3.micro to find
R_max, the highest request rate one instance sustains with zero errors and a
stable server-side p95 (ARCHITECTURE.md 8.4 E0, method 3.4 / 5.3.3). R_max then
sets `SIGN_WORK` and the E5a/E5b load and scaling-target values.

Load: `POST /api/v1/authenticate` (the CPU-bearing endpoint), synthetic `TEST-`
records, driven from a laptop with Locust `FastHttpUser` at a fixed per-user
rate. ASG pinned to **1 instance** (min=desired=max=1), scaling suspended (set
by Jeel before each run).

## Runs

| Run id        | SIGN_WORK | Instance            | Shape (ramp) | requests | failures | achieved rps (top) | p50 / p95 |
|---------------|-----------|---------------------|--------------|----------|----------|--------------------|-----------|
| e0-r01-ramp   | 1000      | i-0bf16bd4884d0c1a5 | 40 u × 10, 0→400 rps, 10 min | 211,681 | 0 | ~390 | 78 / 120 ms |
| e0-r02-ramp   | 2600      | i-024e72db6da681d00 | 20 u × 10, 0→200 rps, 10 min | 109,156 | 0 | ~193 | 78 / 120 ms |
| (aborted)     | 18000     | i-006d8f6e424bab94c | 16 u × 10, aborted ~40 s | — (discarded) | yes | **~2** | p50 300–1000 ms, p95 9200 ms |
| e0-r03-ramp   | 4500      | i-034175448e88b5f7a | 16 u × 10, 0→160 rps, 10 min | 91,870 | 0 | ~158 | 70 / 110 ms |

The 18000 attempt was aborted and its directory discarded: at only 16 concurrent
users throughput collapsed to ~2 rps with p95 ~9 s and failures. Not a valid
knee; recorded here as the upper bracket only. The run id `e0-r03-ramp` was then
reused for the SIGN_WORK=4500 run.

Client: home laptop, Wi-Fi, ~70 ms RTT to `ap-south-1`. Runs 2026-11-04 (UTC).
Raw files per run: `locust_stats.csv`, `locust_stats_history.csv`, `locust.html`,
`served_by.json`, `meta.json`. Chart: `charts/latency_vs_load.png`.

## Finding: one t3.micro does not saturate from a laptop at SIGN_WORK ≤ 2600

Both runs show a **rate-independent latency floor**, i.e. no R_max knee:

- p50 held flat at **~75 ms** across the whole ramp in both runs; p95 wobbled
  100–150 ms from Wi-Fi jitter with no monotonic climb (the odd 530/710 ms
  single-interval spikes are network blips, not saturation — p90-of-p95 ≈ 150 ms).
- **Zero failures** in 320k+ requests combined.
- The top-of-ramp rate (~390 rps at SIGN_WORK=1000, ~193 rps at 2600) tracks the
  **laptop / Wi-Fi ceiling**, not the instance. Raising SIGN_WORK 1000→2600 cut
  the achievable top rate (more CPU per request) but did **not** raise the
  latency floor, because the signing work is still small next to the network
  RTT. The server was never the bottleneck.

This is the situation ARCHITECTURE.md 3.4 / 5.1.2 anticipates: auth is too cheap
to saturate a t3.micro within a laptop-drivable rate, so E5a (p95 at N=2 clearly
below N=1) and E5b (autoscale under load) cannot show their effect yet.

## SIGN_WORK is strongly non-linear under concurrency — the window is a cliff

The runs bracket the behaviour and show the cost is **not** linear in iterations:

| SIGN_WORK | Achievable rps on 1 instance | p50 / p95 | State |
|-----------|------------------------------|-----------|-------|
| 1000      | ~390 (laptop ceiling)        | 78 / 120 ms | not saturated |
| 2600      | ~193 (laptop ceiling)        | 78 / 120 ms | not saturated |
| 4500      | ~158 (laptop ceiling)        | 70 / 110 ms | not saturated |
| 18000     | ~2                           | 300–1000 / 9200 ms | collapsed |

A 7× rise 2600→18000 cut throughput ~100× (193→~2), not ~7×: once requests
arrive faster than the 2 vCPUs can sign, the queue runs away and throughput
craters. Between 4500 (flat ~100 ms at 158 rps, unsaturated) and 18000
(collapsed) there is **no value that produces a gentle knee under this laptop's
~158 rps ceiling** — the server's knee at a stable SIGN_WORK sits above what a
laptop over Wi-Fi to Mumbai can drive. This is risk R7 / the 5.3.4 laptop-limit
caveat in practice.

## Decision (group, 2026-11-05): lock SIGN_WORK = 4500, R_max ≈ 160 rps (laptop-bounded)

Rather than burn more retune cycles chasing a single-instance latency knee the
laptop can't reach, we **fix SIGN_WORK = 4500** and take **R_max ≈ 160 rps** as a
laptop-bounded cap (documented as such, not a true server knee). This is enough
to demonstrate the scaling *mechanism*, which is what Week 3 grades:

- **E5a (N=1 vs N=2):** drive the full ~150 rps. On N=1 one instance carries it
  all; on N=2 the ALB splits it ~75 rps each. The scaling effect is read from the
  **per-instance** `ALBRequestCountPerTarget` and `CPUUtilization` (5.3.2's
  primary signal), which halve from N=1 to N=2, rather than from client latency
  (which stays Wi-Fi-flat). Client p50/p95 is reported alongside as context.
- **E5b (autoscale):** the target-tracking policy fires on
  `ALBRequestCountPerTarget`, **not** latency, so a load step that pushes per-
  target request count past 30 × R_max_per_target/min triggers desired 1 → 2
  regardless of whether latency saturates.

E5 values from R_max ≈ 160: E5a load ≈ 0.9 × R_max ≈ **145 rps**; E5b step
0.8 → 1.6 × R_max ≈ **130 → 230 rps** (the 230 is above the laptop ceiling, so in
practice the step goes ~130 → ~155 rps, still enough to cross the scale-out
threshold); scaling target ≈ 30 × (R_max/2) ≈ **2400 requests/target/minute**
(Jeel sets `scaling_target_requests_per_minute`).

The r01/r02 runs and the discarded 18000 attempt stay documented as the
calibration evidence that justifies SIGN_WORK = 4500 (3.4).
