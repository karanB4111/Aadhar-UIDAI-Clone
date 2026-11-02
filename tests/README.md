# tests/

Test tooling that drives load and records what clients see.

```
prober.py         failover prober (step 4): open loop, CSV per request
event.py          log a manual injection or restore to events.csv (step 4)
step7_run.ps1     one-run driver for E1 / E1b / E2 (step 7, PowerShell)
step7_run.sh      the same, for bash
unit/             pytest suite for the prober
requirements.txt  pytest now; Locust is added in step 9
```

- **Failover prober** (PLAN step 4, owner: Kanu). Spec: ARCHITECTURE.md 8.3.
- **Locust file** (PLAN step 9, owner: Kanu). `FastHttpUser`, paced at a fixed
  rate. Used for calibration (E0) and the scaling experiments (E5a, E5b).

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

## Unit tests

```bash
cd tests
python -m venv .venv && .venv/Scripts/activate   # bin/activate on macOS/Linux
pip install -r requirements.txt
python -m pytest
```
