# infra/

Terraform for every AWS resource. Filled by PLAN steps 6, 8, 11 and 12
(owner: Jeel).

Planned layout and state setup: ARCHITECTURE.md section 7.

```
bootstrap/   S3 bucket for Terraform state (once)
global/      ECR repository and Route 53 hosted zone (kept until step 12)
modules/     network, alb, app_static, app_asg, observability, dns_failover
envs/        tier1, tier2, loadgen, tier3
```

Rules are in CONTRIBUTING.md: one person applies, `fmt` + `validate` before
committing, and `terraform destroy` after every session.
