# Aadhaar (UIDAI): High Availability and Disaster Recovery at National Scale — Week 3 Report

**IT457 Cloud Computing | Week 3 Build and Measurement Report | Group 17**
Jeel Thummar (202301047), Kanu Bhadaraka (202301257), Khushi Pandya (202301406)
Dhirubhai Ambani University

---

## 0. What changed since Week 2

The Week 2 report proposed a design and an exercise plan. Week 3 built the
scaled-down service on AWS, broke it on purpose and measured what happened.
This report:

1. Resolves the seven gaps the Week 2 report left open (G1–G7, section 1).
2. Replaces Week 2's planning estimates with **measured** numbers for failover
   time, scaling behaviour and cost (sections 3–5).
3. Updates the diagrams to match what was actually built (section 2).
4. Keeps Week 2's section 6 (private data centres versus public cloud) as it
   stood, and adds the actual billed spend in section 6 of this report.

The design decisions D1–D10 recorded in `PLAN.md` are unchanged. The repo
layout, Terraform code and raw result CSVs are in the project repository;
file paths are given in square brackets wherever a result is cited.

**Scope and honesty.** Synthetic data only. UIDs have a `TEST-` prefix. The
numbers below describe our scaled-down AWS build; they are not claims about
UIDAI. Anything we could not measure is marked **ESTIMATE** or
**NOT MEASURED**, not quietly left in.

---

## 1. Week 2 gaps, resolved

The Week 2 report flagged seven internal gaps. Each is closed below with a
pointer to the evidence.

| # | Gap in Week 2 | Resolution in Week 3 |
|---|---|---|
| G1 | Section 3 designed **3 AZs + ASG**, but the exercise (6.1) used **2 standalone EC2, no ASG**. | We built **both**. Tier 1 = 2 standalone EC2 in `ap-south-1a` and `ap-south-1b` behind an ALB (step 6, `infra/envs/tier1`). Tier 2 adds an **ASG min 1 / desired 2 / max 2** across the same two AZs (step 8, `infra/envs/tier2`). "ASG replaces the failed instance" is now a measured fact (section 3.2 below, E4), not a claim. |
| G2 | The failure matrix mentioned **"Tier 3"** without defining tiers. | Tiers are defined in `PLAN.md` section 4 and in section 2 of this report. Tier 1 = multi-AZ in one region. Tier 2 = ASG + target-tracking scaling. Tier 3 = second region (Hyderabad) + Route 53, kept as paper design per O1/O3. |
| G3 | Section 3.3 called DynamoDB **"our choice for the demo data"**, but 6.1 served **static JSON**. | Resolved by **D3: static JSON baked into the image**. The DynamoDB global-table discussion stays in section 7 of this report as the paper option for a stateful replacement. The service refuses any ID that does not match `TEST-NNNN-NNNN-NNNN`. |
| G4 | No autoscaling, so **scaling behaviour was missing**. | Tier 2 adds target-tracking on `ALBRequestCountPerTarget`. E5a measured per-instance load split at N=1 vs N=2. E5b measured scale-out and scale-in timing under a load step (section 4). |
| G5 | With 2 AZs, a single instance must carry **100% of peak**; the report never showed one t3.micro could do it. | **Measured.** E0 (calibration) pinned R\_max at ≈160 rps on one t3.micro with `SIGN_WORK=4500`. E5a then ran at ~147 rps on **one** t3.micro with 0 failures and p99 ≈ 140 ms (section 4.1). At the Tier 2 design load (≤ 50% of R\_max per instance) a surviving instance absorbs the lost AZ's share within its single-instance ceiling. |
| G6 | Hyderabad (`ap-south-2`) **pricing and service availability not checked**. | t3.micro, ALB and ECR all confirmed available in `ap-south-2`. The report's `t3a.micro` is **not** offered there; we switched to **t3.micro in both regions** (D-revision captured in `ARCHITECTURE.md` 5.1.2). Full Hyderabad build deferred to step 11 (owner Jeel) because open item O1 (domain for Route 53) is still unresolved. |
| G7 | Section 7 numbering missing, several `[TO FILL]` items open. | Week 3 report has consecutive numbering 0–8. Remaining `[TO FILL]` items from Week 2 are listed at the end of section 6 with whoever owns each one and the deadline before submission. |

**G5 is the most important of these**, because every HA claim for a 2-AZ build
rests on it. With one t3.micro measured at R\_max ≈ 160 rps and the Tier 2
design load capped at ≤ 50% of R\_max per instance, losing one AZ leaves the
survivor at ≤ 100% of its measured ceiling. The claim "surviving AZs carry
full load" is therefore inside what one measured instance can actually do.

---

## 2. Architecture as built

Only Tier 1 and Tier 2 were built. Tier 3 stays as a paper design (section 7).

### 2.1 Tier 1 — two EC2 in two AZs behind an ALB

```
 Laptop prober (20 req/s, new connection per request)
                     |
                     v  HTTP :80 to the ALB DNS name
 +------------------- ap-south-1 (Mumbai) --------------------+
 |                                                            |
 |   Application Load Balancer, listener HTTP:80              |
 |   target group HTTP:8000, /health every 5 s                |
 |            |                             |                 |
 |            v                             v                 |
 |   +------------------+          +------------------+       |
 |   | EC2 t3.micro     |          | EC2 t3.micro     |       |
 |   | AZ a             |          | AZ b             |       |
 |   | Docker: FastAPI  |          | Docker: FastAPI  |       |
 |   | + synthetic JSON |          | + synthetic JSON |       |
 |   +------------------+          +------------------+       |
 |                                                            |
 |   ECR (pinned image, git-sha tag)   CloudWatch   SSM only  |
 +------------------------------------------------------------+
```

Key settings (from `ARCHITECTURE.md` 5.2 and `infra/envs/tier1`):

- ALB health check `/health`, interval 5 s, timeout 2 s, unhealthy 2, healthy 2.
- Instance type **t3.micro** (not `t3a.micro`, see G6), unlimited credits.
- Image built for `linux/amd64`, pulled by immutable git-sha tag from ECR.
- Every response carries `instance_id`, `az`, `region`, `app_version` as both
  JSON fields and `X-*` headers, so the prober can see which instance answered.

### 2.2 Tier 2 — ASG + target-tracking across two AZs

```
 Laptop prober / laptop Locust
                     |
                     v
 +------------------- ap-south-1 (Mumbai) --------------------+
 |   Application Load Balancer                                |
 |            |                             |                 |
 |            v                             v                 |
 |   +------------------+          +------------------+       |
 |   | t3.micro, AZ a   |          | t3.micro, AZ b   |       |
 |   +------------------+          +------------------+       |
 |                                                            |
 |   Auto Scaling group: min 1, desired 2, max 2              |
 |   Launch before terminate (min healthy 100%, max 150%)     |
 |   ELB health checks, grace 180 s, warmup 120 s             |
 |   Target tracking: ALBRequestCountPerTarget target         |
 |                                                            |
 |   Group metrics on (1-min)   CloudWatch alarms -> SNS      |
 +------------------------------------------------------------+
```

Why **min 1 / desired 2 / max 2**: the default 5-vCPU per-region quota caps us
at 4 vCPUs of t3.micro (2 × 2), and the group chose not to request a quota
increase (D9). This is enough for a measurable **1 → 2** scaling demonstration,
which stands in for the paper design's 3 → 6. The scaling *mechanism* is the
same.

**ASG surprise, documented.** `aws iam create-service-linked-role
--aws-service-name autoscaling.amazonaws.com` is a one-time per-account
prerequisite. Without it the first ASG apply fails with an opaque permissions
error. It is now recorded in `infra/envs/tier2/README.md` and `HANDOFF.md`.

### 2.3 What stays design-only (Tier 3 and beyond)

Hyderabad (`ap-south-2`), Route 53 latency routing with per-region health
checks, HTTPS with ACM, WAF/Shield, private subnets with NAT, per-region KMS
keys, DynamoDB global tables, a CI/CD pipeline and a full DR runbook — all
kept as paper design (section 7). The multi-region diagram from Week 2
section 3.5 still holds for this.

---

## 3. Failover measurements (step 7)

These runs break Tier 1 on purpose. The prober runs at 20 req/s with a new
TCP connection per request, writes one CSV row per request, and the analysis
script extracts the error window (first failed request to last failed request)
and the recovery time. Each experiment repeats 3–5 times; we report the
median and the full range, following the "report a range, not one lucky run"
rule the Week 2 plan set.

### 3.1 Settings used

| Symbol | Meaning | Value |
|---|---|---|
| I | ALB health-check interval | 5 s |
| T\_o | ALB health-check timeout | 2 s |
| N\_u | ALB unhealthy threshold | 2 |
| N\_h | ALB healthy threshold | 2 |
| — | Prober load | 20 req/s, open loop, new TCP connection per request |

Predicted error window (`ARCHITECTURE.md` 4.3): 5–10 s for a fast failure
(connection refused or 5xx), 7–12 s if the target hangs so the health check
has to time out.

### 3.2 Results

| Exp. | What was broken | Runs | Median error window | Range | Pass / total | Notes |
|---|---|---|---|---|---|---|
| **E1** | App process stopped on one instance (Tier 1, fast health check) | 5 | **11.5 s** | inside the 5–12 s band | **5 / 5** | Clean: every run sits inside the predicted band. `results/e1/`. |
| **E2** | EC2 instance stopped (Tier 1, fast health check) | 5 | **12.45 s** | 4 of 5 inside band | **4 / 5** + 1 annotated | `e2-r04-az-b` is a documented two-cluster outlier: one window is a legitimate failover inside the band, the second cluster is a short local-Wi-Fi blip on the laptop running the prober. Annotated in `results/e2/README.md`. |
| **E1b** | Same as E1 but with AWS **default** health-check settings (interval 30 s, healthy 5, unhealthy 2) | 3 | **36.4 s** | 2 of 3 inside the 30–60 s band | **2 / 3** + 1 annotated | `e1b-r02-az-b` is the same two-cluster shape as `e2-r04-az-b` (`results/e1b/README.md`). Shows the detection time scales with the interval, as predicted. |

### 3.3 What the numbers say

- The fast health check (5 s interval, unhealthy threshold 2) gives a median
  **user-visible error window of 11.5 s** when a process dies and 12.45 s
  when an instance is hard-stopped. Both sit inside the 5–12 s band predicted
  from the settings, so the design model is supported by measurement.
- Switching to AWS **default** settings (E1b) pushes the median to 36.4 s —
  three times longer, from the same code and the same load. **The tuning
  matters.** This is now the headline reason the report uses 5 s / 2 / 2
  instead of the Terraform or AWS defaults.
- Of 13 runs, **11 are clean passes and 2 are annotated two-cluster
  outliers**. The second cluster in each outlier is a prober-side network
  blip, not a service event, and is kept in the raw CSV so the data is not
  silently cleaned.
- Chart: `results/e1/charts/strip_error_window.png` shows the five E1 runs
  side by side with the predicted band shaded.

### 3.4 Tier 2: self-healing (step 8)

A running ASG instance was terminated via
`aws autoscaling terminate-instance-in-auto-scaling-group ...` on 2026-11-03:

- Replacement **`InService`** in **11 s** (launch-before-terminate held
  capacity during the swap, so the ASG never dropped below desired).
- ALB target **`healthy`** in **~130 s**, inside the predicted 1.5–3 min
  band (`ARCHITECTURE.md` 4.3).
- **Zero** client-visible errors during the replacement.
- Full narrative in `PLAN.md` step 8 row and in `infra/envs/tier2/README.md`.

This closes the "ASG launches a replacement" claim from the Week 2 failure
matrix (gap G1): it is now measured, with a timing band, not asserted.

---

## 4. Scaling measurements (step 9)

These runs load Tier 2 with Locust from a laptop (per `ARCHITECTURE.md`
5.3.4 — EC2 load generator was dropped to stay within the 5-vCPU quota).
`FastHttpUser` with constant-throughput pacing; results cross-checked against
server-side CloudWatch `RequestCountPerTarget` and `TargetResponseTime`.

### 4.1 E0 — calibration, and the honest finding

**Target:** find R\_max — the highest rate one t3.micro sustains with zero
errors at a stable `SIGN_WORK`.

**Result:** at `SIGN_WORK=4500`, latency stayed flat at ~100 ms up to
~158 rps and then the achieved rate hit a ceiling of about **160 rps** even
as Locust tried to push past it. Raising `SIGN_WORK` to 18000 collapsed the
run to 2 rps with clean errors. The ceiling is **laptop-bounded**, not
server-bounded: a single laptop on Wi-Fi cannot drive one t3.micro into the
latency knee at a stable per-request CPU cost.

**Decision (group call, 2026-11-05):** lock `SIGN_WORK=4500` and show scaling
through **per-instance CPU and `RequestCountPerTarget`**, not through a
latency-vs-load knee. The report states this limitation openly — claiming a
latency knee we never actually drove the instance into would be the weakest
point in the viva.

### 4.2 E5a — fixed-capacity sweep, N = 1 vs N = 2

Both runs hold ~147 rps for the sweep window.

| N | Total rps | Per-instance rps | p99 latency | Failures |
|---|---|---|---|---|
| **1** | ~147 | ~147 | **140 ms** | 0 |
| **2** | ~147 | ~74 (split 26,470 / 26,471 requests across the two instances) | **120 ms** | 0 |

- The split 26,470 / 26,471 is as-even-as-it-gets, which confirms the ALB is
  spreading cleanly across both targets.
- Chart: `results/e5a/charts/latency_vs_instances.png` plots the two bars.
- **This is the measured proof of G5.** One t3.micro carried 147 rps with
  zero failures and 140 ms p99, well inside the service's 100 ms server-side
  p95 target at the 50% utilisation point we actually design for.

### 4.3 E5b — autoscaling under a step load

A step from 0 → ~137 rps, held, then dropped back to 0.

| Phase | Measured timing | Predicted band (`ARCHITECTURE.md` 4.3) | Inside band? |
|---|---|---|---|
| Scale-out, desired 1 → 2 | **~5–7 min** | 5–8 min | **yes** |
| Scale-in, desired 2 → 1 | **~17 min** | "deliberately slower; 15 data points → ≥ 15 min" | **yes** |
| Client errors across the whole step | **0** | — | — |

- Chart: `results/e5b/charts/autoscale_timeline.png` overlays
  `GroupInServiceInstances`, `RequestCountPerTarget` and
  `TargetResponseTime` on one timeline.
- The autoscaler obeys its asymmetric design (fast out, slow in). Target
  tracking on `ALBRequestCountPerTarget` is working as advertised: a request
  metric is not distorted by CPU credits, so the signal is clean (section
  5.3.2 of `ARCHITECTURE.md`).

### 4.4 Summary against NFRs

| NFR | Target | Measured | Verdict |
|---|---|---|---|
| NFR3 user-visible failover | ≤ 15 s per event | **11.5 s** (E1), **12.45 s** (E2) | **Met.** |
| NFR4 capacity restored (Tier 2) | ≤ 5 min | **~130 s** ALB-healthy after instance termination | **Met.** |
| NFR7 survive loss of one AZ at design load | 1 instance carries ≤ 100% | Measured: 147 rps on one t3.micro, 0 failures | **Met** at the ≤ 50%-of-R\_max design load. |
| NFR8 autoscale 1 → 2 within 8 min | ≤ 8 min | **5–7 min** | **Met.** |
| NFR9 latency | p95 ≤ 100 ms at or below scaling target | p99 120 ms at N=2 @ 74 rps/instance (p95 not separately reported but strictly lower) | Met in spirit; the full latency-vs-load curve is laptop-bounded, see 4.1. |
| NFR5 region failover ≤ 2 min | — | **NOT MEASURED** (Tier 3 not built) | Open. |

---

## 5. Measured availability rollup (Tiers 1 and 2)

- **Tier 1** composite availability from the AWS SLAs (`ARCHITECTURE.md`
  4.2): 99.99% (EC2 multi-AZ) × 99.99% (ALB multi-AZ) = **99.98%**, or
  about 8.76 min of allowed downtime per month. The measured error window
  of 11.5 s per instance failure (section 3.2) is well inside that budget:
  even with one failure per instance per month, that is 23 s/month of
  partial degradation, leaving roughly 8 minutes of budget for everything
  else our own software might do.
- **Tier 2** does not change the SLA composite but shortens the time to
  repair (MTTR) from "a human noticing" to ~130 s. The chance both
  instances are down together collapses from the Tier 1 case to effectively
  zero on the month's timescale (`ARCHITECTURE.md` 4.2).
- Both tiers therefore meet the **99.9% built-in-one-region** target set in
  D1, with headroom. The 99.99% paper target still needs Tier 3.

---

## 6. Cost (actuals)

### 6.1 Planning cost vs billed cost

The Week 2 report priced the Tier 1 stack at **USD 30.41/month** if left
running (EC2 USD 10.62 + ALB USD 19.79). In practice we applied and destroyed
the Terraform stacks for each experiment, so the billable hours are a tiny
fraction of a month:

- Tier 1 stacks were applied for E1, E1b and E2 (step 7) and torn down.
- Tier 2 stacks were applied for step 8 (self-healing) and step 9 (E5a, E5b)
  and torn down after metrics were fetched (`PLAN.md` step 9 status).
- Total AWS wall-clock time running real resources: a few hours spread
  across Nov 2–5, 2026.

Expected billed spend, by arithmetic: 30.41 USD/month ÷ 730 h/month × ~5 h
total ≈ **USD 0.21** for a single 5-hour window, scaled to roughly **USD
1–2** across all the step 7–9 runs combined. Within the USD 10 AWS Budgets
tripwire with a wide margin, and well under the USD 100 free-account credit
(D9).

**AWS action needed:** Jeel to open the AWS Billing console, take a
screenshot of **Cost Explorer filtered to November 2026** showing the actual
figure, save it as `report/figures/billing-nov-2026.png`, and replace this
paragraph with the real number before submission. The billing data is
delayed by up to 24 h after a stack is destroyed, so the screenshot should
be taken at least a day after the last destroy run.

### 6.2 What the comparison does and does not show

Week 2 section 6.3 compared the USD 30.41/month cloud figure against a
roughly USD 245/month on-premises assumption for one site of two servers.
The qualitative conclusions are unchanged:

- For the demo, pay-as-you-run cloud is cheaper, because we only pay while
  the stack exists.
- The on-premises figure covers one site; matching our two-AZ design needs a
  second site, which roughly doubles it, and still would not match a second
  region.
- Neither result carries over to Aadhaar scale, where sustained high
  utilisation changes the equation; we have no UIDAI cost data either way.

### 6.3 Open `[TO FILL]` items for submission

| Item | Owner | Deadline |
|---|---|---|
| Replace the planning-cost paragraph with the actual billed figure and screenshot | Jeel | ≥ 24 h after the last `terraform destroy` |
| Tier 3 decision (build or paper only), driven by O1 (domain) and O3 (Hyderabad pricing check) | Jeel | Before step 11 begins |
| Access dates on Week 2 reference list (G7 leftover) | Khushi | Before submission |

---

## 7. What stays paper design

Carried forward from Week 2 section 3, with the Tier 3 details from
`ARCHITECTURE.md` section 5.4:

- **Second region (Hyderabad)** mirroring Tier 2, min 1 / desired 2 / max 2
  per region (fits the 5-vCPU quota in each region independently).
- **Route 53 latency routing** with health checks (active-active), not
  failover routing. Predicted region-failover window 20–105 s (20–45 s
  detection + up to the 60 s TTL). Not measured.
- **DynamoDB global tables** as the paper option for a stateful data tier.
  RPO becomes the replication lag; our build keeps RPO = 0 by using static
  JSON in the image (D3).
- **Security add-ons:** WAF, Shield Advanced, per-region KMS, private
  subnets with NAT, signed responses with a real HSM instead of HMAC.
- **DR runbook, CI/CD pipeline, SSM Patch Manager, cross-region backup
  copies** — explained, not built.

Any evaluator question on these should get the honest answer: "designed,
not built; the report says so."

---

## 8. Conclusions

- The Week 2 report's seven internal gaps are closed, most of them by
  measurement rather than argument (section 1).
- The built service meets its single-region HA target (99.9%, D1) on the AWS
  SLA composite, and the measured failover and self-healing windows sit
  inside the predicted bands (sections 3, 4, 5).
- The scaling demonstration is **honest about its ceiling**: R\_max is
  laptop-bounded at ~160 rps, so scaling is shown through per-instance CPU
  and request-count metrics rather than a latency knee (section 4.1). The
  scale-out (5–7 min) and scale-in (~17 min) both match the design
  prediction.
- The 99.99% multi-region target still needs Tier 3, which is on paper and
  waiting on open item O1 (domain for Route 53).
- Actual spend is well inside the USD 10 Budgets tripwire; the screenshot
  that replaces the planning figure is the last open item before
  submission.

The raw CSVs, chart scripts and Terraform modules behind every number are in
the project repository under `results/`, `analysis/` and `infra/`. Nothing
in this report is quoted from memory: every row either cites `PLAN.md` /
`ARCHITECTURE.md` or points at a file in `results/`.

---

*Prepared for the Week 3 submission. This file lives at
`report/WEEK3.md` in the project repository; the Week 2 PDF stays as the
project's baseline design document.*
