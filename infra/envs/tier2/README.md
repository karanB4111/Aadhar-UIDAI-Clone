# envs/tier2/

Tier 2 stack in `ap-south-1`: VPC + ALB + an Auto Scaling group (min 1 /
desired 2 / max 2) across AZs `a` and `b`, with the four CloudWatch
alarms from Tier 1 and a target-tracking scaling policy on
`ALBRequestCountPerTarget` (ARCHITECTURE.md 5.3, 8.2). PLAN step 8.

The ASG uses ELB health checks, so an instance whose `/health` fails is
terminated and replaced automatically. The 2-instance ceiling fits the
default 5-vCPU per-region quota (D9); the scaling demo (step 9, E5)
exercises the `desired 1 -> desired 2` transition.

Reuses `modules/network`, `modules/alb` and `modules/observability`
unchanged, and swaps `modules/app_static` for `modules/app_asg`. The VPC
CIDR is `10.11.0.0/16` so Tier 1 (`10.10.0.0/16`) and Tier 2 can be up
at the same time for a review session.

Prerequisites (apply in order, once per account):

1. `infra/bootstrap/` applied — state bucket exists.
2. `infra/global/ecr/` applied — repo and replication rule exist.
3. Service image for the current commit pushed to that repo (see
   `infra/global/ecr/README.md`).

Tier 1 does not need to be destroyed first; the two stacks use separate
VPC CIDRs and separate Terraform state keys.

Then:

```
cd infra/envs/tier2
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

## Verifying self-healing (step 8 "Done when")

The PLAN row for step 8 passes when a killed instance is replaced
automatically. Any of these should trigger an ASG replacement within
1.5-3 min (ARCHITECTURE.md 4.3, measured for real in E4):

```
ASG=$(terraform output -raw asg_name)

# Pick a target (either instance in the ASG).
INSTANCE_ID=$(aws autoscaling describe-auto-scaling-groups \
  --auto-scaling-group-names "$ASG" \
  --query 'AutoScalingGroups[0].Instances[0].InstanceId' --output text)

# Option 1: terminate the instance through the ASG (replacement is immediate).
aws autoscaling terminate-instance-in-auto-scaling-group \
  --instance-id "$INSTANCE_ID" --no-should-decrement-desired-capacity

# Option 2: stop the container via SSM; the ELB health check fails after
# the unhealthy threshold is reached, then the ASG replaces it.
aws ssm send-command --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker stop aadhaar-mock"]'
```

Watch `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG"`
or the CloudWatch `GroupInServiceInstances` metric for the replacement.

AWS actions needed (console, Jeel):

- Confirm the SNS email subscription if `alarm_email` was set.
- `terraform destroy` here at the end of every session. The `global/`
  stack stays up until step 12.
