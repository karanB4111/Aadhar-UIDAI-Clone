# results/e5a/

PLAN step 9 (Kanu; reviewer Jeel) — **fixed-capacity sweep**: response time and
per-instance load at **N=1 vs N=2 instances**, scaling off (ARCHITECTURE.md 8.4
E5a, 5.3.3 step 4). This is the course's "response time against instance count"
deliverable.

Load: `POST /api/v1/authenticate`, `SIGN_WORK=4500`, driven from a laptop with
Locust `FastHttpUser` at a fixed ~150 rps (≈ 0.9 × R_max; R_max ≈ 160 laptop-
bounded, see `../e0/README.md`). Same load at both capacities so the comparison
is apples-to-apples. ASG pinned (min=desired=max=N), scaling suspended.

## Runs

| Run id      | N | Instances | achieved rps | per-instance rps | p50 | p95 | p99 | failures |
|-------------|---|-----------|--------------|------------------|-----|-----|-----|----------|
| e5a-r01-n1  | 1 | i-034175448e88b5f7a (1b) | 146 | ~146 | 74 ms | 110 ms | 140 ms | 0 |
| e5a-r02-n2  | 2 | + i-0abef6a7d76dfb715 (1a) | 147 | **~74 each** | 69 ms | 110 ms | 120 ms | 0 |

Both runs 6 min, 2026-11-05 (UTC), home laptop / Wi-Fi. Chart:
`charts/latency_vs_instances.png`. Per-run detail in `<run>/load_summary.json`.

## Result: adding the second instance halves per-instance load

- **Load split cleanly.** At N=2 the ALB divided the ~147 rps almost exactly in
  half — 26,470 requests to `ap-south-1a` vs 26,471 to `ap-south-1b` (from
  `e5a-r02-n2/served_by.json`), i.e. ~74 rps per instance versus ~146 on the one
  N=1 instance. Each instance's `ALBRequestCountPerTarget` and `CPUUtilization`
  therefore halve — this is the primary scaling signal (5.3.2), read from the
  server side via `tests/fetch_metrics.py` (Jeel's CSVs → `aws_metrics.csv`).
- **Client latency is Wi-Fi-flat, tail improves.** p50/p95 are ~70/110 ms at
  both N (the ~70 ms laptop→Mumbai RTT dominates, and one t3.micro was never the
  client-latency bottleneck at this load — see E0). The benefit shows in the
  **tail**: p99 fell 140 → 120 ms and p99.9 310 → 170 ms from N=1 to N=2, as the
  halved per-instance load leaves more headroom for transient queueing.

**Reading for the report.** With one t3.micro already well under its knee at
145 rps, the N=1→N=2 story is "load per instance halves, tail latency tightens,
zero errors" rather than "median latency drops sharply". The sharp-drop version
needs either a heavier per-request cost than a laptop can then saturate, or a
load generator inside AWS (dropped to stay within the 5-vCPU quota, 5.3.4). The
per-instance CPU / request-count halving is the direct evidence of the capacity
effect and is what the autoscaler acts on in E5b.
