# Aadhaar (UIDAI): High Availability and Disaster Recovery Demo

IT457 Cloud Computing, Group 17, Dhirubhai Ambani University.

Jeel Thummar (202301047), Kanu Bhadaraka (202301257), Khushi Pandya (202301406).

## About

This is a scaled-down version of a national-scale identity authentication
service, built to show high availability (HA) and disaster recovery (DR) on AWS.
It uses Aadhaar's two-site active-active design as the reference architecture.

**Synthetic data only.** No real Aadhaar numbers, biometrics or personal data
are used anywhere in this project. Synthetic IDs use a `TEST-` prefix so they
can never be mistaken for real ones. This is not affiliated with or endorsed by
UIDAI.

## Status

Build phase. Decisions D1–D10 are recorded in [PLAN.md](PLAN.md), and the
detailed design is in [ARCHITECTURE.md](ARCHITECTURE.md).

| Tier | What | State |
|---|---|---|
| 1 | Two EC2 instances in two AZs of Mumbai behind an ALB | Not started |
| 2 | Auto Scaling group across three AZs, scaling on request count | Not started |
| 3 | Second region (Hyderabad) with Route 53 health checks | Not started |

## Stack

| Layer | Choice |
|---|---|
| Service | Python, FastAPI |
| Packaging | Docker, built for `linux/amd64`, stored in ECR |
| Infrastructure as code | Terraform (S3 backend) |
| Cloud | AWS, Mumbai (`ap-south-1`) and Hyderabad (`ap-south-2`) |
| Instances | t3.micro, unlimited credits, Amazon Linux 2023 |
| Testing | Python failover prober, Locust |
| Analysis | pandas, matplotlib |

## Repository layout

```
service/   FastAPI app, Dockerfile, synthetic data
local/     docker compose + nginx for local rehearsal
infra/     Terraform
tests/     failover prober, Locust file
analysis/  scripts that turn results into charts
results/   CSVs and charts used in the report
```

Each folder has its own README saying what goes in it and which PLAN.md step
fills it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Work goes in step by step, as laid out
in [PLAN.md](PLAN.md), and each member commits their own steps so the history
shows who did what.
