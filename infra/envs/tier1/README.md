# envs/tier1/

Tier 1 stack in `ap-south-1`: VPC + ALB + two standalone EC2 instances
across AZs `a` and `b`, with the four Tier-1 CloudWatch alarms
(ARCHITECTURE.md 5.2, 8.2). PLAN step 6.

Prerequisites (apply in order, once per account):

1. `infra/bootstrap/` applied — state bucket exists.
2. `infra/global/ecr/` applied — repo and replication rule exist.
3. Service image for the current commit pushed to that repo
   (see `infra/global/ecr/README.md`).

Then:

```
cd infra/envs/tier1
cp terraform.tfvars.example terraform.tfvars    # fill in ARN, URL, image tag
cp backend.tfvars.example   backend.tfvars      # fill in bucket name
terraform init -backend-config=backend.tfvars
terraform plan
terraform apply
```

The `alb_url` output is the working URL. First few health checks need
about 90 s while user data installs Docker, logs into ECR and pulls the
image. Then:

```
curl $(terraform output -raw alb_url)/health
curl $(terraform output -raw alb_url)/
curl -X POST $(terraform output -raw alb_url)/api/v1/authenticate \
  -H 'content-type: application/json' \
  -d '{"uid":"TEST-0000-0000-0001","otp":"000001"}'
```

AWS actions needed (console, Jeel):

- Confirm the SNS email subscription if `alarm_email` was set.
- `terraform destroy` here at the end of every session. The `global/`
  stack stays up until step 12.
