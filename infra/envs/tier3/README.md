# envs/tier3 — PLAN step 11

Tier 3: two independent regional stacks, Mumbai + Hyderabad, each Tier-2
shaped (VPC + ALB + ASG `min 1 / desired 2 / max 2` across 2 AZs + alarms).
Reuses `modules/network`, `modules/alb`, `modules/app_asg` and
`modules/observability` with no changes.

## Scope: what Tier 3 is and is not here

**As designed in ARCHITECTURE.md §5.4:** Route 53 latency-based routing with
health checks in front of both regions (`api.<domain>` -> active-active).

**As built (2026-11-05):** two regional stacks, **no Route 53**. Open item O1
(domain) was descoped by the group — the backend works, and we did not want
to publish a public DNS name. Route 53 stays as paper design in
ARCHITECTURE.md §5.4.

Consequence for the measurement in step 11:

- **E6a / E6b use client-side failover**, not DNS failover. The prober
  (`tests/prober.py --urls primary,secondary`) holds both ALB URLs and
  switches to the secondary after N consecutive errors on the primary. The
  measured number is a **lower bound** on the Route 53 case — a real client
  would also pay DNS detection + TTL (20–105 s per ARCHITECTURE.md §4.3),
  which this setup does not exercise.
- The report (`report/WEEK3.md`) states this explicitly.

If the group later decides to buy a domain (O1), the Tier 3 code here stays
and a new stack `infra/global/dns/` + a `modules/dns_failover/` would be
added separately.

## Hyderabad prerequisite (one-time, per account)

`ap-south-2` is an opt-in region. Enable it in the AWS console first:

- `Account → AWS Regions → Asia Pacific (Hyderabad) ap-south-2 → Enable`.
- Enabling is free. Already done for this account on 2026-11-02
  (HANDOFF.md §7).

**AWS action needed (first time only):** confirm Hyderabad is enabled by
running:

```
aws ec2 describe-regions --all-regions --region-names ap-south-2 \
  --query 'Regions[0].OptInStatus' --output text
# expect: opted-in
```

## ECR image must exist in BOTH regions before applying

`infra/global/ecr` created a replication rule from `ap-south-1` to
`ap-south-2` on 2026-11-02. That rule only replicates images **pushed after
the rule exists**, and AWS docs say "most images replicate in under 30
minutes" (ARCHITECTURE.md §5.1.3). Image `6cc656f` was pushed
2026-11-02 so it should already be in both regions.

Check before `terraform apply`:

```
export AWS_PROFILE=aadhaar
TAG=6cc656f
aws ecr describe-images --region ap-south-1 --repository-name aadhaar-mock \
  --image-ids imageTag=$TAG --query 'imageDetails[0].imagePushedAt'
aws ecr describe-images --region ap-south-2 --repository-name aadhaar-mock \
  --image-ids imageTag=$TAG --query 'imageDetails[0].imagePushedAt'
```

Both must return a timestamp. If Hyderabad returns `ImageNotFoundException`,
push the image directly to Hyderabad once:

```
aws ecr get-login-password --region ap-south-2 | \
  docker login --username AWS --password-stdin \
  573979276874.dkr.ecr.ap-south-2.amazonaws.com
docker pull 573979276874.dkr.ecr.ap-south-1.amazonaws.com/aadhaar-mock:$TAG
docker tag  573979276874.dkr.ecr.ap-south-1.amazonaws.com/aadhaar-mock:$TAG \
            573979276874.dkr.ecr.ap-south-2.amazonaws.com/aadhaar-mock:$TAG
docker push 573979276874.dkr.ecr.ap-south-2.amazonaws.com/aadhaar-mock:$TAG
```

## First-time apply (per laptop)

```
cd infra/envs/tier3
cp backend.tfvars.example   backend.tfvars
cp terraform.tfvars.example terraform.tfvars
# edit both: fill account id (573979276874) and confirm image_tag.

export AWS_PROFILE=aadhaar
terraform init -backend-config=backend.tfvars
terraform fmt
terraform validate
terraform plan              # paste summary into the step-11 commit message
terraform apply             # type yes; takes ~4 min (two regions in parallel)
```

Expected outputs (DNS names change every apply):

```
mumbai_alb_url     = "http://aadhaar-tier3-mu-alb-XXXXXXXXXX.ap-south-1.elb.amazonaws.com"
hyderabad_alb_url  = "http://aadhaar-tier3-hy-alb-XXXXXXXXXX.ap-south-2.elb.amazonaws.com"
prober_urls        = "http://aadhaar-tier3-mu-alb-...,http://aadhaar-tier3-hy-alb-..."
```

The first ~90 seconds after apply, instances are installing Docker, logging
into their regional ECR, pulling and starting. Then both regions respond:

```
MU=$(terraform output -raw mumbai_alb_url)
HY=$(terraform output -raw hyderabad_alb_url)
curl -s $MU/ | jq .region   # "ap-south-1"
curl -s $HY/ | jq .region   # "ap-south-2"
```

## Running E6a and E6b

See [`tests/README.md`](../../../tests/README.md) for prober usage and
`results/e6a/README.md` / `results/e6b/README.md` for what each run
captures.

Short form:

```
# E6a: planned Mumbai evacuation (set desired=0 on the Mumbai ASG).
URLS=$(cd ../../envs/tier3 && terraform output -raw prober_urls)
python tests/prober.py --urls "$URLS" --run-id e6a-r01-mu-evac \
  --duration 300 \
  --action 60 inject_start "aws autoscaling set-desired-capacity \
    --auto-scaling-group-name $(cd infra/envs/tier3 && terraform output -raw mumbai_asg_name) \
    --desired-capacity 0 --region ap-south-1" \
  --action 240 restore "aws autoscaling set-desired-capacity \
    --auto-scaling-group-name $(cd infra/envs/tier3 && terraform output -raw mumbai_asg_name) \
    --desired-capacity 2 --region ap-south-1"

# E6b: unplanned Mumbai loss (attach the deny-all NACL to Mumbai app
# subnets). See tests/README.md.
```

## End of session: DESTROY

**Hard rule (CONTRIBUTING.md / AGENTS.md):** `terraform destroy` on
`envs/*` at the end of every session. Tier 3 has two regional ALBs and up
to 4 running instances, so a forgotten `tier3` stack costs USD 0.05+/hour.

```
terraform destroy          # type yes; takes ~3 min
```

The `bootstrap/` and `global/ecr/` stacks stay up; they are destroyed only
in step 12.

## Current apply history

Tracked in [HANDOFF.md §7](../../../HANDOFF.md).
