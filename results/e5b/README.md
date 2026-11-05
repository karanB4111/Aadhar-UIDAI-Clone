# results/e5b/

PLAN step 9 (Kanu; reviewer Jeel) — **autoscaling behaviour**: one load step
drives the ASG from **desired 1 → 2**, then removing load lets it scale back to
1 (ARCHITECTURE.md 8.4 E5b, 5.3.3). Scaling is **on** (target-tracking on
`ALBRequestCountPerTarget`), unlike E5a.

Load: `POST /api/v1/authenticate`, `SIGN_WORK=4500`, Locust from a laptop.
ASG min 1 / desired 1 / max 2, scaling resumed, target **3000
req/target/minute** (≈ 50 rps/target). App version `6cc656f`.

## Run

| Run id       | Step load | Hold | requests | failures | p50 / p95 / p99 |
|--------------|-----------|------|----------|----------|------------------|
| e5b-r01-step | ~137 rps (14 users × 10) | 10 min, then load removed | 81,850 | 0 | 71 / 110 / 130 ms |

Run 2026-11-05 (UTC), home laptop / Wi-Fi. Raw files in `e5b-r01-step/`.

## Result: scale-out 1 → 2 fired under load, zero client disruption

- **Trigger.** At ~137 rps on one target the per-target request count was
  ~8,200/min, well over the 3,000/min target, so the target-tracking policy
  raised desired capacity. This is the 5.3.2 metric acting exactly as designed —
  scale-out keys off request count, not latency.
- **Timeline.** Load started ~15:25 UTC with one instance
  (`i-0abef6a7d76dfb715`, 1a). A second instance (`i-0b96784c3750d5c44`, 1b)
  was healthy and serving by ~15:32:41 UTC — **scale-out ≈ 5–7 min**, inside the
  5–8 min estimate (ARCHITECTURE.md 4.3). The run's per-instance tally shows the
  asymmetric split that marks a mid-run launch: 69,120 requests to the original
  instance vs 12,730 to the one that joined late (`served_by.json`).
- **No disruption.** Latency stayed flat (p50 71 ms, p95 110 ms) and there were
  **0 failures** across all 81,850 requests. The new instance joined the target
  group without any error window for clients.
- **Scale-in (2 → 1).** Load stopped at ~15:35 UTC; the ASG held 2 instances,
  then dropped the second once `ALBRequestCountPerTarget` stayed below target for
  the scale-in window. The ALB was serving from only one instance again by
  **15:52:38 UTC — scale-in ≈ 17 min** after load removal (measured from a
  post-run ALB instance-count watch, 30 s probe interval). Scale-in is
  deliberately slower than scale-out (ARCHITECTURE.md 4.3 / 5.3: ~15 one-minute
  datapoints below target, so ≥ ~15 min) — the measured ~17 min matches. The ASG
  `GroupInServiceInstances` metric in `aws_metrics.csv` is the authoritative
  timeline.

## Server-side timeline (Jeel)

`tests/fetch_metrics.py` over the full window (padded) gives
`GroupInServiceInstances`, `GroupDesiredCapacity` and `RequestCountPerTarget` —
the definitive autoscale timeline that `analysis/analyze_load.py` plots as
`charts/autoscale_timeline.png` (the chart needs `aws_metrics.csv`, so it is
generated after the fetch). Run, from Jeel's profile:

```
python tests/fetch_metrics.py --run-dir results/e5b/e5b-r01-step --region ap-south-1 \
  --alb app/aadhaar-tier2-alb/26d1de711ef9d727 \
  --target-group targetgroup/aadhaar-tier2-tg/5eb4b2b38910c3a8 \
  --asg aadhaar-tier2-asg
```

Use a window from ~5 min before the load start to ~20 min after it stopped, so
both the scale-out and the slow scale-in are captured.
