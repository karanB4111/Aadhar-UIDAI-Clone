# Project Plan: Aadhaar HA/DR Demo

**Status:** Approved by all three members on 2026-11-02. Decisions D1–D10
recorded (see [Approval](#7-approval)).

**Progress (updated 2026-11-05):** steps 0–7 done, step 7 reviewed; step 8
Terraform (Tier 2 ASG) landed, applied once on AWS to verify self-healing
(see step 8 row), then destroyed, waiting for Khushi's review. Step 9 (Locust
load test) is **done and committed** (E0/E5a/E5b run on AWS): R_max is
laptop-bounded at ≈160 rps so `SIGN_WORK=4500` is locked and scaling is shown
via per-instance CPU/request-count; E5a load split cleanly 1→2 instances; E5b
scaled out 1→2 (~5–7 min) and back 2→1 (~17 min) with zero client errors.
Server-side CloudWatch metrics for E5a/E5b and the E5b autoscale-timeline chart
fetched and committed (`e93638b`); Tier 2 stack destroyed. Waiting for Jeel's review. Step 2 is
waiting for Jeel's review, step 3 for Kanu's, step 4 for Khushi's, step 5
for Jeel's, and step 6 for Kanu's. Step 7 results: E1 (5 runs, median
11.5 s, all 5 pass), E2 (5 runs, median 12.45 s, 4 of 5 pass + 1 annotated
outlier), E1b (3 runs, median 36.4 s, 2 of 3 pass + 1 annotated outlier).
The two outliers (`e2-r04-az-b`, `e1b-r02-az-b`) have the same two-cluster
shape: a legitimate primary failover window inside the predicted band plus
a short local-wifi blip; both are documented in each experiment's
`results/<e>/README.md`. Tier 1 stack reverted to fast hc and destroyed.
Step 10 (Week 3 report) is **done**: `report/WEEK3.md` closes gaps G1–G7
and folds in the measured step 7 and step 9 numbers, waiting for all-member
review; the actual-billing screenshot (section 6.1 of the report) is the
one open item before submission and needs Jeel to pull it from the AWS
console. Step 11 (Tier 3, Jeel) **done and committed** `3a5fead` (applied
once on AWS 2026-11-05, 8 measurement runs taken, stack destroyed): E6a
3/3 pass (median 13.7 s), E6b 5/5 pass on prober v3 (median 3.9 s);
E6b-r01 kept as documented prober-v2 switch-oscillation finding, fixed
in v3 with regression test. Step 12 (Jeel, reviewer Kanu) **done**
2026-11-06: `global/ecr` and `bootstrap` destroyed, Hyderabad ECR
replica cleaned up manually (replication-created, not Terraform-
managed), final sweep confirms 0 project resources in either region.
**Final November bill: USD 4.20 incl. GST** (`report/billing-nov-2026.pdf`,
Week 3 report §6.1 updated), 4.2% of the USD 100 free-account credit.
**All 12 build steps done.** Open reviews: steps 1–6, 8–12 (see Status
column); open content item: Khushi G7 leftover (reference-list access
dates) before submission.
The live tracker is the **Status** column in
[section 6](#6-work-steps-after-approval).

**Taking over on a new laptop / AWS setup:** see [HANDOFF.md](HANDOFF.md).
It has the shared AWS values (account id, state bucket, ECR URL, current
image tag), the one-time credential setup, and the exact commands to
apply or destroy each stack.

This plan restates what the course asks for, flags gaps in our Week 2 report,
lists the decisions we need to make, and splits the build into small steps,
each with an owner.

---

## 1. What the course asks for

From the course brief (Theme 5, Government and Public Platforms):

> Design a multi-region, high-availability architecture for a national-scale
> service, then build a scaled-down version of one component.

Week 3 asks us to:

- build the core of the exercise
- run experiments and collect measurements: **latency, scaling behaviour, cost**
- test the system and update the report with final results

Our Week 2 report set the goal as demonstrating **High Availability (HA) and
Disaster Recovery (DR)**, with a measured failover test (section 6.2).

So the work has two parts:

1. **Design (on paper):** the full multi-region architecture. Mostly done in the
   Week 2 report, but needs the fixes in section 2.
2. **Build (scaled down):** one component that we deploy, break on purpose and
   measure.

---

## 2. Gaps in the Week 2 report to resolve first

These are places where the report contradicts itself, or where the exercise
plan won't produce what the report or the course asks for.

| # | Gap | Why it matters |
|---|---|---|
| G1 | Section 3 designs **3 AZs plus an Auto Scaling group (ASG)**, but the exercise (6.1) uses **2 standalone EC2 instances, no ASG**. | The failure matrix (3.5) says "the ASG launches a replacement". Without an ASG that won't happen, so we would be claiming something we don't demo. |
| G2 | The failure matrix mentions **"Tier 3"**, but tiers are never defined. | An examiner will ask what Tier 1 and Tier 2 are. |
| G3 | Section 3.3 calls DynamoDB **"our choice for the demo data"**, but 6.1 serves **static JSON**. | Pick one. With static JSON, the "data replica unreachable" scenario and the deep health check have nothing to test. |
| G4 | Week 3 asks for **scaling behaviour**, but the plan only has an optional Locust run and no autoscaling. | We'd be missing one of the three required measurements. |
| G5 | With 2 AZs, each instance must carry **100% of peak load** alone (the report's own N/(N−1) rule gives 200%). | We have to show that one t3a.micro can handle the test load, or the "survives an AZ loss" claim doesn't hold. |
| G6 | Hyderabad (`ap-south-2`) pricing and service availability were **not checked**. | Needed before anyone commits to a multi-region build. |
| G7 | Housekeeping: section 7 is missing from the numbering, and `[TO FILL]` items are still open. | Fix before final submission. |

---

## 3. Availability targets (decide these first)

Every design choice follows from the target, so we should agree on numbers.

| Target | Allowed downtime per month | What it needs |
|---|---|---|
| 99.9% | about 43.8 min | Multiple AZs in one region |
| 99.99% | about 4.4 min | Multiple AZs, fast automated recovery, ideally a second region |

**Recommendation:** for the built demo, aim for **99.9%+ in one region**, and
show how the paper design reaches 99.99% with a second region.

Recovery targets for the built component:

- **RTO (time to recover):** about 20–30 s, set by the load balancer health
  check (for example a 10 s interval × 2 failed checks), plus connection
  draining. We **measure** this rather than claim it.
- **RPO (data loss):** 0, because the service is stateless and its data is
  read-only.

> Note: if we quote AWS SLA figures (EC2, ALB) in the report, check them on the
> current AWS SLA pages first. Don't quote from memory.

---

## 4. Proposed architecture: build in tiers

Defining tiers fixes G2, and each tier is a natural stopping point if we run
short on time.

### Tier 1: Multi-AZ, one region (must have)

```
Client / failover script
        │
        ▼
Application Load Balancer (ap-south-1, health check /health)
        │
   ┌────┴────┐
   ▼         ▼
EC2 in 1a   EC2 in 1b      (FastAPI in Docker, synthetic data in the image)
```

- Demonstrates surviving the loss of one instance or one AZ.
- Matches the Week 2 exercise plan (6.1 and 6.2).

### Tier 2: Self-healing and scaling (should have)

- Replace the standalone instances with an **ASG** across 2 AZs, **min 1,
  desired 2, max 2**. This fits inside the default 5-vCPU per-region quota
  (2 × t3.micro = 4 vCPUs) so we do **not** need to file a quota increase.
- A failed instance is replaced automatically, which makes the failure matrix
  claim true (fixes G1).
- Add a target-tracking scaling policy (for example on requests per target)
  and run Locust from a laptop to show scaling behaviour. The demonstrated
  scale is `desired 1 → desired 2` (fixes G4, G5 within quota limits).

### Tier 3: Second region (planned, per D4; built after Tier 2 works)

- Copy the stack to Hyderabad (`ap-south-2`). Route 53 health checks plus
  failover or latency routing steer traffic between regions.
- **Needs a domain and a Route 53 hosted zone.** That's a small extra cost and
  some setup. See open item O1.
- Data stays as static JSON in the image (D3). Both regions serve the same
  image, so there's nothing to replicate. A DynamoDB global table remains a
  design-only option in the report.

### Not built, design only

WAF/Shield, private subnets with NAT, KMS per region, signed responses
(optional extension), and a full DR runbook. These stay in the report as
design.

---

## 5. Decisions for the group

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Availability target for the demo | 99.9% one region / 99.99% multi-region | 99.9% built, 99.99% on paper |
| D2 | How far we build | Tier 1 / Tier 1+2 / Tier 1+2+3 | **Tier 1 + 2**, Tier 3 only if time and budget allow |
| D3 | Data tier | Static JSON in the image / DynamoDB | Static JSON for Tiers 1–2, update report 3.3 to match |
| D4 | Second region | Yes (needs a domain) / No | Decide after Tier 2 works |
| D5 | Service stack | FastAPI / Flask / Node.js | **FastAPI** (Python, auto API docs, same language as the tests) |
| D6 | How it runs on EC2 | Docker / systemd | **Docker** (same image locally and on AWS) |
| D7 | How infrastructure is created | Terraform / CloudFormation / Console clicks | **Terraform** (repeatable, `destroy` keeps cost low, matches the report's "infrastructure as code" point) |
| D8 | Load-test tool | Locust / k6 | **Locust** (Python) |
| D9 | AWS account and budget | Whose account, spend cap | Use the group's **free AWS account** (USD 100 sign-up credit). Set an **AWS Budgets alert** at USD 10 actual spend as an early-warning tripwire; the credit covers the planned ~USD 5 build comfortably |
| D10 | Git workflow | Direct to `main` / branch + pull request | **Branch per step + PR reviewed by one other member** |

---

## 6. Work steps (after approval)

Each step is committed by its owner, straight to `main` (D10), so the history
shows all three members' work. Pull before you start and push when the step is
done. The reviewer checks the step after it lands and raises anything wrong.
Owners are balanced so every member touches design, build and
documentation. Roles can be swapped if someone is blocked.

**Keeping the Status column current.** It is the single place to see where the
project stands, for all three of us and for any AI agent working in the repo.

- ⬜ Not started → 🟡 In progress (your name) → ✅ Done `<commit>` · review
  pending (reviewer) → ✅ Done `<commit>` · reviewed (reviewer)
- The owner updates the row in the same commit that finishes the step (or
  marks 🟡 when starting, so nobody duplicates work). The reviewer changes
  "review pending" to "reviewed", or adds a link to the issue they raised.
- Also update the **Progress** line at the top of this file.
- ⛔ Blocked (reason) is fine too; say what unblocks it.

| Step | Work | Owner | Reviewer | Done when | Status |
|---|---|---|---|---|---|
| 0 | Approve this plan, record decisions D1–D10 | All | All | Section 7 ticked by all three | ✅ Done `945fba6` |
| 1 | Repo layout, README, contribution notes | Khushi | Kanu | Folders and conventions merged | ✅ Done `de7f30e` · review pending (Kanu) |
| 2 | FastAPI mock service: `/`, `/health`, `/api/v1/authenticate`, responses include instance ID and AZ; Dockerfile | Kanu | Jeel | Runs locally in Docker | ✅ Done `d6dff0d` · review pending (Jeel) |
| 3 | Local two-instance rehearsal (docker compose + nginx) | Khushi | Kanu | Stopping one container shows traffic moving | ✅ Done `f9065c8` · review pending (Kanu) |
| 4 | Failover request-loop script (CSV output) | Kanu | Khushi | Produces a CSV against the local setup | ✅ Done `28095cb` · review pending (Khushi) |
| 5 | Analysis script: summary + charts from CSV | Khushi | Jeel | Chart generated from step 4 output | ✅ Done `<pending>` · review pending (Jeel) |
| 6 | Terraform Tier 1: security groups, 2 EC2 in 1a/1b, ALB, target group, health check, healthy-host alarm | Jeel | Kanu | `terraform apply` gives a working ALB URL | ✅ Done `1cc9a17` · review pending (Kanu) |
| 7 | Tier 1 failover tests, **3 runs minimum**, results committed | Khushi | Jeel | CSVs and charts in `results/` | ✅ Done `0cbeb19` · reviewed (Jeel) — E1 5/5 pass (median 11.5 s), E2 5/5 (median 12.45 s; `e2-r04-az-b` is an annotated two-cluster outlier), E1b 3/3 (median 36.4 s; `e1b-r02-az-b` same shape). Tier 1 stack reverted to fast hc and destroyed. |
| 8 | Tier 2: ASG + scaling policy | Jeel | Khushi | Killed instance is replaced automatically | ✅ Done `135bfe5` · review pending (Khushi) — `modules/app_asg/` and `envs/tier2/` added; ASG min 1/desired 2/max 2 across AZs a,b, target-tracking on `ALBRequestCountPerTarget`, ELB health checks. Applied on AWS 2026-11-03: ASG came up healthy in both AZs. Terminated `i-018673c…` via `terminate-instance-in-auto-scaling-group`; replacement `InService` in 11 s (launch-before-terminate held capacity), ALB target `healthy` in ~130 s (inside the 1.5–3 min predicted band, ARCHITECTURE.md 4.3). Zero outage to clients. Stack destroyed. One-time AWS prerequisite surfaced: `aws iam create-service-linked-role --aws-service-name autoscaling.amazonaws.com` (recorded in `envs/tier2/README.md` and `HANDOFF.md`). |
| 9 | Locust load test, latency vs load and instance count | Kanu | Jeel | Load test CSVs and chart | ✅ Done `71294a1`, `e93638b` · review pending (Jeel) — tooling + all runs done. **E0**: R_max ≈ 160 rps **laptop-bounded** (one t3.micro doesn't saturate from a laptop/Wi-Fi at a stable `SIGN_WORK`; 4500→flat 100 ms @158 rps, 18000→collapse @2 rps), so **`SIGN_WORK=4500` locked** and scaling shown via per-instance CPU/`RequestCountPerTarget` not latency (group call 2026-11-05). **E5a**: N=1 vs N=2 at ~147 rps — load split cleanly 26,470/26,471 (~74 rps/instance), p99 140→120 ms, 0 fail; `charts/latency_vs_instances.png`. **E5b**: step ~137 rps → **scale-out 1→2 in ~5–7 min**, 0 client errors; **scale-in 2→1 in ~17 min** after load removed (both inside the 4.3 bands); `charts/autoscale_timeline.png`. Raw CSVs + per-run `load_summary.json` + server-side `aws_metrics.csv` + READMEs in `results/e0,e5a,e5b/`. Tier 2 stack destroyed after metrics fetch. |
| 10 | Report updates: fix G1–G7, new diagrams, measured results, actual cost + billing screenshot | Khushi | All | Week 3 add-ons ready | ✅ Done `<pending>` · review pending (All) — `report/WEEK3.md` created. G1–G7 closed (section 1), as-built Tier 1 + Tier 2 diagrams (section 2), measured failover window E1 11.5 s / E2 12.45 s / E1b 36.4 s and Tier 2 self-healing 130 s (section 3), scaling E5a per-instance split and E5b scale-out 5–7 min / scale-in ~17 min (section 4), SLA availability rollup (section 5), planning-cost paragraph with `AWS action needed: Jeel — Cost Explorer screenshot for November 2026` as the one open item before submission (section 6). Tier 3 stays paper design (section 7), pending O1. |
| 11 | Tier 3: second region (Hyderabad), **client-side** failover (O1 descoped) | Jeel | All | Region failover measured | ✅ Done `3a5fead` · review pending (All) — Tier 3 applied once on AWS 2026-11-05 (both regions came up healthy on image `6cc656f`; Hyderabad serving from AZs 2a+2b, Mumbai from 1a+1b), 8 measurement runs taken, Tier 3 stack destroyed. **E6a (3 runs)**: planned Mumbai evacuation via ASG min/desired=0 — median time-to-switch **~13.7 s** (range 12.4–13.9), 4–5 ALB 5xx per run, 0 errors after switch, Hyderabad took every request. **E6b (5 runs r02–r06, prober v3)**: unplanned Mumbai loss via deny-all NACL on app subnets — median time-to-switch **~3.9 s** (range 3.3–5.3), 103 timeouts per run (= the open-loop's in-flight count at inject moment), 0 errors after drain, 1 switch per run. **E6b-r01 (prober v2)** is kept as a documented finding: late timeouts from the dead primary thrashed the switch decision (38 switch events in ~8 s) — fixed in prober v3 (switch decisions now use the request's own `active_url`, regression test `test_urls_mode_late_errors_from_old_target_do_not_thrash` pins it). See `results/e6a/README.md` and `results/e6b/README.md`. Measurement caveat: these are **client-side** failover numbers, a lower bound on the Route 53 case the paper design describes. |
| 12 | `terraform destroy`, confirm the bill | Jeel | Kanu | No resources left running | ✅ Done `09ee338` · review pending (Kanu) — all `envs/*` already destroyed in earlier steps. 2026-11-06: `global/ecr` destroyed (image `6cc656f` + two untagged platform manifests `20aae8f...` and `ee40f77...` deleted first; Hyderabad replica repo was NOT Terraform-managed — replication creates it, destroying the replication rule does not — so it was deleted manually by `aws ecr delete-repository --region ap-south-2`); `bootstrap/` destroyed (bucket versions + delete markers cleared first). Final sweep: 0 EC2, 0 ALB, 0 project VPC, 0 ECR repo, 0 state bucket in both regions. **Final November 2026 bill: USD 4.20 incl. 18% GST** (pre-tax USD 3.56 — ALB USD 1.40, EC2+EBS USD 0.94, public IPv4 USD 0.94, non-project KMS keys in eu-north-1/us-west-2 USD 0.28; everything else inside free tier). Report `report/billing-nov-2026.pdf` + §6.1 updated with actuals. Within USD 10 Budgets tripwire (2.4× margin) and 4.2% of the USD 100 free-account credit (D9). |

**Workload split (steps 1–12, excluding step 0 which is shared):**

| Member | Owns | Reviews | Mix of work |
|---|---|---|---|
| Jeel Thummar | 6, 8, 11, 12 | 2, 5, 9 | Terraform / infra across all three tiers, teardown |
| Kanu Bhadaraka | 2, 4, 9 | 1, 3, 6, 10, 11, 12 | Service code, test tooling |
| Khushi Pandya | 1, 3, 5, 7, 10 | 4, 8, 10, 11 | Repo setup, local rehearsal, analysis, Tier 1 tests, report |

Each member owns at least one build task and one measurement or
documentation task, so no one is limited to a single kind of work.

### Proposed repo layout (set up in step 1)

```
service/   FastAPI app, Dockerfile, synthetic data
local/     docker compose + nginx for local rehearsal
infra/     Terraform
tests/     failover loop, Locust file
analysis/  scripts that turn results into charts
results/   CSVs and charts used in the report
```

---

## 7. Approval

Tick when you agree with the plan and decisions. Write any change you want next
to your name, or open a GitHub issue.

| Member | Approved | Changes requested |
|---|---|---|
| Jeel Thummar | [x] | |
| Kanu Bhadaraka | [x] | |
| Khushi Pandya | [x] | |

**Final decisions:**

| ID | Decision |
|---|---|
| D1 | 99.9% built in one region; 99.99% shown on paper with a second region |
| D2 | Build Tier 1 + Tier 2, then Tier 3 (see D4) |
| D3 | Static JSON in the image; update report section 3.3 to match |
| D4 | **Yes**, build the second region (Hyderabad) after Tier 2 works |
| D5 | FastAPI |
| D6 | Docker |
| D7 | Terraform |
| D8 | Locust |
| D9 | Group's free AWS account (USD 100 credit); AWS Budgets alert at USD 10 as a tripwire. **No vCPU quota increase will be requested** — we stay within the default 5 vCPUs per region |
| D10 | Commit directly to `main` |

**Open items:**

| ID | Item | Needed by |
|---|---|---|
| O1 | Domain for Route 53 failover: the group will arrange this themselves (own domain or a cheap one). Flag at least a week before step 11. | Step 11 |
| O2 | ~~Whose AWS account we deploy to~~ — **resolved**: the group's shared free account (USD 100 credit); the account owner handles each AWS console action when Jeel flags it. | — |
| O3 | Check Hyderabad (`ap-south-2`) pricing and that it offers what we need (t3a instances, ALB) (G6). | Step 11 |

### Working convention: AWS console actions are manual

The group runs AWS actions themselves from the account owner's laptop
(sign-up, region opt-in, Budgets alert, root MFA, IAM user creation,
domain purchase and so on). Steps in this plan that need a console action
will say so explicitly — look for a line starting with **"AWS action
needed:"**. Terraform `apply` and `destroy` are also run from the account
owner's laptop (Jeel), one person at a time, per section 7 of
`ARCHITECTURE.md`.
