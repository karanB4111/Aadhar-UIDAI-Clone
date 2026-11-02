# results/e1/

PLAN step 7 (Khushi; reviewer Jeel) — Tier 1 failover when the service
**process** stops on one instance (ARCHITECTURE.md 8.4, E1). Health-check
settings on the ALB are the "fast" ARCHITECTURE.md 5.2 values
(interval 5 s, timeout 2 s, healthy 2, unhealthy 2).

**Predicted error window:** 5–10 s for a connection-refused failure, up to
12 s if the TCP connect hangs (ARCHITECTURE.md 4.3). **Pass criterion:** the
measured window ≤ 15 s in **all 5 runs**, no errors outside the window, and
the restarted instance rejoins within 20 s of restart (ARCHITECTURE.md 8.4).

## Runs

Five runs, alternating between AZ `a` and AZ `b` (ARCHITECTURE.md 8.5), at
least 2 minutes apart. Each run is 180 s at 20 req/s, inject at t = 30 s,
restore at t = 120 s. The service container is launched with `--restart=no`
(see `infra/modules/app_static/main.tf`), so `docker stop` leaves the
process down for the whole error window.

| Run id         | Target instance        | AZ | errors | window_s | pass |
|----------------|------------------------|----|--------|----------|------|
| e1-r01-az-a    | i-09e04fbc68955b460    | a  | 117    | 11.60    | ✅ |
| e1-r02-az-b    | i-010438766fd85a857    | b  | 113    | 11.20    | ✅ |
| e1-r03-az-a    | i-09e04fbc68955b460    | a  | 116    | 11.50    | ✅ |
| e1-r04-az-b    | i-010438766fd85a857    | b  | 116    | 12.15    | ✅ |
| e1-r05-az-a    | i-09e04fbc68955b460    | a  | 107    | 10.65    | ✅ |

Aggregate (`results/e1/aggregate.csv`): median error_window_s = **11.5 s**;
range [10.65 s, 12.15 s]. All five runs pass the ≤ 15 s criterion. The
runs cluster at the upper end of the predicted 5-12 s band, consistent
with ARCH 4.3's note that each ALB node decides independently so the
measured window tends toward the upper bound.

Latency on successful responses: p95 = 130.5 ms (median across runs,
[129.1, 134.0]), p99 = 161.3 ms. These are client-side numbers from a
laptop in Gandhinagar; the server-side numbers from ALB
`TargetResponseTime` will be smaller.

## How to run (from the repo root)

AWS action needed on Jeel's laptop first:

```
cd infra/envs/tier1
terraform apply                                     # fast health checks
terraform output -raw alb_dns_name
terraform output instance_ids
```

Then on Khushi's laptop, one run at a time:

```
# PowerShell
$env:AWS_PROFILE = 'aadhaar'
.\tests\step7_run.ps1 `
    -Experiment e1 `
    -RunNumber 1 `
    -TargetAz a `
    -InstanceId <i-...> `
    -AlbDns <alb-dns-from-tf> `
    -ImageTag 6cc656f `
    -Network wired
```

Between runs: wait at least 2 min, then alternate the AZ. After all 5:

```
python analysis\analyze.py --experiment e1
```

Commit the raw `prober.csv`, `events.csv` and `meta.json` under each run
directory, plus the generated `summary.*`, `aggregate.csv`, `*.png` files.
Raw files are never edited by hand (CONTRIBUTING.md).

## Report notes

For the final report (step 10), quote **median** and the **[min, max] range**
across the 5 runs next to the predicted 5–12 s range (ARCHITECTURE.md 8.5).
The spread comes mainly from the health-check phase: inject can land
anywhere in a 5 s interval, so the error window varies by that amount.
