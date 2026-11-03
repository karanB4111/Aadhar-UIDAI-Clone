# Handoff: how to pick up the project on any member's laptop

What you need to know, in order, to work on your own step without
breaking anyone else's. Read this once; refer back when a new step
needs AWS.

- `PLAN.md` says what to do and whose turn it is.
- `ARCHITECTURE.md` says how it is designed.
- `CONTRIBUTING.md` says how to commit and the Terraform rules.
- **This file** says what credentials, values and commands you need the
  first time you apply Terraform on a new laptop.

The AWS account is shared across the group; the Terraform state lives
in S3 in that account, so whoever is next for a build step picks up
from where the last person left off without copying files around.

---

## 1. Shared account facts (do not change)

Set once, used by everyone.

| Thing | Value |
|---|---|
| AWS account id | `573979276874` |
| Account owner (root, console) | Khushi |
| Primary region | `ap-south-1` (Mumbai) |
| Second region, opt-in | `ap-south-2` (Hyderabad) — already enabled |
| Terraform state bucket | `aadhaar-ha-demo-tfstate-573979276874` |
| ECR repository (URL) | `573979276874.dkr.ecr.ap-south-1.amazonaws.com/aadhaar-mock` |
| ECR repository (ARN) | `arn:aws:ecr:ap-south-1:573979276874:repository/aadhaar-mock` |
| Service image tag in ECR | `6cc656f` (short SHA of commit `6cc656f`) |
| AWS Budgets tripwire | USD 10 actual spend (D9) |

Rotating one of these values (new image tag, new region) means every
owner updates the row above in the same commit as the change. Do not
hardcode them in your scripts; copy from here.

---

## 2. First-time setup on your own laptop

Each member does this once per laptop.

### 2.1 AWS credentials

Ask Khushi (the account owner) to create you a dedicated IAM user:

- `IAM → Users → Create user`
- Username: your name, lowercase and `-cli` (e.g. `Jeel-cli`,
  `Khushi-cli`, `Kanu-cli`).
- Attach the AWS-managed policy `AdministratorAccess` for the project
  duration.
- Open the new user → `Security credentials → Create access key →
  Command Line Interface (CLI)`. Download the CSV, keep it safe,
  **never commit it**.

On your Mac, create a named profile (never overwrite your default
profile from other work):

```
aws configure --profile aadhaar
# AWS Access Key ID:     <from CSV>
# AWS Secret Access Key: <from CSV>
# Default region name:   ap-south-1
# Default output format: json
```

Verify:

```
export AWS_PROFILE=aadhaar
aws sts get-caller-identity   # must print Account: 573979276874
```

Add `export AWS_PROFILE=aadhaar` to your shell rc file if you want it
on by default for this project. Otherwise prefix every command, or
`export` it in each new terminal session.

**Rotate your access key** by making it inactive and creating a new
one on the IAM console if you ever paste it anywhere (chat, email,
screenshot). Delete the CSV once the key is loaded into
`~/.aws/credentials`.

### 2.2 Tools on your laptop

- Terraform ≥ 1.10 (`brew tap hashicorp/tap && brew install hashicorp/tap/terraform`, then `terraform version`).
- AWS CLI v2 (`brew install awscli`).
- Docker Desktop (needed only when rebuilding the service image).
- `git`, `python 3.13`, `jq` (useful but optional).

### 2.3 Repo

```
git clone <repo url>
cd Aadhar-UIDAI-PROJECT
git pull
```

Always `git pull` before you start work (PLAN section 6).

---

## 3. The Terraform stacks and their lifecycles

| Stack | What it holds | Lifecycle | Owner for apply |
|---|---|---|---|
| `infra/bootstrap/` | S3 bucket for Terraform state | Applied **once** per account. Local state. Stays up forever. | Jeel (step 6) |
| `infra/global/ecr/` | `aadhaar-mock` ECR repo + replication to `ap-south-2` | Long-lived; destroyed only in step 12 | Jeel (step 6) |
| `infra/envs/tier1/` | Tier 1 VPC + ALB + 2 EC2 | **Apply when working on a Tier 1 step; destroy at end of session** | step 6 Jeel; step 7 Khushi |
| `infra/envs/tier2/` | Tier 2 ASG stack | Written (step 8), not yet applied. **Apply when working on a Tier 2 step; destroy at end of session** | step 8 Jeel; step 9 Kanu |
| `infra/envs/tier3/` | Two regions + Route 53 | Not written yet (step 11, Jeel) | Jeel (step 11) |

**Hard rule (CONTRIBUTING.md):** `terraform destroy` on `envs/*` at
the end of every session. The `bootstrap/` and `global/ecr/` stacks
stay up until step 12. S3-native locking (`use_lockfile = true`)
prevents two people applying the same env at the same time.

---

## 4. Running Tier 1 (envs/tier1) — the usual flow

Needed for step 7 (Khushi), and any time Kanu reviews step 6.

### 4.1 One-time per laptop

Create the two values files inside `infra/envs/tier1/`:

```
cd infra/envs/tier1

cat > backend.tfvars <<'EOF'
bucket = "aadhaar-ha-demo-tfstate-573979276874"
EOF

cat > terraform.tfvars <<'EOF'
ecr_repository_arn = "arn:aws:ecr:ap-south-1:573979276874:repository/aadhaar-mock"
ecr_repository_url = "573979276874.dkr.ecr.ap-south-1.amazonaws.com/aadhaar-mock"
image_tag          = "6cc656f"
alarm_email        = ""
EOF
```

Both files are git-ignored, so they stay on your laptop.

Optional: set `alarm_email` to your own address if you want SNS
notifications of healthy-host / 5xx / latency alarms during your run.
AWS will send a confirm-subscription email — click it once.

### 4.2 Every session

```
export AWS_PROFILE=aadhaar
cd infra/envs/tier1

terraform init -backend-config=backend.tfvars   # only the first time per laptop
terraform fmt
terraform validate
terraform plan                                   # paste summary into commit message
terraform apply                                  # type yes
```

Expected outputs (DNS name changes every apply):

```
alb_url      = "http://aadhaar-tier1-alb-XXXXXXXXXX.ap-south-1.elb.amazonaws.com"
alb_dns_name = "aadhaar-tier1-alb-XXXXXXXXXX.ap-south-1.elb.amazonaws.com"
instance_ids = ["i-...", "i-..."]
sns_topic_arn = "arn:aws:sns:ap-south-1:573979276874:aadhaar-tier1-alerts"
```

First ~90 seconds after apply, instances are installing Docker,
pulling the image and starting the container. Then:

```
ALB=$(terraform output -raw alb_url)
curl -s $ALB/health
curl -s $ALB/
curl -s -X POST $ALB/api/v1/authenticate \
  -H 'content-type: application/json' \
  -d '{"uid":"TEST-0000-0000-0001","otp":"000001"}'
for i in 1 2 3 4 5 6; do curl -s $ALB/health | grep -o '"az":"[^"]*"'; done
```

If `/health` returns 503, wait 30 s and retry — instances still booting.

### 4.3 End of session

```
terraform destroy       # type yes; takes ~2 min
```

This brings AWS costs back to ~USD 0.01 / month (state bucket + ECR
image). Never leave `envs/tier1` up overnight.

---

## 5. Rebuilding the service image

Needed only when Kanu changes code in `service/`. The image tag in
`terraform.tfvars` must match the pushed tag, so push before you apply.

```
export AWS_PROFILE=aadhaar
cd Aadhar-UIDAI-PROJECT
TAG=$(git rev-parse --short HEAD)
REPO=573979276874.dkr.ecr.ap-south-1.amazonaws.com/aadhaar-mock

aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin 573979276874.dkr.ecr.ap-south-1.amazonaws.com

cd service
docker buildx build --platform linux/amd64 --load -t "$REPO:$TAG" .
docker push "$REPO:$TAG"
```

Then update `image_tag` in `infra/envs/tier1/terraform.tfvars` to the
new `$TAG` and `terraform apply`. **ECR tags are immutable**: you
cannot overwrite `6cc656f`; a code change needs a new commit so the
short SHA is different.

Update section 1 of this file with the new tag so other members pick
it up.

---

## 6. What to do if…

| Situation | Do this |
|---|---|
| Starting a new session | `git pull`, read PLAN Progress line, `export AWS_PROFILE=aadhaar`. |
| `terraform apply` says state is locked | Someone else is applying. Wait, then retry. Never force-unlock without asking in the group chat. |
| `/health` keeps returning 503 after 3 min | SSM into the instance (console → EC2 → Session Manager → Start session → run `sudo docker ps` and `sudo cat /var/log/cloud-init-output.log`). Likely the image tag in `terraform.tfvars` is not in ECR. |
| Need to review step 6 without applying | Read `infra/` on the branch; `terraform plan` is read-only and safe. |
| Forgot to destroy | Destroy now. Budgets alert at USD 10 will warn before you eat the credit, but check `Billing → Bills` in the console. |
| CSV / access key leaked | Deactivate the key on IAM, create a new one, update `~/.aws/credentials`. Tell the group. |

---

## 7. Current state (keep updated)

| Resource | Status | Last touched by | Date (UTC) |
|---|---|---|---|
| `bootstrap/` (state bucket) | Applied, stays up | Jeel | 2026-11-02 |
| `global/ecr/` (repo + replication) | Applied, stays up | Jeel | 2026-11-02 |
| ECR image `6cc656f` | Pushed | Jeel | 2026-11-02 |
| `envs/tier1/` | Reverted to fast hc and destroyed at the end of step 7 (2026-11-03). Reapply only if a Tier 1 review needs it. | Jeel (apply), Khushi (step 7 runs) | 2026-11-03 |
| `envs/tier2/` | Terraform written (step 8). **Next AWS action (Jeel):** `terraform init` + `terraform apply` to bring the ASG up and verify self-healing (see `infra/envs/tier2/README.md`), then `terraform destroy` to end the session. | Jeel | 2026-11-03 |
| `ap-south-2` opt-in | Enabled | Khushi (console) | 2026-11-02 |
| Budgets alert at USD 10 | **AWS action needed** (confirm it exists) | — | — |

Update this table whenever a stack goes up or down.
