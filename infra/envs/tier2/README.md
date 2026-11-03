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

**One-time per account:** the ASG needs the `AWSServiceRoleForAutoScaling`
service-linked role. On a fresh account the first `apply` fails with
"Access denied when attempting to assume role ... Validating load balancer
configuration failed." Create the role once (already done for the group's
account on 2026-11-03):

```
export AWS_PROFILE=aadhaar
aws iam create-service-linked-role --aws-service-name autoscaling.amazonaws.com
# "InvalidInput: already exists" on later runs is fine.
```

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

## Step 9 load test: setting ASG capacity / scaling per experiment

The load test (PLAN step 9, `tests/step9_load.ps1`) drives load from a laptop
but does **not** change capacity. Set the ASG state in AWS first, per
ARCHITECTURE.md 5.3.3. Capacity comes from `terraform.tfvars` (`asg_min`,
`asg_desired`, `asg_max`). The target-tracking policy
(`aws_autoscaling_policy.request_count`) is always created by `modules/app_asg`,
so to run with scaling **off** (E0, E5a), pin min=desired=max to fix the count,
or suspend the scaling processes; for E5b leave room between desired and max and
keep the processes resumed:

| Exp | What to set before the run | How |
|---|---|---|
| E0  | 1 instance, no scaling | `asg_min=asg_desired=asg_max=1`, then `terraform apply`; pinning min=max holds it at 1 even though the policy exists |
| E5a | fixed N (1, then 2), no scaling | `asg_min=asg_desired=asg_max=N`, apply (two applies: N=1 then N=2); or `aws autoscaling suspend-processes --auto-scaling-group-name <asg> --scaling-processes AlarmNotification` |
| E5b | min 1 / desired 1 / max 2, scaling **on** | apply with `asg_min=1 asg_desired=1 asg_max=2`, processes resumed. The load step drives desired 1 → 2 |

Share with Kanu after apply: `terraform output -raw alb_dns_name`,
`terraform output -raw asg_name`, and the ALB / target-group ARN suffixes
(`app/.../...` and `targetgroup/.../...`, from `aws elbv2 describe-load-balancers`
/ `describe-target-groups` or the ARNs) for `tests/fetch_metrics.py`.

Hold each E5a point ≥ 5 min and each E5b step ≥ 10 min after warm-up, because
scale-out takes about 5–8 min (ESTIMATE, 4.3). Keep `unlimited` credit mode on
and export `CPUSurplusCreditBalance` after each run to prove there was no
throttling (5.1.2).

AWS actions needed (console / CLI, Jeel):

- Confirm the SNS email subscription if `alarm_email` was set.
- Set the ASG capacity / scaling for each step-9 experiment (table above).
- `terraform destroy` here at the end of every session. The `global/`
  stack stays up until step 12.
