# tests/

Test tooling that drives load and records what clients see.

```
prober.py         failover prober (step 4): open loop, CSV per request
event.py          log a manual injection or restore to events.csv (step 4)
step7_run.ps1     one-run driver for E1 / E1b / E2 (step 7, PowerShell)
step7_run.sh      the same, for bash
locustfile.py     Locust load test (step 9): FastHttpUser, fixed-rate
step9_load.ps1    one-point load driver for E0 / E5a / E5b (step 9, PowerShell)
step9_load.sh     the same, for bash
fetch_metrics.py  pull ALB + ASG CloudWatch metrics for a run into CSV (step 9)
unit/             pytest suite for the prober and the locustfile
requirements.txt  pytest and Locust (2.47.0)
```

- **Failover prober** (PLAN step 4, owner: Kanu). Spec: ARCHITECTURE.md 8.3.
- **Locust load test** (PLAN step 9, owner: Kanu). `FastHttpUser`, paced at a
  fixed rate. Used for calibration (E0) and the scaling experiments (E5a, E5b).

Output goes to `results/`, in the layout described in CONTRIBUTING.md.

## Failover prober

Standard library only (Python 3.11+), so there's nothing to install on a
laptop just to probe.

What it does on every request, per ARCHITECTURE.md 8.3:

- Sends on a fixed schedule (default 20/s) whether or not earlier requests
  have answered (open loop). A thread pool sized for a full timeout's worth of
  hung requests keeps the schedule.
- Resolves the host through the system resolver and logs the IP it used.
- Opens a new TCP connection and sends `Connection: close`.
- Connect timeout 2 s, and a hard 5 s deadline for the whole request.
- Reads `instance_id`, `az` and `region` from the `X-Instance-Id`, `X-AZ` and
  `X-Region` headers, which the service sets on every response, errors included.

### Run it

From the repo root. Use the `GET /` endpoint; it is the cheapest.

```bash
# Until Ctrl+C
python tests/prober.py http://localhost:8080/ --run-id local-r02-app-a

# A whole E1-style run: inject at 30 s, restore at 150 s, stop at 180 s
python tests/prober.py http://<alb-dns-name>/ --run-id e1-r01-az-a --duration 180 \
    --image-tag $(git rev-parse --short HEAD) --network wired --client-location "DAU lab" \
    --meta hc_interval_s=5 --meta hc_unhealthy=2 --meta instance_type=t3.micro \
    --action 30  inject_start "aws ssm send-command ... docker stop app" \
    --action 150 restore      "aws ssm send-command ... docker start app"
```

- `--run-id` must be `<experiment>-r<NN>-<target>` (CONTRIBUTING.md). The
  files go in `results/<experiment>/<run_id>/`. The prober refuses to reuse a
  run id that already has a `prober.csv`.
- `--action AT_S EVENT COMMAND` runs `COMMAND` from the repo root `AT_S`
  seconds into the run, in the background so the schedule is not delayed, and
  logs `EVENT` to `events.csv` **when the command returns** (8.3). Repeatable.
- If you inject by hand instead, log it with `event.py` while the prober runs:

  ```bash
  python tests/event.py e2-r01-az-a inject_start -- aws ec2 stop-instances --instance-ids i-0abc
  python tests/event.py e2-r01-az-a restore --detail "started i-0abc from the console"
  ```

- Every 5 s it prints running counts to stderr. At the end it prints the
  error counts and writes `meta.json`.
- Sync your clock (NTP) before a run. All times are UTC in milliseconds.

### Output

`prober.csv`, one row per request, in completion order (sort by
`t_send_utc_ms` or `seq`):

| Column | Meaning |
|---|---|
| `seq` | Schedule slot, 0, 1, 2 ... Slot `n` was due at `n / rate` s after the start |
| `t_send_utc_ms`, `t_recv_utc_ms` | Wall clock when the request started and when it finished or failed |
| `latency_ms` | Monotonic duration including DNS, connect and the full response |
| `status` | HTTP status, empty if there was none |
| `error_class` | Empty on 2xx, else `timeout`, `conn_error`, `http_5xx` or `http_other` |
| `error_detail` | What exactly failed, e.g. `connect_timeout`, `total_timeout`, `connect: ConnectionRefusedError ...`, `dns: ...` |
| `instance_id`, `az`, `region` | From the response headers; empty if no response arrived |
| `resolved_ip` | The address this request connected to |
| `run_id` | Same as the folder name |

`events.csv`: `t_utc_ms, event, detail, run_id`. The prober writes
`probe_start` and `probe_end` itself, plus one row per `--action`.

`meta.json`: the settings above, git SHA, image tag, client location and
network, tool versions, any `--meta key=value` pairs, and a `summary` with
counts per error class and the send lag (how late requests left against their
schedule). Check `send_lag_ms.max` is well under the 50 ms interval; if not, the
laptop could not keep up and the run is not a true open loop.

### Gotchas

- `localhost` resolves to `::1` first on Windows; that is fine and shows in
  `resolved_ip`.
- On Windows a refused TCP connection is retried for about 2 s before it
  fails, so it can show as `connect_timeout` instead of `conn_error`. Behind the
  ALB this rarely matters, because the client always connects to the ALB.
- **Locally, nginx hides the failover as latency, not errors.**
  `proxy_next_upstream` (local/nginx.conf) retries a failed request on the
  other app. In `results/local/local-r01-app-a` there are zero errors. Instead,
  every 5 s (`fail_timeout`) one request takes about 2 s while nginx waits out
  `proxy_connect_timeout` on the stopped app. The ALB does not retry like this,
  so on AWS the same failure shows as 502s on the failed target's share until
  the health check removes it (ARCHITECTURE.md 5.2).

## Step 7: driving E1 / E1b / E2 against the Tier 1 ALB

`step7_run.ps1` (and the bash `step7_run.sh`) is a thin wrapper that calls
`prober.py` with the right injection commands for each experiment:

- **E1 / E1b** inject with `aws ssm send-command ... docker stop
  aadhaar-mock` and restore with `docker start aadhaar-mock`.
- **E2** injects with `aws ec2 stop-instances` and restores with
  `aws ec2 start-instances`.

Preconditions, in order (details in `results/e1/README.md` and the per-run
HANDOFF notes):

1. Jeel applies `infra/envs/tier1` on his laptop. For E1 / E2 that is the
   default fast health-check build; for E1b he applies with
   `terraform.tfvars.e1b` on top (`infra/envs/tier1/README.md`).
2. Jeel shares `terraform output -raw alb_dns_name` and
   `terraform output instance_ids` in the group chat.
3. On Khushi's laptop:

   ```powershell
   $env:AWS_PROFILE = 'aadhaar'
   .\tests\step7_run.ps1 `
       -Experiment e1 -RunNumber 1 -TargetAz a `
       -InstanceId <i-...> -AlbDns <alb-dns> -ImageTag <sha> `
       -Network wired
   ```

4. After each experiment's runs:
   ```
   python analysis\analyze.py --experiment e1
   ```

Alternate the target between AZ `a` and AZ `b` between runs, and wait at
least 2 min for everything to be healthy before the next run
(ARCHITECTURE.md 8.5). The script refuses to overwrite an existing
`prober.csv`, so a repeated run id fails fast.

## Step 9: Locust load test against the Tier 2 ASG (E0 / E5a / E5b)

The load test measures **latency against load** and **against instance count**
(the Week 3 "scaling behaviour" deliverable, ARCHITECTURE.md 5.3.3-5.3.4, 8.4).
It runs from a laptop, never an EC2 generator, so the whole project stays inside
the default 5-vCPU quota (D9, 5.3.4).

`locustfile.py` is a `FastHttpUser` that POSTs to `/api/v1/authenticate` (the
CPU-bearing endpoint, so `SIGN_WORK`/`R_max` are meaningful) with synthetic
`TEST-` records, paced with `constant_throughput` so the rate is fixed rather
than closed-loop. It tallies responses per AZ / instance from the identity
headers into `served_by.json`.

The three experiments differ only in the ASG capacity/scaling set **in AWS
first** (Jeel, per 5.3.3) and in the load shape:

| Exp | ASG state before the run | Load | Shows |
|---|---|---|---|
| E0  | min=desired=max=1, scaling off | ramp 10 → ~R_max | R_max (the knee); fix `SIGN_WORK` |
| E5a | desired=N fixed (N=1, then 2), scaling off | 0.9 × R_max, ≥ 5 min | response time vs instance count |
| E5b | min 1 / des 1 / max 2, scaling **on** | step 0.8 → 1.6 × R_max, 10 min each way | autoscaler moves desired 1 → 2 → 1 |

### Preconditions (in order)

1. `R_max` is known from E0 before you set the E5a/E5b rates (5.3.4).
2. Jeel applies `infra/envs/tier2` and sets the ASG capacity / scaling for the
   experiment, then shares `terraform output -raw alb_dns_name`,
   `terraform output -raw asg_name`, and the ALB / target-group ARN suffixes.
3. On the load laptop: install deps (below), set `$env:AWS_PROFILE = 'aadhaar'`,
   go wired or on a quiet Wi-Fi, and turn off VPN / backups / OS updates
   (5.3.4 validity checks). Sync the clock (NTP).

### Run one point

```powershell
$env:AWS_PROFILE = 'aadhaar'
# E5a at N=2 instances, 0.9 x R_max (example R_max = 100/s -> 90/s = 18 users x 5):
.\tests\step9_load.ps1 -Experiment e5a -RunNumber 2 -RunLabel n2 `
    -AlbDns <alb-dns> -ImageTag <sha> -Users 18 -RpsPerUser 5 -RunTime 6m -Network wired
```

Bash twin: `tests/step9_load.sh e5a 2 n2 <alb-dns> <sha> --users 18 --rps-per-user 5 --run-time 6m`.

Total target rate = `Users × RpsPerUser`. The run id is `<exp>-r<NN>-<label>`
(e.g. `e5a-r02-n2`, `e0-r01-ramp`, `e5b-r01-step-up`). Output lands in
`results/<experiment>/<run_id>/`:

- `locust_stats.csv`, `locust_stats_history.csv`, `locust_failures.csv`, `locust.html`
- `served_by.json` — request counts per AZ / instance
- `meta.json` — rate, host, image tag, network, UTC window

### Pull the server-side metrics (required)

Locust latency carries laptop/Internet jitter. The report quotes the ALB's
`TargetResponseTime` and the ASG `GroupInServiceInstances` timeline. For the
same window:

```powershell
python tests\fetch_metrics.py --run-dir results\e5a\e5a-r02-n2 --region ap-south-1 `
    --alb app/aadhaar-tier2-alb/<id> --target-group targetgroup/aadhaar-tier2-tg/<id> `
    --asg <asg_name>
```

With no `--start/--end` it reads the window out of `meta.json` (padded one
period). Writes `aws_metrics.csv` and `aws_metrics.json`. ALB metrics are
60 s data points published only while traffic flows and appear ~1-2 min late,
so run this a couple of minutes after the load stops.

### Build the charts

```bash
python analysis/analyze_load.py --experiment e5a   # or e0 / e5b
```

Produces `results/<exp>/load_summary.csv`, per-run `load_summary.json`, and the
chart that fits the experiment (`latency_vs_load.png`, `latency_vs_instances.png`
or `autoscale_timeline.png`) under `results/<exp>/charts/`.

### Validity, before you report a run (5.3.4)

- Achieved req/s within 5% of the target (`analyze_load.py` flags `valid_rate`
  false otherwise). If it fell short, lower the rate and rerun.
- No Locust CPU-bound warnings in the console.
- `served_by.json` / the ASG metric shows the instance count you expected.

## Step 11: driving E6a / E6b against two regional ALBs

Tier 3 is built as two independent regional stacks (Mumbai + Hyderabad)
with **no Route 53** (O1 descoped — see `infra/envs/tier3/README.md`).
The measurement is **client-side failover**: the prober holds both ALB
URLs and switches to the secondary after N consecutive errors on the
primary. This is a lower bound on the Route 53 case the paper design
describes.

### Prober `--urls` mode

```
python tests/prober.py --urls <primary>,<secondary> --run-id <exp>-r<NN>-<...>
    [--switch-after 3]            # consecutive errors before switch (default 3)
    [--duration 300]
    [--rate 20]                   # default 20/s, same as single-URL mode
    [--action AT_S EVENT COMMAND] # usual injections; repeatable
```

- Positional `url` and `--urls` are mutually exclusive.
- The CSV gets an extra column `active_url` (the base URL that served each
  request). Single-URL runs set it too, and it is constant there.
- Every switch appends a `switch_target` row to `events.csv`:
  `switch_target  <primary> -> <secondary> after 3 consecutive errors`.
- `meta.json` has new fields `urls` (list of 2), `switch_after`, and
  `summary.switches` (one object per switch with `t_utc_ms`, `from_url`,
  `to_url`, `at_seq`).
- Single-URL callers (step-4/7/9 scripts) are unchanged.

### E6a: planned Mumbai evacuation

**Fault:** scale Mumbai's ASG to desired 0 (no healthy instances), so the
ALB returns 503 "no healthy targets" and the prober switches to Hyderabad.
Restore by setting desired back to 2.

Preconditions: `infra/envs/tier3` applied; both regions healthy
(`curl $MU/` and `curl $HY/` each return a 200 with the right region).

```bash
export AWS_PROFILE=aadhaar
cd infra/envs/tier3
URLS=$(terraform output -raw prober_urls)
MU_ASG=$(terraform output -raw mumbai_asg_name)
cd ../../..

python tests/prober.py --urls "$URLS" --run-id e6a-r01-mu-evac \
    --rate 20 --duration 360 \
    --image-tag $(git rev-parse --short HEAD) --network wired \
    --client-location "DAU campus" --switch-after 3 \
    --meta hc_interval=5 --meta tier=3 \
    --action 60  inject_start "aws autoscaling set-desired-capacity \
       --auto-scaling-group-name $MU_ASG --desired-capacity 0 --region ap-south-1" \
    --action 300 restore      "aws autoscaling set-desired-capacity \
       --auto-scaling-group-name $MU_ASG --desired-capacity 2 --region ap-south-1"
```

- Repeat **3 times** (ARCHITECTURE.md 8.5 / PLAN "minimum 3 runs").
- Alternate `--run-id` suffix. Target is always Mumbai here (set identifier
  in the run id is for the AZ or region being evicted, so `mu-evac`).

### E6b: unplanned Mumbai region loss

**Fault:** attach the deny-all network ACL to Mumbai's two app subnets so
instances become unreachable from the ALB (8.6). ALB health checks time
out, targets go unhealthy, the ALB returns 503, and the prober switches
to Hyderabad.

Finding the subnet IDs once per run (Terraform does not expose a module
output for them yet; shell out):

```bash
export AWS_PROFILE=aadhaar
MU_VPC=$(aws ec2 describe-vpcs --region ap-south-1 \
  --filters 'Name=tag:Name,Values=aadhaar-tier3-mu' --query 'Vpcs[0].VpcId' --output text)
MU_APP_SUBNETS=$(aws ec2 describe-subnets --region ap-south-1 \
  --filters "Name=vpc-id,Values=$MU_VPC" 'Name=tag:Role,Values=app' \
  --query 'Subnets[*].SubnetId' --output text)
MU_DENY_NACL=$(aws ec2 describe-network-acls --region ap-south-1 \
  --filters "Name=vpc-id,Values=$MU_VPC" 'Name=tag:Name,Values=aadhaar-tier3-mu-deny-all' \
  --query 'NetworkAcls[0].NetworkAclId' --output text)

# Record the current (default) ACL associations so we can restore them.
for sn in $MU_APP_SUBNETS; do
  aws ec2 describe-network-acls --region ap-south-1 \
    --filters "Name=association.subnet-id,Values=$sn" \
    --query "NetworkAcls[0].Associations[?SubnetId=='$sn'].[NetworkAclAssociationId,NetworkAclId]" \
    --output text
done | tee /tmp/mu-acl-assoc.txt
```

Each line in `/tmp/mu-acl-assoc.txt` is `<assoc-id> <default-nacl-id>`. The
injection replaces each `assoc-id` with `MU_DENY_NACL`; the restore replaces
each `assoc-id` with the default NACL id back. Write the two multi-line
commands in advance and paste them into `--action` strings, or wrap them
in `tests/e6b_inject.sh` / `tests/e6b_restore.sh` on your laptop (they are
specific to the current `assoc-id`s and are not committed).

Run shape (5 runs, ARCHITECTURE.md 8.4 E6b):

```bash
cd infra/envs/tier3
URLS=$(terraform output -raw prober_urls)
cd ../../..

python tests/prober.py --urls "$URLS" --run-id e6b-r01-mu-nacl \
    --rate 20 --duration 360 \
    --image-tag $(git rev-parse --short HEAD) --network wired \
    --client-location "DAU campus" --switch-after 3 \
    --meta hc_interval=5 --meta tier=3 \
    --action 60  inject_start "bash tests/e6b_inject.sh" \
    --action 300 restore      "bash tests/e6b_restore.sh"
```

**Pass criterion (ARCHITECTURE.md 8.4 E6b):** error window ≤ 120 s in at
least 4 of 5 runs (predicted 20–105 s by Route 53; the client-side case
should be *faster* because the prober only waits `--switch-after` × interval,
with no DNS caching). 100% success from Hyderabad afterwards. Report the
failback time (time from the deny-all NACL being removed until the prober
switches back to Mumbai), which here is `--switch-after` error samples on
the current secondary.

### Analysing E6a / E6b

The step-7 analyser (`analysis/analyze.py`) works on single-target runs.
For the `--urls` CSVs the new `active_url` column makes the switch visible;
add a simple summary (first switch time, number of switches, error window,
rejoin time) in `analysis/analyze_tier3.py` — not written yet.

## Unit tests

```bash
cd tests
python -m venv .venv && .venv/Scripts/activate   # bin/activate on macOS/Linux
pip install -r requirements.txt
python -m pytest
```
