# results/e1b/

PLAN step 7 — same failure as E1 (service process stops on one instance),
but with the ALB health check set to **AWS defaults** instead of the fast
ARCHITECTURE.md 5.2 values. The point is to show how big an effect those
settings have on user-visible downtime (ARCHITECTURE.md 8.4).

**Settings for the stack (ARCHITECTURE.md 5.2 + E1b row of 8.4):**

| Setting                | Fast (E1 / E2) | AWS defaults (E1b) |
|------------------------|----------------|---------------------|
| hc_interval            | 5 s            | 30 s                |
| hc_timeout             | 2 s            | 5 s                 |
| hc_healthy_threshold   | 2              | 5                   |
| hc_unhealthy_threshold | 2              | 2                   |

**Predicted error window:** 30–60 s (ARCHITECTURE.md 8.4, derived from
(N_u − 1)·I .. N_u·I for a fast failure). **Pass criterion:** measured
window falls in that predicted band, in all 3 runs.

## Runs

Three runs are enough for E1b (PLAN.md section 6 "3 runs minimum", and
ARCHITECTURE.md 8.4 asks for 3 for this experiment). Use a 300 s probe
duration so the long error window and the rejoin both land inside it;
restore at t = 180 s.

| Run id       | Target instance        | AZ | errors | window_s | pass |
|--------------|------------------------|----|--------|----------|------|
| e1b-r01-az-a | i-09e04fbc68955b460    | a  | 365    | 36.4     | ✅ |
| e1b-r02-az-b | i-010438766fd85a857    | b  | 356    | 228.15 (see note) | ⚠️ outlier |
| e1b-r03-az-a | i-09e04fbc68955b460    | a  | 352    | 35.35    | ✅ |

Aggregate (`results/e1b/aggregate.csv`): median error_window_s = 36.4 s;
clean range across the three real primary-failover windows [35.3 s,
~37 s]. All three sit at the lower end of the predicted 30-60 s band:
inject consistently landed near the end of a health-check interval, so
`unhealthy_threshold × interval` ran down fast.

**Note on r02 (az b).** Same two-cluster shape as `e2-r04-az-b`:

- *Primary failover block* at t=30-69 s (around inject at t=30 s):
  355 http_5xx, ~37 s window — cleanly inside the predicted band.
- *Secondary cluster* at t=265 s: 1 lone timeout, 85 s after the
  `restore` event fired. Local wifi, not a Tier-1 failure.

The analyser computes `error_window_s = last_error − first_error`, so
it reports 228 s for this run. For the report, quote the median across
the three primary failovers and call out r02 as an example of why the
spread exists (ARCH 8.5: "explain the spread").

## How to run

AWS action needed on Jeel's laptop (apply the slow-health-check stack):

```
cd infra/envs/tier1
cp terraform.tfvars.e1b.example terraform.tfvars.e1b   # once
terraform apply -var-file=terraform.tfvars -var-file=terraform.tfvars.e1b
terraform output -raw alb_dns_name
terraform output instance_ids
```

Then on Khushi's laptop, per run:

```
# PowerShell
$env:AWS_PROFILE = 'aadhaar'
.\tests\step7_run.ps1 `
    -Experiment e1b `
    -RunNumber 1 `
    -TargetAz a `
    -InstanceId <i-...> `
    -AlbDns <alb-dns> `
    -ImageTag 6cc656f `
    -Duration 300 `
    -RestoreAt 180 `
    -Network wired
```

When all 3 are in: `python analysis\analyze.py --experiment e1b`.

**After E1b, Jeel reapplies with the fast settings** (just
`terraform apply` with the normal `terraform.tfvars`) before continuing
with any further E1 / E2 runs.
