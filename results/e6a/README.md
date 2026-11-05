# results/e6a/

PLAN step 11 (Jeel; reviewers: all) — Tier 3 **planned Mumbai evacuation**
(ARCHITECTURE.md 8.4 E6a). Scale Mumbai's ASG to desired 0, confirm the
Mumbai ALB returns 503 "no healthy targets", and measure how fast the
client-side prober switches to the Hyderabad ALB.

## Scope note (2026-11-05)

Open item O1 (domain) was descoped by the group. Route 53 latency-based
failover stays as paper design in ARCHITECTURE.md §5.4 and is **not
built**. E6a therefore measures **client-side failover** here, not DNS
failover. The prober (`tests/prober.py --urls <mu-alb>,<hy-alb>`) holds
both ALB URLs and switches after `--switch-after` consecutive errors. The
Route 53 case would add DNS detection (20–45 s) plus client TTL (0–60 s)
on top — treat the E6a numbers here as a **lower bound** on what the
paper-design NFR5 would deliver.

## Predicted and pass

- **Predicted error window (client-side):** `--switch-after` × `--rate⁻¹`
  ≈ 3 × 50 ms = 0.15 s per prober, plus the ALB's 503 response time
  (≤ 1 s). Expected: **< 2 s** of 5xx on Mumbai, zero on Hyderabad.
- **Pass (adapted from ARCHITECTURE.md 8.4 E6a):** zero failed requests
  after the first switch; ≥ 95% of requests served by Hyderabad within
  10 s of injection; failback to Mumbai once desired is restored (within
  the ALB rejoin ≈ 10–15 s + `--switch-after` samples).
- A real Route 53 E6a run (health check inverted) would have 0 failed
  requests throughout, and the delay is the DNS TTL instead.

## Runs

3 runs minimum, at least 2 min apart.

| Run id            | Target region evicted | errors | first_switch_s | pass |
|-------------------|-----------------------|--------|----------------|------|
| e6a-r01-mu-evac   | Mumbai                | TBD    | TBD            | ⬜   |
| e6a-r02-mu-evac   | Mumbai                | TBD    | TBD            | ⬜   |
| e6a-r03-mu-evac   | Mumbai                | TBD    | TBD            | ⬜   |

Run command: see [`tests/README.md`](../../tests/README.md) §E6a.

## Files per run

- `prober.csv` — one row per request; look at `active_url` to see the
  switch (`.../tier3-mu-alb/...` before, `.../tier3-hy-alb/...` after).
- `events.csv` — `probe_start`, `inject_start` (desired=0), `switch_target`
  (first switch), optional later `switch_target`s on failback,
  `restore` (desired=2), `probe_end`.
- `meta.json` — includes `urls` (list of 2), `switch_after`, and
  `summary.switches`.

## How to read the numbers

Pseudo-code of what `analysis/analyze_tier3.py` will compute per run (not
yet written; add before step 11 is marked reviewed):

```
error_window_s = max(t_recv) for error rows between inject_start and
                 first switch_target, minus inject_start timestamp
first_switch_s = switches[0].t_utc_ms - events.inject_start.t_utc_ms, /1000
rejoin_switch_s = time from events.restore to the next switch_target (if any)
pct_from_hy_after_switch = rows with active_url=hy / total rows after first switch
```

See `tests/prober.py` for the CSV schema (step 4).
