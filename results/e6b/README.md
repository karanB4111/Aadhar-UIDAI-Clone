# results/e6b/

PLAN step 11 (Jeel; reviewers: all) — Tier 3 **unplanned Mumbai region
loss** (ARCHITECTURE.md 8.4 E6b). Attach the deny-all network ACL to
Mumbai's two app subnets so ALB targets become unreachable, measure the
client-side prober's error window, and confirm Hyderabad continues to
serve.

## Scope note (2026-11-05)

Open item O1 (domain) was descoped by the group. Route 53 latency-based
failover with health checks (`--urls` paper design, ARCHITECTURE.md §5.4)
is **not built**. E6b therefore measures **client-side failover** here,
not DNS failover. The prober (`tests/prober.py --urls <mu-alb>,<hy-alb>`)
holds both ALB URLs and switches after `--switch-after` consecutive
errors. The Route 53 case would add DNS detection (20–45 s) plus client
TTL (0–60 s) on top — treat the E6b numbers here as a **lower bound** on
what the paper-design NFR5 would deliver.

## Predicted and pass

- **Predicted error window (client-side):** the ALB takes 7–12 s to mark
  all targets unhealthy with fast health checks (ARCHITECTURE.md 4.3),
  then every request is a 503 until `--switch-after` samples are
  classified as errors (3 × 50 ms ≈ 0.15 s). Expected error window:
  **7–13 s**, well below the 20–105 s predicted for the Route 53 case.
- **Pass (ARCHITECTURE.md 8.4 E6b, adapted):** error window ≤ 120 s in
  at least 4 of 5 runs; 100% success from Hyderabad afterwards; failback
  time recorded (time from deny-all NACL removed, through ALB rejoin,
  until the prober switches back to Mumbai).

The underlying ALB detection timing is the same as E1 (process stop) —
we are measuring an ALB with no healthy targets, which is what the
deny-all NACL produces.

## Runs

5 measured runs (r02–r06), at least 2 min apart (ARCHITECTURE.md 8.5).
r01 is kept as a documented finding — see the next section.

| Run id             | Prober | Fault              | errors | window_s | pass |
|--------------------|--------|--------------------|--------|----------|------|
| e6b-r01-mu-nacl    | v2     | Mumbai deny-all    | 299 timeouts (thrash) | — | ⚠ finding, not counted |
| e6b-r02-mu-nacl    | v3     | Mumbai deny-all    | TBD    | TBD      | ⬜   |
| e6b-r03-mu-nacl    | v3     | Mumbai deny-all    | TBD    | TBD      | ⬜   |
| e6b-r04-mu-nacl    | v3     | Mumbai deny-all    | TBD    | TBD      | ⬜   |
| e6b-r05-mu-nacl    | v3     | Mumbai deny-all    | TBD    | TBD      | ⬜   |
| e6b-r06-mu-nacl    | v3     | Mumbai deny-all    | TBD    | TBD      | ⬜   |

Run command: see [`tests/README.md`](../../tests/README.md) §E6b.

### r01: the switch-oscillation finding (prober v2)

**What happened.** Deny-all NACL attached at t ≈ 65 s. In-flight requests to
Mumbai hung until the 5 s total-timeout, and returned as `timeout` errors
*after* the prober had already decided (correctly) to switch to Hyderabad
at ~t = 75 s. The prober v2 switch logic counted every incoming error
against whichever target was *currently* active, so those late Mumbai
timeouts (which belong to the old active URL) tripped a second switch back
to Mumbai, which then tripped a third switch forward, and so on.
`events.csv` has **38 switch_target events in ~8 s**. The CSV's
`active_url` column reflects what the prober thought at *send time*, not
the thrash in the writer thread, so it is not trustworthy for this run.

Measurement that still holds (read from `prober.csv` directly, ignoring
`active_url`):

- 299 timeouts in a ~40 s window (t ≈ 65 → ~105 s), 0 after that.
- Mumbai ALB served 0 errors because the error class was `timeout`, not
  `5xx` — the in-flight requests simply never came back after the NACL
  swap, instead of the ALB answering with a 503.
- The 5-minute post-inject window (t = 65 → 300 s) had 0 errors after the
  first ~40 s.

**Fix (committed in prober v3).** Switch decisions now use the request's
*own* `active_url` (what it was sent to), not the current active target
at the time the result lands. Late results from the previous target feed
only their own counter, which is thrown away when the active target
flips. Regression test
`tests/unit/test_prober.py::test_urls_mode_late_errors_from_old_target_do_not_thrash`
pins this.

**Lesson for the report.** Client-side failover without acknowledging
in-flight state is fragile. Route 53 (or any upstream DNS failover) has
the same problem for keep-alive connections already open to the failed
region; the usual mitigation is a health-check-aware client or a
connection draining period at the ALB. Our paper design calls this out
(ARCHITECTURE.md 5.4.4 §"caching effect").

## Files per run

Same as E6a:

- `prober.csv` — `active_url` flips from Mumbai ALB to Hyderabad ALB and
  back after restore.
- `events.csv` — `probe_start`, `inject_start` (deny-all NACL attached),
  `switch_target` (first switch), later `switch_target`s on failback,
  `restore` (default NACL re-attached), `probe_end`.
- `meta.json` — `urls`, `switch_after`, `summary.switches`.

## Reading the numbers

Same as E6a. The chart to produce (one per run, plus an aggregate strip
chart) is `latency_vs_time.png` coloured by `active_url`, with `error_class`
marked. Not generated yet (`analysis/analyze_tier3.py` is the next helper
to write once runs are in).

## Lesson the report should state

The client-side error window here is **a lower bound** on the Route 53
case, not a drop-in replacement. The real Route 53 answer the paper
design NFR5 bounds (≤ 2 min for unplanned) is not measured in this
project. Buying a domain and standing up `infra/global/dns/` +
`modules/dns_failover/` is the follow-on (O1).
