# Architecture: Aadhaar-Style HA/DR Demo on AWS

**Status:** Approved with PLAN.md on 2026-11-02. Built so far: the mock service
(sections 2.1 and 5.1.1, PLAN step 2, in `service/`). Nothing on AWS yet. Step
progress is tracked in PLAN.md section 6.
**Prepared:** 31 October 2026. AWS facts were checked against AWS documentation,
SLA pages and the AWS Price List API between 29 and 31 October 2026.

**How to read this document**

- Every number has a reference in square brackets (see [section 14](#14-references))
  or a calculation shown next to it.
- **UNVERIFIED** means we could not confirm it from an official source. Check it
  before relying on it.
- **ESTIMATE** means a planning number that one of our experiments will replace with
  a measurement.
- **Decision** marks a choice this document asks the group to approve.
- Prices are indicative, taken from the AWS Price List API. Once the bill of
  materials ([section 9.1](#91-bill-of-materials)) is approved, confirm them in the
  AWS Pricing Calculator.

**Where each PLAN.md step finds its inputs**

| PLAN step | Sections |
|---|---|
| 2 FastAPI service | 2.1, 5.1 |
| 4 Failover script | 8.3, 8.5 |
| 6 Terraform Tier 1 | 5.2, 6, 7 |
| 7 Tier 1 tests | 8.4 (E1, E1b, E2) |
| 8 Tier 2 ASG | 5.3, 8.4 (E3, E4) |
| 9 Locust | 5.3.3, 5.3.4, 8.4 (E0, E5a, E5b) |
| 10 Report updates | 11 |
| 11 Tier 3 | 5.4, 8.4 (E6a, E6b), 12 (O1) |
| 12 Destroy and confirm bill | 9, 10 |

---

## 1. Summary

We will build a small, Aadhaar-style authentication service (FastAPI in Docker on
EC2, synthetic data only) in three tiers, and measure how it behaves when parts of it
fail. Tier 1 places two instances in two Availability Zones (AZs) of Mumbai behind an
Application Load Balancer (ALB) and measures how long users see errors when an
instance or process dies. Tier 2 replaces the instances with an Auto Scaling group
(ASG) across two AZs (**min 1, desired 2, max 2**, within the default 5-vCPU
per-region quota), so failed instances are replaced automatically and capacity
follows load between 1 and 2 instances. Tier 3 copies the stack to Hyderabad
(**min 1, desired 2, max 2** there too) and puts Route 53 latency-based routing with
health checks in front, which makes both regions active, in the same way UIDAI runs
its two data centres. On paper, the same pattern scaled to UIDAI's stated target of
25 to 30 crore authentications a day needs about 21,000 authentications per second at
peak, and about 42,000 per second of provisioned capacity across two regions and six
AZs. The SLA maths gives 99.98% for one region, which meets our 99.9% build target.
Two regions give about 99.996% if a regional failover happens at most about twice a
month and takes no more than about 1.5 minutes, which meets 99.99% on paper. The
account is the group's **free AWS account with the USD 100 sign-up credit**; the
planned test spend is about USD 5.5 including GST if we do not buy a domain, well
within the credit, and the USD 10 Budgets alert is kept as a tripwire. **We will not
request a vCPU quota increase**; Tier 2's instance count is sized to fit the default
5-vCPU quota. The biggest practical risks are forgotten resources and the lead time
for a domain.

| Key number | Value | Basis |
|---|---|---|
| Aadhaar volume, 2026 | about 10 crore authentications/day, about 1,157/s on average | UIDAI chairman, Sep 2026 [77][78] |
| Aadhaar design target | 30 crore/day: 3,472/s average, about 20,800/s at peak | [77]; peak factor 6.0 (section 3.2) |
| Paper capacity, 2 regions × 3 AZs | 2.0 × peak, about 41,700/s (6,944/s per AZ) | N/(N−1) rule, section 3.3 |
| Built availability, Tiers 1–2 (SLA composite) | 99.98%, about 8.8 min/month | EC2 99.99% × ALB 99.99% [1][2] |
| Paper availability, Tier 3 | about 99.996% with one regional failover a month | Section 4.2 |
| ALB health check | 5 s interval, 2 s timeout, healthy 2, unhealthy 2 | Section 5.2 |
| User-visible failover, instance or AZ | 5–12 s expected | Section 4.3 |
| Capacity restored by the ASG | 1.5–3 min (ESTIMATE; E4 measures it) | Section 4.3 |
| Region failover, unplanned | 20–105 s (detection 20–45 s plus a TTL of up to 60 s) | Section 4.3 |
| Recovery point objective (RPO) | 0, because the data is read-only and baked into the image | D3 |
| Instance type | t3.micro in both regions, unlimited credit mode | Section 5.1.2 |
| Failover test load | 20 requests/s, open loop, a new connection per request | Section 3.4 |
| Runs per failover experiment | 5, reported as median and min–max | Section 8.5 |
| Planned spend | about USD 4 incl. GST with no domain bought; about USD 7.5 with a USD 3 `.click` domain. Hard ceiling: USD 100 free-account credit (D9). | Section 9.4 |

**Decisions this document asks the group to approve**

1. t3.micro in both regions, credits set to unlimited, image built for `linux/amd64`
   (section 5.1.2).
2. Tier 2 runs across 2 AZs with **min 1, desired 2, max 2**, and scales on
   `ALBRequestCountPerTarget` (section 5.3). The ceiling of 2 is set by the
   default 5-vCPU per-region quota and the group's choice not to request an
   increase (D9).
3. Tier 3 uses latency-based routing with health checks (active-active) rather than
   failover routing. This is P1 in [section 13](#13-proposed-changes-to-approved-decisions).
4. Images are stored in ECR in Mumbai and replicated to Hyderabad. Nothing is built
   on the instances (section 5.1.3).
5. Each region gets a custom VPC with separate load-balancer and app subnets per AZ
   (section 6.1).
6. Terraform state lives in S3 with S3-native locking (section 7).
7. The test method: a 20 requests/s open-loop prober and 5 runs per failover
   experiment (section 8).
8. The domain route for open item O1, and the account checklist for O2 (section 12).

---

## 2. Requirements

Sources: the course brief [81], the Week 2 report [81] (sections 2, 3 and 6), and
PLAN.md.

### 2.1 Functional requirements

| ID | Requirement |
|---|---|
| FR1 | `POST /api/v1/authenticate` takes a synthetic ID and one factor (an OTP or demographic fields). It returns a Yes or No decision, a transaction ID, a timestamp and an HMAC signature, mimicking UIDAI's signed Yes/No response (report 2.1). |
| FR2 | Every response carries `instance_id`, `az`, `region` and `app_version`, so the client can see which server answered (report 6.1). |
| FR3 | `GET /health` is a shallow check: the process is up and the dataset is loaded. It must answer in under 100 ms and must never call anything outside the process. The ALB uses it. |
| FR4 | `GET /health/deep` is a canary check: it runs one synthetic authentication end to end (record lookup and signing) for a known test record and returns 200 or 503. Only Route 53 uses it, in Tier 3. |
| FR5 | `GET /` returns the service identity, with the same fields as FR2. |
| FR6 | The synthetic dataset is static JSON baked into the image (D3). IDs use an obviously fake format (for example a `TEST-` prefix) so they can never be mistaken for real Aadhaar numbers. |
| FR7 | The CPU cost per authentication can be configured (an environment variable such as `SIGN_WORK` sets the number of hashing iterations). Calibration (E0) uses it to make one instance saturate at a known rate. |
| FR8 | Test tooling: an open-loop failover prober that writes CSV (step 4), a Locust test (step 9), analysis scripts that draw charts (step 5), and run scripts that log the time of each failure injection. |

### 2.2 Non-functional requirements

| ID | Requirement | Target | Why | How we check it |
|---|---|---|---|---|
| NFR1 | Availability, built | ≥ 99.9% a month in one region | D1 | SLA composite (4.2) plus measured failover windows |
| NFR2 | Availability, paper design | ≥ 99.99% a month across two regions | D1 | Section 4.2 |
| NFR3 | User-visible failover after losing an instance or AZ | ≤ 15 s per event | ALB health-check settings (4.3) | E1–E3 |
| NFR4 | Capacity restored after losing an instance | ≤ 5 min (Tier 2) | ASG replacement (4.3) | E4 |
| NFR5 | Region failover | ≤ 2 min when unplanned; zero failed requests when planned | Route 53 plus TTL (4.3) | E6a, E6b |
| NFR6 | RPO | 0 | Read-only data (D3) | By design |
| NFR7 | Survive the loss of one AZ at design load without overload | Capacity of N/(N−1) × load | Report 3.3 | E3 |
| NFR8 | Scale out automatically | 1 → 2 instances in the live demo (the paper design targets 3 → 6; the live cap is set by the free-account 5-vCPU quota, D9); the new instance serving within 8 min of a load step | The course asks for scaling behaviour [81] | E5b |
| NFR9 | Latency | Server-side p95 ≤ 100 ms at or below the scaling target; client-side p99 ≤ 2 s | UIDAI answered more than 98% of field requests within 2 s [79]. The server-side value is our own choice. | ALB `TargetResponseTime`, prober |
| NFR10 | Cost | ≤ USD 100 in total (the free-account credit), including tax; USD 10 Budgets alert as early tripwire | D9 | AWS Budgets, final bill |
| NFR11 | Reproducible | Every tier is created and destroyed by Terraform; the image is pinned by an immutable tag | D7, report 3.4 | Steps 6, 8, 11, 12 |
| NFR12 | Data residency | Indian regions only (`ap-south-1`, `ap-south-2`) | Report 5.1 | By design |
| NFR13 | Security baseline | No inbound path except through the ALB; no SSH; IMDSv2; least-privilege IAM; synthetic data only | Report 3.6 | Review checklist (section 6) |
| NFR14 | Observability | Every experiment produces a per-request CSV and CloudWatch exports; alarms cover healthy hosts, 5xx, latency and Route 53 status | Report 3.6 | `results/` |

### 2.3 Constraints

- A budget of USD 10 (D9), three members, and the Week 3 build window [81].
- A single AWS account, still to be chosen (O2).
- The default EC2 quota for running On-Demand standard instances is **5 vCPUs per
  region** [48]. The whole project is sized to fit within this default — no quota
  increase will be requested (D9, section 10, risk R1).
- Hyderabad is an opt-in region and must be enabled before use [56].
- What the Free Tier gives depends on when the account was created (section 9.5).
- Decisions D1–D10 are approved: FastAPI, Docker, Terraform, Locust, commits straight
  to `main`.

### 2.4 Out of scope

Real UIDAI APIs, data or biometrics; enrolment and e-KYC; HSM or PKI signing (we use
an HMAC demo signature); WAF and Shield; private subnets with NAT; per-region KMS keys;
DynamoDB, which stays in the paper design; a CI/CD pipeline; a full DR runbook; IPv6;
multiple accounts.

---

## 3. Capacity estimates

### 3.1 Real Aadhaar volumes

One crore is 10^7. Average per second = daily volume ÷ 86,400.

| Period | Authentications | Per day | Average/s | Year on year | Source |
|---|---|---|---|---|---|
| Apr 2025 | about 210 crore in the month | 7.00 crore | 810 | about 8% | PIB, 16 May 2025 [73] |
| Jul 2025 | 221 crore | 7.13 crore | 825 | 3.8% | UIDAI/PIB release, 8 Aug 2025 [74] |
| Aug 2025 | 221 crore | 7.13 crore | 825 | 10.3% | Outlook Business, quoting UIDAI [75] |
| Oct 2025 | 219.51 crore | 7.08 crore | 820 | — | Tribune/ANI, quoting MeitY [76] |
| Nov 2025 | 231 crore | 7.70 crore | 891 | 8.47% | Tribune/ANI, quoting MeitY [76] |
| Sep 2026 | "about 10 crore a day" | 10.0 crore | 1,157 | about +40% on Aug 2025 (indicative) | UIDAI chairman at Global Fintech Fest 2026 [77][78] |
| Target | "25 to 30 crore" a day | 30.0 crore | 3,472 | — | Same speech [77][78] |

- The cumulative total passed 15,011.82 crore (150 billion) by the end of April
  2025 [73].
- Peak-day evidence: on 1 September 2025 there were over 1.5 crore face
  authentications in one day [75], against an August 2025 face-authentication average
  of 18.6 crore ÷ 31 = 0.60 crore a day, a factor of **2.5**. On 1 July 2025 the
  figure was 1.22 crore against 19.36 crore ÷ 31 = 0.62 crore a day [74], a factor of
  **1.95**. Both peaks fall on the first day of a month.
- UIDAI's own website still says the CIDR "is currently capable of handling tens of
  millions of authentications on a daily basis" [72]. Actual volume is now about
  100 million a day [77], so that page is out of date (report fix F13).

### 3.2 From daily volume to peak requests per second

Peak = daily average/s × peak-day factor × peak-hour factor.

- **Peak-day factor = 2.5.** This is the largest first-of-month surge seen in face
  authentications (3.1). It is the only modality with published single-day records,
  so we assume the total follows the same pattern, which is conservative.
- **Peak-hour factor = 2.4.** ASSUMPTION: the busiest hour carries 10% of the day's
  traffic, so 24 × 0.10 = 2.4. No public hourly data exists. Sensitivity: 8% gives
  1.92 and 12% gives 2.88.
- **Combined factor = 2.5 × 2.4 = 6.0.**

| Scenario | Average/s | Peak/s (× 6.0) | Range from the 8–12% hour sensitivity |
|---|---|---|---|
| 2026 actual (10 crore a day) | 1,157 | **6,944** | 5,556–8,333 |
| Design target (30 crore a day) | 3,472 | **20,833** | 16,667–25,000 |

### 3.3 Provisioned capacity in the paper design

The paper design is two regions with three AZs each, both regions active, and we
design for any single failure. Call the peak P = 20,833/s.

- **If a whole region is lost,** the other region must carry P by itself across its
  three AZs, so each AZ needs P/3 = 6,944/s.
- **If one AZ is lost while both regions are up,** each region carries P/2 across two
  AZs, which is P/4 = 5,208/s per AZ. That is less than P/3, so the region-loss case
  sets the size.
- **Total provisioned = 6 AZs × P/3 = 2P, about 41,700/s.**
- To survive a double failure (a region plus an AZ in the surviving region), each AZ
  needs P/2, so the total is 3P, about 62,500/s.
- The report's single-region rule (3 AZs need 1.5P) is not enough on its own once we
  also want to survive losing a region. That is why the two-region total is 2P, not
  1.5P (report fix F24).

### 3.4 Demo load

**Failover experiments (E1–E4, E6): 20 requests/s, open loop, a new TCP connection
per request.** The reasons:

1. **Resolution.** At 20 requests/s we get a reading every 50 ms. The report's
   1 request/s gives only 1 s resolution and about 5 failed requests per run.
2. **Enough failures to measure.** Expected failed requests = rate × share routed to
   the dead target × window = 20 × 0.5 × (5 to 12 s), which is 50 to 120 per event.
3. **One instance can carry it all.** This is far below one t3.micro's capacity,
   even with signing work, which closes gap G5.
4. **Cheap.** 20 new connections/s is 0.8 of an ALB capacity unit (LCU), because one
   LCU covers 25 new connections/s [12]. That costs about USD 0.0064 an hour.

**Calibration (E0).** Find R_max, the highest rate one t3.micro sustains with zero
errors and a server-side p95 below twice its low-load value. Tune `SIGN_WORK` so that
R_max lands at about 100–200 requests/s. That keeps every test within what one small
load generator can drive.

**Scaling settings, derived from R_max** (sized for the free-account 5-vCPU
quota, so Tier 2 and Tier 3 run with 2 instances maximum per region):

- Target per instance: T = 0.5 × R_max. As an `ALBRequestCountPerTarget` target value
  that is 30 × R_max requests per minute (for example 3,000 when R_max = 100/s).
- **E5a, fixed-capacity sweep:** total load L = 0.9 × R_max with N = 1 and N = 2
  instances, giving per-instance utilisation of 90% and 45%. The sweep is short, but
  it shows the direction of the response-time curve clearly enough for the report.
- **E5b, autoscaling step:** one step from 0.8 × R_max to 1.6 × R_max, held
  10 minutes, then back down. Expected: `desired` moves 1 → 2, then back to 1 after
  the scale-in cooldown.
- **E3, AZ loss under load:** 0.8 × R_max on 2 instances (each at 40% of R_max).
  After one AZ is lost, the survivor carries 0.8 × R_max (80% of R_max). This is the
  2-AZ 200% rule in action and sits inside the single-instance ceiling.

### 3.5 Linking the demo to the paper design

Instances needed = ceil(provisioned rate ÷ measured R_max). As an example only: if
R_max = 150/s, then 41,667 ÷ 150 gives about 278 instances of our size. Real
biometric matching is far heavier than our mock, so the method is what matters here,
not the number.

---

## 4. Availability and recovery targets

### 4.1 AWS SLAs (checked on the official pages)

| Service | Commitment | Condition | Source |
|---|---|---|---|
| EC2, Region-Level | 99.99% a month | Instances run in two or more AZs. "Unavailable" means all of them have no external connectivity at the same time. | [1], updated 25 May 2022 |
| EC2, Instance-Level | 99.5% per instance | — | [1] |
| ELB, Multi-AZ load balancer | 99.99% | The load balancer is in two or more AZs and has at least one healthy target | [2], updated 25 Jul 2022 |
| ELB, single AZ | 99.9% | — | [2] |
| Route 53 | 100% per hosted zone | "Unavailable" only if all four name servers fail every query for a whole minute | [3], updated 16 Apr 2025 |

SLAs are thresholds for service credits, not measured availability. They exclude our
own software, our misconfigurations and problems on the Internet [1][2][3].

Downtime allowed in a 730-hour month (43,800 minutes): 99.5% allows 219 min; 99.9%
allows 43.8 min; 99.98% allows 8.76 min; 99.99% allows 4.38 min.

### 4.2 Composite availability for each tier

**Assumptions**

- A1. Each component delivers exactly its SLA. We treat the SLA as an availability
  floor.
- A2. Failures are independent across AZs and across regions. Correlated events break
  this, for example a control-plane bug, or a bad deployment of our own reaching every
  instance at once.
- A3. Components in series multiply. A redundant group has availability
  1 − Π(1 − A_i).
- A4. Our own software, deployments and operator mistakes are left out. They would
  use up whatever budget remains.
- A5. While a failed instance is still being detected, only the share of traffic sent
  to it fails. We count this separately, below.

**Baseline with no redundancy (one instance behind an ALB):**
0.9999 × 0.995 = **99.49%**, about 223 minutes of downtime a month.

**Tier 1**

- The instance pair, if failures were independent: 1 − (1 − 0.995)² = 99.9975%.
  However, AWS only commits to 99.99% for instances spread over several AZs (the
  Region-Level SLA), so we use **99.99%** for the compute layer.
- Combined with the ALB: 0.9999 × 0.9999 = **99.98%, or 8.76 min/month**. That meets
  the 99.9% target and leaves 35 min/month for our own faults.
- Cost of the detection window: each instance failure loses about
  0.5 × 12 s = 6 s of full-outage equivalent. One failure per instance per month costs
  about 12 s, which is negligible.

**Tier 2**

The SLA composite stays at 99.98%. What changes is the time to repair (MTTR), which
makes it much less likely that both instances are down together. As an illustration,
assume one failure per instance per month (MTBF = 730 h):

- Manual repair, MTTR 4 h: U = 4/734 = 0.545%, so the pair is down
  U² = 2.97 × 10⁻⁵ of the time, about 1.3 min/month.
- ASG repair, MTTR 5 min: U = 0.0114%, so U² = 1.3 × 10⁻⁸, about 0.0006 min/month.

The MTBF and MTTR here are assumptions to show the effect; E4 measures the real MTTR.
With three AZs and one instance per AZ, losing an AZ leaves two instances at 75% of
R_max at the design load (3.4), so a capacity shortfall causes no downtime.

**Tier 3**

- Each region is 99.98%, so its unavailability U is 0.0002.
- Losing both regions at once (independent) is U² = 4 × 10⁻⁸, about 0.002 min/month.
  Route 53 itself is 100% [3].
- The term that dominates is the failover time for clients of the failed region. With
  k regional failovers a month, each taking t_fo:
  A ≈ 1 − k × t_fo ÷ 43,800 min.
- For k = 1 and t_fo = 94 s: **99.9964%**. 99.99% holds while
  k × t_fo ≤ 4.38 min, which allows 2 failovers a month at 94 s or 7 at 34 s.
- Caveat on A2: a bad image deployed to both regions defeats the second region. We
  therefore deploy one region at a time and use instance refresh with automatic
  rollback (5.3).

### 4.3 RTO and RPO for each tier, from the settings

**Settings used**

| Symbol | Meaning | Value |
|---|---|---|
| I | ALB health-check interval | 5 s |
| T_o | ALB health-check timeout | 2 s |
| N_u | ALB unhealthy threshold | 2 |
| N_h | ALB healthy threshold | 2 |
| D | Deregistration delay | 15 s |
| G | ASG health-check grace period | 180 s |
| W | Default instance warmup | 120 s |
| I_r | Route 53 health-check interval | 10 s |
| N_r | Route 53 failure threshold | 3 |
| — | Route 53 limits per check | TCP connect within 4 s, HTTP status within 2 s [39] |
| TTL | DNS time to live | 60 s, fixed for an alias record pointing at an ALB [43][29] |

**Formulas**

- **ALB detection.** For a fast failure such as connection refused or a 5xx,
  t_det is between (N_u − 1)·I and N_u·I, that is 5–10 s. For a failure that hangs or
  is blackholed, add T_o, giving 7–12 s. Each ALB node checks every target on its
  own [26], so the error window ends when the last node decides. Expect results near
  the upper bound.
- **ALB rejoin.** N_h × I = 10 s after the app is ready, plus up to 5 s of phase.
- **Stopped instance.** The target moves to the `unused` state with reason
  `Target.InvalidState` [26]. This can be faster than the health checks; E2 measures
  it. Note that the deregistration delay D does not apply to failed health checks. It
  only applies when a target is deregistered, for example when the ASG terminates an
  instance [27]. PLAN.md section 3 should drop "plus connection draining".
- **Tier 2 replacement (ESTIMATE, E4 measures it).** t_det (≤ 12 s), plus the ASG's
  reaction to the ELB marking the instance unhealthy (not documented; UNVERIFIED,
  measure it), plus launch and boot (30–60 s), plus user data (40–90 s: install
  Docker, log in to ECR, pull, start), plus the initial health checks (10–15 s).
  Total: **about 1.5–3 min.**
- **Scale-out reaction (ESTIMATE).** The target-tracking scale-out alarm on a
  1-minute metric reportedly needs 3 breaching data points (a community observation;
  UNVERIFIED, so check the alarm in the console). Add metric delay and launch-to-healthy
  time of 1.5–3 min: **about 5–8 min.** Scale-in is deliberately slower [35]; the
  reported 15 data points mean at least 15 min.
- **Route 53 detection.** For a fast failure such as a 503: (N_r − 1)·I_r to N_r·I_r,
  that is 20–30 s. For a blackhole, each check waits 4 s for the TCP connect before it
  fails, and the next check starts I_r later, so about 28–42 s. Route 53 marks an
  endpoint unhealthy only when 18% or fewer of its checkers still report it
  healthy [39].
- **DNS caching.** Clients keep the old answer for up to the 60 s TTL.

**Results**

| Tier | Failure | User-visible error window (RTO for users) | Capacity back (RTO for capacity) | RPO |
|---|---|---|---|---|
| 1 | App process stopped on one instance | 5–10 s, on the share of requests going to that instance | Manual (someone restarts it) | 0 |
| 1 | Instance stopped | ≤ 10 s expected (measure in E2) | Manual | 0 |
| 1 | Network loss of one AZ | 7–12 s for its target. If the ALB node in that AZ is also cut off, clients using its IP fail until AWS removes it from DNS (AWS-managed; timing UNVERIFIED) [29] | Manual | 0 |
| 2 | Instance failure | 5–12 s | 1.5–3 min (ESTIMATE, E4) | 0 |
| 2 | Loss of one AZ (one instance per AZ) | 7–12 s; two AZs then carry the load at 75% of R_max | The ASG tries to rebalance into the cut-off AZ; see 8.6 | 0 |
| 2 | Load surge | Latency rises until new capacity arrives | 5–8 min (ESTIMATE, E5b) | — |
| 3 | Region unreachable (unplanned) | 20–45 s detection + 0–60 s TTL = **20–105 s** | The other region is already serving | 0 |
| 3 | Planned evacuation (Route 53 health check inverted [40]) | 0 failed requests; traffic moves within 0–60 s (TTL) | — | 0 |
| 3 | Failback | Route 53 needs N_r successes (20–30 s) + TTL | — | 0 |

RPO is 0 for every tier we build, because the data is read-only and baked into the
image (D3). In the paper design with DynamoDB global tables, replication is
asynchronous, so RPO equals the replication lag, which should be measured rather than
assumed.

---

## 5. Architecture for each tier

### 5.1 Common building blocks

#### 5.1.1 Service and container

- Each instance runs one container with uvicorn and 2 workers (t3.micro has
  2 vCPUs) on port 8000.
- The container restarts automatically. For E1, which needs the process to stay down,
  disable the restart policy first.
- User data reads the instance ID, AZ and region from the instance metadata service
  (IMDS) on the host, and passes them into the container as environment variables
  (`INSTANCE_ID`, `AZ`, `REGION`, `APP_VERSION`). See 6.3 for why.
- The dataset is loaded at startup, before `/health` returns 200, so slow start is
  not needed.
- uvicorn's keep-alive is set to 65 s, longer than the ALB's 60 s idle timeout.
  With uvicorn's default of 5 s, the ALB can reuse a connection the app has just
  closed and return a 502, which would look like a failover error.
- As built (step 2): identity is also sent as `X-Instance-Id`, `X-AZ`, `X-Region`
  and `X-App-Version` headers on every response, errors included. `SIGN_WORK`
  is the PBKDF2-HMAC-SHA256 iteration count, default 1000. Details in
  `service/README.md`.

#### 5.1.2 Instance type and the burstable-CPU trap

| Type | Mumbai | Hyderabad | vCPU / memory | USD/h [4] | Free-tier eligible [25] | Notes |
|---|---|---|---|---|---|---|
| t3a.micro | yes | **no** [47] | 2 / 1 GiB | 0.0062 | no | The report's choice; not offered in Hyderabad |
| t2.micro | yes | **no** [47] | 1 / 1 GiB | 0.0124 | old accounts only | Not in Hyderabad |
| **t3.micro** | yes | yes [47] | 2 / 1 GiB | 0.0112 (same in both) | yes, old and new accounts | **Chosen** |
| t4g.micro | yes | yes | 2 / 1 GiB, arm64 | 0.0056 | new accounts | Needs an arm64 image |
| t8i.micro | yes | yes | 2 / 1 GiB | 0.0134 | no | Newer and more expensive |
| c7g.medium | yes | yes | 1 / 2 GiB, arm64, fixed performance | 0.0245 | no | Cleanest measurements |

**Decision:** t3.micro in both regions, Amazon Linux 2023 (AL2023) on x86_64, with
the credit specification set to `unlimited` in the launch template.

- The image must be built for `linux/amd64` (`docker buildx --platform linux/amd64`).
  At least one of our laptops is an Apple M2 (arm64), and a default build there
  produces an arm64 image that will not start on a t3.micro.

**How burstable credits work** [49][50][51]

- A t3.micro has 2 vCPUs with a baseline of 10% per vCPU. It earns 12 credits an hour
  and can bank up to 288. One credit is one vCPU at 100% for one minute.
- T3 and T3a launch in **unlimited mode by default and never receive launch
  credits** [50][51].
- In unlimited mode, sustained use above the baseline is billed at **USD 0.05 per
  vCPU-hour** (Linux, in both regions) [4][50]. The worst case for a t3.micro is
  (100% − 10%) × 2 vCPU × 0.05 = **USD 0.09/h**. At our 50% scaling target it is
  USD 0.04/h.

**The trap.** If someone switches to standard mode to avoid those charges, every
instance added by a scale-out starts with zero credits [51] and, once those run out,
is held at its baseline. The instances added to relieve load then become the
slowest. Latency rises because of throttling, not load, and that corrupts a
latency-versus-instance-count measurement. Whether CloudWatch `CPUUtilization` then
reads close to the baseline, so that a CPU-based policy would never fire, is
UNVERIFIED. Watch `CPUCreditBalance` instead.

**What we do about it**

1. Set unlimited mode explicitly in the launch template, so an account-level default
   cannot change it.
2. Scale on request count, not CPU (5.3.2).
3. After every load test, export `CPUSurplusCreditBalance` and
   `CPUSurplusCreditsCharged` to prove there was no throttling and to price the extra
   CPU. Credit metrics are only available at 5-minute resolution [52].

**Cleaner alternative.** A c7g.medium has one full Graviton3 core and no credits, and
four of them fit inside the default 5-vCPU quota. It is not free-tier eligible and
needs an arm64 image, so we keep it as an optional comparison run of E5a, only if the
account allows it.

#### 5.1.3 How each region gets the app image

| Option | Boot to healthy (ESTIMATE) | What it depends on during a recovery | Repeatability | Cost |
|---|---|---|---|---|
| Build from GitHub on boot | Slowest: 1–3 min extra for clone, `pip install` and `docker build` | GitHub, PyPI and Docker Hub. Anonymous Docker Hub pulls are limited to 100 per 6 hours per IP [70]. | Weak: builds whatever is on `main` at that moment | None |
| **ECR with cross-region replication** | Medium: the pull takes tens of seconds | Only ECR in the same region | Strong: immutable tag or digest | USD 0.10/GB-month [11]; replication billed as inter-region transfer, USD 0.086/GB [10] |
| Baked AMI (Docker and image pre-loaded) | Fastest | Only EC2 | Strong, but every change needs a new AMI copied to Hyderabad | Snapshots USD 0.05/GB-month [4] |

**Decision:** an ECR repository `aadhaar-mock` in `ap-south-1`, replicated to
`ap-south-2`, with tag immutability on and tags set to the short git SHA. User data
installs Docker from the AL2023 repository, logs in to the region's own ECR, pulls by
tag and runs the container.

- Replication only copies images pushed after the rule exists, and "the majority of
  images replicate in less than 30 minutes" [63]. Push at least 30 minutes before
  Tier 3 tests, or push to both regions directly.
- Revisit a baked AMI only if E4 shows boot to healthy takes longer than 3 minutes.

#### 5.1.4 Health-check design (the "trap" in report 3.2)

- **ALB target health uses `/health` (shallow).** The ASG uses ELB health [32], so
  it only replaces an instance whose own process is broken.
- **Route 53 uses `/health/deep`**, a canary request sent through the ALB. It makes
  the region-level decision.
- **Why the split matters.** If the ALB used a deep check, a fault in a shared
  dependency would fail every target at once. The ALB would then fail open and send
  traffic to all targets anyway [26], but the ASG would still see them as unhealthy
  and keep replacing healthy instances. Putting the deep check at the Route 53 layer
  moves traffic to the other region instead.
- With static data (D3), "deep" means: the dataset is loaded, a known synthetic record
  authenticates, and signing works.
- Route 53 needs a TCP connection within 4 s and a status code within 2 s [39], so
  the deep check must be fast.
- ALB target-group health thresholds (DNS failover and unhealthy-state routing)
  exist [27]. We leave them at their defaults and mention them in the paper design.

### 5.2 Tier 1: two instances in two AZs behind an ALB

```
 Laptop prober (20 req/s, new connection per request)
                     |
                     | HTTP :80 to the ALB's DNS name
                     v
 +---------------- ap-south-1 (Mumbai), VPC 10.10.0.0/16 ----------------+
 |                                                                       |
 |   Application Load Balancer (nodes in subnets lb-a, lb-b)             |
 |   listener HTTP:80 -> target group HTTP:8000, /health every 5 s       |
 |            |                                  |                       |
 |            v                                  v                       |
 |   +------------------+               +------------------+             |
 |   | EC2 t3.micro     |               | EC2 t3.micro     |             |
 |   | AZ a, app-a      |               | AZ b, app-b      |             |
 |   | Docker: FastAPI  |               | Docker: FastAPI  |             |
 |   | + synthetic JSON |               | + synthetic JSON |             |
 |   +------------------+               +------------------+             |
 |                                                                       |
 |   ECR (image)    CloudWatch (metrics, alarms)    SSM (no SSH)         |
 +-----------------------------------------------------------------------+
```

**Components:** a VPC and subnets (6.1), the ALB with its listener and target group,
two EC2 instances with an instance role, two security groups, three CloudWatch
alarms and an SNS email topic.

| Setting | Value | Why | Source |
|---|---|---|---|
| AZs | `ap-south-1a`, `ap-south-1b` | Tier 1 as approved | PLAN |
| ALB | Internet-facing, HTTP:80, two `lb` subnets, `drop_invalid_header_fields = true`, idle timeout 60 s (default) | — | [28] |
| Target group | HTTP:8000, target type `instance`, round robin | — | [27] |
| Health-check path and matcher | `/health`, 200 | Shallow check (5.1.4) | [26] |
| Health-check interval | **5 s**, the minimum (AWS default 30) | Fastest detection | [26] |
| Health-check timeout | **2 s**, the minimum (AWS default 5) | `/health` answers in milliseconds, so a hang shows up quickly | [26] |
| Unhealthy threshold | **2** (AWS default 2) | Detection in 5–10 s | [26] |
| Healthy threshold | **2** (AWS default 5) | Rejoin in about 10 s | [26] |
| Deregistration delay | **15 s** (default 300) | Requests take under 1 s; makes scale-in and refresh faster | [27] |
| Slow start | 0 (off) | The app has no warm-up | [27] |
| Cross-zone load balancing | On. It is always on for an ALB, and AWS does not charge for this cross-zone traffic | Even spread across targets | [27][22] |
| Instances | 2 × t3.micro, unlimited credits, AL2023 x86_64, 8 GiB gp3 | Section 5.1.2 | [4] |
| IMDS | IMDSv2 required, hop limit 1 | Section 6.3 | [53] |
| Shell access | SSM Session Manager; no key pair, no port 22 | Section 6.4 | — |

**Trade-offs of fast health checks**

- **More health-check traffic.** Each ALB node checks each target every 5 s. With two
  nodes that is about 0.4 requests/s per target (ASSUMPTION: one node per AZ), which is
  negligible.
- **False positives.** A target that misses two checks, for example because its CPU
  is saturated during E0 or E5, gets removed. With only two targets, the survivor then
  takes double load and may fail too. If every target fails, the ALB fails open [26].
- **Mitigations.** Keep `/health` cheap, run 2 workers, never saturate instances
  during failover tests, and watch `UnHealthyHostCount` during load tests. If false
  removals appear, change Tier 2 to a 4 s timeout and an unhealthy threshold of 3, and
  record the change.
- **Terraform defaults are not AWS defaults.** `aws_lb_target_group` defaults to
  healthy 3, unhealthy 3, interval 30 s and a 6 s timeout for HTTP [66]. AWS documents
  5, 2, 30 s and 5 s [26]. **Set every value explicitly.**
- **E1b** repeats E1 with AWS's default settings (30 s, healthy 5, unhealthy 2).
  Predicted detection is 30–60 s, against 5–10 s for ours.

| Failure in Tier 1 | Survived? | Expected effect | Test |
|---|---|---|---|
| App process stopped on one instance | Yes | Fast 502s on that instance's share of requests for 5–10 s [30], then every response comes from the other AZ | E1 |
| Instance stopped | Yes | The target goes to `unused`; errors until it is removed | E2 |
| Network loss of one AZ | Partly | The target is removed after 7–12 s. If the ALB node in that AZ is also cut off, see 4.3. | E3 (in Tier 2) |
| Bug present on both instances | No | The ALB fails open and the errors continue | — |
| Region outage | No | Needs Tier 3 | — |
| Restoring capacity | Manual | Someone restarts the instance | — |

### 5.3 Tier 2: Auto Scaling group across two AZs (within the free-account quota)

```
                 Laptop prober / laptop Locust
                                |
                                v
 +---------------- ap-south-1 (Mumbai), VPC 10.10.0.0/16 ----------------+
 |   Application Load Balancer (nodes in lb-a, lb-b)                     |
 |            |                                  |                       |
 |            v                                  v                       |
 |   +------------------+               +------------------+             |
 |   | t3.micro         |               | t3.micro         |             |
 |   | AZ a (app-a)     |               | AZ b (app-b)     |             |
 |   +------------------+               +------------------+             |
 |   Auto Scaling group: min 1, desired 2, max 2, ELB health checks      |
 |   Target tracking: ALBRequestCountPerTarget = 30 x R_max req/min      |
 |                                                                       |
 |   CloudWatch: ALB + ASG group metrics, alarms -> SNS email            |
 +-----------------------------------------------------------------------+
```

| Setting | Value | Why | Source |
|---|---|---|---|
| AZs | **2** (a, b) | The default 5-vCPU per-region quota caps us at 2 × t3.micro (4 vCPUs); a third AZ needs a quota increase we are not requesting (D9) | [48] |
| Min / desired / max | **1 / 2 / 2** | 2 instances fit the 5-vCPU quota. The scaling demo exercises `desired 1 → desired 2` (E5a) and uses `max 2` as the autoscaler ceiling (E5b). | — |
| vCPUs needed | 2 × 2 = **4** (within the 5-vCPU default) | No quota increase requested | [48] |
| Health-check type | `ELB` | Replace instances that fail `/health` | [32] |
| Health-check grace period | **180 s**. Terraform's default is 300 s and the API's is 0 s. | At least 1.5 × the estimated 120 s from boot to healthy; tune after E4 | [31][66] |
| Default instance warmup | **120 s** | AWS "strongly recommends" setting it; it is off by default | [34] |
| Launch template version | A specific version number, never `$Latest` or `$Default` | Automatic rollback only works with numbered versions | [37] |
| Instance maintenance policy | Launch before terminating: min healthy 100%, max healthy 150% | By default the ASG terminates first and launches while terminating [33]; this keeps capacity during replacements and refreshes | [33][38] |
| Instance refresh | Rolling, with automatic rollback on the ALB 5xx alarm | Covers the bad-deployment scenario (E7) | [37] |
| Group metrics | Enabled (free, 1-minute granularity) | Needed for the timeline charts | [36] |
| Scaling policy | Target tracking on `ALBRequestCountPerTarget`, target 30 × R_max per minute; scale-in enabled | 5.3.2 | [35] |
| ALB and target group | As in Tier 1, across 3 AZs | — | — |

#### 5.3.1 Two AZs or three

With N AZs, surviving the loss of one needs N/(N−1) × peak in total: 200% with two
AZs, 150% with three (report 3.3). Three AZs with one instance each gives the better
headroom, but it needs at least 3 × 2 = 6 vCPUs, which exceeds the default 5-vCPU
per-region quota. Since the group has chosen not to request a quota increase (D9),
**Tier 2 runs across 2 AZs**, with the 200% rule explicit in the report: at Tier 2's
design load each instance runs at ≤ 50% of R_max, so losing one AZ leaves the
survivor at ≤ 100%. The 3-AZ layout is kept as the paper design in section 3.3,
alongside the 2 × peak total-provisioned rule.

#### 5.3.2 Scaling metric: CPU or request count

- **`ALBRequestCountPerTarget`** is a predefined metric. The ALB publishes it every
  60 s whenever there is traffic [28]. It is directly proportional to the load we
  control, CPU credits do not distort it, and its target value means "throughput per
  instance per minute" [35].
- **`ASGAverageCPUUtilization`** relies on EC2 metrics, which are 5-minute by default.
  One-minute data needs detailed monitoring, which is charged [35]. On burstable
  instances it is measured against a CPU whose capacity depends on credits (5.1.2).
- **Decision:** `ALBRequestCountPerTarget`. We still record CPU as a second signal.
- In Tier 3, Route 53 health checks add more than 1 request/s per region [40]. This
  is negligible against the target.

#### 5.3.3 Making scaling visible in a short demo

The quota caps us at 2 instances, so the demo shows the **1 → 2 transition**
clearly, not a full 3 → 6 ramp.

1. **Calibrate first (E0).** Use `SIGN_WORK` so that a known rate saturates one
   instance (ASG set to min 1 / desired 1 / max 1 for this run).
2. **Set the target at 50% of R_max**, so crossing it triggers the single scale-out
   step from 1 to 2.
3. **Hold each load step for at least 10 minutes**, because scale-out takes about
   5–8 minutes (ESTIMATE, 4.3).
4. **Run the fixed-capacity sweep (E5a)** with N = 1 and N = 2 to produce the
   course's "response time against instance count" chart [81] without waiting for the
   autoscaler.
5. **Plot on one timeline:** group metrics, `RequestCountPerTarget` and the p95 of
   `TargetResponseTime`.
6. **Keep unlimited credits on**, and check `CPUSurplusCreditBalance` after each run.
7. **The report must say explicitly** that the 1 → 2 scaling demo stands in for the
   paper design's 3 → 6, because the free-account quota caps the live demo at
   2 instances. The autoscaling mechanism is the same.

#### 5.3.4 Where to run Locust

| | Laptop on campus Wi-Fi | EC2 load generator in `ap-south-1` |
|---|---|---|
| Network jitter | High: shared Wi-Fi and NAT | Low: AWS network |
| Client CPU | Laptop is doing other work; Locust warns when it is CPU-bound [68] | Dedicated machine |
| What the latency means | The user's view, including the Internet | Close to ALB plus server time |
| Cost and quota | Free | t3.small, about USD 0.028/h including its public IP [4][6]; **uses 2 vCPUs of quota, which would push Tier 2 (4 vCPUs) over the 5-vCPU default** |

**Decision**

- **Run every load and failover test from a laptop.** An EC2 load generator would
  put the total vCPU need at 6 (4 app + 2 generator) and exceed the default
  5-vCPU quota. Since D9 keeps us within the default quota, the EC2 generator is
  dropped.
- The target rates (E0 at 100–200 req/s, E5 at up to 3 × R_max) are modest enough
  that a laptop running `FastHttpUser` can drive them, provided the laptop is on
  wired or a lightly loaded Wi-Fi and no other heavy process is running.
- Always record the ALB's `TargetResponseTime` as the server-side check, so laptop
  jitter does not corrupt the latency numbers that matter.

**Validity checks for every load run**

- The achieved rate is within 5% of the target rate (if it is not, lower the target
  and rerun; do not report a run that fell short).
- Locust gives no CPU warnings.
- Use `FastHttpUser`. One process can reach thousands of requests per second, against
  about 4,000 at best for `HttpUser` [68].
- Run one worker per core if more is needed [69].
- Pace users at a fixed rate (Locust's constant-throughput wait time) rather than
  waiting for each response.
- Prefer wired Ethernet; disable VPN, backups and OS updates during the run; close
  other browsers and video calls.

| Failure in Tier 2 | Survived? | Expected effect | Test |
|---|---|---|---|
| Instance fails | Yes | 5–12 s of errors on its share, then the ASG replaces it in 1.5–3 min (ESTIMATE) | E4 |
| AZ network loss | Partly | The surviving AZ carries 100% of load. At the Tier 2 design load (≤ 50% of R_max per instance) that is still within the one-instance ceiling; at higher load the survivor saturates. The ASG keeps relaunching into the cut-off AZ until it is excluded (8.6). | E3 |
| Load surge | Yes, up to 2 × R_max | Latency rises until the single scale-out step completes (about 5–8 min). Beyond 2 × R_max the ASG is at `max 2` and cannot scale further. | E5b |
| Bad deployment | Yes, if caught | Instance refresh rolls back when the 5xx alarm fires | E7 (optional) |
| Region outage | No | Needs Tier 3 | — |

### 5.4 Tier 3: second region (Hyderabad) with Route 53

```
                 Clients (laptop prober; OS resolver cache)
                                  |
                      DNS query: api.<domain>
                                  v
        Route 53 public hosted zone: latency records, alias to each ALB
          HC-M: /health/deep via the Mumbai ALB, 10 s, threshold 3
          HC-H: /health/deep via the Hyderabad ALB, 10 s, threshold 3
                 |                                    |
                 v                                    v
 +--- ap-south-1 (Mumbai) ---+        +--- ap-south-2 (Hyderabad) ---+
 | ALB, 2 AZs                |        | ALB, 2 AZs                   |
 | ASG min 1 / des 2 / max 2 |        | ASG min 1 / des 2 / max 2    |
 | ECR repo (source) ------------ replication ----> ECR replica      |
 +---------------------------+        +------------------------------+
 CloudWatch alarms on the Route 53 health checks live in us-east-1.
```

| Setting | Value | Why | Source |
|---|---|---|---|
| Regions | `ap-south-1` and `ap-south-2`, the same module in each, **2 AZs**, ASG **min 1 / desired 2 / max 2** | Same design in both regions; each region uses 4 vCPUs, which fits the default 5-vCPU quota (no quota increase requested per D9) | [48] |
| Records | `api.<domain>` A alias records with latency routing, one per region (set identifier = region), Evaluate Target Health = Yes | Active-active | [42][46] |
| Health checks | HTTP; target is the ALB's DNS name on port 80; path `/health/deep`; **10 s (fast) interval**; failure threshold **3** (the default); all default checker regions | Detection in 20–45 s | [40][41] |
| Health-check price | The first 50 checks of AWS endpoints are free. The fast interval is an optional feature at USD 1.00/month per check, prorated. | — | [14] |
| TTL | 60 s, fixed: an alias to an ALB cannot have its own TTL | — | [43][29] |
| HTTPS (optional) | One public ACM certificate in each region, validated through DNS | ACM certificates are regional [62]; free for use with an ALB [20] | — |
| Alarms | `HealthCheckStatus` for each region, in `us-east-1` | Route 53 metrics exist only in N. Virginia [45] | — |

#### 5.4.1 Failover routing or latency routing

- Route 53's documentation says failover routing gives active-passive, and any other
  policy with health checks (latency, weighted and so on) gives active-active [42].
- Our paper design and Aadhaar's two sites are active-active (report 3.1–3.2), so
  **the decision is latency routing with health checks** (P1 in section 13).
- From a single client in Gujarat, latency routing will normally return one region
  (probably Mumbai). Latency routing picks a region from AWS's own latency data, not
  from live probes [44]. The measured switch therefore looks the same as with failover
  routing.
- To show that Hyderabad is live, call its ALB directly, or run a second prober from
  an instance in Hyderabad.

#### 5.4.2 Hosted zone and domain (O1)

- We need a public hosted zone and a domain delegated to its four name servers. The
  Route 53 SLA only applies if all four are used [3].
- A hosted zone costs USD 0.50 a month. It is not prorated, but a zone deleted within
  12 hours of creation is free [14].
- **Keep the zone in a separate, long-lived Terraform stack** (`infra/global/dns`).
  Every new zone gets new name servers, so destroying and recreating it would break
  the delegation.
- Domain options and costs are in section 12 (O1).

#### 5.4.3 HTTPS

- An ACM certificate cannot be issued for the ALB's own `amazonaws.com` name, so HTTPS
  is only possible in Tier 3 with our own domain.
- **Decision:** every measurement uses HTTP, so results are comparable across tiers.
- One HTTPS sanity run in Tier 3 is optional, and we state the HTTP-only setup as a
  simplification in the report.

#### 5.4.4 Effect of TTL on measured failover time

The measured failover is the Route 53 detection time plus the time until each
client's cached answer expires, which is anywhere from 0 to 60 s. Three things affect
what a client actually sees:

1. **The OS resolver** may cache an answer for up to its TTL.
2. **Python's standard library** asks the OS for each lookup and keeps no DNS cache of
   its own.
3. **Keep-alive connections skip DNS entirely**, so our prober must open a new
   connection for every request.

To separate "Route 53 changed its answer" from "the cache expired", a second process
queries the hosted zone's own name servers directly once a second (for example
`dig @<route53-name-server>`) and logs the answer. The gap between that change and the
prober's switch is the caching effect.

Optional E6c: repeat the test with a non-alias CNAME record with a 10 s TTL to show
the effect of TTL. Latency-record queries then cost USD 0.60 per million [7], which is
negligible.

#### 5.4.5 Hyderabad check (O3)

| Need | Hyderabad (`ap-south-2`) | Source |
|---|---|---|
| Must it be enabled? | **Yes**, it is an opt-in region | [56] |
| AZs | 3 | [56][57] |
| t3a | **Not available** | [47] |
| t3, t4g, t8i | Available | [47] |
| ALB | USD 0.0239/h + USD 0.008 per LCU-hour, the same as Mumbai | [5] |
| t3.micro | USD 0.0112/h, the same as Mumbai | [4] |
| Public IPv4 | USD 0.005/h per address, the same as Mumbai | [6] |
| EBS gp3 | USD 0.0912/GB-month, the same as Mumbai | [4] |
| ECR | Available, USD 0.10/GB-month | [11] |
| ACM | Expected to be available (UNVERIFIED; check the endpoints page) | [62] |
| AWS Fault Injection Service (FIS) | **Not available** (no Hyderabad endpoint) | [58] |
| Data transfer between Mumbai and Hyderabad | USD 0.086/GB in each direction | [10] |

| Failure in Tier 3 | Survived? | Expected effect | Test |
|---|---|---|---|
| Mumbai unreachable | Yes | 20–105 s of errors for clients on Mumbai, then Hyderabad serves them | E6b |
| Planned evacuation (health check inverted) | Yes | No errors; traffic moves within the TTL | E6a |
| Broken dataset in one region | Yes | The deep check fails, the region is removed from DNS, and the ALB and ASG are untouched (no churn) | Optional |
| Health checkers blocked by a security group | No; this causes a false failover | Keep the ALB's port 80 open to the Internet | Design rule |
| Bad image deployed to both regions | No (a correlated failure) | Both regions break | Deploy one region at a time |
| Both regions down | No | — | — |

---

## 6. Network and security design

### 6.1 VPC

**Decision:** a custom VPC in each region, built by Terraform, rather than the default
VPC.

- **It lets us cut off one AZ cleanly.** We need separate subnets for the load
  balancer and the app in each AZ (see below).
- **No overlapping addresses.** Every default VPC uses the same CIDR, which would block
  any later peering between regions.
- **It rebuilds identically in both regions,** which is the report's point about
  rebuildability.
- **It costs nothing extra,** because we use no NAT gateway.

| Subnet | AZ | Mumbai | Hyderabad | Purpose |
|---|---|---|---|---|
| `lb-a`, `lb-b`, `lb-c` | a, b, c | 10.10.0.0/24, 10.10.1.0/24, 10.10.2.0/24 | 10.20.0.0/24, 10.20.1.0/24, 10.20.2.0/24 | ALB nodes |
| `app-a`, `app-b`, `app-c` | a, b, c | 10.10.10.0/24, 10.10.11.0/24, 10.10.12.0/24 | 10.20.10.0/24, 10.20.11.0/24, 10.20.12.0/24 | Instances (public IP for outbound traffic only) |

- One public route table sends `0.0.0.0/0` to the Internet gateway.
- A spare "deny-all" network ACL, attached to nothing, is used by the AZ-loss test
  (8.6).
- **Why load-balancer and app subnets are separate.** This lets us cut off one AZ's
  app tier without touching its ALB node (losing the instances in that AZ), or cut off
  both (losing the whole AZ). FIS's network disruption also acts per subnet and still
  allows traffic inside a subnet [60]. With shared subnets, the ALB-to-instance path
  inside the cut-off AZ would stay open.
- **Public subnets for instances are a stated simplification** (report 3.6).
  - Instances get a public IPv4 address only so they can reach ECR and package
    repositories without a NAT gateway.
  - Their security group blocks all inbound traffic except from the ALB.
  - Each public IPv4 address costs USD 0.005/h [6] (counted in section 9).
  - Production would use private subnets with NAT or VPC endpoints.

### 6.2 Security group chain

| Security group | Inbound | Outbound |
|---|---|---|
| `alb-sg` | TCP 80 (and 443 in Tier 3) from `0.0.0.0/0`. This must stay open, because Route 53 health checkers connect from the Internet. | TCP 8000 to `app-sg` |
| `app-sg` | TCP 8000 from `alb-sg` only | TCP 443 to `0.0.0.0/0`, for ECR and the AL2023 package repositories |
| `loadgen-sg` (Tier 2 only) | Nothing | TCP 80 to `0.0.0.0/0`, TCP 443 for packages |

No security group opens port 22.

### 6.3 IMDSv2 and the hop limit

- **Set `http_tokens = required` and `http_put_response_hop_limit = 1` explicitly.**
- The AL2023 AMI would otherwise default to IMDSv2-only with a **hop limit of 2** [55].
  AWS advises 2 only when containers need IMDS, because a container counts as an extra
  network hop [53][54].
- Our container does not need IMDS. User data reads the instance ID, AZ and region on
  the host and passes them in as environment variables (5.1.1). With a hop limit of 1,
  the container cannot reach IMDS, so a server-side request forgery (SSRF) bug in the
  app cannot fetch the instance role's credentials.
- Terraform's launch template defaults are `http_tokens = optional` and a hop limit
  of 1 [66], so set both explicitly.

### 6.4 IAM (least privilege)

- **Instance role:**
  - `AmazonSSMManagedInstanceCore`, for Session Manager.
  - An inline ECR policy: `ecr:GetAuthorizationToken` on `*`, and `ecr:BatchGetImage`,
    `ecr:GetDownloadUrlForLayer` and `ecr:BatchCheckLayerAvailability` on the
    `aadhaar-mock` repository only.
  - Nothing else.
- **People:**
  - One named user per member (IAM Identity Center or IAM), each with MFA.
  - The member who runs `terraform apply` gets administrator access during the
    project.
  - The other two get read-only access plus billing view.
  - No access keys for the root user, and MFA on root.
- **FIS (only if used):** an experiment role allowed to replace network ACL
  associations on subnets carrying the experiment tag.
- **Budgets:** create the D9 budget before the first deploy.

### 6.5 Other controls

- HTTP only in Tiers 1–2, as stated in 5.4.3.
- ALB set to drop invalid header fields.
- Synthetic data in an obviously fake format (FR6), plus the existing README
  disclaimer.
- Every resource tagged `Project`, `Tier`, `Owner` and `ManagedBy`, so we can find
  anything left running.
- Instances are reached only through SSM Run Command or Session Manager. AL2023 is
  expected to include the SSM Agent (UNVERIFIED; confirm in step 6).

---

## 7. Terraform layout

```
infra/
├── bootstrap/            # once: S3 bucket for state (versioned, private, encrypted)
├── global/               # long-lived; destroyed only in step 12
│   ├── ecr/              # repository + replication rule to ap-south-2
│   └── dns/              # Route 53 public hosted zone (Tier 3)
├── modules/
│   ├── network/          # VPC, internet gateway, lb/app subnets, route table, deny-all NACL
│   ├── alb/              # ALB, target group, listener(s), alb-sg
│   ├── app_static/       # Tier 1: two aws_instance + attachments, app-sg, instance role
│   ├── app_asg/          # Tiers 2-3: launch template, ASG, scaling policy, app-sg, role
│   ├── observability/    # SNS topic + alarms for one region
│   └── dns_failover/     # Route 53 health checks, latency alias records (+ optional ACM)
└── envs/
    ├── tier1/            # ap-south-1: network + alb + app_static + observability
    ├── tier2/            # ap-south-1: network + alb + app_asg + observability
    └── tier3/            # Mumbai + Hyderabad (network + alb + app_asg each) + dns_failover
```

**State**

- An S3 backend: bucket `aadhaar-ha-demo-tfstate-<account-id>` in `ap-south-1`, with
  versioning on, one state key per environment, and `use_lockfile = true`.
- S3-native locking replaces the DynamoDB lock table, which Terraform now marks as
  deprecated [64].
- Needs Terraform 1.10 or later. The latest releases are Terraform 1.17.1 and
  `hashicorp/aws` 6.71.0, both from 28 October 2026 [67]. Pin `hashicorp/aws ~> 6.0`.
- **Why not local state:** three people commit to `main`. State on one laptop can be
  lost (leaving resources running and billing), and two people applying at once would
  corrupt it.
- **Rule:** one person applies per step. Everyone else uses `plan` only.

**Providers for two regions**

- `envs/tier3` declares three provider configurations with aliases: Mumbai,
  Hyderabad and `us-east-1`. The `us-east-1` one is needed because Route 53
  health-check metrics, and therefore their alarms, exist only there [45].
- Each regional module call receives its provider through the module's `providers`
  argument. The Route 53 resources are global and use the Mumbai provider.
- AWS provider 6.x also supports a per-resource `region` argument, which can replace
  aliases [65]. We use aliases because they make "one module, two regions" explicit.

**Variables per region:** `region`, `azs`, `vpc_cidr`, `instance_type`, `asg_min`,
`asg_desired`, `asg_max`, `image_tag`, `hc_interval`, `hc_timeout`, `hc_healthy`,
`hc_unhealthy`, `dereg_delay`, `enable_https`, `tags`.

- The AMI ID comes from the public SSM parameter for the latest AL2023 x86_64 image.
- Real values go in `*.tfvars`, which are git-ignored. `*.tfvars.example` files are
  committed (see the existing `.gitignore`).

**Conventions and gotchas**

- Add `default_tags` to every provider.
- Run `terraform fmt` and `terraform validate` before each commit, and paste the plan
  summary into the commit message.
- Run `terraform destroy` at the end of every session. The `global/` stack stays until
  step 12.
- Terraform defaults differ from AWS defaults: target-group thresholds and timeout
  (5.2), the ASG grace period (300 s in Terraform, 0 s in the API) [31][66], and the
  launch template's IMDS settings (6.3). Set them all explicitly.
- An ASG that points at `$Latest` cannot roll back [37].
- An ALB is billed per hour or part hour [12], so many short apply/destroy cycles cost
  more than one long session.
- Enable Hyderabad before the first Tier 3 apply (R2). No vCPU quota increase is
  requested; Tier 2 and Tier 3 are sized to the default 5-vCPU per-region quota (R1).

---

## 8. Observability and test plan

### 8.1 Metrics

| Metric | Namespace and dimensions | Statistic | Why |
|---|---|---|---|
| `HealthyHostCount`, `UnHealthyHostCount` | `AWS/ApplicationELB`; target group, load balancer (+ AZ) | Min / Max | When targets leave and rejoin |
| `HTTPCode_ELB_5XX_Count` (and the 502, 503, 504 counts) | ALB | Sum | Errors made by the ALB itself: dead targets (502), no targets (503), timeouts (504) [30] |
| `HTTPCode_Target_5XX_Count` | ALB | Sum | Errors from the app |
| `TargetResponseTime` | ALB | p50 / p95 / p99 | Server-side latency |
| `RequestCount`, `RequestCountPerTarget` | ALB | Sum | Load and the scaling signal |
| `TargetConnectionErrorCount` | ALB | Sum | Failed connections to targets |
| `GroupDesiredCapacity`, `GroupInServiceInstances`, `GroupPendingInstances` | `AWS/AutoScaling` | Max | Scaling timeline; must be enabled (free) [36] |
| `CPUUtilization`, `CPUCreditBalance`, `CPUSurplusCreditBalance`, `CPUSurplusCreditsCharged` | `AWS/EC2` | Avg / Max | Load and credit checks (5-minute data) [52] |
| `HealthCheckStatus`, `HealthCheckPercentageHealthy` | `AWS/Route53` (only in `us-east-1`) | Min | Region status [45] |

All the ALB metric names above appear in the ALB metrics documentation [28]. ALB
metrics are 60-second data points, and are only published while requests are
flowing [28]. CloudWatch therefore cannot time a 10-second failover. **Our prober is
the main instrument; CloudWatch confirms it.**

### 8.2 Alarms

At most 10 alarms across all regions, so they are free [8]. Each sends an email
through SNS.

1. Mumbai `HealthyHostCount` below the desired count, over 1 minute.
2. Mumbai `UnHealthyHostCount` ≥ 1.
3. Mumbai `HTTPCode_ELB_5XX_Count` ≥ 1 in 1 minute. Tier 2 instance refresh rolls back
   on this alarm.
4. Mumbai `TargetResponseTime` p90 above 0.5 s for 3 minutes.
5. Hyderabad `HealthyHostCount` below the minimum (Tier 3).
6. Hyderabad `HTTPCode_ELB_5XX_Count` ≥ 1 (Tier 3).
7. Route 53 health check for Mumbai, `HealthCheckStatus` < 1 (in `us-east-1`).
8. Route 53 health check for Hyderabad, `HealthCheckStatus` < 1 (in `us-east-1`).

Cost alerts come from AWS Budgets, not CloudWatch (D9; see P2 in section 13).

### 8.3 Instruments

**Failover prober (step 4)**

- Open loop: it sends requests on a fixed schedule at 20 requests/s, whether or not
  earlier requests have answered.
- A new TCP connection for every request (`Connection: close`).
- Connect timeout 2 s, total timeout 5 s.
- The system resolver is used for every request, and the resolved IP is logged.
- One CSV row per request: `t_send_utc_ms`, `t_recv_utc_ms`, `latency_ms`, `status`,
  `error_class` (`timeout`, `conn_error`, `http_5xx`, `http_other`), `instance_id`,
  `az`, `region`, `resolved_ip`, `run_id`.

**Event log.** `events.csv` records every action (`inject_start`, `inject_end`,
`restore` and so on) with its UTC timestamp, taken when the CLI or SSM command
returns.

**Run metadata.** `meta.json` holds the git SHA, image tag, health-check settings,
instance types, rate, client location, whether the network was wired or Wi-Fi, and
tool versions.

**Locust (step 9)**

- `FastHttpUser`, paced at a fixed rate, keep-alive on.
- Its CSV and HTML reports go to `results/`.

**AWS-side records**

- CloudWatch exports of the metrics in 8.1, fetched with `get-metric-data` into CSV.
- ALB access logs to S3 during experiments (optional; useful as per-request ground
  truth).
- CloudTrail event history, for the exact times of API calls such as instance stops.

**Clock.** The laptop clock must be NTP-synchronised. All derived times are measured
from `t_inject`.

### 8.4 Experiments

| ID | Tier | What it shows | How we inject the failure | Load | Runs | Pass when |
|---|---|---|---|---|---|---|
| E0 | 2 | R_max of one instance | Ramp from 10 to about 400 requests/s over 10 min (ASG min = desired = max = 1 for this run, scaling off) | Laptop Locust | 2 | Knee point found; `SIGN_WORK` fixed |
| E1 | 1 | Failover when the process stops | Stop the container through SSM, leave it down 2 min, then start it | 20/s prober | 5 | Error window ≤ 15 s in all runs (predicted 5–10 s); no errors outside the window; rejoins ≤ 20 s after restart |
| E1b | 1 | Effect of health-check settings | As E1, with AWS default settings (30 s, healthy 5, unhealthy 2) | 20/s | 3 | Windows fall in the predicted 30–60 s band |
| E2 | 1 | Failover when an instance stops | `aws ec2 stop-instances` | 20/s | 5 | Error window ≤ 15 s |
| E3 | 2 | Losing an AZ under load (2-AZ 200% rule) | Attach the deny-all network ACL to `app-a` for 5 min (8.6) | 0.8 × R_max + 20/s prober | 3 | Error window ≤ 15 s; ≤ 1% failed requests over 10 min; server p95 after the loss ≤ 2 × its value before |
| E4 | 2 | Self-healing | Terminate one instance (or stop its container) | 20/s | 5 | Replacement is InService and healthy within 5 min in all 5 runs; no errors beyond the detection window |
| E5a | 2 | Response time against instance count | Scaling off; desired N = 1 and N = 2, 5 min per point after warm-up | 0.9 × R_max, laptop Locust | 2 sweeps | p95 latency at N = 2 is clearly below N = 1; chart produced |
| E5b | 2 | Autoscaling behaviour | One step from 0.8 × R_max to 1.6 × R_max, 10 min each way | Laptop Locust | 2 | Scale-out starts within 5 min of the step; desired capacity goes 1 → 2; p95 back under the NFR9 target within 10 min; scale-in back to 1 afterwards |
| E6a | 3 | Planned region evacuation | Invert the Mumbai health check [40] | 20/s | 3 | Zero failed requests; ≥ 95% of requests served by Hyderabad within 90 s |
| E6b | 3 | Unplanned region loss | Attach the deny-all network ACL to Mumbai's `lb` subnets | 20/s | 5 | Error window ≤ 120 s in at least 4 of 5 runs (predicted 20–105 s); 100% success from Hyderabad afterwards; failback time recorded |
| E7 (optional) | 2 | Bad-deployment rollback | Instance refresh to an image that fails `/health/deep`, or returns 500s | 20/s | 1 | Automatic rollback completes; errors limited to the refresh window |

### 8.5 Method: number of runs, what to log, reporting a range

**Runs**

- **5 runs** of each failover experiment; PLAN.md asks for at least 3.
- With n runs, the chance that the true median lies between the smallest and largest
  result is 1 − 2 × 0.5ⁿ, whatever the distribution. That is 75% for n = 3 and 93.75%
  for n = 5. Five runs are cheap (about 7 minutes each) and give a much more defensible
  range.
- Alternate the target between runs (AZ a, then b, and so on) and wait at least
  2 minutes for everything to return healthy.

**What to compute from each run**

- First error and last error, both relative to `t_inject`.
- The error window: last error minus first error.
- Failed requests, as a count and as a percentage of the window and of the whole run.
- The time until the last response from the failed target.
- The rejoin time: the first response from the restored instance, minus the restore
  time.
- For Tier 3: the time of the first response from Hyderabad, and the time Route 53's
  answer changed (5.4.4).

**How to report**

- For each experiment, give the median and the [min, max] range across runs next to
  the predicted range from section 4.3.
- Show every run as a dot on a strip chart, and draw one timeline per experiment
  (latency against time, coloured by AZ or region, with errors marked).
- Explain the spread. The main sources are the phase of the health checks (the failure
  can land anywhere within an interval), ALB nodes deciding independently, and DNS
  caching.
- Never quote a single "lucky" run.

**Pass means** the measured range sits inside the predicted range plus the stated
tolerance, in the number of runs stated in 8.4.

### 8.6 Simulating the loss of an AZ, and FIS

- **Does FIS offer an AZ outage?** Yes. FIS has an "AZ Availability: Power
  Interruption" scenario, and FIS has an endpoint in Mumbai. It is **not offered in
  Hyderabad** [58][59].
- **What the scenario does, by default** [59]:
  - Stops every instance in the AZ for 30 minutes.
  - Blocks new instance launches in the AZ for 30 minutes.
  - Cuts the AZ's subnets off the network for 2 minutes.
  - Skips any action that finds no targets.
  - Then simulates 30 minutes of recovery symptoms.
- **What it costs.** FIS charges USD 0.10 per action-minute [16][9]. For our setup that
  is about 30 + 30 + 2 = 62 action-minutes, roughly **USD 6.20 a run**, which is too
  much for our budget.
- **A cheaper FIS option.** A custom template with only
  `aws:network:disrupt-connectivity` (scope `all`) on the `app-a` subnet for
  3 minutes costs USD 0.30 a run. This action clones the subnet's network ACL, adds
  deny rules, and restores the original ACL afterwards [60].
- **A free manual option** does the same thing: a script attaches the pre-built
  deny-all network ACL to the subnet, then puts the original back.
- **Decision:** use the manual network ACL swap for repeated E3 and E6b runs, and
  optionally do one FIS run (about USD 0.30) for the report.
- **The ASG relaunch loop.** While AZ a is cut off, the ASG will try to rebalance by
  launching into AZ a. Those instances cannot become healthy, so they are replaced
  again and again. That churn is itself a finding. To show the ASG restoring three
  healthy instances, temporarily remove `app-a` from the ASG's subnets. The
  AWS-native way is an ARC zonal shift, which supports both ALBs and ASGs [61] and is
  free [21]. Whether the ALB needs an attribute switched on first is UNVERIFIED.
- **Full-AZ variant (exploratory).** Cut off both `lb-a` and `app-a`. Clients that
  resolved the ALB node's IP in AZ a will time out until that IP leaves DNS, and AWS
  only removes zonal IPs itself during real infrastructure events [29]. A zonal shift
  on the ALB removes it at once [61]. Report this run separately, as a lesson about
  ALB nodes being tied to an AZ.

---

## 9. Cost

Indicative prices, before tax, from the AWS Price List API (EC2 file published
29 October 2026) and the AWS pricing pages. Mumbai and Hyderabad prices are identical
for every item we use. **Confirm them in the Pricing Calculator after approval.**
Indian accounts pay **18% GST** on top [71].

### 9.1 Bill of materials

| Resource | Tier 1 | Tier 2 | Tier 3 | Notes |
|---|---|---|---|---|
| EC2 t3.micro (app) | 2 | 1 to 2 (ASG min 1 / max 2) | 2 + 2 (one per region, ASG min 1 / max 2) | Unlimited credits |
| EC2 t3.small (load generator) | — | — | — | Dropped: laptop-only load testing keeps us inside the 5-vCPU quota |
| EBS gp3, 8 GiB | One per instance | One per instance | One per instance | — |
| ALB | 1 (2 AZs) | 1 (2 AZs) | 2 (2 AZs each) | — |
| Public IPv4 addresses | 4 | 3 to 4 | 8 | One per instance plus one per ALB AZ (ASSUMPTION: one node IP per AZ at our load) |
| Route 53 hosted zone | — | — | 1 | Kept for the month |
| Route 53 health checks | — | — | 2, with the fast interval | — |
| Domain | — | — | 0 or 1 | See O1 |
| ECR repository | 1 | 1 | 1 + replica | — |
| S3 bucket (Terraform state) | 1 | 1 | 1 | — |
| CloudWatch alarms | Up to 3 | Up to 4 | Up to 8 in total | First 10 free |
| FIS | — | Optional, 1 run | — | — |

### 9.2 Unit prices (indicative)

| Item | Price | Source |
|---|---|---|
| t3.micro | USD 0.0112/h | [4] |
| t3.small | USD 0.0224/h | [4] |
| Surplus CPU credits (T3, Linux) | USD 0.05 per vCPU-hour | [4] |
| EBS gp3 | USD 0.0912/GB-month, billed per second with a 60 s minimum | [4][18] |
| EC2 billing | Per second, 60 s minimum | [17] |
| ALB | USD 0.0239/h (any part hour counts as a full hour) + USD 0.008 per LCU-hour | [5][12] |
| Public IPv4 | USD 0.005/h per address, in use or idle, including the ALB's addresses | [6][12][13] |
| Route 53 hosted zone | USD 0.50/month, not prorated; free if deleted within 12 h | [14] |
| Route 53 health checks | First 50 checks of AWS endpoints free; optional features USD 1.00/month each, prorated | [14] |
| Route 53 queries | Alias queries to an ELB free; latency records USD 0.60 per million | [14][7] |
| Domain via Route 53 | `.click` USD 3/yr, `.link` USD 5, `.in` USD 8, `.com` USD 16. Credits cannot be used. | [15] |
| Data transfer | First 100 GB/month to the Internet free, then USD 0.1093/GB; Mumbai to Hyderabad USD 0.086/GB; between AZs USD 0.01/GB | [10] |
| CloudWatch alarms | USD 0.10 per alarm-month; first 10 free | [8] |
| FIS | USD 0.10 per action-minute | [16][9] |
| ECR | USD 0.10/GB-month | [11] |
| AWS Budgets | Monitoring is free | [19] |

### 9.3 Cost per hour for each tier

Each total below is the sum of these lines. LCUs are 0.8 for the prober's
20 connections/s, or 1.6 under laptop Locust (processed-bytes dimension).

| Line | Tier 1 | Tier 2 base (desired 2) | Tier 2 under load (desired 2) | Tier 3 (2 regions × desired 2) |
|---|---|---|---|---|
| App instances | 2 × 0.0112 | 2 × 0.0112 | 2 × 0.0112 | 4 × 0.0112 |
| EBS | 2 × 0.0010 | 2 × 0.0010 | 2 × 0.0010 | 4 × 0.0010 |
| Public IPv4 addresses | 4 × 0.005 | 4 × 0.005 | 4 × 0.005 | 8 × 0.005 |
| ALBs | 1 × 0.0239 | 1 × 0.0239 | 1 × 0.0239 | 2 × 0.0239 |
| LCUs | 0.8 × 0.008 | 0.8 × 0.008 | 1.6 × 0.008 | 0.8 × 0.008 |
| Surplus CPU credits | — | — | 2 × 0.04 (at 50% CPU) | — |
| Route 53 fast checks | — | — | — | 2 × 1.00 ÷ 730 |
| **Total, USD/h** | **0.075** | **0.075** | **0.162** | **0.139** |
| **If left running 24/7 for 730 h** | **≈ 55** | **≈ 55** | — | **≈ 101** (+ 0.50 hosted zone) |

The whole project is capped at **USD 100 total** (D9: the group's USD 100 sign-up
credit). The numbers above show that even an all-tier stack left running by mistake
would eat the credit within about a month, which is why `terraform destroy` after
every session is a hard rule (R3).

**Correction to the Week 2 report.** The report's USD 30.41 a month (2 × t3a.micro +
ALB) leaves out **public IPv4**: 4 addresses × USD 0.005 × 730 h = **USD 14.60**. The
same configuration actually costs about **USD 44.90 a month**, and a 5-hour test costs
about USD 0.31, not USD 0.21.

### 9.4 Planned test hours against the USD 100 budget

The hard ceiling is the group's **USD 100 free-account sign-up credit** (D9).
A USD 10 Budgets alert is kept as an early tripwire so a forgotten stack is noticed
well before it eats the credit.

| Item | Hours | USD, before tax |
|---|---|---|
| Tier 1: deploy, debug, E1, E1b, E2 | 6 | 0.45 |
| Tier 2: deploy, debug, E3, E4, E0, E5a, E5b | 10 | 0.90 |
| Tier 3: both regions, DNS, E6a, E6b | 8 | 1.11 |
| Route 53 hosted zone (one month) | — | 0.50 |
| FIS, one optional run of 3 action-minutes | — | 0.30 |
| ECR, S3, replication, miscellaneous | — | 0.10 |
| **Subtotal** | **24** | **3.36** (USD 3.96 with GST) |
| Contingency: a Tier 2 stack forgotten for 24 hours | 24 | +1.80 |
| Domain, if a `.click` is bought through Route 53 (card, not credit) | — | +3.00 |

| Scenario | Before tax | With 18% GST | Within USD 100 credit? | Trips the USD 10 Budgets alert? |
|---|---|---|---|---|
| No domain bought, no contingency | 3.36 | **3.96** | Yes, by a wide margin | No |
| No domain bought, with 24 h forgotten | 5.16 | 6.09 | Yes | No |
| `.click` domain, no contingency | 6.36 | 7.50 (+ USD 3 card) | Yes | No |
| Full all-tier stack forgotten for a month | — | ≈ USD 100 | **No — eats the whole credit** | Yes, long before |

**Conclusion:** the planned work costs about **USD 4–7 total** against the USD 100
credit, so the credit covers the whole project — including a domain — with plenty of
headroom. The real risk is **a forgotten stack running for days or weeks**, which can
drain the credit (see R3). Each apply/destroy session adds up to one extra ALB-hour
(USD 0.024) because ALB billing rounds up to the hour [12], but that is negligible
against the credit.

**This is a course demo, not an operational system.** Every number above is sized
for one demo session per tier plus debugging, not sustained running.

### 9.5 Free Tier status (as of 31 October 2026)

- **Accounts created before 15 July 2025:** the 12-month Free Tier [25] has now ended
  for every such account (the latest possible end date was 14 July 2026). These
  accounts pay standard rates.
- **Accounts created on or after 15 July 2025:**
  - USD 100 at sign-up, plus up to USD 100 more for five console activities. One of
    those activities is creating an AWS Budgets cost budget, which D9 asks for
    anyway [23][24].
  - Credits must be used within 12 months of account creation [12].
  - The Free plan ends after 6 months or when the credits run out, and includes only
    "select AWS services and features" [23].
  - Whether a Free-plan account can launch types outside the eligible list
    (for example c7g.medium) or register a domain is UNVERIFIED. Domain fees can never
    be paid with credits [15].
- **t3.micro is free-tier eligible under both schemes** [25], so our choice works with
  any account.
- Charges with free allowances for every account: 10 CloudWatch alarms [8], 100 GB a
  month of data out to the Internet [10], and 50 Route 53 health checks of AWS
  endpoints [14].

### 9.6 Comparison with on-premises (carried over from report 5.3)

| Option | USD/month | Notes |
|---|---|---|
| On-premises, 1 site, 2 servers | 245.23 | The report's own assumptions; its arithmetic checks out (83.33 + 21.90 + 100 + 40) |
| On-premises, 2 sites, 2 servers each | 490.46 | Twice the above. This is the fair comparison for multi-site HA, as Aadhaar runs two data centres. ASSUMPTION. |
| AWS Tier 1, running 24/7 (corrected) | ≈ 50–55 | Section 9.3 |
| AWS Tier 3, running 24/7 | ≈ 114 | Two regions plus Route 53 |
| AWS Tier 1, our actual 6 test hours | ≈ 0.45 | Section 9.4 |

At this toy scale, fixed per-resource charges (ALB hours, public IPv4) dominate the
cloud bill. At national scale and high utilisation the comparison can reverse, which
is the argument in report 5.1, but we have no UIDAI cost data to test it. The
on-premises figures also leave out data-centre power overhead (PUE) and the upfront
capital cost.

---

## 10. Risks and mitigations

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | ~~Default 5-vCPU quota blocks Tier 2~~ — **resolved by design**: Tier 2 is sized at min 1 / desired 2 / max 2 (4 vCPUs), and the laptop runs Locust. No quota increase is requested (D9). The cost is a smaller live scaling demo (1 → 2 instead of 3 → 6); the full 3-AZ design stays on paper. | — / — | — |
| R2 | Hyderabad not enabled, or the account plan restricts services | Medium / High | Enable the region and check the plan type now (O2) |
| R3 | A forgotten stack eats the USD 100 credit | **High / High** | Budgets alert at USD 10 actual spend as an early tripwire; `terraform destroy` after every session; an end-of-day check by tag (`Project`); only the `global/` stack is kept running |
| R4 | Domain delegation takes time | Medium / Medium | Create the hosted zone and delegation at least a week before step 11, and keep the zone |
| R5 | Burstable credits distort measurements | Medium / Medium | Unlimited mode, scaling on request count, credit metrics exported (5.1.2) |
| R6 | Health checks fail under load and cascade | Medium / High | Cheap `/health`, 2 workers, watch `UnHealthyHostCount`, adjust thresholds if needed (5.2) |
| R7 | Invalid measurements: keep-alive, DNS caching, a closed-loop client, laptop limits, clock drift | Medium / High | The prober design (8.3), an EC2 load generator for load tests, NTP |
| R8 | An arm64 image on an x86 instance fails with "exec format error" | Medium / Medium | `buildx --platform linux/amd64`; check the image manifest before pushing |
| R9 | Outside services needed at boot (Docker Hub limits [70], PyPI, GitHub) | Low / Medium | Images in ECR; nothing built on instances |
| R10 | Terraform state conflicts or loss | Medium / High | S3 backend with a lock file; one person applies per step |
| R11 | The grace period is wrong: too short causes a replacement loop, too long slows replacing broken instances | Medium / Medium | Measure boot to healthy in E4 and set the grace period to 1.5 × that |
| R12 | The ECR replica is not ready when Tier 3 tests start | Low / Medium | Push at least 30 minutes early [63], or push to both regions |
| R13 | Route 53 checkers are blocked, causing a false failover | Low / High | Keep the ALB's port 80 open to the Internet; only add deny ACLs to `lb` subnets during E6b |
| R14 | FIS costs too much | Medium / Medium | Use one action, or the manual network ACL swap (8.6) |
| R15 | The same bad image fails both regions at once | Low / High | Deploy one region at a time; instance refresh with automatic rollback |
| R16 | Instances with public IPs are exposed | Low / Medium | Security group chain, no SSH, IMDSv2 with hop limit 1, least-privilege IAM |
| R17 | Synthetic data is mistaken for real data | Low / High | Fake ID format (FR6), README disclaimer |
| R18 | An AWS Academy Learner Lab account, if that is the plan, may restrict regions and services | UNVERIFIED | Check its region list before choosing O2 |

---

## 11. Fixes needed in our Week 2 report

| # | Where | Problem | Fix |
|---|---|---|---|
| F1 | 2.3, 3.5 | "The ASG launches a replacement", but the exercise has no ASG (G1) | Add a "Tier" column to the failure matrix; the ASG behaviour is demonstrated from Tier 2 |
| F2 | Throughout | Tiers are never defined (G2) | Add the Tier 1–3 definitions from section 5 |
| F3 | 3.3 | DynamoDB is called "our choice for the demo data", but the demo serves static JSON (G3) | Say "static JSON in the image (D3)"; DynamoDB global tables stay as the paper design for data that changes |
| F4 | 3.3 heading | Typo: "Compute and Data Tires" | Change to "Tiers" |
| F5 | 3.2 | "each level failover on its own" | Change to "each level fails over on its own" |
| F6 | 3.2 | "We set a 60 s TTL" | An alias record pointing at an ALB cannot have its own TTL; the ELB's 60 s applies [43][29] |
| F7 | 3.2 | "Three failed probes at a 10 s interval" | Add that the 10 s interval is a paid option, that the status is decided across many checkers (healthy only if more than 18% report healthy) [39][14], and that detection takes 20–45 s plus the TTL |
| F8 | 3.2 and PLAN step 11 | The report describes latency routing; PLAN says failover routing | Use latency routing with health checks (P1) |
| F9 | 3.5 | "AWS FIS may offer an AZ scenario" | It does, in Mumbai only; a default run costs about USD 6.20, so use one action or a manual network ACL change (8.6) [58][59][16] |
| F10 | 3.5 | "Data replica unreachable" has nothing to test with static JSON | Redefine it as "dataset broken in one region: the deep check fails and Route 53 removes the region" (Tier 3) |
| F11 | 4.1 | No availability numbers | Add the SLA table and composite maths from section 4 |
| F12 | 5.1 | "in the figures above" points to figures that are not in the body; references 6–10 are only cited in the reference list | Add the table from 3.1. Soften "steady 8–10% growth": the September 2026 statement (about 10 crore a day, preparing for 25–30 crore) implies about 40% growth on August 2025 [77] |
| F13 | Week 1 summary 4; report 1 and reference 1 | "Tens of millions of authentications daily" | Quote UIDAI's page [72], but add that actual volume is about 100 million a day in 2026 [77] |
| F14 | 5.3 | The cost model leaves out public IPv4 | +USD 14.60 a month, giving USD 44.90 for the same configuration; a 5-hour test is USD 0.31, not 0.21 (9.3) |
| F15 | 5.3 and 6.1 | t3a.micro is not offered in Hyderabad [47] | Switch to t3.micro (5.1.2) |
| F16 | 5.3 | "assuming Hyderabad prices match Mumbai, which we have not checked" | Now checked: identical for every item we use [4][5][6]; Tier 3 costs about USD 0.156/h (G6) |
| F17 | 5.3 | The on-premises comparison is one site against a multi-AZ cloud design | Add the two-site variant (USD 490/month) and note PUE and capital cost (9.6) |
| F18 | 6.1 | "[TO FILL] final values" for the health check | 5 s interval, 2 s timeout, healthy 2, unhealthy 2, 15 s deregistration delay |
| F19 | 5.3 | "[TO FILL] actual cost + billing screenshot" | Fill in after step 12 |
| F20 | 6.2 | "The brief says traffic should reroute 'instantly'" | The course brief in `docs/` contains no such statement [81]. Cite the source, or rephrase as "a naive expectation is instant rerouting". |
| F21 | 6.2 | A 1 request/s loop; process stop and instance stop treated the same | 20 requests/s open loop with a new connection per request; separate E1 and E2; 5 runs; median and range (section 8) |
| F22 | 6.3 | "Optional: a Locust load test" | Required: scaling behaviour is a Week 3 measurement (G4); see E0 and E5 |
| F23 | Numbering | Section 7 is missing (6 jumps to 8) (G7) | Renumber |
| F24 | 3.3 | The N/(N−1) rule is stated only for one region | Add the two-region version: 2 × peak in total for any single failure, 3 × for a double failure (3.3) |
| F25 | 3.6 | "TLS on the load balancer using ACM certificates per region" | Only possible with our own domain (Tier 3); Tiers 1–2 use HTTP as a stated simplification |

---

## 12. Answers and recommendations for open items O1–O3

### O1: Domain for Route 53

Requirement: a public hosted zone (USD 0.50 a month [14]) and a domain whose name
servers point at it. Options, cheapest first:

1. **A member already owns a domain:** delegate a subdomain (for example
   `aadhaar-demo.<domain>`) to a Route 53 hosted zone by adding four NS records at the
   current DNS provider. **Cost: USD 0.50 a month.**
2. **A free student domain:** the GitHub Student Developer Pack lists a free one-year
   `.me` domain from Namecheap [80] (whether the offer still applies is UNVERIFIED for
   our accounts). Point its name servers at Route 53. **Cost: USD 0.50 a month.**
3. **Buy `.click` through Route 53:** USD 3 a year (`.link` USD 5, `.in` USD 8, `.com`
   USD 16) [15]. Credits cannot pay for it [15], so it goes on a card. It fits the
   budget but uses about a third of it once GST is added (9.4).

**Recommendation:** option 1 if anyone has a domain, otherwise option 2, with option 3
as the fallback.

- **Owner:** the AWS account owner (O2), so DNS and AWS sit with one person. Keep the
  registrar login in a shared password manager, never in Git.
- **When:** set it up at least a week before step 11. The hosted zone lives in
  `infra/global/dns` and is not destroyed between sessions (5.4.2).

### O2: Whose AWS account, and who sets up the budget

**Resolved:** the group uses its **shared free AWS account with the USD 100 sign-up
credit** (D9). The account owner performs every AWS console action manually from
their laptop; Jeel owns the infrastructure steps and flags when an action is needed
with an **"AWS action needed:"** note in `PLAN.md` or in chat.

Setup checklist for the account owner (one-time, before step 6):

1. **Confirm the account's plan is the post-15-July-2025 Free plan** with the USD 100
   credit intact [23]. Note the credit expiry date (12 months from account
   creation) [12].
2. **Enable `ap-south-2`** [56] (needed from step 11 onwards; enabling is free).
3. **Do not request any vCPU quota increase.** Tier 2 and Tier 3 are sized to fit
   within the default 5-vCPU per-region quota (R1).
4. **Create the D9 Budgets alert** before anything is deployed: USD 10 actual-spend
   tripwire with email to all three members, plus a USD 50 forecast alert as a
   second line of defence (the real ceiling is the USD 100 credit, but we want
   warnings long before). On a new account this activity also earns extra
   credit [24].
5. **Create one named IAM user per member with MFA** (6.4). Put MFA on the root user
   and give it no access keys.

### O3: Hyderabad prices and services

Answered in 5.4.5:

- **Prices:** identical to Mumbai for everything we use.
- **Available:** ALB, ECR, t3 and t4g.
- **Not available:** t3a, t2 and FIS.
- **Opt-in:** the region must be enabled first.
- **AZs:** 3.
- **Consequence:** we use t3.micro in both regions, and run any AZ-loss experiments in
  Mumbai only.

---

## 13. Proposed changes to approved decisions

| # | Affects | Proposed change | Reasoning |
|---|---|---|---|
| **P1** | D4 (how PLAN step 11 describes Tier 3) | Use **latency-based routing with health checks** (active-active) instead of failover routing (active-passive) | Route 53 defines failover routing as active-passive and every other policy with health checks as active-active [42]. Our report (3.1–3.2) and Aadhaar's two sites are active-active. The failover measurement and the cost are the same either way, because alias queries are free. If the group keeps failover routing, the report must describe Tier 3 as active-passive (warm standby). |
| P2 | D9 (a clarification) | The hard ceiling is the **USD 100 free-account credit**; the USD 10 Budgets alert is the early tripwire. Define both as **total cost including 18% GST and before credits**, with alerts at USD 2.50, 5.00 and 10 actual spend, and a USD 50 forecast alert. | GST adds 18% [71]. On a new account, credits would hide real usage. Whether Budgets includes tax and credits by default is UNVERIFIED, so check the budget's cost settings. Budgets themselves are free [19]. |
| P3 | D4 (timing) | **Start O1 now**, in parallel with Tier 1. Building Tier 3 still waits until Tier 2 works. | DNS delegation has a lead time, and the hosted zone must stay stable (5.4.2) |
| P4 | D6 (an extension) | Fix the image architecture (`linux/amd64`) and the registry (ECR, replicated to Hyderabad); never build images on instances | R8 and R9; recovery should not depend on GitHub, PyPI or Docker Hub |

**Changes to plan details (not D1–D10 decisions):**

- t3a.micro becomes t3.micro (F15).
- Tier 2 uses **2 AZs with min 1 / desired 2 / max 2**, fitting the default 5-vCPU
  quota (no quota increase is requested — D9).
- Tier 3 uses **2 AZs per region with min 1 / desired 2 / max 2**, same reason.
- All load testing runs from a laptop (an EC2 load generator would push vCPU use
  over the default quota).
- The live scaling demo shows the **1 → 2 transition**; the 3 → 6 ramp stays as the
  paper design in section 3.3.
- 5 runs per failover experiment instead of 3.
- The prober runs at 20 requests/s open loop instead of 1 request/s.
- A custom VPC with separate load-balancer and app subnets.
- Terraform state in S3 with a lock file.
- PLAN.md section 3 should drop "plus connection draining" from its RTO, because the
  deregistration delay does not apply to failed health checks [27].
- **AWS console actions are performed manually by the account owner**; the
  infrastructure owner (Jeel) flags each one with an "AWS action needed:" note.

---

## 14. References

All web sources were accessed between 29 and 31 October 2026.

**AWS SLAs**

1. AWS, Amazon Compute Service Level Agreement (updated 25 May 2022). https://aws.amazon.com/compute/sla/
2. AWS, Elastic Load Balancing Service Level Agreement (updated 25 Jul 2022). https://aws.amazon.com/elasticloadbalancing/sla/
3. AWS, Amazon Route 53 Service Level Agreement (updated 16 Apr 2025). https://aws.amazon.com/route53/sla/

**AWS Price List API (official machine-readable prices)**

4. AmazonEC2 offer, `ap-south-1` and `ap-south-2` (version 20261029175634; on-demand Linux, EBS, CPU credits). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-south-1/index.csv and https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-south-2/index.csv
5. AWSELB offer (published 11 Sep 2026). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSELB/current/region_index.json
6. AmazonVPC offer, public IPv4 (published 16 Oct 2026). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/region_index.json
7. AmazonRoute53 offer, global items (published 11 Sep 2026). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRoute53/current/region_index.json
8. AmazonCloudWatch offer (published 7 Oct 2026). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/region_index.json
9. AWSFIS offer (published 11 Sep 2026; no Hyderabad entry). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSFIS/current/region_index.json
10. AWSDataTransfer offer (published 16 Sep 2026). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSDataTransfer/current/region_index.json
11. AmazonECR offer (published 11 Sep 2026). https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECR/current/region_index.json

**AWS pricing pages and FAQs**

12. Elastic Load Balancing pricing (per-hour billing, LCU dimensions, IPv4 note, Free Tier text). https://aws.amazon.com/elasticloadbalancing/pricing/
13. Amazon VPC pricing (public IPv4). https://aws.amazon.com/vpc/pricing/
14. Amazon Route 53 pricing (hosted zones, health checks, alias queries). https://aws.amazon.com/route53/pricing/
15. Amazon Route 53 Pricing for Domain Registration (PDF created 14 Sep 2026). https://d32ze2gidvkk54.cloudfront.net/Amazon_Route_53_Domain_Registration_Pricing_20140731.pdf
16. AWS FIS pricing. https://aws.amazon.com/fis/pricing/
17. Amazon EC2 On-Demand pricing (per-second billing). https://aws.amazon.com/ec2/pricing/on-demand/
18. Amazon EBS pricing (per-second billing). https://aws.amazon.com/ebs/pricing/
19. AWS Budgets pricing. https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/
20. AWS Certificate Manager pricing. https://aws.amazon.com/certificate-manager/pricing/
21. Amazon Application Recovery Controller pricing (zonal shift at no extra charge). https://aws.amazon.com/application-recovery-controller/pricing/
22. Elastic Load Balancing FAQs (no charge for ALB cross-zone data transfer). https://aws.amazon.com/elasticloadbalancing/faqs/

**AWS Free Tier**

23. Choosing a Free Tier plan. https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html
24. Earning additional Free Tier credits. https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans-activities.html
25. Track your Free Tier usage for Amazon EC2 (eligible instance types before and after 15 Jul 2025). https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html

**Elastic Load Balancing documentation**

26. Health checks for ALB target groups. https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html
27. Edit target group attributes (deregistration delay, slow start, health settings, cross-zone). https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-target-group-attributes.html
28. CloudWatch metrics for your Application Load Balancer. https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html
29. How Elastic Load Balancing works (60 s DNS TTL, zonal IP removal). https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/how-elastic-load-balancing-works.html
30. Troubleshoot your Application Load Balancers (HTTP 502, 503, 504). https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html

**EC2 Auto Scaling documentation**

31. Set the health check grace period. https://docs.aws.amazon.com/autoscaling/ec2/userguide/health-check-grace-period.html
32. Health checks for instances in an Auto Scaling group. https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-health-checks.html
33. Replace unhealthy instances. https://docs.aws.amazon.com/autoscaling/ec2/userguide/replace-unhealthy-instance.html
34. Default instance warmup. https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-default-instance-warmup.html
35. Target tracking scaling policies. https://docs.aws.amazon.com/autoscaling/ec2/userguide/as-scaling-target-tracking.html
36. Auto Scaling group metrics. https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-metrics.html
37. Undo changes with a manual or auto rollback (instance refresh). https://docs.aws.amazon.com/autoscaling/ec2/userguide/instance-refresh-rollback.html
38. Instance maintenance policies. https://docs.aws.amazon.com/autoscaling/ec2/userguide/instance-maintenance-policy-overview-and-considerations.html

**Route 53 documentation**

39. How Route 53 determines whether a health check is healthy. https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover-determining-health-of-endpoints.html
40. Values for creating and updating health checks (interval, failure threshold, invert). https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/health-checks-creating-values.html
41. HealthCheckConfig API reference (FailureThreshold default of 3). https://docs.aws.amazon.com/Route53/latest/APIReference/API_HealthCheckConfig.html
42. Active-active and active-passive failover. https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover-types.html
43. Choosing between alias and non-alias records (TTL of alias records). https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resource-record-sets-choosing-alias-non-alias.html
44. Latency-based routing. https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/routing-policy-latency.html
45. Monitoring health checks using CloudWatch (metrics only in US East, N. Virginia). https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/monitoring-health-checks.html
46. Configuring failover in more complex configurations (Evaluate Target Health). https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover-complex-configs.html

**EC2 documentation**

47. Amazon EC2 instance types by Region. https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-regions.html
48. Amazon EC2 instance type quotas (default of 5 vCPUs). https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html
49. Key concepts for burstable performance instances. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html
50. Unlimited mode concepts. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode-concepts.html
51. Standard mode concepts. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-standard-mode-concepts.html
52. Monitor CPU credits for burstable instances. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-monitoring-cpu-credits.html
53. Configure instance metadata options for new instances. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html
54. Access instance metadata (container considerations). https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html
55. IMDSv2 in Amazon Linux 2023. https://docs.aws.amazon.com/linux/al2023/ug/imdsv2.html

**Regions, FIS, ARC, ACM, ECR**

56. AWS Regions (opt-in status, number of AZs). https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html
57. Availability Zone IDs. https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-availability-zones.html
58. AWS Fault Injection Service endpoints and quotas. https://docs.aws.amazon.com/general/latest/gr/fis.html
59. AZ Availability: Power Interruption scenario. https://docs.aws.amazon.com/fis/latest/userguide/az-availability-scenario.html
60. FIS actions reference (`aws:network:disrupt-connectivity`). https://docs.aws.amazon.com/fis/latest/userguide/fis-actions-reference.html
61. Resources supported for zonal shift (ALB, ASG). https://docs.aws.amazon.com/r53recovery/latest/dg/arc-zonal-shift.resource-types.html
62. AWS Certificate Manager overview (certificates are regional). https://docs.aws.amazon.com/acm/latest/userguide/acm-overview.html
63. Private image replication in Amazon ECR. https://docs.aws.amazon.com/AmazonECR/latest/userguide/replication.html

**Terraform, Locust and Docker**

64. HashiCorp, Terraform S3 backend (`use_lockfile`; DynamoDB locking deprecated). https://developer.hashicorp.com/terraform/language/backend/s3
65. HashiCorp, "Terraform AWS provider 6.0 now generally available" (per-resource region). https://www.hashicorp.com/en/blog/terraform-aws-provider-6-0-now-generally-available
66. Terraform AWS provider docs: `aws_lb_target_group`, `aws_autoscaling_group`, `aws_launch_template`. https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lb_target_group, https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/autoscaling_group, https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/launch_template
67. GitHub releases: Terraform v1.17.1 and AWS provider v6.71.0 (28 Oct 2026), Locust 2.47.0 (21 Oct 2026). https://github.com/hashicorp/terraform/releases, https://github.com/hashicorp/terraform-provider-aws/releases, https://github.com/locustio/locust/releases
68. Locust documentation, Increase performance (`FastHttpUser`). https://docs.locust.io/en/stable/increase-performance.html
69. Locust documentation, Distributed load generation. https://docs.locust.io/en/stable/running-distributed.html
70. Docker, Docker Hub pull usage and limits; Docker blog "Revisiting Docker Hub Policies" (Apr 2025). https://docs.docker.com/docker-hub/usage/pulls/, https://www.docker.com/blog/revisiting-docker-hub-policies-prioritizing-developer-experience/

**Tax**

71. AWS, Tax help for India (18% GST). https://aws.amazon.com/tax-help/india/

**Aadhaar and UIDAI**

72. UIDAI, About Authentication (two data centres in active-active mode, CIDR capacity statement). https://uidai.gov.in/en/about-authentication
73. PIB / MeitY, "Aadhaar authentication crosses 150 billion transactions" (16 May 2025). https://www.pib.gov.in/PressReleasePage.aspx?PRID=2129121
74. UIDAI / PIB, release on July 2025 face authentication and total transactions (8 Aug 2025). https://uidai.gov.in/images/Press_Release-_16.pdf
75. Outlook Business, "Aadhaar Authentication Transactions Rise 10% to 221 Cr in Aug: UIDAI". https://www.outlookbusiness.com/news/aadhaar-authentication-transactions-rise-10-to-221-cr-in-aug-uidai
76. The Tribune / ANI, "UIDAI records 8.47% YoY growth with 231 crore Aadhaar authentication transactions in November" (2 Dec 2025). https://www.tribuneindia.com/news/business/uidai-records-8-47-yoy-growth-with-231-crore-aadhaar-authentication-transactions-in-november/amp
77. Business Standard, "Aadhaar prepares to scale authentications to 300 million a day: UIDAI chief" (9 Sep 2026). https://www.business-standard.com/india-news/aadhaar-authentication-scale-300-million-uidai-neelkantha-mishra-126090900683_1.html
78. UNI, "Aadhaar authentications could touch 300 million a day as usage expands: UIDAI Chairman" (9 Sep 2026). https://www.uniindia.com/business-economy/aadhaar-authentications-could-touch-300-million-a-day-as-usage-expands-uidai-chairman/174098
79. ISB Bharti Institute of Public Policy, "Aadhaar enabled Public Distribution System in Haryana" (more than 98% of responses within 2 s, 78% within 1 s). https://www.isb.edu/faculty-and-research/bharti-institute-of-public-policy/aadhaar-enabled-public-distribution-system-in-haryana

**Other**

80. GitHub Education, Student Developer Pack (offer terms UNVERIFIED for our accounts). https://education.github.com/pack
81. Course and group documents, kept locally in `docs/` (git-ignored): the IT457 Cloud Computing Case Study Project brief; Group 17 Week 1 summary; Group 17 Week 2 report.
