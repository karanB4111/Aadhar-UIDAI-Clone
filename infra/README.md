# infra/

Terraform for every AWS resource. Filled by PLAN steps 6, 8, 11 and 12
(owner: Jeel).

Layout and state setup: ARCHITECTURE.md section 7.

```
bootstrap/   S3 bucket for Terraform state (apply once per account)
global/
  ecr/       aadhaar-mock repository with ap-south-2 replication (step 6)
modules/
  network/      VPC, IGW, lb/app subnets, public route table, deny-all NACL
  alb/          ALB, listener, target group, alb-sg + app-sg chain
  app_static/   Tier 1: standalone EC2 instances + instance role + ECR pull
  observability/ SNS topic + Tier 1 CloudWatch alarms
envs/
  tier1/     ap-south-1: network + alb + app_static + observability (step 6)
```

Apply order on a fresh account:

1. `bootstrap/` — once; local state. Outputs the state bucket name.
2. `global/ecr/` — once; S3 backend. Push the service image after apply.
3. `envs/tier1/` — the Tier 1 stack. The `alb_url` output is the demo URL.

Rules (CONTRIBUTING.md): one person applies, `terraform fmt` and
`terraform validate` before committing, and `terraform destroy` after
every session. `global/` is the only stack that stays up between
sessions, and only until step 12.

Steps 8 (ASG), 11 (Tier 3 + Route 53) and 12 (destroy) will add
`modules/app_asg/`, `modules/dns_failover/`, `global/dns/` and
`envs/tier2/`, `envs/tier3/`.
