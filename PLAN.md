# Project Plan: Aadhaar HA/DR Demo (Draft for Group Approval)

**Status:** Draft. Nothing gets built until all three members approve (see
[Approval](#7-approval)).

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

- Replace the standalone instances with an **ASG** (min 2) across 2–3 AZs.
- A failed instance is replaced automatically, which makes the failure matrix
  claim true (fixes G1).
- Add a target-tracking scaling policy (for example on CPU or requests per
  target) and run Locust to show scaling behaviour (fixes G4, G5).

### Tier 3: Second region (could have, decide in D4)

- Copy the stack to Hyderabad (`ap-south-2`). Route 53 health checks plus
  failover or latency routing steer traffic between regions.
- **Needs a domain and a Route 53 hosted zone.** That's a small extra cost and
  some setup, so confirm we have or will buy one.
- Only at this tier would a data layer (DynamoDB global table) make sense
  (see G3).

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
| D9 | AWS account and budget | Whose account, spend cap | Set an **AWS Budgets alert** (for example USD 10) before the first deploy |
| D10 | Git workflow | Direct to `main` / branch + pull request | **Branch per step + PR reviewed by one other member** |

---

## 6. Work steps (after approval)

Each step is committed by its owner, so the history shows all three members'
work. Owners follow the roles in the Week 2 report and can be swapped.

| Step | Work | Owner | Reviewer | Done when |
|---|---|---|---|---|
| 0 | Approve this plan, record decisions D1–D10 | All | All | Section 7 ticked by all three |
| 1 | Repo layout, README, contribution notes | Kanu | Khushi | Folders and conventions merged |
| 2 | FastAPI mock service: `/`, `/health`, `/api/v1/authenticate`, responses include instance ID and AZ; Dockerfile | Kanu | Jeel | Runs locally in Docker |
| 3 | Local two-instance rehearsal (docker compose + nginx) | Kanu | Jeel | Stopping one container shows traffic moving |
| 4 | Failover request-loop script (CSV output) | Kanu | Khushi | Produces a CSV against the local setup |
| 5 | Analysis script: summary + charts from CSV | Khushi | Kanu | Chart generated from step 4 output |
| 6 | Terraform Tier 1: security groups, 2 EC2 in 1a/1b, ALB, target group, health check, healthy-host alarm | Jeel | Kanu | `terraform apply` gives a working ALB URL |
| 7 | Tier 1 failover tests, **3 runs minimum**, results committed | Jeel | Khushi | CSVs and charts in `results/` |
| 8 | Tier 2: ASG + scaling policy | Jeel | Kanu | Killed instance is replaced automatically |
| 9 | Locust load test, latency vs load and instance count | Kanu | Jeel | Load test CSVs and chart |
| 10 | Report updates: fix G1–G7, new diagrams, measured results, actual cost + billing screenshot | Khushi | All | Week 3 add-ons ready |
| 11 | (Optional) Tier 3 second region | Jeel | All | Region failover measured |
| 12 | `terraform destroy`, confirm the bill | Jeel | Khushi | No resources left running |

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
| Jeel Thummar | [ ] | |
| Kanu Bhadaraka | [ ] | |
| Khushi Pandya | [ ] | |

**Final decisions** (fill in once agreed):

| ID | Decision |
|---|---|
| D1 | |
| D2 | |
| D3 | |
| D4 | |
| D5 | |
| D6 | |
| D7 | |
| D8 | |
| D9 | |
| D10 | |
