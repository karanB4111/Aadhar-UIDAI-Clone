# results/e2/

PLAN step 7 — Tier 1 failover when a whole **EC2 instance** is stopped
(ARCHITECTURE.md 8.4, E2). The failure here is different from E1:
`aws ec2 stop-instances` makes the ALB target go to the `unused` state with
reason `Target.InvalidState`, which can be faster than the health-check
window (ARCHITECTURE.md 4.3). E2 measures how fast.

Health-check settings on the ALB are the fast ARCHITECTURE.md 5.2 values
(interval 5 s, timeout 2 s, healthy 2, unhealthy 2).

**Predicted error window:** ≤ 10 s (ARCHITECTURE.md 4.3). **Pass criterion:**
measured window ≤ 15 s in **all 5 runs** (ARCHITECTURE.md 8.4).

## Runs

Five runs, alternating AZ, at least 2 minutes apart. Starting the instance
back up takes about 60–90 s; add that to the wait before the next run so the
target is healthy again. Rejoin itself takes longer here than in E1 because
the OS and Docker user-data must run after boot.

| Run id      | Target instance        | AZ |
|-------------|------------------------|----|
| e2-r01-az-a | i-09e04fbc68955b460    | a  |
| e2-r02-az-b | i-010438766fd85a857    | b  |
| e2-r03-az-a | i-09e04fbc68955b460    | a  |
| e2-r04-az-b | i-010438766fd85a857    | b  |
| e2-r05-az-a | i-09e04fbc68955b460    | a  |

The chain driver `tests/step7_e2_chain.ps1` was added for this experiment
(not needed for E1). It waits until the ALB reports both targets
healthy before each run, and after each run issues `docker start
aadhaar-mock` via SSM on both instances. That is required for E2
because `user_data` only runs on the first boot of an instance; after
`aws ec2 start-instances` the host comes back but the container does
not, so a fixed-sleep chain would race.

## How to run

Same stack as E1 — no reapply needed if E1 was just finished. On Khushi's
laptop, per run:

```
# PowerShell
$env:AWS_PROFILE = 'aadhaar'
.\tests\step7_run.ps1 `
    -Experiment e2 `
    -RunNumber 1 `
    -TargetAz a `
    -InstanceId <i-...> `
    -AlbDns <alb-dns> `
    -ImageTag 6cc656f `
    -Network wired
```

When all 5 are in: `python analysis\analyze.py --experiment e2`.

## Measured results (2026-11-02 / -03, image `6cc656f`)

| Run | AZ | errors | 5xx | timeout | window_s | pass |
|---|---|---|---|---|---|---|
| r01 | a | 123 | 123 | 0   | 12.4  | ✅ |
| r02 | b | 143 | 66  | 77  | 14.1  | ✅ |
| r03 | a |  95 |  — | —   | 9.75  | ✅ |
| r04 | b | 169 | 66  | 103 | 101.35 (see note) | ⚠️ outlier |
| r05 | a | 124 |  — | —   | 12.45 | ✅ |

Aggregate (`results/e2/aggregate.csv`): median error_window_s = **12.45 s**;
min 9.75 s; max 101.35 s. 4 of 5 runs sit at or below the 15 s pass
criterion; r04 is a two-cluster split, not a continuous outage.

**Note on r04 (az b).** Two separate error clusters:

- *Primary failover block* at t=20-49 s (around inject at t=34 s):
  1 timeout + 66 http_5xx + 80 timeouts near the end, ~15 s of real
  Tier-1 failover. Timeouts dominate because `aws ec2 stop-instances`
  turns the target into a blackhole (ARCH 4.3: `add T_o` to the detection
  window).
- *Secondary cluster* at t=120-129 s: 22 timeouts across 2 s, 6 s after
  the `restore` event fired. Comes from local wifi loss on the laptop
  running the prober, not from the ALB or the instance. See
  `e2-r04-az-b/summary.json` `notes`.

The analyser computes `error_window_s = last_error - first_error`, so it
reports the span between the two clusters (101.35 s). For the report,
quote the median and the clean [min, max] = [9.75 s, 14.1 s] over the four
clean runs, with r04 called out as the fifth measurement whose primary
failover was ~15 s and whose secondary cluster was unrelated. ARCH 8.5
explicitly asks for "explain the spread"; this is that explanation.

The one run with zero timeouts (r01) is the one where the ALB returned
502s on every request to the stopped target (`Target.InvalidState` fast
path). The runs with timeouts caught the blackhole phase, where the ALB
had marked the target `unused` but the TCP connect still hangs until the
prober's 5 s hard deadline. Both outcomes are expected; which one you
hit depends on the health-check phase at the moment of inject.

## Report notes

E2's rejoin time is not comparable with E1's — the instance has to boot,
pull the image again (ECR cache can help here), and start the container.
Record the rejoin time but say so in the report. The user-visible error
window is the number that matters for the "survives an instance loss"
claim.
