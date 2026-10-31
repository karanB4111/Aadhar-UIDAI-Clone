# Aadhaar (UIDAI): High Availability and Disaster Recovery Demo

IT457 Cloud Computing, Group 17, Dhirubhai Ambani University.

Jeel Thummar (202301047), Kanu Bhadaraka (202301257), Khushi Pandya (202301406).

## About

This is a scaled-down version of a national-scale identity authentication
service, built to show high availability (HA) and disaster recovery (DR) on AWS.
It uses Aadhaar's two-site active-active design as the reference architecture.

**Synthetic data only.** No real Aadhaar numbers, biometrics or personal data
are used anywhere in this project. This is not affiliated with or endorsed by
UIDAI.

## Status

Planning. The architecture and work plan are in [PLAN.md](PLAN.md) and need
approval from all three members before any build work starts.

## Proposed stack (pending approval)

| Layer | Choice |
|---|---|
| Service | Python, FastAPI |
| Packaging | Docker |
| Infrastructure as code | Terraform |
| Cloud | AWS, Mumbai (`ap-south-1`) |
| Testing | Python request loop, Locust |
| Analysis | pandas, matplotlib |

## Contributing

Work goes in step by step, as laid out in [PLAN.md](PLAN.md). Each member
commits their own steps, so the history shows who did what.
